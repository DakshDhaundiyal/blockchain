# Experiment E2 — Controlled Tampering Detection Report

**Experiment**: E2 Controlled Tampering Detection  
**Date**: November 17, 2026  
**Execution Environment**: Local Ganache (`CHAIN_ID=1337`), Isolated Research Database (`research_phase4.db`)  
**Artifacts**:
- Script: `research/phase4/run_tampering.py`
- Trial Logs: `research/phase4/results/tampering_experiments.csv` (290 total rows)
- Summary Data: `research/phase4/results/tampering_summary.json`

---

## 1. Objective and Scope

Experiment E2 assesses the sensitivity and accuracy of the TrustHarvest dual-layer cryptographic verification engine in detecting modifications made to provenance records after their original SHA-256 hashes were permanently anchored on the Ethereum blockchain.

The evaluation covers four distinct scenario suites across 10 independent batches:
1. **E2.1 Harvest Tampering**: Individual field mutations (`name`, `quantity`, `farming_method`, `packaging_date`) and multi-field combinations.
2. **E2.2 Transport Tampering**: Individual telemetry and checkpoint mutations (`temperature`, `current_location`, `notes`, `status`, `vehicle_number`, `transporter_id`) and multi-field combinations.
3. **E2.3 Retail Tampering**: Individual store mutations (`price`, `store_name`, `store_location`, `stock_quantity`, `arrival_date`, `shelf_life`) and multi-field combinations.
4. **E2.4 Negative Controls**: Modifications to fields stored in the relational database that are deliberately excluded from cryptographic hash definitions (`FarmerData.certifications`, `FarmerData.notes`, `TransportData.timestamp`, `RetailData.updated_at`).

---

## 2. Experimental Results Summary

### 2.1 Tampering Detection Performance (Hashed Fields)

| Metric | Result | Interpretation |
| :--- | :--- | :--- |
| **Total Tamper Trials** | **250** | 70 Harvest + 90 Transport + 90 Retail trials across 10 batches |
| **True Positives (TP)** | **250** | 100% of tampered records were successfully caught |
| **False Negatives (FN)** | **0** | Zero tampered records escaped detection |
| **False Positives (FP)** | **0** | No authentic records were falsely flagged |
| **Classification Accuracy** | **100.00%** | Mathematical guarantee of SHA-256 collision resistance |
| **Tamper Precision** | **100.00%** | $\frac{\text{TP}}{\text{TP}+\text{FP}} = \frac{250}{250}$ |
| **Tamper Recall (Sensitivity)** | **100.00%** | $\frac{\text{TP}}{\text{TP}+\text{FN}} = \frac{250}{250}$ |
| **F1-Score** | **1.0000** | Perfect harmonic mean |
| **Inconclusive / Offline** | **0** | EVM RPC remained consistently operational |

### 2.2 Stage-Wise Breakdown

| Stage | Samples | Caught | Detection Rate | Mean Latency | Median (P50) | P95 Latency |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Harvest Origin** | 70 | 70 | **100.00%** | 520.99 ms | 531.40 ms | 711.20 ms |
| **Transport Telemetry** | 90 | 90 | **100.00%** | 518.37 ms | 528.90 ms | 722.10 ms |
| **Retail Store Listing** | 90 | 90 | **100.00%** | 533.72 ms | 542.10 ms | 725.30 ms |
| **Total / Overall** | **250** | **250** | **100.00%** | **524.63 ms** | **535.00 ms** | **719.58 ms** |

### 2.3 Single-Field vs. Multi-Field Detection

* **Single-Field Mutations**: 160 trials evaluated. Detection rate: **100.00%** (160/160).
  * Mutating a single character (e.g., modifying `4.0 °C` to `4.1 °C`, or changing `500 kg` to `501 kg`) completely changes the SHA-256 hex digest due to the cryptographic avalanche effect.
* **Multi-Field Combinations**: 90 trials evaluated. Detection rate: **100.00%** (90/90).
  * Simulating simultaneous coordinate, status, price, and method changes triggered instantaneous detection.

---

## 3. Negative Controls & Protection Boundary Analysis

| Negative Control Scenario | Target Database Field | In Hash? | Expected State | Actual State | Result |
| :--- | :--- | :---: | :---: | :---: | :---: |
| `neg_farmer_certifications` | `FarmerData.certifications` | No | `verified` | `verified` | **PASS** |
| `neg_farmer_notes` | `FarmerData.notes` | No | `verified` | `verified` | **PASS** |
| `neg_transport_timestamp` | `TransportData.timestamp` | No | `verified` | `verified` | **PASS** |
| `neg_retail_updated_at` | `RetailData.updated_at` | No | `verified` | `verified` | **PASS** |

### Critical Architectural Finding
* **Total Negative Control Trials**: 40 trials across 10 batches.
* **Correctly Remained `verified`**: 40 / 40 (**100.00%**).
* **False Tamper Alarms**: **0**.
* **Research Insight**: A cryptographic hash protects **only the fields explicitly serialized into its canonical payload**. Modifying `farmer_data.certifications` or `transport_data.timestamp` does NOT alter the hash because those attributes were excluded from `compute_batch_hash()` and `compute_transport_hash()`.
* **Recommendation**: In a future V3 revision, if organic certification bodies require immutable certification auditing, `certifications` should be integrated directly into the canonical payload of `compute_batch_hash()`.

---

## 4. Latency Characteristics

* Verification of tampered records requires identical compute overhead to authentic verification: fetching on-chain hashes via RPC (`inspect_batch_on_chain`), recalculating local hashes, and loading `StageSnapshot` to extract field-level diffs.
* Verification latency remained tightly bounded with a mean of **524.63 ms** and a P95 of **719.58 ms** on local Ganache.

