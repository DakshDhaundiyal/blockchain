# Smart Contract & Provenance Security Audit (`TrustHarvestV2.sol`)

> **PUBLIC DEPLOYMENT HOLD NOTICE**
> **Nothing has been — or will be — deployed to Ethereum Sepolia or any public network until you explicitly review and approve this audit.**
> Zero smart contract code (`contracts/TrustHarvestV2.sol`) or hashing logic has been modified during Phase 0.

---

## 1. Audited Contract Scope

* **Contract File:** `contracts/TrustHarvestV2.sol` (`Solidity ^0.8.19`)
* **Backwards Compatibility Contract:** `contracts/legacy/TrustHarvest.sol` (Legacy V1)
* **Contract State & Entry Points:**
  * `address public immutable owner` (assigned in `constructor()` to `msg.sender`)
  * `storeHash(string batchId, string hash)` — seals a batch harvest SHA-256 hash once (`if (records[batchId].exists) revert AlreadyRegistered(batchId)`).
  * `addStageHash(string batchId, string stage, string dataHash)` — pushes an append-only `StageRecord` (`stage`, `dataHash`, `recordedBy`, `timestamp`) onto `stageHistory[batchId]`.
  * Read-only views: `getHash(batchId)`, `getRecord(batchId)`, `getStageCount(batchId)`, `getStageRecord(batchId, index)`.

---

## 2. Critical Smart Contract Findings (Why `TrustHarvestV2.sol` Is Risky Unprotected on a Public Network)

### 2.1 `storeHash` and `addStageHash` Are Public & Permissionless (No Access Control)
Both state-mutating functions are `public` with **zero caller checks** (`msg.sender` is never validated against `owner` or any role allowlist).

**Concrete Consequences on a Public Network (Even Sepolia):**
1. **Batch ID Front-Running / Squatting:** Anyone monitoring pending transactions (mempool) or guessing batch IDs can call `storeHash(batchId, fakeHash)` first. Because `TrustHarvestV2` enforces one-time-write via `AlreadyRegistered(batchId)`, the legitimate farmer's transaction will revert permanently for that `batchId`.
2. **Unremovable Junk / Poison Stage Entries:** Once a batch exists, **any address on Ethereum** can call `addStageHash(batchId, "TRANSPORT", "junk")` or inject arbitrary fake stages (`"RETAIL"`, `"POISON"`). `stageHistory[batchId]` is append-only with no removal/hide mechanism, so unauthorized entries remain permanently inside `stageHistory[batchId]`.
3. **Signer Address Recorded, Never Enforced:** `registeredBy = msg.sender` and `recordedBy = msg.sender` are stored and emitted in events, creating the *appearance* of actor attribution, **but the contract itself accepts any `msg.sender`**. On-chain alone does not guarantee that a `"TRANSPORT"` record came from a transporter or that a `"RETAIL"` record came from a retailer.
4. **Spam, Public Gas Waste & Verification Griefing (RPC / Loop DoS):** Even though spammers pay their own test ETH gas, they can push hundreds of `StageRecord` entries onto a public batch ID. Every verification view/API request loops `0 .. getStageCount(batchId) - 1` via RPC (`getStageRecord`), which can exhaust **Alchemy Free Tier** compute-unit/rate limits or cause timeouts on **Render Free Tier** (`Can't check right now` Denial of Service).
5. **Unused `owner` Variable & No Pause / Circuit Breaker:** `address public immutable owner` is declared and initialized in the constructor, yet **never referenced** in any modifier or function. There is no `pause()` / emergency stop, no way to revoke compromised role keys on-chain, and no ownership transfer.

---

## 3. Multi-Stage Support Check (Multiple Transport Checkpoints)

* **Question:** Does `TrustHarvestV2` allow several entries with the same stage name (e.g., `"TRANSPORT"`) for one batch?
* **Verified Answer:** **Yes.**
  * Line 37 defines `mapping(string => StageRecord[]) private stageHistory;` (a dynamic array per `batchId`).
  * `addStageHash` (lines 87–107) only checks that `batchId` exists, `stage` is non-empty, and `dataHash` is non-empty — there is **no deduplication or uniqueness restriction on `stage`**.
  * Every call appends (`push`) a new `StageRecord` in chronological insertion order, readable sequentially via `getStageCount(batchId)` and `getStageRecord(batchId, index)`.
  * **No Solidity change is needed to anchor and verify multiple chronological transport checkpoints.**

---

