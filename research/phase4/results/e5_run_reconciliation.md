# TrustHarvest Phase 4 — Experiment E5 Run Reconciliation Report

**Date**: November 17, 2026  
**Auditor**: Senior Research Engineer (Blockchain Systems & Empirical Software Engineering)  
**Target File**: `research/phase4/results/checkpoint_experiments.csv`  
**Associated Summaries**: `checkpoint_summary.json`, `checkpoint_summary_run3.json`  
**Git Branch**: `research/phase4-baseline-experiments`  
**Commit**: `3c596359b9459e7170ed59d20154378b370a10f5`

---

## 1. Executive Summary

This reconciliation report resolves the discrepancy identified in `checkpoint_experiments.csv`, which contains 60 rows generated across two distinct experiment IDs:
1. **Run 1 (`EXP-CHKPT-20261117-152524`)**: 30 trials with 15 expected-versus-actual outcome failures (50.0% accuracy).
2. **Run 2 (`EXP-CHKPT-20261117-152812`)**: 30 trials with 30 successes (100.0% accuracy).
3. **Run 3 (`EXP-CHKPT-RUN3-20261117-162441`)**: 30 newly executed trials with 30 successes (100.0% accuracy), archived in separate files `checkpoint_experiments_run3.csv` and `checkpoint_summary_run3.json`.

The investigation established that:
- The summary JSON `checkpoint_summary.json` was generated solely from **Run 2** (`"experiment_id": "EXP-CHKPT-20261117-152812"`). The CSV logger appends records rather than overwriting them, which caused Run 1 and Run 2 to coexist in the raw CSV.
- **Root cause of Run 1 failures**: Run 1 failed due to a **role-signer account misconfiguration**. Every on-chain transaction (Harvest, Transport, Retail) was submitted from Ganache account 0 (`0xF0a259aE08d96534A58653450E818e409F8AB693`, the deployer/admin account). The verification engine enforces role-based signer verification, expecting account 1 for farmer, account 2 for transporter, and account 3 for retailer. As a result, authentic records were rejected as `cannot_verify` with the explicit diagnostic message: `"The farm harvest record on-chain was signed by an unexpected account"` or `"Transport checkpoint on-chain was signed by an unexpected account"`.
- Run 2 corrected the signer configuration and created fresh batches (`TH-E5-V3-...`), achieving 100% accuracy.
- To eliminate any residual doubt about state leakage or stale record reuse, an independent clean **Run 3** was executed with fresh batch IDs (`TH-E5-RUN3-...`), confirming 100% accuracy across all five configurations.

---

## 2. Independent Run-by-Run Analysis

### 2.1 Run 1 (`EXP-CHKPT-20261117-152524`)
- **Execution Timestamp**: 2026-11-17 15:25:24 UTC
- **Batch Identifier Prefix**: `TH-E5-CP01`, `TH-E5-CP02`, `TH-E5-CP05`, `TH-E5-CP10`, `TH-E5-CP20`, `TH-E5-EXTRA-...`
- **Total Rows**: 30
- **Passed Trials**: 15 / 30 (50.0%)
- **Failed Trials**: 15 / 30 (50.0%)
- **Latency**: Mean = 307.65 ms, Min = 100.81 ms, Max = 847.68 ms

