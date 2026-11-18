import os
import shutil
import zipfile
import subprocess
import json

def main():
    repo_root = os.path.abspath(os.path.dirname(__file__))
    print(f"=== TRUSTHARVEST RESEARCH PACKAGE BUILDER ===")
    print(f"Repository Root: {repo_root}")

    # 1. Pre-flight Checks
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo_root).decode().strip()
    branch = subprocess.check_output(['git', 'branch', '--show-current'], cwd=repo_root).decode().strip()
    print(f"Git Branch: {branch}")
    print(f"Git Commit: {commit}")

    staging_dir = os.path.join(repo_root, "TrustHarvest_Phase4_Research_Package")
    zip_path = os.path.join(repo_root, "TrustHarvest_Phase4_Research_Package.zip")

    if os.path.exists(staging_dir):
        shutil.rmtree(staging_dir)
    os.makedirs(staging_dir, exist_ok=True)

    # 2. Prepare REPRODUCIBILITY.md at staging root
    src_repro = os.path.join(repo_root, "research", "phase4", "REPRODUCIBILITY.md")
    dst_repro = os.path.join(staging_dir, "REPRODUCIBILITY.md")
    if os.path.exists(src_repro):
        shutil.copy2(src_repro, dst_repro)
        print("Copied REPRODUCIBILITY.md to package root")

    # 3. Create RESEARCH_HANDOVER.md at staging root
    handover_content = f"""# TrustHarvest Phase 4 Research Handover Document

## 1. Executive Summary & Repository Metadata
- **Project**: TrustHarvest — Decentralized Agricultural Supply Chain Provenance System
- **Repository**: https://github.com/DakshDhaundiyal/blockchain.git
- **Git Branch**: `{branch}`
- **Commit Hash**: `{commit}`
- **Environment**:
  - Python: `3.11.9`
  - Solidity: `solc 0.8.19` (py-solc-x) / `0.8.20`
  - Ganache: `v7.9.2` (@ganache/cli: 0.10.2, @ganache/core: 0.10.2)
  - EVM Chain ID: `1337` (Network ID: 1337)
  - Active Contract Address: `0x6bbAcD565E12B91E9214E5e00650D46d4b13676E` (Contract Version: V2)
  - Isolated Research Database: `research/phase4/data/research_phase4.db`

---

## 2. Implemented Features & Architecture
TrustHarvest provides end-to-end food provenance tracking using a hybrid Web2/Web3 architecture:
1. **Relational Database Tier**: SQLite storing entity records across `products`, `farmer_data`, `transport_data`, and `retail_data`.
2. **Deterministic Hashing Engine**: SHA-256 state serialization using pipe-delimited canonical representations:
   - Harvest: `batch_id|product_name|quantity|farming_method|harvest_date|packaging_date`
   - Transport: `batch_id|stage_name|location|temperature|vehicle_number`
   - Retail: `batch_id|store_name|location|price|stock_quantity|arrival_date|shelf_life`
3. **Smart Contract Tier (`TrustHarvestV2.sol`)**:
   - `storeHash(batchId, hash)`: Anchors harvest batch root hash.
   - `addStageHash(batchId, stage, hash)`: Records sequential supply chain checkpoint hashes.
   - `verifyBatch(batchId, clientHash)`: Constant-time comparison between stored root and client state.
   - `getBatchStages(batchId)`: Retrieves on-chain checkpoint stage tuples.
4. **Three-State Verification Pipeline**:
   - `verified`: On-chain hash matches local state.
   - `tampered`: Local hash mismatches on-chain record.
   - `cannot_verify`: Graceful degradation upon network outages, node timeouts, missing anchors, or invalid signatures.
5. **Local Snapshot Engine**:
   - Off-chain JSON snapshots stored in `stage_snapshots` capture point-in-time state upon stage commitment.
   - Snapshot hash is validated against on-chain hash to provide collision-resistant field-level discrepancy attribution.

---

## 3. Actual Experimental Trial Counts & Verified Metrics (E1–E6)

| Experiment | Focus | Trials | Success Rate | Detection Rate | Mean Latency | Key Empirical Finding |
| :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| **E1** | Baseline Authenticity | 120 | 100.0% | N/A (0 tampered) | 169.49 ms | 100% verification accuracy on unmodified records. |
| **E2** | Controlled Tampering | 290 | 100.0% | 100.0% (250/250) | 525.95 ms | 100% sensitivity on hashed fields; 0 false alarms on unhashed fields. |
| **E3** | Snapshot Diagnosis | 80 | 100.0% | 100.0% | 212.44 ms | 100% field diagnostic F1 score; DB+snapshot collusion defeated. |
| **E4** | Failure Modes & Robustness | 50 | 90.0%* | N/A (0 false alerts) | 184.20 ms | 0 false tamper alerts under RPC loss/reverts; positional vulnerability identified. |
| **E5** | Multi-Checkpoint Scaling | 30 | 100.0% | 100.0% | 285.98 ms | Linear O(N) latency growth (~22.5 ms per additional checkpoint). |
| **E6** | Performance & Scalability | 1,170 | 100.0% | N/A (authentic set) | 214.28 ms | 2.01–2.36 batches/sec throughput; 99.8% latency spent in RPC I/O. |
| **Total** | **All Trials Audited** | **1,740** | — | — | — | **All raw CSVs and summary JSONs match 100%**. |

*\*Note on E4: 45/50 matched expected output; 5 trials in scenario e4_3_extra_transport_onchain produced tampered instead of cannot_verify due to positional array-index alignment shift.*

---

## 4. Gas & Performance Measurements

### 4.1 Smart Contract Gas Consumption
- `storeHash()`: **163,382 gas** (14-char batch ID) / **163,442 gas** (18-char batch ID).
- `addStageHash()`: **190,612 gas** (14-char batch ID) / **190,672 gas** (18-char batch ID).
- Calldata delta: Exactly +60 gas for +4 characters ($4 \\times 16 - 4$ packing adjustment).

### 4.2 Latency Component Decomposition (E6 Benchmark)
- Local SHA-256 CPU hashing: **0.19 ms (0.09%)**
- EVM JSON-RPC Network I/O: **209.23 ms (99.8%)**
- Application Context Logic: **~1.5 ms (0.1%)**
- System Throughput: **2.01 to 2.36 batches/second** on single-threaded synchronous Python.

---

## 5. Security Insights, Vulnerabilities, & Known Limitations
1. **Positional Matching Vulnerability**: Checkpoint matching between local DB and on-chain records relies on sequential array index matching. Appending extraneous on-chain stages shifts array alignment, flagging authentic subsequent stages as `tampered` rather than identifying an unanchored/foreign stage.
2. **Protection Boundaries**: Certain metadata fields (`FarmerData.certifications`, `FarmerData.notes`, `TransportData.timestamp`, `RetailData.updated_at`) are excluded from SHA-256 hashing. Modifying these fields does not trigger tamper alarms.
3. **RPC Roundtrip Bottleneck**: Sequential synchronous `eth_call` RPCs dominate latency (99.8%). High-throughput production deployments require Multicall3 (EIP-1822) or batched RPC multicalls.
4. **Sepolia Deployment**: Gated and unverified. All experimental measurements were conducted on local Ganache (`CHAIN_ID=1337`) in strict adherence to Safety Rule #4.
"""
    handover_path = os.path.join(staging_dir, "RESEARCH_HANDOVER.md")
    with open(handover_path, "w", encoding="utf-8") as f:
        f.write(handover_content)
    print("Created RESEARCH_HANDOVER.md in package root")

    # Also keep a copy in research/phase4/ for completeness
    shutil.copy2(handover_path, os.path.join(repo_root, "research", "phase4", "RESEARCH_HANDOVER.md"))

    # 4. Copy Application Source Code
    app_files = [
        "app.py",
        "blockchain.py",
        "models.py",
        "seed.py",
        "requirements.txt",
        "README.md",
        "TrustHarvest_Comprehensive_Project_Overview.pdf"
    ]
    for af in app_files:
        src = os.path.join(repo_root, af)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(staging_dir, af))
            print(f"Copied {af}")

    # Copy directories: contracts, docs, tests, templates, static
    dirs_to_copy = ["contracts", "docs", "tests", "templates", "static"]
    for d in dirs_to_copy:
        src_d = os.path.join(repo_root, d)
        dst_d = os.path.join(staging_dir, d)
        if os.path.exists(src_d):
            shutil.copytree(src_d, dst_d, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".git*"))
            print(f"Copied directory {d}/")

    # 5. Copy entire research/phase4 directory
    src_res = os.path.join(repo_root, "research", "phase4")
    dst_res = os.path.join(staging_dir, "research", "phase4")
    shutil.copytree(src_res, dst_res, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".git*"))
    print(f"Copied complete research/phase4/ framework")

    # 6. Audit Staging Directory for Forbidden Items
    forbidden_terms = [".env", "venv", ".venv", "node_modules", ".git", "__pycache__"]
    found_forbidden = []
    total_files = 0
    for root, dirs, files in os.walk(staging_dir):
        for d in list(dirs):
            if any(term in d for term in forbidden_terms):
                shutil.rmtree(os.path.join(root, d))
                print(f"Removed forbidden dir: {d}")
        for f in files:
            p = os.path.join(root, f)
            if any(term in f for term in forbidden_terms) or f.endswith(".pyc") or f == ".env":
                os.remove(p)
                print(f"Removed forbidden file: {f}")
            else:
                total_files += 1

    print(f"Total staged files ready for archiving: {total_files}")

    # 7. Create ZIP archive
    print(f"Creating ZIP archive: {zip_path}")
    if os.path.exists(zip_path):
        os.remove(zip_path)

    with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(staging_dir):
            for file in files:
                abs_file = os.path.join(root, file)
                rel_file = os.path.relpath(abs_file, staging_dir)
                # Store under TrustHarvest_Phase4_Research_Package/
                archive_name = os.path.join("TrustHarvest_Phase4_Research_Package", rel_file)
                zipf.write(abs_file, archive_name)

    # 8. Post-Flight Integrity Verification
    if not os.path.exists(zip_path):
        print("ERROR: ZIP was not created!")
        return False

    zip_size_bytes = os.path.getsize(zip_path)
    zip_size_mb = zip_size_bytes / (1024 * 1024)
    print(f"ZIP Size: {zip_size_mb:.2f} MB ({zip_size_bytes:,} bytes)")

    with zipfile.ZipFile(zip_path, 'r') as zipf:
        test_result = zipf.testzip()
        infolist = zipf.infolist()
        namelist = zipf.namelist()

    integrity_status = "PASS" if test_result is None else f"FAIL (Corrupt: {test_result})"
    print(f"ZIP Integrity Test: {integrity_status}")
    print(f"Total Archived Files: {len(infolist)}")

    # Verify crucial files inside ZIP
    must_have = [
        "TrustHarvest_Phase4_Research_Package/app.py",
        "TrustHarvest_Phase4_Research_Package/blockchain.py",
        "TrustHarvest_Phase4_Research_Package/models.py",
        "TrustHarvest_Phase4_Research_Package/contracts/TrustHarvestV2.sol",
        "TrustHarvest_Phase4_Research_Package/contracts/TrustHarvestV2.abi.json",
        "TrustHarvest_Phase4_Research_Package/REPRODUCIBILITY.md",
        "TrustHarvest_Phase4_Research_Package/RESEARCH_HANDOVER.md",
        "TrustHarvest_Phase4_Research_Package/research/phase4/results/PHASE4_EVIDENCE_AUDIT.md",
        "TrustHarvest_Phase4_Research_Package/research/phase4/results/PHASE4_FINAL_REPORT.md",
        "TrustHarvest_Phase4_Research_Package/research/phase4/results/baseline_verification.csv",
        "TrustHarvest_Phase4_Research_Package/research/phase4/results/baseline_summary.json",
        "TrustHarvest_Phase4_Research_Package/research/phase4/results/tampering_experiments.csv",
        "TrustHarvest_Phase4_Research_Package/research/phase4/results/tampering_summary.json",
        "TrustHarvest_Phase4_Research_Package/research/phase4/results/snapshot_experiments.csv",
        "TrustHarvest_Phase4_Research_Package/research/phase4/results/snapshot_summary.json",
        "TrustHarvest_Phase4_Research_Package/research/phase4/results/failure_experiments.csv",
        "TrustHarvest_Phase4_Research_Package/research/phase4/results/failure_summary.json",
        "TrustHarvest_Phase4_Research_Package/research/phase4/results/checkpoint_experiments.csv",
        "TrustHarvest_Phase4_Research_Package/research/phase4/results/checkpoint_summary.json",
        "TrustHarvest_Phase4_Research_Package/research/phase4/results/performance_experiments.csv",
        "TrustHarvest_Phase4_Research_Package/research/phase4/results/performance_summary.json"
    ]

    missing = []
    for mh in must_have:
        # Normalize slashes for zip namelist
        normalized = mh.replace('\\', '/')
        if not any(n.replace('\\', '/') == normalized for n in namelist):
            missing.append(mh)

    print(f"Must-Have Files Check: {'ALL FOUND' if not missing else 'MISSING: ' + str(missing)}")

    # Check for forbidden entries
    forbidden_in_zip = [n for n in namelist if any(term in n for term in [".env", "venv/", ".git/", "__pycache__", ".pyc"])]
    print(f"Forbidden Entries in ZIP: {'NONE (Clean)' if not forbidden_in_zip else str(forbidden_in_zip)}")

    # Print top-level folders in zip
    top_levels = set()
    for n in namelist:
        parts = n.replace('\\', '/').split('/')
        if len(parts) > 1:
            top_levels.add(parts[0] + '/' + parts[1])
        else:
            top_levels.add(parts[0])
    print("Archive Structure Summary:")
    for tl in sorted(top_levels):
        print(f"  - {tl}")

    return True

if __name__ == "__main__":
    main()

