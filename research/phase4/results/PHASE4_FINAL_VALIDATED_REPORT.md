# TrustHarvest Phase 4: Comprehensive Empirical Validation Report

**Document Title**: Final Validated Empirical Evaluation of Blockchain-Anchored Agricultural Provenance Verification  
**Evaluation Scope**: Experiments E1 through E6 (Baseline, Tampering, Snapshots, Failure Modes, Multi-Checkpoint Scaling, and Performance)  
**Date**: November 17, 2026  
**Auditor / Lead Engineer**: Senior Research Engineer (Blockchain Systems & Empirical Software Engineering)  
**Target Repository**: `https://github.com/DakshDhaundiyal/blockchain.git`  
**Git Branch**: `research/phase4-baseline-experiments`  
**Commit Hash**: `3c596359b9459e7170ed59d20154378b370a10f5`  
**Evaluation Node**: Local Ganache (`CHAIN_ID=1337`, Port 7545)  
**Database Isolation**: Isolated Research Database (`research/phase4/data/research_phase4.db`)

---

## 1. Experimental Environment & Setup

| Parameter | Ground-Truth Specification | Evidence / Verification Method |
| :--- | :--- | :--- |
| **Operating System** | Windows 11 Enterprise x64 | System environment audit |
| **Repository URL** | `https://github.com/DakshDhaundiyal/blockchain.git` | `git remote -v` |
| **Git Branch** | `research/phase4-baseline-experiments` | `git branch --show-current` |
| **Commit Hash** | `3c596359b9459e7170ed59d20154378b370a10f5` | `git rev-parse HEAD` |
| **Python Version** | Python `3.11.9` | `sys.version` |
| **Solidity Compiler** | `solc 0.8.19` (via `py-solc-x`) | `contracts/TrustHarvestV2.sol` pragma & `blockchain.py` |
| **Local EVM Node** | `ganache v7.9.2` (@ganache/cli: 0.10.2) | `ganache --version` |
| **EVM Chain ID** | `1337` (Network ID: `1337`) | Ganache RPC parameter |
| **Active Contract Address**| `0x6bbAcD565E12B91E9214E5e00650D46d4b13676E` | `config.json` (Contract Version: `V2`) |
| **Isolated Research DB** | `research/phase4/data/research_phase4.db` (SQLite) | `os.environ["DATABASE_URL"]` |

---

## 2. Experimental Methodologies (E1–E6)

### E1: Baseline Verification Accuracy
- **Goal**: Establish the baseline verification behavior on authentic, unmodified agricultural batches.
- **Methodology**: 30 synthetic batches containing harvest records, 1 to 5 transport checkpoints, and retail listings were anchored on Ganache. Verification was executed across 120 evaluation points (30 harvest, 30 transport stage, 30 retail stage, and 30 overall verification points).
- **Limitation**: Evaluates only the negative class (unmodified data); cannot measure precision, recall, or sensitivity in isolation.

### E2: Controlled Tampering Detection
- **Goal**: Quantify the detection sensitivity of cryptographic SHA-256 verification across 29 distinct field-level and structural mutation scenarios.
- **Methodology**: Evaluated 10 synthetic batches across 290 trials (250 positive tampering trials and 40 negative control trials). Mutations targeted harvest quantities, dates, farming methods, transport temperatures, locations, vehicle numbers, notes, retail prices, shelf lives, and stock quantities.

### E3: Snapshot Integrity & Field-Level Diagnosis
- **Goal**: Test whether point-in-time off-chain snapshots enable accurate field-level discrepancy attribution and withstand database-snapshot collusion.
- **Methodology**: Evaluated 10 synthetic batches across 8 adversarial scenarios (80 trials), simulating single-field tampering, multi-field tampering, and collusion attacks where an adversary modified both SQL tables and local snapshot records.
- **Critical Scope Limitation**: **Only HARVEST stage snapshots were evaluated.** Transport and retail snapshots were not covered in this experiment.

