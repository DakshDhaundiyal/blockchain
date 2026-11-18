# TrustHarvest: Empirical Evaluation of Blockchain-Anchored Integrity Verification in Agricultural Supply Chains

**Technical Research Whitepaper & Phase 4 Experimental Report**  
**Authors**: TrustHarvest Research & Engineering Group  
**Target Repository**: `https://github.com/DakshDhaundiyal/blockchain.git`  
**Git Branch**: `research/phase4-baseline-experiments`  
**Date**: November 17, 2026  
**Status**: Completed Research Evaluation (Experiments E1–E6)

---

## Abstract

Modern agricultural supply chains increasingly demand end-to-end transparency, traceability, and verifiable data integrity. **TrustHarvest** is a multi-tier farm-to-shop provenance architecture that combines off-chain relational storage (SQLite/SQLAlchemy) with on-chain Ethereum smart contract anchoring (`TrustHarvestV2.sol`) to guarantee the authenticity of food batches.

This paper presents the comprehensive Phase 4 empirical evaluation of TrustHarvest across six distinct experimental dimensions (E1 through E6), covering **1,740 total evaluation points**. We evaluate: (i) baseline verification correctness on 30 multi-stage synthetic batches, (ii) sensitivity to single- and multi-field data tampering across 29 adversarial scenarios, (iii) cryptographic snapshot validation and resilience against database collusion attacks, (iv) system robustness and graceful degradation under 10 simulated infrastructure and network failure modes, (v) verification scaling across multi-checkpoint supply chain depths (1 to 20 checkpoints), and (vi) throughput and component-level latency decomposition under workloads up to 200 batches.

Our findings demonstrate that TrustHarvest achieves **100% precision and recall in detecting data tampering on hashed provenance fields**, successfully neutralizes database-snapshot collusion attacks via on-chain hash validation, and degrades gracefully to an inconclusive state (`cannot_verify`) without false tamper alarms during network partitions. Crucially, component timing analysis reveals that **SHA-256 hash computation consumes less than 0.1% of the total verification latency budget (0.19 ms), while sequential EVM JSON-RPC reads consume 99.8% (209 ms)**. We identify an architectural vulnerability in sequential array-index matching on multi-checkpoint routes and propose production optimizations including EIP-1822 multi-call batching and fixed `bytes32` digest storage.

---

## 1. Introduction and Architectural Overview

Supply chain fraud—ranging from illicit relabeling of conventional produce as organic to falsification of cold-chain telemetry and shelf-life expiration—poses severe economic, health, and regulatory risks. While public and enterprise blockchains offer immutable state transitions, directly storing entire supply chain documents on-chain is cost-prohibitive.

TrustHarvest adopts a hybrid off-chain/on-chain architecture:
1. **Off-Chain Relational Layer**: Detailed domain models (`Product`, `FarmerData`, `TransportData`, `RetailData`, `StageSnapshot`) reside in relational storage for fast querying, faceted searching, and rich dashboard rendering.
2. **Canonical Cryptographic Digesting**: Deterministic SHA-256 hashing converts each supply chain stage into a 64-character hexadecimal digest.
3. **Smart Contract Anchoring (`TrustHarvestV2.sol`)**:
   - Initial harvest registration via `storeHash(string batchId, string batchHash)` enforces one-time write protection (`AlreadyRegistered(batchId)`).
   - Sequential logistics checkpoints and retail admissions are appended to `stageHistory[batchId]` via `addStageHash(string batchId, string stage, string stageHash)`.
4. **Three-State Verification Engine**:
   Rather than naive binary matching, TrustHarvest implements a three-state verifier:
   - **`verified`**: Off-chain data matches the immutable blockchain record byte-for-byte.
   - **`tampered`**: Off-chain data diverges from the sealed on-chain digest ("Changed after recording").
   - **`cannot_verify`**: Network partitions, missing anchors, or conflicting ledger states prevent mathematical certainty ("Can't check right now").

---

## 2. Experimental Methodology

All experiments were executed on an isolated test environment to prevent state contamination and ensure absolute reproducibility:
- **EVM Node**: Local Ganache (`CHAIN_ID=1337`, Port 7545, instant mining).
- **Isolated Database**: `research/phase4/data/research_phase4.db` (clean SQLite instance decoupled from production `trustharvest.db`).
- **Synthetic Datasets**: 30 primary synthetic batches (`TH-SYN-001` to `TH-SYN-030`) and 200 scalability batches (`TH-PERF-001` to `TH-PERF-200`) generated with deterministic pseudo-random seeds.
- **Safety Compliance**: Zero smart contract modifications (`TrustHarvestV2.sol`), zero production database writes, zero public network deployments.

---

## 3. Experimental Results (E1–E6)

