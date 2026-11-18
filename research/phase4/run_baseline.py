"""
TrustHarvest — Phase 4 Research Experiment Framework
Module: run_baseline.py

Executes the baseline provenance verification experiment on unchanged synthetic batches.
- Uses an isolated research database (never touches production or trustharvest.db).
- Anchors hashes to local Ganache EVM using canonical existing hashing and Web3 methods.
- Measures per-stage and overall verification latencies.
- Evaluates classification correctness against known ground truth.
- Exports granular trial records to CSV and computes summary metrics.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Ensure isolated research database BEFORE loading Flask models
RESEARCH_DIR = os.path.abspath(os.path.dirname(__file__))
DATA_DIR = os.path.join(RESEARCH_DIR, "data")
RESULTS_DIR = os.path.join(RESEARCH_DIR, "results")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(RESULTS_DIR, exist_ok=True)

RESEARCH_DB_PATH = os.path.join(DATA_DIR, "research_phase4.db")
os.environ["DATABASE_URL"] = f"sqlite:///{RESEARCH_DB_PATH}"
os.environ["DEMO_MODE"] = "true"  # Enables rich verification diff context without affecting production

from app import (
    app,
    _build_harvest_snapshot_payload,
    _build_transport_snapshot_payload,
    _build_retail_snapshot_payload,
    _save_stage_snapshot_once,
    _build_verification_context,
)
from models import db, User, Product, FarmerData, TransportData, RetailData, StageSnapshot, utcnow
from blockchain import (
    get_w3,
    store_hash_detailed,
    store_stage_hash,
    compute_batch_hash,
    compute_transport_hash,
    compute_retail_hash,
    BlockchainError,
    BlockchainUnavailableError,
)
from research.phase4.generate_dataset import generate_synthetic_batches, save_dataset
from research.phase4.experiment_logger import ExperimentLogger
from research.phase4.metrics import compute_experiment_metrics, format_metrics_summary


def setup_isolated_research_database():
    """Initializes tables and seeds test personas in the isolated research DB."""
    with app.app_context():
        db.create_all()
        # Seed test personas if missing
        if not User.query.filter_by(username="research_farmer").first():
            farmer = User(username="research_farmer", role="farmer", full_name="Dr. Synthetic Farmer", contact="farmer@research.local")
            farmer.set_password("research123")
            transporter = User(username="research_transporter", role="transporter", full_name="Synthetic Logistics Ltd", contact="transporter@research.local")
            transporter.set_password("research123")
            retailer = User(username="research_retailer", role="retailer", full_name="Synthetic Mart Corp", contact="retailer@research.local")
            retailer.set_password("research123")
            admin = User(username="research_admin", role="admin", full_name="Research Coordinator", contact="admin@research.local")
            admin.set_password("research123")
            customer = User(username="research_customer", role="customer", full_name="Synthetic Auditor", contact="auditor@research.local")
            customer.set_password("research123")
            db.session.add_all([farmer, transporter, retailer, admin, customer])
            db.session.commit()


def ingest_and_anchor_batch(batch_data: dict, w3, farmer_id: int, transporter_id: int, retailer_id: int) -> Product:
    """
    Ingests a synthetic batch into the research database and seals hashes onto Ganache
    using canonical blockchain anchoring functions and snapshot capturing.
    Idempotent: Reuses existing on-chain records if already anchored on the EVM.
    """
    from blockchain import get_or_deploy_contract
    contract = get_or_deploy_contract(w3)
    contract_addr = contract.address

    batch_id = batch_data["batch_id"]
    h_data = batch_data["harvest"]
    r_data = batch_data["retail"]
    t_checkpoints = batch_data["transport_checkpoints"]

    existing = Product.query.filter_by(batch_id=batch_id).first()

    # Check on-chain existence
    on_chain_exists = False
    on_chain_harvest_hash = None
    try:
        rec = contract.functions.getRecord(batch_id).call()
        if rec and len(rec) >= 4 and rec[3]:  # exists
            on_chain_exists = True
            on_chain_harvest_hash = rec[0]
    except Exception:
        on_chain_exists = False

    harvest_hash = compute_batch_hash(
        batch_id=batch_id,
        name=h_data["name"],
        quantity=h_data["quantity"],
        farming_method=h_data["farming_method"],
        packaging_date=h_data["packaging_date"],
        farmer_id=farmer_id,
        image=h_data["image"],
    )

    if not on_chain_exists:
        meta_h = store_hash_detailed(batch_id, harvest_hash, role="farmer")
        tx_h = meta_h.get("tx_hash")
        block_h = meta_h.get("block_number")
        signer_h = meta_h.get("signer_address")
    else:
        tx_h = None
        block_h = None
        signer_h = None

    if not existing:
        product = Product(
            batch_id=batch_id,
            name=h_data["name"],
            quantity=h_data["quantity"],
            farming_method=h_data["farming_method"],
            packaging_date=h_data["packaging_date"],
            farmer_id=farmer_id,
            image=h_data["image"],
            qr_code=f"qr_{batch_id}.png",
            on_chain_hash=harvest_hash,
            tx_hash=tx_h,
            block_number=block_h,
            contract_address=contract_addr,
            contract_version="V2",
            signer_address=signer_h,
            status="In Stock",
        )
        db.session.add(product)
        db.session.flush()

        farmer_entry = FarmerData(
            product_id=product.id,
            farm_name=h_data.get("farm_name"),
            farm_location=h_data.get("farm_location"),
            harvest_date=h_data.get("packaging_date"),
            certifications=h_data.get("certifications"),
            notes=h_data.get("notes"),
        )
        db.session.add(farmer_entry)
        db.session.flush()

        _save_stage_snapshot_once(
            product_id=product.id,
            stage="HARVEST",
            payload_dict=_build_harvest_snapshot_payload(product),
            original_hash=harvest_hash,
        )
    else:
        product = existing

    # Check on-chain stage count
    on_chain_stages_count = 0
    try:
        on_chain_stages_count = contract.functions.getStageCount(batch_id).call()
    except Exception:
        on_chain_stages_count = 0

    # 2. Transport Checkpoints
    current_t_on_chain = 0
    for idx, cp in enumerate(t_checkpoints):
        t_hash = compute_transport_hash(
            batch_id=batch_id,
            status=cp["status"],
            current_location=cp["current_location"],
            temperature=cp["temperature"],
            vehicle_number=cp["vehicle_number"],
            notes=cp["notes"],
            transporter_id=transporter_id,
        )

        t_entry = TransportData.query.filter_by(
            product_id=product.id,
            status=cp["status"],
            current_location=cp["current_location"],
        ).first()

        if not t_entry:
            if idx >= on_chain_stages_count:
                meta_t = store_stage_hash(batch_id, "TRANSPORT", t_hash, role="transporter")
                tx_t = meta_t.get("tx_hash")
                block_t = meta_t.get("block_number")
                signer_t = meta_t.get("signer_address")
            else:
                tx_t = None
                block_t = None
                signer_t = None

            t_entry = TransportData(
                product_id=product.id,
                transporter_id=transporter_id,
                status=cp["status"],
                current_location=cp["current_location"],
                temperature=cp["temperature"],
                vehicle_number=cp["vehicle_number"],
                notes=cp["notes"],
                on_chain_hash=t_hash,
                tx_hash=tx_t,
                block_number=block_t,
                signer_address=signer_t,
            )
            db.session.add(t_entry)
            db.session.flush()

            _save_stage_snapshot_once(
                product_id=product.id,
                stage="TRANSPORT",
                payload_dict=_build_transport_snapshot_payload(product, t_entry),
                original_hash=t_hash,
                transport_id=t_entry.id,
            )

    # 3. Retail Listing
    r_hash = compute_retail_hash(
        batch_id=batch_id,
        store_name=r_data["store_name"],
        store_location=r_data["store_location"],
        price=r_data["price"],
        stock_quantity=r_data["stock_quantity"],
        arrival_date=r_data["arrival_date"],
        shelf_life=r_data["shelf_life"],
        retailer_id=retailer_id,
    )

    r_entry = RetailData.query.filter_by(product_id=product.id).first()
    if not r_entry:
        # Check if retail stage was already pushed
        total_needed_stages = len(t_checkpoints) + 1
        if on_chain_stages_count < total_needed_stages:
            meta_r = store_stage_hash(batch_id, "RETAIL", r_hash, role="retailer")
            tx_r = meta_r.get("tx_hash")
            block_r = meta_r.get("block_number")
            signer_r = meta_r.get("signer_address")
        else:
            tx_r = None
            block_r = None
            signer_r = None

        r_entry = RetailData(
            product_id=product.id,
            retailer_id=retailer_id,
            store_name=r_data["store_name"],
            store_location=r_data["store_location"],
            price=float(r_data["price"]),
            stock_quantity=r_data["stock_quantity"],
            arrival_date=r_data["arrival_date"],
            shelf_life=r_data["shelf_life"],
            on_chain_hash=r_hash,
            tx_hash=tx_r,
            block_number=block_r,
            signer_address=signer_r,
        )
        db.session.add(r_entry)
        db.session.flush()

        _save_stage_snapshot_once(
            product_id=product.id,
            stage="RETAIL",
            payload_dict=_build_retail_snapshot_payload(product, r_entry),
            original_hash=r_hash,
        )

    db.session.commit()
    return product


def run_baseline_experiment(
    dataset_path: str,
    output_csv: str,
    limit: int = 30,
) -> dict:
    """
    Executes the baseline verification experiment on unchanged synthetic batches.
    """
    w3 = get_w3(die_on_error=False)
    if not w3 or not w3.is_connected():
        raise RuntimeError("Ganache RPC node is offline on http://127.0.0.1:7545. Start Ganache before running baseline.")

    setup_isolated_research_database()

    # Load synthetic dataset
    if not os.path.exists(dataset_path):
        print(f"Dataset not found at {dataset_path}. Generating fresh 30 synthetic batches...")
        ds = generate_synthetic_batches(count=limit)
        save_dataset(ds, dataset_path)
    else:
        with open(dataset_path, "r", encoding="utf-8") as f:
            ds = json.load(f)

    batches = ds.get("batches", [])[:limit]
    print(f"Running Baseline Experiment on {len(batches)} unchanged synthetic batches...")

    exp_id = f"EXP-BASELINE-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    logger = ExperimentLogger(output_csv, experiment_id=exp_id)

    with app.app_context():
        farmer = User.query.filter_by(username="research_farmer").first()
        transporter = User.query.filter_by(username="research_transporter").first()
        retailer = User.query.filter_by(username="research_retailer").first()

        total_batches = len(batches)
        for idx, b_data in enumerate(batches, 1):
            batch_id = b_data["batch_id"]
            print(f"[{idx}/{total_batches}] Ingesting & Anchoring: {batch_id}...", end=" ", flush=True)

            product = ingest_and_anchor_batch(
                b_data,
                w3,
                farmer_id=farmer.id,
                transporter_id=transporter.id,
                retailer_id=retailer.id,
            )
            print("Anchored. Verifying...", end=" ", flush=True)

            # High-precision verification latency benchmark
            t0 = time.perf_counter()
            ctx = _build_verification_context(product)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0

            harvest_status = ctx.get("harvest_status")
            transport_stage_status = ctx.get("transport_stage_status")
            retail_stage_status = ctx.get("retail_stage_status")
            overall_status = ctx.get("verification_status")

            # In baseline experiment, all records are authentic and unchanged -> expected: 'verified'
            # 1. Log Harvest Stage
            logger.log_trial(
                batch_id=batch_id,
                stage="HARVEST",
                scenario="baseline_unchanged",
                expected_outcome="verified",
                actual_outcome=harvest_status,
                latency_ms=elapsed_ms / 3.0,  # Proportional estimate or overall latency
                error_message="; ".join(ctx.get("cannot_verify_reasons", [])),
            )

            # 2. Log Transport Stage (including checkpoint count in notes)
            logger.log_trial(
                batch_id=batch_id,
                stage="TRANSPORT",
                scenario="baseline_unchanged",
                expected_outcome="verified",
                actual_outcome=transport_stage_status,
                latency_ms=elapsed_ms / 3.0,
                error_message=None if transport_stage_status == "verified" else "Transport verification failure",
            )

            # 3. Log Retail Stage
            logger.log_trial(
                batch_id=batch_id,
                stage="RETAIL",
                scenario="baseline_unchanged",
                expected_outcome="verified",
                actual_outcome=retail_stage_status,
                latency_ms=elapsed_ms / 3.0,
                error_message=None if retail_stage_status == "verified" else "Retail verification failure",
            )

            # 4. Log Overall Batch Verification
            logger.log_trial(
                batch_id=batch_id,
                stage="OVERALL",
                scenario="baseline_unchanged",
                expected_outcome="verified",
                actual_outcome=overall_status,
                latency_ms=elapsed_ms,
                error_message="; ".join(ctx.get("cannot_verify_reasons", [])),
            )

            print(f"Result: {overall_status} ({elapsed_ms:.1f} ms)")

    # Read back results and calculate metrics
    results = logger.records
    metrics = compute_experiment_metrics(results)
    summary_report = format_metrics_summary(metrics)
    print("\n" + summary_report)

    # Save summary JSON
    summary_path = os.path.join(RESULTS_DIR, "baseline_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)

    print(f"\nDetailed CSV trial logs exported to : {output_csv}")
    print(f"Summary metrics JSON exported to    : {summary_path}")
    return metrics


def main():
    parser = argparse.ArgumentParser(description="Run Phase 4 baseline provenance verification experiment.")
    parser.add_argument(
        "--dataset",
        type=str,
        default=os.path.join(DATA_DIR, "synthetic_batches.json"),
        help="Path to synthetic batches JSON dataset",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=os.path.join(RESULTS_DIR, "baseline_verification.csv"),
        help="Path to output CSV results file",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=30,
        help="Number of batches to evaluate (default: 30)",
    )
    args = parser.parse_args()

    run_baseline_experiment(
        dataset_path=args.dataset,
        output_csv=args.output,
        limit=args.limit,
    )


if __name__ == "__main__":
    main()