### E4: Failure Modes & Availability Robustness
- **Goal**: Evaluate system behavior under adverse networking, contract reverts, missing anchors, unauthorized signers, and state divergence.
- **Methodology**: Evaluated 5 batches across 10 failure modes (50 trials): RPC node offline, invalid RPC endpoint, RPC timeout, contract execution revert, unanchored batch, missing stages on-chain, unauthorized signer accounts, unexpected on-chain stage enum, extraneous on-chain stages, and unmined transaction hashes.

### E5: Multi-Checkpoint Scaling
- **Goal**: Measure verification correctness and latency scaling across variable supply chain depths (1, 2, 5, 10, and 20 checkpoints).
- **Methodology**: Conducted trials testing unchanged state, single-checkpoint modification, multi-checkpoint modification, missing local records, unexpected on-chain records, and duplicate database records.
- **Run History**: Run 1 (50% accuracy due to signer misconfiguration), Run 2 (100% accuracy, 30 trials), and independent validation Run 3 (100% accuracy, 30 trials).

### E6: Performance & Scalability Benchmark
- **Goal**: Profile system throughput, total latency distribution, and component latency breakdown under variable batch workloads.
- **Methodology**: Evaluated 5 workload sizes (10, 30, 50, 100, and 200 batches) repeated over 3 independent trials (1,170 evaluated batches total). Instrumented local CPU SHA-256 hashing time, isolated on-chain read time, and full verification time.

---

## 3. Actual Trial Counts & Ground-Truth Numerical Results

| Experiment | Raw CSV Artifact | Actual Trials | Expected Outcome Match | Success Rate | Mean Latency | Median Latency | P95 Latency |
| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **E1** | `baseline_verification.csv` | 120 | 120 / 120 | **100.0%** | 169.49 ms | 120.80 ms | 412.93 ms |
| **E2** | `tampering_experiments.csv` | 290 | 290 / 290 | **100.0%** | 525.95 ms | 533.96 ms | 719.58 ms |
| **E3** | `snapshot_experiments.csv` | 80 | 80 / 80 | **100.0%** | 212.44 ms | 198.54 ms | 312.45 ms |
| **E4** | `failure_experiments.csv` | 50 | 45 / 50 | **90.0%**\* | 184.20 ms | 175.40 ms | 289.12 ms |
| **E5 (Run 2)** | `checkpoint_experiments.csv` | 30 | 30 / 30 | **100.0%** | 285.98 ms | 212.80 ms | 685.16 ms |
| **E5 (Run 3)** | `checkpoint_experiments_run3.csv`| 30 | 30 / 30 | **100.0%** | 272.84 ms | 224.62 ms | 658.74 ms |
| **E6** | `performance_experiments.csv` | 1,170 | 1,170 / 1,170 | **100.0%** | 214.28 ms | 212.17 ms | 328.25 ms |

*\*In E4, 45/50 trials matched the formal test expectation; 5 trials in scenario `e4_3_extra_transport_onchain` produced `tampered` instead of `cannot_verify` due to the Positional Matching Vulnerability.*

### Detailed Confusion Matrices

#### E2 Controlled Tampering Classification Matrix (290 Trials):
- **True Positives (TP)**: 250 (Tampered records correctly flagged as `tampered`)
- **True Negatives (TN)**: 40 (Negative control records correctly verified as `verified`)
- **False Positives (FP)**: 0 (No authentic records falsely flagged as tampered)
- **False Negatives (FN)**: 0 (No tampered records escaped detection)
- **Inconclusive (`cannot_verify`)**: 0
- **Precision**: $1.0000$ (100.0%)
- **Recall / Sensitivity**: $1.0000$ (100.0%)
- **Specificity**: $1.0000$ (100.0%)

#### E4 Failure & Robustness Distribution (50 Trials):
- **Network / Transport Failures** (15 trials): 15 degraded safely to `cannot_verify` (0 false tamper alerts).
- **EVM Reverts & Contract Errors** (5 trials): 5 degraded safely to `cannot_verify`.
- **Anchor & Signature Inconsistencies** (25 trials): 25 identified safely as `cannot_verify`.
- **Extraneous On-Chain Record Injection** (5 trials): 5 flagged as `tampered` (due to array shift in `app.py`).

