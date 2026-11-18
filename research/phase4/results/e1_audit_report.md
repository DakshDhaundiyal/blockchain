# TrustHarvest — Phase 4: E1 Baseline Experiment Audit Report

**Date of Audit**: November 17, 2026  
**Auditor**: Senior Research Engineer  
**Repository Branch**: `research/phase4-baseline-experiments`  
**Execution Environment**: Local Ganache EVM (`http://127.0.0.1:7545`, Chain ID `1337`), Python 3.11.9, SQLite  

---

## 1. Executive Audit Summary

The initial E1 baseline experiment framework was subjected to a comprehensive audit covering data integrity, database isolation, metric soundness, cryptographic determinism, and environment safety.

**Overall Status**: **PASSED AUDIT (WITH DOCUMENTED METHODOLOGICAL NOTES)**

---

## 2. Granular Verification Findings

### 2.1 Synthetic Dataset Integrity (`data/synthetic_batches.json`)
* **Batch Count**: Confirmed exactly 30 unique synthetic produce batches (`TH-SYN-001` through `TH-SYN-030`).
* **Supply Chain Completeness**:
  * **Harvest Records**: 30/30 populated with variety, quantity, farming methods, packaging dates, and farm origins.
  * **Transport Checkpoints**: 94 total checkpoints across the 30 batches (ranging from 1 to 5 sequential legs per batch, average 3.13 checkpoints/batch). All include realistic cold-chain temperatures ($2.8^\circ\text{C}$ to $4.4^\circ\text{C}$), vehicle IDs, and transit hubs.
  * **Retail Listings**: 30/30 populated with store names, branches, normalized unit pricing ($3.79 to $5.29), arrival dates, and shelf-life horizons.
* **Privacy & Isolation**: Every batch is explicitly tagged with `"is_synthetic": true` and contains zero real personal or commercial data.

### 2.2 Results Verification (`results/baseline_verification.csv` & `baseline_summary.json`)
* **Evaluation Points**: Confirmed exactly 120 trial records (30 Harvest, 30 Transport, 30 Retail, 30 Overall).
* **Ground Truth Consistency**: All 120 trials expected `verified` and returned `verified` (100.00% accuracy, 120/120).
* **Numeric Latencies**: All recorded latencies are strictly positive floating-point numbers derived from `time.perf_counter()` (min: 66.42 ms, max: 726.47 ms, mean: 169.49 ms, median P50: 120.80 ms, P95: 406.15 ms).
* **Zero Denominator Handling in Baseline**: In an all-negative baseline dataset (120 untampered records), the positive class count is zero ($\text{TP}=0, \text{FP}=0, \text{TN}=120, \text{FN}=0$). Precision and Recall are mathematically indeterminate ($0/0$). The evaluation framework safely returned $0.00\%$ without crashing and correctly emphasized **Specificity (True Negative Rate) = 100.00%**. Genuine tampering detection precision and recall will be measured in Experiment E2 when positive (tampered) samples are evaluated.

### 2.3 Stage vs. Overall Latency Methodological Note
* In `run_baseline.py`, the complete end-to-end verification call (`_build_verification_context(product)`) performs a unified blockchain query (`inspect_batch_on_chain`) that retrieves all on-chain hashes in a single call.
* The overall batch latency ($338.98\text{ ms}$ average) captures the complete round-trip (blockchain RPC query + local DB queries + SHA-256 recalculation across all stages). The stage records in E1 represented proportional allocations ($112.99\text{ ms}$). For E2–E6, timing measurements will clearly separate individual component computation from the holistic verification pass.

### 2.4 Database and State Isolation
* **Database Target**: Confirmed that `run_baseline.py` strictly writes to and queries `research/phase4/data/research_phase4.db` (file size: 200,704 bytes).
* **Production Database Integrity**: Confirmed that `instance/trustharvest.db` (file size: 53,248 bytes) was never modified or overwritten and still contains only the original seeded batches (`TH-APPLES-001`, `TH-TOMATO-002`).

---

## 3. Audit of Changes Outside `research/phase4/`

Two minimal configuration adjustments were reviewed:
1. **`tests/conftest.py`**:
   * *Change*: Explicitly sets `os.environ["DEMO_MODE"] = "false"` at fixture initialization.
   * *Assessment*: **Safe and essential**. In developer environments with `.env` files specifying `DEMO_MODE=true`, unit tests testing default production behavior (e.g., ensuring demo tamper buttons return 404) would fail without this isolation.
2. **`seed.py`**:
   * *Change*: Removes stale local `config.json` during database reset when `CONTRACT_ADDRESS` is not fixed to an external network.
   * *Assessment*: **Safe and necessary**. When local database tables are dropped and re-seeded, attempting to re-store the same batch IDs against the same contract address on Ganache reverts due to `TrustHarvestV2`'s `AlreadyRegistered` one-time write protection. Clearing `config.json` allows a clean contract deployment on the local chain, making the seeding process idempotent.

---

## 4. Conclusion & Approval for E2–E6

The E1 baseline experiment outputs are validated, preserved, and reproducible. The research environment is confirmed safe for proceeding to:
* **E2**: Controlled Tampering Detection
* **E3**: Snapshot Integrity and Diagnosis
* **E4**: Failure and Security Scenarios
* **E5**: Multi-Checkpoint Provenance Evaluation
* **E6**: Performance and Scalability Benchmarking

