# TrustHarvest — Phase 4 Reproducibility Guide

This document provides exact specifications, environmental configurations, dependencies, and execution commands required to independently reproduce every Phase 4 experiment (E1 through E6) from scratch.

---

## 1. System & Environment Specifications

| Component | Verified Specification |
| :--- | :--- |
| **Operating System** | Windows 11 / Windows Server x64 |
| **Repository URL** | `https://github.com/DakshDhaundiyal/blockchain.git` |
| **Git Branch** | `research/phase4-baseline-experiments` |
| **Base Commit Hash** | `3c596359b9459e7170ed59d20154378b370a10f5` |
| **Python Version** | Python `3.11.9` |
| **Solidity Compiler** | `solc 0.8.19` (via `py-solc-x`) |
| **Local EVM Node** | `ganache v7.9.2` (@ganache/cli: 0.10.2, @ganache/core: 0.10.2) |
| **EVM Chain ID** | `1337` (Network ID: `1337`) |
| **RPC Host & Port** | `http://127.0.0.1:7545` |
| **Active Contract Address** | `0x6bbAcD565E12B91E9214E5e00650D46d4b13676E` (Contract Version: `V2`) |
| **Isolated Research DB** | `research/phase4/data/research_phase4.db` (SQLite) |

---

## 2. Environment Setup Commands

### 2.1 Clone Repository & Switch Branch
```powershell
git clone https://github.com/DakshDhaundiyal/blockchain.git
cd blockchain
git checkout research/phase4-baseline-experiments
```

### 2.2 Create Virtual Environment & Install Dependencies
```powershell
python -m venv venv
& ".\venv\Scripts\python.exe" -m pip install --upgrade pip
& ".\venv\Scripts\python.exe" -m pip install -r requirements.txt
& ".\venv\Scripts\python.exe" -m pip install matplotlib pytest
```

### 2.3 Start Local Ganache EVM Node
In an independent terminal:
```powershell
npx ganache -p 7545 -h 127.0.0.1 --chain.chainId 1337 --chain.networkId 1337
```

### 2.4 Verify Smart Contract Deployment
The active contract `0x6bbAcD565E12B91E9214E5e00650D46d4b13676E` is defined in `config.json`. To verify connectivity:
```powershell
& ".\venv\Scripts\python.exe" -c "from blockchain import get_w3, load_config; w3 = get_w3(); cfg = load_config(); print('Connected:', w3.is_connected(), 'Contract:', cfg['contract_address'])"
```

---

## 3. Step-by-Step Experiment Reproduction Commands

All experiment scripts run out of the project root and automatically bind to the isolated research database `research/phase4/data/research_phase4.db`.

### Experiment E1: Baseline Verification
```powershell
& ".\venv\Scripts\python.exe" research/phase4/run_baseline.py
```
- **Outputs**: `research/phase4/results/baseline_verification.csv`, `research/phase4/results/baseline_summary.json`
- **Expected Outcome**: 120 / 120 trials `verified`, 0 errors, mean latency ~169 ms.

### Experiment E2: Controlled Tampering Detection
```powershell
& ".\venv\Scripts\python.exe" research/phase4/run_tampering.py
```
- **Outputs**: `research/phase4/results/tampering_experiments.csv`, `research/phase4/results/tampering_summary.json`
- **Expected Outcome**: 250 / 250 tampering trials caught (`tampered`), 40 / 40 negative controls `verified`.

### Experiment E3: Snapshot Integrity & Diagnosis
```powershell
& ".\venv\Scripts\python.exe" research/phase4/run_snapshot_tests.py
```
- **Outputs**: `research/phase4/results/snapshot_experiments.csv`, `research/phase4/results/snapshot_summary.json`
- **Expected Outcome**: 80 / 80 trials passed across 8 adversarial scenarios, 100% collusion detection.

### Experiment E4: Failure Modes & Availability
```powershell
& ".\venv\Scripts\python.exe" research/phase4/run_failure_tests.py
```
- **Outputs**: `research/phase4/results/failure_experiments.csv`, `research/phase4/results/failure_summary.json`
- **Expected Outcome**: 45 / 50 expected matches (zero false tamper alarms under RPC offline; positional shift on extra on-chain stage).

### Experiment E5: Multi-Checkpoint Scaling
```powershell
& ".\venv\Scripts\python.exe" research/phase4/run_checkpoint_tests.py
```
- **Outputs**: `research/phase4/results/checkpoint_experiments.csv`, `research/phase4/results/checkpoint_summary.json`
- **Expected Outcome**: 30 / 30 trials passed across 1, 2, 5, 10, 20 checkpoints; linear latency scaling.

### Experiment E6: Performance & Scalability
```powershell
& ".\venv\Scripts\python.exe" research/phase4/run_performance.py
```
- **Outputs**: `research/phase4/results/performance_experiments.csv`, `research/phase4/results/performance_summary.json`
- **Expected Outcome**: 1,170 evaluated batches across 10–200 workload sizes with 3 repetitions; sustained ~2.3 batches/s throughput.

### Publication Figures Generation
```powershell
& ".\venv\Scripts\python.exe" research/phase4/generate_figures.py
```
- **Outputs**: 8 PNG (300 DPI) and 8 vector PDF figures in `research/phase4/figures/`.

### Automated Test Suite Execution
```powershell
& ".\venv\Scripts\python.exe" -m pytest tests/ research/phase4/tests/ -v
```
- **Expected Outcome**: Exactly 67 passed, 0 failed in ~49 seconds.

---

## 4. Database Schema Reference

The research database maintains the following SQLAlchemy relational schema:
1. `users`: User identity and credentials (`id`, `username`, `password_hash`, `role`, `contact`, `created_at`).
2. `products`: Batch parent entity (`id`, `batch_id`, `name`, `quantity`, `farming_method`, `packaging_date`, `farmer_id`, `image`, `qr_code`, `on_chain_hash`, `tx_hash`, `block_number`, `contract_address`, `contract_version`, `signer_address`, `status`, `created_at`).
3. `farmer_data`: Harvest specifications (`id`, `batch_id`, `product_name`, `quantity`, `farming_method`, `harvest_date`, `packaging_date`, `certifications`).
4. `transport_data`: Logistics checkpoints (`id`, `product_id`, `transporter_id`, `status`, `current_location`, `temperature`, `vehicle_number`, `notes`, `on_chain_hash`, `tx_hash`, `block_number`, `signer_address`, `timestamp`).
5. `retail_data`: Retail store entries (`id`, `product_id`, `retailer_id`, `store_name`, `store_location`, `price`, `stock_quantity`, `arrival_date`, `shelf_life`, `on_chain_hash`, `tx_hash`, `block_number`, `signer_address`, `updated_at`).
6. `stage_snapshots`: Immutable local snapshots (`id`, `product_id`, `stage`, `transport_id`, `original_hash`, `snapshot_json`, `created_at`).