---

## 4. Reconciliation of Experiment E5 (Multi-Checkpoint Scaling)

The raw file `checkpoint_experiments.csv` contains 60 total rows split across two execution runs:
1. **Run 1 (`EXP-CHKPT-20261117-152524`)**:
   - Result: 15 passed, 15 failed (50.0% accuracy).
   - Root Cause: All transactions were submitted from account 0 (`0xF0a259...`, deployer key). The application's verification logic rejected authentic stages because the signing key did not match the role allowlists (Farmer = account 1, Transporter = account 2, Retailer = account 3).
2. **Run 2 (`EXP-CHKPT-20261117-152812`)**:
   - Result: 30 passed, 0 failed (100.0% accuracy).
   - Signer configuration was corrected; fresh batch IDs (`TH-E5-V3-...`) were created and anchored on-chain.
   - Summary file `checkpoint_summary.json` reflects Run 2 exclusively.
3. **Run 3 (`EXP-CHKPT-RUN3-20261117-162441`)**:
   - Result: 30 passed, 0 failed (100.0% accuracy).
   - Fully independent clean validation run executed on fresh batches (`TH-E5-RUN3-...`).
   - Archived separately in `checkpoint_experiments_run3.csv` and `checkpoint_summary_run3.json`.

### Empirical Latency by Checkpoint Count:
| Checkpoint Count | Run 2 Mean Latency | Run 2 Median Latency | Run 3 Mean Latency | Run 3 Median Latency |
| :---: | :---: | :---: | :---: | :---: |
| **1 Checkpoint** | 144.34 ms | 146.54 ms | 114.86 ms | 104.35 ms |
| **2 Checkpoints**| 167.83 ms | 160.76 ms | 131.05 ms | 134.15 ms |
| **5 Checkpoints**| 199.54 ms | 196.16 ms | 192.15 ms | 174.78 ms |
| **10 Checkpoints**| 346.74 ms | 349.00 ms | 301.27 ms | 301.45 ms |
| **20 Checkpoints**| 571.43 ms | 611.60 ms | 624.89 ms | 527.27 ms |

**Limitation on Complexity Claims**: The observed empirical latency increases monotonically with checkpoint depth. However, claiming asymptotic computational complexity $\mathcal{O}(N)$ from five observed configurations on a local loopback network is mathematically unfounded. In production, this overhead is dominated by sequential HTTP JSON-RPC roundtrips, which can be mitigated via batched RPC or multicall contracts.

---

## 5. Architectural Findings, Vulnerabilities & Protection Boundaries

### 5.1 True Canonical Hash Serialization Implementation
Inspection of `blockchain.py` reveals that TrustHarvest **does not use pipe-delimited strings**. It strictly uses UTF-8 encoded JSON strings with lexicographically sorted keys:
```python
payload = json.dumps(data, sort_keys=True)
return hashlib.sha256(payload.encode("utf-8")).hexdigest()
```
- **Harvest Hash**: Hashed keys = `batch_id`, `farmer_id`, `farming_method`, `image`, `name`, `packaging_date`, `quantity`.
- **Transport Hash**: Hashed keys = `batch_id`, `current_location`, `notes`, `stage` ("TRANSPORT"), `status`, `temperature`, `transporter_id`, `vehicle_number`.
- **Retail Hash**: Hashed keys = `arrival_date`, `batch_id`, `price` (normalized to `%.2f`), `retailer_id`, `shelf_life`, `stage` ("RETAIL"), `stock_quantity`, `store_location`, `store_name`.

### 5.2 Protection Boundaries (Unhashed Fields)
The following database columns are **not included** in the canonical JSON hashing payload:
- `farmer_data`: `certifications`, `notes`.
- `transport_data`: `timestamp`.
- `retail_data`: `updated_at`.
Modifying these unhashed fields produces **zero cryptographic tamper alerts**. They represent unprotected metadata in the current architecture.

