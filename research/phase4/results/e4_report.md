# Experiment E4 — Failure Modes, Availability & Threat Model Evaluation

**Experiment**: E4 Failure Scenarios and Robustness Evaluation  
**Date**: November 17, 2026  
**Execution Environment**: Local Ganache (`CHAIN_ID=1337`), Isolated Research Database (`research_phase4.db`)  
**Artifacts**:
- Script: `research/phase4/run_failure_tests.py`
- Trial Logs: `research/phase4/results/failure_experiments.csv` (50 total rows)
- Summary Data: `research/phase4/results/failure_summary.json`

---

## 1. Objective and Theoretical Scope

The TrustHarvest verifier must operate reliably under real-world infrastructure failures, network partitions, and adversarial on-chain conditions. In a three-state verification architecture:
1. `verified`: Cryptographic proof confirms record integrity matches the anchored blockchain state.
2. `tampered`: Off-chain record has been modified after on-chain anchoring.
3. `cannot_verify`: Infrastructure or ledger evidence is inconclusive, inaccessible, or contradictory (e.g., RPC down, missing anchor, chain reorg).

**Critical Security Property**: A network outage or missing record must NEVER be falsely reported to end users as `tampered` (which would falsely accuse legitimate farmers/retailers of fraud), nor must it be reported as `verified` (which would allow unverified food to pass inspection).

Experiment E4 evaluates 10 failure scenarios across 5 synthetic batches (50 total trials):
- **E4.1 RPC / Network Failures**: Offline node, invalid RPC endpoint, RPC timeout, and EVM contract read reverts.
- **E4.2 Missing Blockchain Anchor**: Unanchored batch ID, missing stage entries on-chain.
- **E4.3 Unexpected On-Chain State**: Unauthorized/foreign transporter signer address, unknown stage tag on-chain, and extra unexpected transport checkpoint on-chain.
- **E4.4 Database / State Inconsistencies**: Database record exists with transaction hash, but chain reverted/never mined that transaction.

---

## 2. Experimental Results Summary

| Scenario ID | Category | Simulated Fault | Expected | Actual | Passed | False Tamper | False Verified |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| `e4_1_rpc_node_offline` | Network | Connection refused (port 9999) | `cannot_verify` | `cannot_verify` | 5/5 | 0 | 0 |
| `e4_1_rpc_invalid_endpoint` | Network | HTTP 404 / malformed URL | `cannot_verify` | `cannot_verify` | 5/5 | 0 | 0 |
| `e4_1_rpc_timeout` | Network | Socket read timeout | `cannot_verify` | `cannot_verify` | 5/5 | 0 | 0 |
| `e4_1_contract_read_revert`| Network | EVM call revert | `cannot_verify` | `cannot_verify` | 5/5 | 0 | 0 |
| `e4_2_missing_blockchain_anchor`| Ledger | Batch not registered on-chain | `cannot_verify` | `cannot_verify` | 5/5 | 0 | 0 |
| `e4_2_stages_missing_onchain` | Ledger | Harvest anchored; transport missing | `cannot_verify` | `cannot_verify` | 5/5 | 0 | 0 |
| `e4_3_unexpected_transporter_signer` | Security | Checkpoint signed by unauthorized key | `cannot_verify` | `cannot_verify` | 5/5 | 0 | 0 |
| `e4_3_unexpected_stage_onchain` | Security | Checkpoint has invalid stage enum | `cannot_verify` | `cannot_verify` | 5/5 | 0 | 0 |
| `e4_3_extra_transport_onchain` | Security | Extra unrecorded checkpoint on-chain | `cannot_verify` | `tampered`* | 0/5 | 5 | 0 |
| `e4_4_db_saved_chain_reverted` | State | Tx hash recorded, but tx failed/dropped| `cannot_verify` | `cannot_verify` | 5/5 | 0 | 0 |

\* *See Section 3.1 regarding the Positional Matching Vulnerability.*

### Aggregate Metrics

| Metric | Measured Value | Theoretical Assessment |
| :--- | :---: | :--- |
| **Total Trials Executed** | **50 trials** | 10 failure modes $\times$ 5 batches |
| **Trial Pass Rate** | **90.0% (45/50)** | 9 out of 10 failure modes matched ideal specification |
| **False Verified Leaks** | **0 / 50 (0.0%)** | Zero unverified or corrupted states leaked into `verified` |
| **False Tamper Alarms (RPC / Network)** | **0 / 20 (0.0%)** | Perfect graceful degradation on connection / timeout faults |
| **Honest Inconclusive Rate** | **90.0%** | System correctly halts with "Can't check right now" |

---

## 3. Key Findings & Architectural Vulnerabilities

### 3.1 Positional Matching Vulnerability in Multi-Checkpoint Verification
* In scenario `e4_3_extra_transport_onchain`, a foreign actor calls `addStageHash()` on-chain, appending an extra stage.
* The expected behavior under a robust threat model is an inconclusive security alert (`cannot_verify`: unauthorized on-chain checkpoint detected).
* **Observed Implementation Behavior**: `app.py` iterates through checkpoints using index matching:
  ```python
  for idx, tp in enumerate(db_transports):
      on_chain_rec = on_chain_stages[idx]
      if tp_hash != on_chain_rec["hash"]:
          return "tampered"
  ```
  If on-chain stages are inserted or shifted, index alignment breaks, causing an off-by-one hash mismatch. As a result, the existing application classifies the record as **`tampered`** rather than `cannot_verify`.
* **Academic Significance**: This demonstrates an architectural limitation of naive array-index mapping in smart contracts lacking explicit checkpoint sequence UUIDs or nonce tracking.

### 3.2 Robust Network Fallback
* In all network partition and RPC failure scenarios (offline daemon, bad host, timeouts, execution reverts), the verifier caught the transport exceptions via `is_transport_or_connection_error()` and degraded gracefully to:
  `{"status": "cannot_verify", "badge": "Can't check right now"}`.
* Under no circumstances did a network disruption cause a false positive tamper alert.

