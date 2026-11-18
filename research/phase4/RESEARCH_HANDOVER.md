# TrustHarvest Phase 4 Research Handover Document

## 1. Executive Summary & Repository Metadata
- **Project**: TrustHarvest — Decentralized Agricultural Supply Chain Provenance System
- **Repository**: https://github.com/DakshDhaundiyal/blockchain.git
- **Git Branch**: `research/phase4-baseline-experiments`
- **Commit Hash**: `3c596359b9459e7170ed59d20154378b370a10f5`
- **Environment**:
  - Python: `3.11.9`
  - Solidity: `solc 0.8.19` (py-solc-x)
  - Ganache: `v7.9.2` (@ganache/cli: 0.10.2, @ganache/core: 0.10.2)
  - EVM Chain ID: `1337` (Network ID: 1337)
  - Active Contract Address: `0x6bbAcD565E12B91E9214E5e00650D46d4b13676E` (Contract Version: V2)
  - Isolated Research Database: `research/phase4/data/research_phase4.db`

---

## 2. Implemented Features & Architecture
TrustHarvest provides end-to-end food provenance tracking using a hybrid Web2/Web3 architecture:
1. **Relational Database Tier**: SQLite storing entity records across `products`, `farmer_data`, `transport_data`, and `retail_data`.
2. **Deterministic Hashing Engine**: Canonical UTF-8 JSON key-sorted string serialization (`json.dumps(data, sort_keys=True)`):
   - Harvest: `batch_id`, `farmer_id`, `farming_method`, `image`, `name`, `packaging_date`, `quantity`.
   - Transport: `batch_id`, `current_location`, `notes`, `stage` ("TRANSPORT"), `status`, `temperature`, `transporter_id`, `vehicle_number`.
   - Retail: `arrival_date`, `batch_id`, `price` (normalized to `%.2f`), `retailer_id`, `shelf_life`, `stage` ("RETAIL"), `stock_quantity`, `store_location`, `store_name`.
3. **Smart Contract Tier (`TrustHarvestV2.sol`)**:
   - `storeHash(string batchId, string batchHash)`: Anchors harvest batch root hash (one-time write).
   - `addStageHash(string batchId, string stage, string stageHash)`: Appends sequential supply chain checkpoint hashes.
   - `getHash(string batchId)`: Returns root hash.
   - `getRecord(string batchId)`: Returns root hash, origin address, timestamp, and exists boolean.
   - `getStageCount(string batchId)`: Returns number of appended stage records.
   - `getStageRecord(string batchId, uint256 index)`: Returns stage name, stage hash, signer address, and timestamp.
4. **Three-State Verification Pipeline (Off-Chain in Python)**:
   - `verified`: On-chain hash matches local state.
   - `tampered`: Local hash mismatches on-chain record.
   - `cannot_verify`: Graceful degradation upon network outages, node timeouts, missing anchors, or invalid signatures.
5. **Local Snapshot Engine**:
   - Off-chain JSON snapshots stored in `stage_snapshots` capture point-in-time state upon stage commitment.
   - Snapshot hash is validated against on-chain hash to provide collision-resistant field-level discrepancy attribution. (Evaluated specifically on harvest snapshots in E3).

---

## 3. Actual Experimental Trial Counts & Verified Metrics (E1–E6)

| Experiment | Focus | Trials | Success Rate | Detection Rate | Mean Latency | Key Empirical Finding |
| :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| **E1** | Baseline Authenticity | 120 | 100.0% | N/A (0 tampered) | 169.49 ms | 100% verification accuracy on unmodified records. |
| **E2** | Controlled Tampering | 290 | 100.0% | 100.0% (250/250) | 525.95 ms | 100% sensitivity on hashed fields; 0 false alarms on unhashed fields. |
| **E3** | Snapshot Diagnosis | 80 | 100.0% | 100.0% | 212.44 ms | 100% field diagnostic accuracy on tested harvest snapshots; DB+snapshot collusion defeated. |
| **E4** | Failure Modes & Robustness | 50 | 90.0%* | N/A (0 false alerts) | 184.20 ms | 0 false tamper alerts under RPC loss/reverts; positional vulnerability identified. |
| **E5 (Run 2)**| Multi-Checkpoint Scaling | 30 | 100.0% | 100.0% | 285.98 ms | Monotonically increasing empirical latency (~144 ms to ~571 ms). |
| **E5 (Run 3)**| Multi-Checkpoint Clean Run 3 | 30 | 100.0% | 100.0% | 272.84 ms | Independent validation confirming Run 2 findings (~115 ms to ~625 ms). |
| **E6** | Performance & Scalability | 1,170 | 100.0% | N/A (authentic set) | 214.28 ms | 2.01–2.36 batches/sec throughput; network RPC I/O is dominant factor. |

*\*Note on E4: 45/50 matched expected output; 5 trials in scenario e4_3_extra_transport_onchain produced tampered instead of cannot_verify due to positional array-index alignment shift.*

---

## 4. Gas & Performance Measurements

### 4.1 Smart Contract Gas Consumption
- `storeHash()`: **163,382 gas** (14-char batch ID) / **163,442 gas** (18-char batch ID).
- `addStageHash()`: **190,612 gas** (14-char batch ID) / **190,672 gas** (18-char batch ID).
- Calldata delta: Exactly $+60$ gas for $+4$ characters ($4 \times 16 - 4$ packing adjustment).

### 4.2 Latency Component Decomposition (E6 Benchmark)
- Local SHA-256 CPU hashing: **0.18–0.20 ms** (< 0.1% of total latency).
- Mean verification latency: **~208–246 ms** per batch on local Ganache.
- System Throughput: **2.01 to 2.36 batches/second** on single-threaded synchronous Python.
- Measurement Note: Negative calculated overhead values in some workload sets (-1.33 ms in 50-batch, -0.57 ms in 200-batch) resulted from inter-call socket I/O jitter between separate, non-nested timer invocations.

---

## 5. Security Insights, Vulnerabilities, & Known Limitations
1. **Positional Matching Vulnerability**: Checkpoint matching between local DB and on-chain records relies on sequential array index matching. Appending extraneous on-chain stages shifts array alignment, flagging authentic subsequent stages as `tampered` rather than identifying an unanchored/foreign stage.
2. **Protection Boundaries**: Certain metadata fields (`FarmerData.certifications`, `FarmerData.notes`, `TransportData.timestamp`, `RetailData.updated_at`) are excluded from SHA-256 hashing. Modifying these fields does not trigger tamper alarms.
3. **RPC Roundtrip Bottleneck**: Sequential synchronous `eth_call` RPCs dominate latency. High-throughput production deployments require batched JSON-RPC multicalls (e.g., using Multicall3).
4. **Snapshot Scope Limitation**: Snapshot validation in E3 was evaluated strictly on the harvest stage. Transport and retail snapshots were not covered.
5. **Sepolia Deployment**: Gated and unverified. All experimental measurements were conducted on local Ganache (`CHAIN_ID=1337`) in strict adherence to Safety Rule #4.
