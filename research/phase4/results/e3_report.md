# Experiment E3 — Snapshot Integrity and Diagnosis Report

**Experiment**: E3 Snapshot Integrity and Field-Level Diagnosis  
**Date**: November 17, 2026  
**Execution Environment**: Local Ganache (`CHAIN_ID=1337`), Isolated Research Database (`research_phase4.db`)  
**Artifacts**:
- Script: `research/phase4/run_snapshot_tests.py`
- Trial Logs: `research/phase4/results/snapshot_experiments.csv` (80 total rows)
- Summary Data: `research/phase4/results/snapshot_summary.json`

---

## 1. Objective and Theoretical Model

In the TrustHarvest architecture, the Ethereum blockchain stores only the 64-character SHA-256 cryptographic digest of each supply chain stage. While this hash proves *that* tampering occurred with 100% mathematical certainty, it cannot independently identify *which specific field* was altered.

To achieve localized diagnosis (e.g. informing a consumer that *Farming Method was changed from Organic to Conventional*), TrustHarvest captures an immutable local `StageSnapshot` captured strictly once at initial blockchain anchoring.

Experiment E3 tests the trustworthiness and failure modes of this snapshot mechanism across 8 rigorous adversarial and edge scenarios across 10 independent batches (80 total trials):
1. **Scenario 1 (Baseline)**: Untampered DB record & valid snapshot.
2. **Scenario 2 (Single Hashed Field)**: One hashed field modified after anchoring.
3. **Scenario 3 (Multiple Hashed Fields)**: Multiple hashed fields modified simultaneously.
4. **Scenario 4 (Independent Snapshot Corruption)**: Attacker modifies `snapshot_json` in the SQL database while leaving the product record authentic.
5. **Scenario 5 (Missing Snapshot)**: Database record is tampered with, but the snapshot row has been deleted.
6. **Scenario 6 (Malformed Snapshot JSON)**: Snapshot contains corrupted, unparseable JSON syntax.
7. **Scenario 7 (Unhashed Field Modified)**: An unhashed database field (`FarmerData.certifications`) is modified.
8. **Scenario 8 (Collusion Attack)**: A sophisticated attacker modifies **both** the database record and the `snapshot_json` to identical fraudulent values, attempting to trick the diff engine.

---

## 2. Experimental Results Summary

| Scenario ID | Scenario Description | Tamper Detected? | Snapshot Valid? | Field Diagnosis Result | Accuracy |
| :---: | :--- | :---: | :---: | :--- | :---: |
| **S1** | Baseline Authentic | No (`verified`) | Yes | 0 diffs correctly identified | **100.0%** |
| **S2** | Single Hashed Field Tampered | Yes (`tampered`) | Yes | Exact altered field diagnosed (`farming_method`) | **100.0%** |
| **S3** | Multi Hashed Fields Tampered | Yes (`tampered`) | Yes | Both fields diagnosed (`farming_method`, `packaging_date`) | **100.0%** |
| **S4** | Snapshot Corrupted in SQL | No (`verified`) | No (Rejected) | Snapshot untrusted; refuses to use for diffs | **100.0%** |
| **S5** | Snapshot Missing | Yes (`tampered`) | No (Missing) | Refuses to guess; reports snapshot unavailable | **100.0%** |
| **S6** | Snapshot Corrupted JSON | Yes (`tampered`) | No (Invalid) | Refuses to guess; reports parse error | **100.0%** |
| **S7** | Unhashed Field Modified | No (`verified`) | Yes | 0 diffs (outside hash boundary) | **100.0%** |
| **S8** | Collusion (DB + Snap Modified) | Yes (`tampered`) | No (Rejected) | Re-validates against on-chain hash; rejects snapshot | **100.0%** |

### Aggregate Diagnosis Metrics

| Metric | Measured Value | Theoretical Significance |
| :--- | :---: | :--- |
| **Total Scenarios Evaluated** | **80 trials** | 8 scenarios $\times$ 10 independent batches |
| **Tamper Detection Accuracy** | **100.00%** | On-chain hash comparison is never bypassed by snapshot tampering |
| **Snapshot Validation Accuracy** | **100.00%** | Every corrupted or colluding snapshot was caught |
| **Field-Level Diagnosis Accuracy** | **100.00%** | When snapshot is authentic, exact fields are isolated |
| **Field Diagnosis Precision** | **100.00%** | $\frac{\text{TP}}{\text{TP}+\text{FP}} = \frac{30}{30}$ |
| **Field Diagnosis Recall** | **100.00%** | $\frac{\text{TP}}{\text{TP}+\text{FN}} = \frac{30}{30}$ |
| **Field Diagnosis F1-Score** | **1.0000** | Perfect localization on valid snapshots |

---

## 3. Key Architectural Findings

### 3.1 Defense Against Collusion Attacks (Scenario 8)
* A critical vulnerability in naive snapshot designs is assuming that local snapshots are immutable. If an attacker has database write access, they can alter both the record and the snapshot to match.
* **TrustHarvest Mitigation**: Before `_compute_changed_fields` is ever executed, `_load_validated_snapshot` recomputes the SHA-256 hash of `parsed` and requires it to match `original_blockchain_hash` from the Ethereum smart contract byte-for-byte (`recomputed.lower() == target_hash_low`).
* Because the attacker cannot rewrite the Ethereum smart contract (`TrustHarvestV2.sol`), the colluded snapshot fails validation and is discarded. The system flags the batch as **Changed after recording** and honestly reports: *"Stored original snapshot did not match the blockchain hash and was rejected."*

### 3.2 Honest Handling of Missing Snapshots (Scenario 5 & 6)
* When a snapshot is missing or corrupted, the system correctly reports that the record has been tampered with on-chain, but refrains from fabricating arbitrary field diffs.
* It presents an explicit warning banner: *"Original field values snapshot is not available for this historical record."* This preserves integrity and eliminates hallucinated diffs.