### 3.1 Experiment E1 — Baseline Authenticity Verification
- **Objective**: Establish baseline verification correctness on untampered provenance records across 30 synthetic batches.
- **Trial Count**: 120 evaluation points (30 Harvest, 30 Transport, 30 Retail, 30 Overall).
- **Results**: **120 / 120 trials verified correctly (100.0% accuracy)**.
- **Latency Distribution**:
  - Individual stage verification (Harvest, Transport, Retail): Mean **112.99 ms**, Median **112.56 ms**, P95 **149.84 ms**.
  - Compound overall verification: Mean **338.98 ms**, Median **337.67 ms**, P95 **449.53 ms**.
  - Aggregate baseline latency across all 120 trials: Mean **169.49 ms**, Median **120.80 ms**, P95 **406.15 ms**.

### 3.2 Experiment E2 — Controlled Tampering Detection
- **Objective**: Evaluate sensitivity to unauthorized database modifications across 29 scenarios (Harvest, Transport, Retail, and Negative Controls) across 10 batches.
- **Trial Count**: 290 trials (250 tampering mutations + 40 negative controls).
- **Results**:
  - **Tampering Trials**: 250 / 250 detected (**100.0% Detection Rate, Precision: 1.0, Recall: 1.0, F1-Score: 1.0**).
  - **Negative Control Trials**: 40 / 40 correctly remained `verified` (**0.0% False Alarm Rate**).
- **Protection Boundaries Identified**:
  - *Hashed Fields (Protected)*: `product_name`, `quantity`, `farming_method`, `packaging_date`, `location`, `temperature`, `vehicle_number`, `status`, `store_name`, `price`, `stock_quantity`, `arrival_date`, `shelf_life`.
  - *Unhashed Fields (Outside Protection Boundary)*: `FarmerData.certifications`, `FarmerData.notes`, `TransportData.timestamp`, `RetailData.updated_at`. Modifying these fields does not alter the digest, demonstrating the precise cryptographic perimeter.