#### Failure Breakdown in Run 1:
| Batch ID | Scenario | Expected | Actual | Root Cause Diagnosis |
| :--- | :--- | :---: | :---: | :--- |
| `TH-E5-CP01` | `e5_all_unchanged_1cp` | `verified` | `tampered` | Harvest snapshot mismatch + unexpected deployer signer on-chain. |
| `TH-E5-CP01` | `e5_missing_checkpoint_db_1cp` | `cannot_verify` | `tampered` | Harvest stage failed with `tampered` before checkpoint evaluation. |
| `TH-E5-CP01` | `e5_duplicate_checkpoint_db_1cp` | `cannot_verify` | `tampered` | Harvest stage failed with `tampered` before checkpoint evaluation. |
| `TH-E5-CP02` | `e5_all_unchanged_2cp` | `verified` | `cannot_verify` | Signed by Deployer (`0xF0a259...`) instead of Transporter/Retailer accounts. |
| `TH-E5-CP02` | `e5_one_modified_2cp` | `tampered` | `cannot_verify` | Stage signer conflict aborted verification to `cannot_verify`. |
| `TH-E5-CP02` | `e5_multi_modified_2cp` | `tampered` | `cannot_verify` | Stage signer conflict aborted verification to `cannot_verify`. |
| `TH-E5-CP05` | `e5_all_unchanged_5cp` | `verified` | `cannot_verify` | Stage signer conflict across all 5 checkpoints. |
| `TH-E5-CP05` | `e5_one_modified_5cp` | `tampered` | `cannot_verify` | Stage signer conflict across all 5 checkpoints. |
| `TH-E5-CP05` | `e5_multi_modified_5cp` | `tampered` | `cannot_verify` | Stage signer conflict across all 5 checkpoints. |
| `TH-E5-CP10` | `e5_all_unchanged_10cp` | `verified` | `cannot_verify` | Stage signer conflict across all 10 checkpoints. |
| `TH-E5-CP10` | `e5_one_modified_10cp` | `tampered` | `cannot_verify` | Stage signer conflict across all 10 checkpoints. |
| `TH-E5-CP10` | `e5_multi_modified_10cp` | `tampered` | `cannot_verify` | Stage signer conflict across all 10 checkpoints. |
| `TH-E5-CP20` | `e5_all_unchanged_20cp` | `verified` | `cannot_verify` | Stage signer conflict across all 20 checkpoints. |
| `TH-E5-CP20` | `e5_one_modified_20cp` | `tampered` | `cannot_verify` | Stage signer conflict across all 20 checkpoints. |
| `TH-E5-CP20` | `e5_multi_modified_20cp` | `tampered` | `cannot_verify` | Stage signer conflict across all 20 checkpoints. |

### 2.2 Run 2 (`EXP-CHKPT-20261117-152812`)
- **Execution Timestamp**: 2026-11-17 15:28:12 UTC (3 minutes after Run 1)
- **Batch Identifier Prefix**: `TH-E5-V3-CP01`, `TH-E5-V3-CP02`, `TH-E5-V3-CP05`, `TH-E5-V3-CP10`, `TH-E5-V3-CP20`, `TH-E5-V3-EXTRA-...`
- **Total Rows**: 30
- **Passed Trials**: 30 / 30 (100.0%)
- **Failed Trials**: 0 / 30 (0.0%)
- **Signer Verification**:
  - Harvest: Signed by `0xA9Ab5d95B3C31423F8376Df9ff969336A2310C4B` (Ganache Account 1 / Farmer).
  - Transport Checkpoints: Signed by `0x5E42b383F8F5813D86a4FA8Cf10BcE6533D8e69A` (Ganache Account 2 / Transporter).
  - Retail: Signed by `0xab2Caa15b160135b602247656Fbd164963282043` (Ganache Account 3 / Retailer).
- **Latency Metrics by Configuration**:
  - 1 Checkpoint: Mean = 144.34 ms, Median = 146.54 ms
  - 2 Checkpoints: Mean = 167.83 ms, Median = 160.76 ms
  - 5 Checkpoints: Mean = 199.54 ms, Median = 196.16 ms
  - 10 Checkpoints: Mean = 346.74 ms, Median = 349.00 ms
  - 20 Checkpoints: Mean = 571.43 ms, Median = 611.60 ms