### 5.3 Positional Array-Index Matching Vulnerability
In `app.py`, checkpoint verification matches local database records against on-chain stage records sequentially by index (`idx`):
```python
chain_stage = transport_chain_stages[idx]
```
If an adversary submits an extraneous transport record directly to the smart contract, the on-chain stage list shifts. Subsequent authentic local records are compared against mismatched on-chain stages, causing authentic subsequent checkpoints to flag as `tampered` rather than identifying an unanchored/foreign record.

### 5.4 Snapshot Limitations
Off-chain snapshots stored in `stage_snapshots` are standard relational SQLite rows. They are **not independently immutable** and possess no native consensus security. Their integrity relies entirely on validating `original_hash` against the on-chain root hash stored in `TrustHarvestV2`. If the on-chain hash is missing or unverified, snapshot records cannot be trusted.

---

## 6. Smart Contract & Gas Measurement Audit

### 6.1 Compiler Version Resolution
- **Pragma**: `pragma solidity ^0.8.19;` in `contracts/TrustHarvestV2.sol`.
- **Compiler Configuration**: Explicitly pinned to `0.8.19` in `blockchain.py` via `solcx.compile_standard(solc_version="0.8.19", ...)`.
- **Finding**: The earlier reference to `0.8.20` was an informal conversational estimate. **Solidity 0.8.19** is the sole compiler version supported by repository evidence.

### 6.2 EVM Gas Consumption Measurements
Gas measurements were sampled from mined transaction receipts on Ganache:
- `storeHash(string, string)`:
  - 14-char batch ID (`GAS-TEST-BATCH`): **163,382 gas**
  - 18-char batch ID (`GAS-AUDIT-BATCH-000`): **163,442 gas**
  - Delta: Exactly $+60$ gas ($4 \times 16\text{ gas/non-zero calldata byte} - 4\text{ gas packing delta}$).
- `addStageHash(string, string, string)`:
  - 14-char batch ID: **190,612 gas**
  - 18-char batch ID: **190,672 gas**
  - Delta: Exactly $+60$ gas.
- **Contract Build & Calldata**: Both measurements used the exact same bytecode build of `TrustHarvestV2.sol`.
- **Public Network Caution**: These measurements represent deterministic EVM execution gas units. On public Ethereum or Sepolia, monetary transaction fees fluctuate dynamically based on EIP-1559 base fees and priority tips.

---

## 7. Performance & Latency Instrumentation Analysis (E6)

### 7.1 Timing Methodology & Negative Overhead Analysis
In `run_performance.py`, the timer instrumentation measured:
1. `hash_ms`: Local SHA-256 CPU hashing.
2. `chain_ms`: Isolated on-chain read via `inspect_batch_on_chain(batch_id)`.
3. `comp_ms`: End-to-end verification via `_build_verification_context(prod)`.

Because `chain_ms` and `comp_ms` were measured during **two separate, sequential invocations**, socket I/O latency jitter between the two independent requests caused the isolated read in some repetitions to take slightly longer than the subsequent verification read. This resulted in negative computed overhead values in `performance_summary.json` (e.g., $-1.329\text{ ms}$ for 50 batches and $-0.566\text{ ms}$ for 200 batches).

### 7.2 Reliable Metrics from E6
- **Mean Verification Latency**: ~208 ms to 246 ms per batch on local Ganache.
- **Local SHA-256 CPU Hashing**: $0.18\text{ ms}$ to $0.20\text{ ms}$ per batch (< 0.1% of total latency).
- **Throughput**: Sustained at **2.01 to 2.36 batches/second** on a single-threaded synchronous Python process.
- **RPC Dominance**: While JSON-RPC network I/O is unambiguously the primary latency driver, claiming an exact figure of "99.8%" across non-nested disparate calls is an artifact of timing instrumentation jitter.

---

## 8. Research Hypotheses & Evidence-Based Status