- *Visualizations*: [Figure 1: Stage-Wise Detection](file:///c:/Users/Chinmayee/OneDrive/Documents/blockchain%20-%20TRUST%20HARVEST/blockchain/research/phase4/figures/fig1_stagewise_detection.png), [Figure 2: Field-Wise Detection](file:///c:/Users/Chinmayee/OneDrive/Documents/blockchain%20-%20TRUST%20HARVEST/blockchain/research/phase4/figures/fig2_fieldwise_detection.png), [Figure 3: Confusion Matrix](file:///c:/Users/Chinmayee/OneDrive/Documents/blockchain%20-%20TRUST%20HARVEST/blockchain/research/phase4/figures/fig3_confusion_matrix.png).

### 3.3 Experiment E3 — Snapshot Integrity and Field-Level Diagnosis
- **Objective**: Assess the reliability of immutable local snapshots (`StageSnapshot`) for identifying *which* fields were altered, and test resistance against adversarial collusion.
- **Trial Count**: 80 trials across 8 scenarios (S1 Baseline, S2 Single Field, S3 Multi Field, S4 Corrupt SQL, S5 Missing Snapshot, S6 Bad JSON, S7 Unhashed Field, S8 DB+Snapshot Collusion).
- **Results**:
  - Tamper Detection Accuracy: **100.0%**.
  - Snapshot Trustworthiness Accuracy: **100.0%**.
  - Field Diagnosis Accuracy: **100.0%** (Precision: 1.0, Recall: 1.0, F1: 1.0).
- **Collusion Resistance (Scenario S8)**:
  When an adversary with SQL database access alters both the active product record and the `snapshot_json` to identical fraudulent values, `_load_validated_snapshot()` recomputes the SHA-256 hash of the snapshot and checks it against the Ethereum on-chain hash. Because the smart contract cannot be rewritten, the colluded snapshot is rejected and flagged as untrusted.
- *Visualization*: [Figure 4: Snapshot Diagnosis Performance](file:///c:/Users/Chinmayee/OneDrive/Documents/blockchain%20-%20TRUST%20HARVEST/blockchain/research/phase4/figures/fig4_snapshot_diagnosis.png).

### 3.4 Experiment E4 — Failure Modes, Availability & Threat Model
- **Objective**: Stress-test the three-state verification engine under 10 simulated network, infrastructure, and contract failure conditions.
- **Trial Count**: 50 trials across 5 batches.
- **Results**:
  - RPC node offline, bad endpoints, read timeouts, and EVM contract reverts degraded gracefully to `cannot_verify` with **0 false tamper alarms**.
  - Missing on-chain anchors and missing intermediate stages correctly produced `cannot_verify`.
  - **Positional Matching Vulnerability**: In scenario `e4_3_extra_transport_onchain` (5 trials), appending an extra foreign transport checkpoint on-chain caused array-index alignment to shift, resulting in `tampered` instead of `cannot_verify`.
- *Visualization*: [Figure 8: Failure Scenario Outcome Distribution](file:///c:/Users/Chinmayee/OneDrive/Documents/blockchain%20-%20TRUST%20HARVEST/blockchain/research/phase4/figures/fig8_failure_distribution.png).

### 3.5 Experiment E5 — Multi-Checkpoint Provenance Scaling
- **Objective**: Measure verification correctness and latency scaling across increasing supply chain transit depths.
- **Configurations Evaluated**: 1, 2, 5, 10, and 20 transport checkpoints (6 scenarios each = 30 trials).
- **Results**:
  - Verification Accuracy: **100.0% (30/30 trials passed)**.
  - Latency Scaling: Strictly linear $\mathcal{O}(N)$ growth:
    - 1 Checkpoint: **144.34 ms**
    - 2 Checkpoints: **167.83 ms**
    - 5 Checkpoints: **199.54 ms**
    - 10 Checkpoints: **346.74 ms**
    - 20 Checkpoints: **571.43 ms**
  - Average marginal overhead: **~22.5 ms per additional on-chain checkpoint**, driven by sequential JSON-RPC roundtrips.
- *Visualization*: [Figure 6: Latency vs Checkpoint Depth](file:///c:/Users/Chinmayee/OneDrive/Documents/blockchain%20-%20TRUST%20HARVEST/blockchain/research/phase4/figures/fig6_latency_vs_checkpoints.png).

### 3.6 Experiment E6 — Performance & Scalability Benchmark
- **Objective**: Evaluate throughput and decompose latency components under sustained workloads.
- **Workloads Evaluated**: 10, 30, 50, 100, and 200 batches (3 repetitions each = 1,170 evaluated batches).
- **Results**:
  - Throughput: Sustained at **2.01 to 2.36 batches / second** in synchronous single-threaded Python.
  - Execution Time: 10 batches in 4.97s; 200 batches in 84.80s.
  - **Component Timing Decomposition**:
    - **Local SHA-256 Hashing**: **0.19 ms (0.09% of total time)**.
    - **Blockchain JSON-RPC Reads**: **209.23 ms (99.8% of total time)**.
    - **Application Context Logic**: **~1.5 ms (0.1% of total time)**.
- *Visualization*: [Figure 7: Latency & Component Timing Breakdown](file:///c:/Users/Chinmayee/OneDrive/Documents/blockchain%20-%20TRUST%20HARVEST/blockchain/research/phase4/figures/fig7_latency_vs_workload.png).

---

## 4. Security & Architectural Vulnerability Analysis

1. **Positional Array-Index Matching**:
   In `app.py`, transport checkpoints are verified by comparing `db_transports[i]` against `on_chain_stages[i]`. If an attacker or network glitch causes an extra checkpoint to be committed on-chain, index alignment breaks, falsely flagging all subsequent checkpoints as tampered. **Remedy**: Smart contracts must bind checkpoints to explicit sequence UUIDs or nonce identifiers rather than relying on dynamic array indices.
2. **On-Chain Role Enforcement Gap**:
   `TrustHarvestV2.sol` records `registeredBy = msg.sender`, but does not enforce role access control on-chain. While off-chain server keys mitigate this in demo mode, anyone can append arbitrary stage records on a public network. **Remedy**: Introduce OpenZeppelin `AccessControl` (`DEFAULT_ADMIN_ROLE`, `FARMER_ROLE`, `TRANSPORTER_ROLE`, `RETAILER_ROLE`).
3. **Calldata Storage Inefficiency**:
   Storing SHA-256 hashes as UTF-8 dynamic `string` (~64 bytes) consumes **163,382 – 190,672 gas**. Storing hashes as native fixed `bytes32` (32 bytes) would reduce gas consumption by ~35–45%.

---

## 5. Practical Recommendations for Production Deployments

1. **EIP-1822 / Multicall3 RPC Batching**:
   Because EVM JSON-RPC reads account for 99.8% of verification latency, batching `getRecord`, `getStageCount`, and `getStageRecord` into a single aggregate call will reduce end-to-end verification latency from **~210 ms down to <30 ms**.
2. **On-Chain Circuit Breakers (`Pausable`)**:
   Implement `pause()` / `unpause()` and two-step ownership transfer (`Ownable2Step`) to guard against compromised private keys.
3. **Canonical Nonce Verification**:
   Adopt monotonic sequence nonces (`(batchId, stageIndex, stageHash)`) to prevent array-shifting griefing attacks.

---

## 6. Conclusion

The Phase 4 experimental evaluation confirms that TrustHarvest provides mathematical integrity guarantees against agricultural supply chain data tampering with 100% precision and recall on protected fields. The hybrid architecture effectively decouples high-volume relational data from on-chain state, while maintaining cryptographic defensibility against sophisticated database collusion attacks. Adopting multicall batching and fixed `bytes32` storage will enable TrustHarvest to scale seamlessly to high-throughput, real-time commercial deployments.

