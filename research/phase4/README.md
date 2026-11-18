# TrustHarvest — Phase 4: Baseline Experiment Framework

This directory houses the reproducible baseline research experiment framework for evaluating the blockchain-based provenance integrity verification of the **TrustHarvest** application.

---

## 1. Experimental Objectives

The primary objective of this phase is to evaluate the existing application's integrity verification engine under normal, untampered operating conditions:
1. **Verification Correctness**: Empirically establish whether authentic, unchanged produce records across all supply-chain stages (Harvest, multi-stop Transport checkpoints, and Retail listings) are correctly classified as `verified`.
2. **Latency Profiling**: Measure the computational and RPC round-trip latency (mean, median P50, and 95th-percentile P95) for querying and verifying records against the Ethereum smart contract (`TrustHarvestV2.sol`).
3. **Reproducibility**: Provide automated, deterministic synthetic dataset generation and experiment logging pipelines without modifying production behavior or corrupting live user data.

---

## 2. Directory Structure

```
research/phase4/
├── __init__.py               # Python package initialization
├── README.md                 # Experiment documentation & reproduction guide
├── generate_dataset.py       # Deterministic synthetic dataset generator
├── experiment_logger.py      # Reusable CSV experiment logger
├── metrics.py                # Statistical & classification metric calculator
├── run_baseline.py           # Main baseline verification execution harness
├── data/
│   ├── synthetic_batches.json # 30 synthetic batches (Harvest, Transport 1-5, Retail)
│   └── research_phase4.db     # Isolated research SQLite database (never touches production DB)
└── results/
    ├── baseline_verification.csv # Granular per-trial experiment logs (120 evaluation points)
    └── baseline_summary.json     # Aggregated classification & latency metrics report
```

---

## 3. Dataset Generation Procedure

Synthetic data is generated deterministically via `generate_dataset.py`:
* **Batch Count**: 30 synthetic batches (`TH-SYN-001` through `TH-SYN-030`).
* **Attributes**:
  * **Harvest**: Crop variety, quantity, certified organic / hydroponic farming methods, GPS origin coordinates, packaging dates, certifications.
  * **Transport Checkpoints**: 1 to 5 sequential transit legs per batch, featuring realistic cold-chain telemetry ($2.8^\circ\text{C}$ to $4.4^\circ\text{C}$), vehicle numbers, and physical transit depots.
  * **Retail Listings**: Store branch names, locations, retail unit prices, arrival dates, and shelf-life horizons.
* **Ground Truth**: Each batch records expected baseline verification outcomes (`verified` across all stages).
* **Privacy & Isolation**: All data is explicitly labeled as synthetic (`"is_synthetic": true`) with zero real-world personal information.

### Command to Re-Generate Dataset:
```bash
python research/phase4/generate_dataset.py --count 30 --seed 42
```

---

## 4. Local Test Environment Configuration

The experiment framework adheres to strict safety boundaries:
1. **Isolated Database**: Configured via `DATABASE_URL=sqlite:///research/phase4/data/research_phase4.db`. Production `trustharvest.db` remains completely untouched.
2. **Local Ganache EVM**: Executes against the local Ganache blockchain node on `http://127.0.0.1:7545` (Chain ID `1337`).
3. **No Public Deployments**: No transactions are broadcast to Ethereum Sepolia or any public network.
4. **Code Reuse**: Directly reuses canonical hashing functions (`compute_batch_hash`, `compute_transport_hash`, `compute_retail_hash`) and verification context engines (`_build_verification_context`, `_save_stage_snapshot_once`) from `blockchain.py` and `app.py`.

### Prerequisites:
Ensure your virtual environment is activated and Ganache is running on port 7545:
```bash
# Terminal 1: Launch Local Ganache
npx ganache -p 7545 -h 127.0.0.1 --chain.chainId 1337 --chain.networkId 1337
```

---

## 5. How to Execute the Baseline Experiment

Run the automated experiment runner:
```bash
# Terminal 2: Run Baseline Experiment
python research/phase4/run_baseline.py --limit 30
```

### Optional Arguments:
* `--limit <int>`: Number of batches to evaluate (default: `30`).
* `--dataset <path>`: Custom synthetic dataset path (default: `research/phase4/data/synthetic_batches.json`).
* `--output <path>`: Target CSV results file (default: `research/phase4/results/baseline_verification.csv`).

---

## 6. Output Files and Schemas

### Granular Trial Results (`results/baseline_verification.csv`)
Each trial records:
* `experiment_id`: Unique run identifier (e.g., `EXP-BASELINE-20261117-143444`).
* `batch_id`: Batch identifier (`TH-SYN-001` .. `TH-SYN-030`).
* `stage`: Evaluated stage (`HARVEST`, `TRANSPORT`, `RETAIL`, `OVERALL`).
* `scenario`: Experiment scenario (`baseline_unchanged`).
* `expected_outcome`: Ground truth expected state (`verified`).
* `actual_outcome`: Measured verification result (`verified`, `tampered`, `cannot_verify`).
* `success`: Boolean (`True` if actual matches expected).
* `latency_ms`: Execution time in milliseconds.
* `timestamp`: ISO 8601 UTC timestamp of execution.
* `error_message`: Error or conflict details if any.

### Summary Metrics (`results/baseline_summary.json`)
Aggregated JSON containing classification accuracy, specificity, confusion matrix counts, and latency statistics.

---

## 7. Metric Definitions

* **Classification Accuracy**:
  $$\text{Accuracy} = \frac{\text{Correct Predictions}}{\text{Total Predictions}}$$
* **Specificity (True Negative Rate)**:
  $$\text{Specificity} = \frac{\text{TN}}{\text{TN} + \text{FP}}$$
  In the baseline setting where all authentic records are untampered, specificity measures the framework's ability to avoid false tamper alarms.
* **Latency Benchmarks**:
  * **Mean**: Arithmetic average of verification round-trip times in milliseconds.
  * **Median (P50)**: 50th-percentile execution latency.
  * **P95**: 95th-percentile execution latency, capturing high-percentile tail latency.
* **Inconclusive Handling**: Network or RPC unavailability (`cannot_verify`) is treated in its own distinct category and is **never** conflated with ordinary tampering detections.

---

## 8. Empirical Baseline Results Summary

* **Batches Evaluated**: 30 synthetic batches.
* **Total Evaluation Points**: 120 trials (30 Harvest, 30 Transport, 30 Retail, 30 Overall).
* **Classification Accuracy**: **100.00%** (120/120 correct).
* **False Alarms**: 0 false positives.
* **Inconclusive / Offline**: 0 failures.
* **Latency Profile**:
  * **Mean Latency**: 169.49 ms
  * **Median Latency (P50)**: 120.80 ms
  * **95th Percentile (P95)**: 406.15 ms
  * **Min / Max Latency**: 66.42 ms / 726.47 ms

---

## 9. Known Limitations

1. **Local Ganache vs Public Network Latency**: Local EVM transactions experience near-zero network delay (~100–300 ms). Public testnets (e.g. Sepolia) will introduce block mining intervals (12–15 seconds) and variable internet RPC jitter.
2. **Fixed Gas Limits**: Local Ganache accounts possess unlimited gas, whereas public execution requires tracking gas budgets and test faucet allocation.
3. **Static Telemetry Sampling**: Transport checkpoints represent discrete point-in-time entries rather than continuous streaming IoT telemetry.