### 2.3 Run 3 (`EXP-CHKPT-RUN3-20261117-162441`) — Independent Validation
- **Execution Timestamp**: 2026-11-17 16:24:41 UTC
- **Batch Identifier Prefix**: `TH-E5-RUN3-CP01`, `TH-E5-RUN3-CP02`, `TH-E5-RUN3-CP05`, `TH-E5-RUN3-CP10`, `TH-E5-RUN3-CP20`, `TH-E5-RUN3-EXTRA-...`
- **Total Rows**: 30
- **Passed Trials**: 30 / 30 (100.0%)
- **Failed Trials**: 0 / 30 (0.0%)
- **Archived In**: `checkpoint_experiments_run3.csv`, `checkpoint_summary_run3.json`
- **Latency Metrics by Configuration**:
  - 1 Checkpoint: Mean = 114.86 ms, Median = 104.35 ms
  - 2 Checkpoints: Mean = 131.05 ms, Median = 134.15 ms
  - 5 Checkpoints: Mean = 192.15 ms, Median = 174.78 ms
  - 10 Checkpoints: Mean = 301.27 ms, Median = 301.45 ms
  - 20 Checkpoints: Mean = 624.89 ms, Median = 527.27 ms

---

## 3. Technical Verification & Database Inspection

1. **Did Run 2 reuse stale blockchain data?**
   - **No.** Run 2 used fresh `TH-E5-V3-*` batch identifiers that had never been written to the contract prior to 15:28:12 UTC. Each batch was sealed with its own EVM transaction receipt and separate block number.
2. **Did Run 2 reuse existing DB records?**
   - **No.** Database queries confirm that `TH-E5-CP*` and `TH-E5-V3-*` exist as separate rows in `products`, `transport_data`, and `retail_data`.
3. **Why did `checkpoint_summary.json` only reflect Run 2?**
   - In `run_checkpoint_tests.py`, the summary calculation filters the CSV rows using:
     ```python
     cfg_rows = [r for r in rows if r.get("experiment_id") == EXPERIMENT_ID]
     ```
     Because `EXPERIMENT_ID` was generated at the start of Run 2 (`EXP-CHKPT-20261117-152812`), the summary JSON exclusively aggregated Run 2. However, the CSV logger opened `checkpoint_experiments.csv` in append mode (`mode="a"`), leaving Run 1 in the raw file.
4. **Separation and Data Preservation**:
   - Both original runs in `checkpoint_experiments.csv` are preserved exactly as logged.
   - Run 3 is preserved separately in `checkpoint_experiments_run3.csv`.

---

## 4. Latency Trends and Limitations on Complexity Inferences

### Empirical Latency Scaling
Across both successful runs (Run 2 and Run 3), verification latency exhibits a monotonically increasing empirical trend as the number of on-chain checkpoints increases:
- **Run 2**: 144.3 ms (1 CP) $\rightarrow$ 167.8 ms (2 CP) $\rightarrow$ 199.5 ms (5 CP) $\rightarrow$ 346.7 ms (10 CP) $\rightarrow$ 571.4 ms (20 CP).
- **Run 3**: 114.9 ms (1 CP) $\rightarrow$ 131.1 ms (2 CP) $\rightarrow$ 192.1 ms (5 CP) $\rightarrow$ 301.3 ms (10 CP) $\rightarrow$ 624.9 ms (20 CP).

### Limitations of Inferring $\mathcal{O}(N)$ Asymptotic Complexity
1. **Sample Size**: Five discrete checkpoint depths ($N \in \{1, 2, 5, 10, 20\}$) are insufficient to claim asymptotic mathematical complexity $\mathcal{O}(N)$ in a formal computer science sense.
2. **Local Ganache Environment**: Measurements were conducted over loopback IPC/HTTP on a local Ganache instance with zero network congestion, zero gas fee market, and near-zero roundtrip latency.
3. **I/O Bound vs Computational Scaling**: The latency growth is driven entirely by sequential HTTP JSON-RPC calls (`getStageRecord(batchId, i)`), not CPU computation. Local SHA-256 hashing accounts for less than 0.2 ms.
4. **Architectural Mitigation**: In a production environment utilizing batched JSON-RPC calls or a contract multicall aggregator (e.g., Multicall3), all $N$ stages could be retrieved in a single network roundtrip, transforming the latency profile from linear network roundtrips to near-constant $\mathcal{O}(1)$ network delay plus minor payload deserialization.