| Hypothesis | Proposed Claim | Evidence-Based Status | Ground-Truth Rationale |
| :--- | :--- | :---: | :--- |
| **H1: Tamper Sensitivity** | SHA-256 hashing detects any modification to recorded supply chain data. | **Partially Supported** | 100% detection on all hashed attributes; 0% detection on unhashed metadata (`certifications`, `notes`, `timestamp`, `updated_at`). |
| **H2: Snapshot Diagnosis** | Local snapshots enable accurate field-level diagnosis and resist collusion. | **Partially Supported** | **Supported** for Harvest stage (100% precision/recall); **Inconclusive** for Transport and Retail stages due to lack of test coverage in E3. |
| **H3: Fault Tolerance** | Verification degrades gracefully without producing false tamper alarms on RPC loss. | **Supported** | 0 false tamper alarms across 15 network/RPC failure trials in E4 (100% degraded to `cannot_verify`). |
| **H4: Checkpoint Verification** | Sequential checkpoint matching correctly verifies multi-stage provenance. | **Partially Supported** | 100% accuracy on matching sequences; fails (flags `tampered`) when foreign on-chain stages alter array alignment. |
| **H5: Linear Scalability** | Sequential off-chain verification scales with $\mathcal{O}(N)$ complexity. | **Partially Supported** | Empirical latency increases monotonically with depth (~115 ms $\rightarrow$ ~625 ms), but formal asymptotic complexity cannot be inferred from 5 local data points. |
| **H6: Truthfulness Guarantee** | Blockchain anchoring guarantees the physical truth of agricultural claims. | **Not Supported** | The blockchain solves data tampering post-commitment, not the real-world Oracle problem. False input data is immutably preserved (Garbage-In, Garbage-Out). |

---

## 9. Threats to Validity

1. **Threats to Internal Validity**:
   - Sequential, non-nested timer instrumentation in E6 introduced measurement jitter and negative calculated overheads.
   - Positional array indexing in `app.py` conflates structural sequence changes with cryptographic hash tampering.
2. **Threats to Construct Validity**:
   - Synthetic datasets were generated programmatically; driver temperatures and truck numbers were entered via form simulations rather than cryptographically authenticated IoT hardware sensors.
3. **Threats to External Validity**:
   - Local Ganache execution features zero network propagation delay, zero gas fee volatility, and instant block confirmation. Verification latency on public EVM networks (e.g., Ethereum Mainnet or Sepolia) will be substantially higher and subject to WAN latency and block times.

---

## 10. Missing / Incomplete Experiments & Future Work

1. **E3 Transport & Retail Snapshot Evaluation**: E3 must be expanded to include dedicated mutation and collusion tests for transport checkpoints and retail listings.
2. **Public Testnet (Sepolia) Dynamic Profiling**: Multi-node latency and EIP-1559 gas fee profiling under real network conditions (omitted under mandatory safety requirements).
3. **Multicall3 RPC Aggregation**: Implementation and benchmarking of a batch contract aggregator to eliminate sequential RPC roundtrips.

---

## 11. Reproducibility Instructions

To independently reproduce the verified findings:
```powershell
# 1. Switch to research branch
git checkout research/phase4-baseline-experiments

# 2. Start local Ganache node
npx ganache -p 7545 -h 127.0.0.1 --chain.chainId 1337 --chain.networkId 1337

# 3. Execute experiment suite
& ".\venv\Scripts\python.exe" research/phase4/run_baseline.py
& ".\venv\Scripts\python.exe" research/phase4/run_tampering.py
& ".\venv\Scripts\python.exe" research/phase4/run_snapshot_tests.py
& ".\venv\Scripts\python.exe" research/phase4/run_failure_tests.py
& ".\venv\Scripts\python.exe" research/phase4/run_checkpoint_run3.py
& ".\venv\Scripts\python.exe" research/phase4/run_performance.py

# 4. Run automated test suite
& ".\venv\Scripts\python.exe" -m pytest tests/ research/phase4/tests/ -v
```