## 4. What the Application Can Safely Do WITHOUT Changing `TrustHarvestV2.sol`

Without editing or redeploying Solidity, the Python verification engine (Phases 1–3) can enforce strong **off-chain cryptographic verification guardrails**:

1. **Role-Signer Allowlist Validation (Safe Conflict Detection):**
   * Configure the server's expected public wallet addresses per role via environment variables (derived from the server-held signer keys for `farmer`, `transporter`, and `retailer`, plus legacy/historical allowlisted signers for older local/V1 batches).
   * During read-only verification (`getRecord` and every `getStageRecord`):
     * Check that Harvest `registeredBy` matches an expected Farmer signer address (when signer enforcement is configured).
     * Check that every `"TRANSPORT"` record's `recordedBy` matches an expected Transporter signer address, and `"RETAIL"` matches an expected Retailer signer address.
     * Treat any record signed by an **unexpected/unknown address** as a **conflicting/untrusted record** → report **`"Can't check right now"`** with a plain reason (*"An unexpected wallet signed an on-chain entry for this batch"*), **never** marking it `"Verified"` and **never** falsely blaming the local database (`"Changed after recording"`).
2. **Matching Stage Hashes Instead of Fragile Index-Only Alignment:**
   * Filter stage history cleanly by expected stage & expected signer when validating ordered checkpoints against DB rows, so one unauthorized external push does not falsely shift indexes and trigger a fake mismatch on valid later checkpoints (while still flagging the unexpected signer conflict honestly).
3. **High-Entropy Random Batch IDs:**
   * Keep random UUID-derived IDs (`TH-<8+ hex chars>`) generated strictly server-side at submission time so pre-computing upcoming batch IDs for squatting is impractical before broadcast.
4. **RPC Cap / Bounded Stage Reading for Free Tiers:**
   * Cap maximum stage reads per batch check (e.g., reject/flag conflict if `getStageCount` is abnormally huge beyond expected bounds) so a griefed batch cannot exhaust Alchemy Free Tier quotas or stall Render worker threads.

### Honest Limitations of Off-Chain-Only Mitigations
Off-chain signer allowlisting **completely prevents an attacker from spoofing a `"Verified"` green badge** with their own wallet. However, **without on-chain access control**, the app **cannot stop** someone who knows a published `batchId` on Sepolia from spending test ETH to append junk to `stageHistory[batchId]` and intentionally causing a `"Can't check right now"` (conflict/spam) state for that batch.

---

## 5. Separate Proposal: Recommended Contract Access-Control Changes (FOR FUTURE APPROVAL — NOT IMPLEMENTED)

If you decide to replace or deploy an audited **`TrustHarvestV3`** before any future permanent/commercial rollout, the following Solidity changes are recommended:

1. **On-Chain Role-Based Access Control:**
   * Add `mapping(address => bool) public authorizedFarmers;` (and `authorizedTransporters`, `authorizedRetailers`, or an `enum Role` registry managed by `owner`), OR restrict `storeHash` and `addStageHash` strictly to trusted server/relayer signer accounts authorized by `owner`.
   * Enforce `if (!authorizedFarmers[msg.sender]) revert UnauthorizedSigner();` inside `storeHash` and matching role checks inside `addStageHash`.
2. **Emergency Pause & Governed Key Rotation:**
   * Add `bool public paused;` with `pause()` / `unpause()` (`onlyOwner`) plus two-step ownership transfer (`pendingOwner` + `acceptOwnership()`) so a leaked signer key can be rotated or frozen immediately.
3. **Stage Validation & Gas Optimization (Free Sepolia Faucet Efficiency):**
   * Store hashes as fixed `bytes32` instead of UTF-8 `string` (~64 bytes hex in dynamic string storage) to cut gas per harvest/checkpoint transaction significantly — stretching free Sepolia faucet ETH much further.
   * Restrict `stage` to an `enum Stage { TRANSPORT, RETAIL }` instead of arbitrary `string`.
   * Optionally enforce per-batch state caps (`MAX_STAGES_PER_BATCH`) so unbounded growth griefing is impossible on-chain.

---

## 6. Explicit Deployment Gate

* **Status:** **NOT APPROVED FOR PUBLIC DEPLOYMENT YET.**
* **Policy:** No contract deployment to Ethereum Sepolia (via Alchemy or any public RPC) will occur in Phases 1–4. Phase 5 deployment/configuration remains strictly gated on your explicit approval of this `docs/CONTRACT_AUDIT.md`.

