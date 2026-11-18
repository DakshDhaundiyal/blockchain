# Experiment E5 — Multi-Checkpoint Provenance Evaluation Report

**Experiment**: E5 Multi-Checkpoint Provenance Evaluation  
**Date**: November 17, 2026  
**Execution Environment**: Local Ganache (`CHAIN_ID=1337`), Isolated Research Database (`research_phase4.db`)  
**Artifacts**:
- Script: `research/phase4/run_checkpoint_tests.py`
- Trial Logs: `research/phase4/results/checkpoint_experiments.csv` (30 rows for active experiment)
- Summary Data: `research/phase4/results/checkpoint_summary.json`

---

## 1. Objective and Experimental Design

TrustHarvest records logistics telemetry sequentially as crops move through supply chain transit. Each intermediate transport checkpoint (cold storage hubs, highway inspection points, cross-dock transfer bays) generates a separate cryptographic hash anchored via `addStageHash(batch_id, "TRANSPORT", hash)`.

Experiment E5 evaluates how the existing verification engine scales in correctness, tamper sensitivity, and verification latency as checkpoint depth grows:
- **Configurations Evaluated**: 1, 2, 5, 10, and 20 transport checkpoints.
- **Scenarios Evaluated per Configuration**:
  1. `all_unchanged`: Authentic batch where all checkpoints match on-chain hashes (Expected: `verified`).
  2. `one_modified`: Single checkpoint temperature modified after anchoring (Expected: `tampered`).
  3. `multi_modified`: Multiple checkpoints (origin and final destination) altered (Expected: `tampered`).
  4. `missing_checkpoint_db`: Checkpoint deleted locally from SQL database (Expected: `cannot_verify`).
  5. `unexpected_checkpoint_chain`: Foreign unrecorded stage appended on-chain (Expected: `cannot_verify`).
  6. `duplicate_checkpoint_db`: Unanchored duplicate checkpoint inserted in SQL database (Expected: `cannot_verify`).

---

## 2. Experimental Results Summary

| Checkpoint Config | Trials | Passed | Accuracy | Mean Latency (ms) | Median Latency (ms) | P95 Latency (ms) | Min / Max (ms) |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **1 Checkpoint** | 6 | 6 | **100.0%** | 144.34 ms | 146.54 ms | 172.11 ms | 118.52 / 178.37 |
| **2 Checkpoints** | 6 | 6 | **100.0%** | 167.83 ms | 160.76 ms | 205.03 ms | 130.49 / 207.38 |
| **5 Checkpoints** | 6 | 6 | **100.0%** | 199.54 ms | 196.16 ms | 252.99 ms | 154.61 / 262.90 |
| **10 Checkpoints** | 6 | 6 | **100.0%** | 346.74 ms | 349.00 ms | 427.34 ms | 277.18 / 442.20 |
| **20 Checkpoints** | 6 | 6 | **100.0%** | 571.43 ms | 611.60 ms | 685.16 ms | 385.71 / 699.48 |
| **Total / Overall** | **30** | **30** | **100.0%** | **285.98 ms** | **223.28 ms** | **642.18 ms** | **118.52 / 699.48** |

---

## 3. Key Observations & Latency Scaling

1. **Strict Linear Verification Overhead $\mathcal{O}(N)$**:
   - Verification latency exhibits a clean linear relationship with checkpoint count $N$.
   - Baseline single-checkpoint verification requires **144.3 ms**.
   - As $N$ expands to 20 checkpoints, latency grows to **571.4 ms**, representing an average marginal overhead of **~22.5 ms per additional transport checkpoint**.
   - This overhead stems directly from iterative EVM RPC calls (`getStageRecord(batch_id, i)`), which require sequential network round-trips over Web3 HTTP providers.

2. **Tamper Sensitivity Across Depth**:
   - In both 1-checkpoint and 20-checkpoint setups, modifying a single telemetry field (such as cold-chain temperature) was caught with **100% precision and recall**.
   - The verifier correctly isolated multi-point tampering without degradation in detection fidelity.

3. **Missing and Extraneous State Defenses**:
   - Deleting a checkpoint from the SQL database immediately triggered `extra_transport_on_chain` detection (`len(on_chain_stages) > len(db_transports)`), causing the engine to halt safely with `cannot_verify` rather than misclassifying the batch as authentic.
   - Inserting duplicate unanchored checkpoints in the database similarly degraded gracefully to `cannot_verify`.

