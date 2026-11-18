"""
TrustHarvest — Phase 4 Research Experiment Framework
Module: run_tampering.py (Experiment E2: Controlled Tampering Detection)

Systematically evaluates whether the TrustHarvest verification engine detects
modifications made to provenance data after its original hash was anchored on Ethereum.
Covers:
- E2.1 Harvest tampering (single-field and multi-field combinations)
- E2.2 Transport tampering (single-field and multi-field combinations)
- E2.3 Retail tampering (single-field and multi-field combinations)
- E2.4 Negative controls (fields outside hash protection boundary)
"""

import argparse
import copy
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

RESEARCH_DIR = os.path.abspath(os.path.dirname(__file__))
DATA_DIR = os.path.join(RESEARCH_DIR, "data")
RESULTS_DIR = os.path.join(RESEARCH_DIR, "results")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(RESULTS_DIR, exist_ok=True)

RESEARCH_DB_PATH = os.path.join(DATA_DIR, "research_phase4.db")
os.environ["DATABASE_URL"] = f"sqlite:///{RESEARCH_DB_PATH}"
os.environ["DEMO_MODE"] = "true"

from app import app, _build_verification_context, _sorted_transports
from models import db, Product, FarmerData, TransportData, RetailData
from research.phase4.experiment_logger import ExperimentLogger
from research.phase4.metrics import compute_experiment_metrics, format_metrics_summary


def restore_clean_batch_state(product_id: int, original_state: dict):
    """Restores database records for a product back to its authentic baseline state."""
    product = Product.query.get(product_id)
    if not product:
        return

    # Restore Product
    for k, v in original_state["product"].items():
        setattr(product, k, v)

    # Restore FarmerData
    if product.farmer_data and "farmer_data" in original_state:
        for k, v in original_state["farmer_data"].items():
            setattr(product.farmer_data, k, v)

    # Restore TransportData
    if "transports" in original_state:
        for t_rec, t_orig in zip(_sorted_transports(product), original_state["transports"]):
            for k, v in t_orig.items():
                setattr(t_rec, k, v)

    # Restore RetailData
    if product.retail_data and "retail_data" in original_state:
        for k, v in original_state["retail_data"].items():
            setattr(product.retail_data, k, v)

    db.session.commit()


def capture_batch_state(product: Product) -> dict:
    """Captures an in-memory dictionary snapshot of a product's current database state."""
    state = {
        "product": {
            "name": product.name,
            "quantity": product.quantity,
            "farming_method": product.farming_method,
            "packaging_date": product.packaging_date,
            "farmer_id": product.farmer_id,
            "image": product.image,
            "status": product.status,
        },
        "farmer_data": {
            "farm_name": product.farmer_data.farm_name if product.farmer_data else None,
            "farm_location": product.farmer_data.farm_location if product.farmer_data else None,
            "harvest_date": product.farmer_data.harvest_date if product.farmer_data else None,
            "certifications": product.farmer_data.certifications if product.farmer_data else None,
            "notes": product.farmer_data.notes if product.farmer_data else None,
        } if product.farmer_data else None,
        "transports": [
            {
                "status": t.status,
                "current_location": t.current_location,
                "temperature": t.temperature,
                "vehicle_number": t.vehicle_number,
                "notes": t.notes,
                "transporter_id": t.transporter_id,
                "timestamp": t.timestamp,
            }
            for t in _sorted_transports(product)
        ],
        "retail_data": {
            "store_name": product.retail_data.store_name,
            "store_location": product.retail_data.store_location,
            "price": product.retail_data.price,
            "stock_quantity": product.retail_data.stock_quantity,
            "arrival_date": product.retail_data.arrival_date,
            "shelf_life": product.retail_data.shelf_life,
            "retailer_id": product.retail_data.retailer_id,
            "updated_at": product.retail_data.updated_at,
        } if product.retail_data else None,
    }
    return state


def run_tampering_experiments(
    output_csv: str = os.path.join(RESULTS_DIR, "tampering_experiments.csv"),
    batches_to_test: int = 10,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Executes controlled tampering mutations and negative controls across synthetic batches.
    Returns (tampering_metrics, negative_control_metrics).
    """
    exp_id = f"EXP-TAMPER-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    logger = ExperimentLogger(output_csv, experiment_id=exp_id)

    tampering_records = []
    negative_control_records = []

    with app.app_context():
        products = Product.query.order_by(Product.id.asc()).limit(batches_to_test).all()
        if not products:
            raise RuntimeError("No batches found in research_phase4.db. Run run_baseline.py first.")

        print(f"Executing E2 Controlled Tampering Evaluation across {len(products)} batches...")

        for p_idx, product in enumerate(products, 1):
            batch_id = product.batch_id
            clean_state = capture_batch_state(product)
            print(f"\n[{p_idx}/{len(products)}] Evaluating Batch {batch_id}...")

            # Confirm clean baseline passes first
            base_ctx = _build_verification_context(product)
            if base_ctx.get("verification_status") != "verified":
                print(f"Warning: Batch {batch_id} baseline is not verified ({base_ctx.get('verification_status')}). Skipping.")
                continue

            # -----------------------------------------------------------------
            # E2.1: HARVEST TAMPERING SCENARIOS
            # -----------------------------------------------------------------
            harvest_scenarios = [
                # Single-field mutations
                ("single_name", "HARVEST", "name", lambda p: setattr(p, "name", p.name + " [Tampered]")),
                ("single_quantity", "HARVEST", "quantity", lambda p: setattr(p, "quantity", "9999 kg (Tampered)")),
                ("single_farming_method", "HARVEST", "farming_method", lambda p: setattr(p, "farming_method", "Chemically Treated Conventional")),
                ("single_packaging_date", "HARVEST", "packaging_date", lambda p: setattr(p, "packaging_date", "2019-01-01")),
                # Multi-field mutations
                ("multi_name_quantity", "HARVEST", "name+quantity", lambda p: (setattr(p, "name", "Fraudulent Fruit"), setattr(p, "quantity", "10 kg"))),
                ("multi_method_date", "HARVEST", "farming_method+packaging_date", lambda p: (setattr(p, "farming_method", "Non-Organic Industrial"), setattr(p, "packaging_date", "2020-05-15"))),
                ("multi_all_harvest", "HARVEST", "all_harvest_fields", lambda p: (
                    setattr(p, "name", "Fake Produce"),
                    setattr(p, "quantity", "1 kg"),
                    setattr(p, "farming_method", "Synthetic Chemical Spray"),
                    setattr(p, "packaging_date", "2018-12-31")
                )),
            ]

            for sc_id, stage, field_label, mutate_fn in harvest_scenarios:
                restore_clean_batch_state(product.id, clean_state)
                mutate_fn(product)
                db.session.commit()

                t0 = time.perf_counter()
                ctx = _build_verification_context(product)
                elapsed_ms = (time.perf_counter() - t0) * 1000.0

                actual = ctx.get("harvest_status")
                # Expected outcome for tampered field is 'tampered'
                row = logger.log_trial(
                    batch_id=batch_id,
                    stage=stage,
                    scenario=f"harvest_{sc_id}",
                    expected_outcome="tampered",
                    actual_outcome=actual,
                    latency_ms=elapsed_ms,
                    error_message=f"Tampered field(s): {field_label}; overall: {ctx.get('verification_status')}",
                )
                tampering_records.append(row)
                restore_clean_batch_state(product.id, clean_state)

            # -----------------------------------------------------------------
            # E2.2: TRANSPORT TAMPERING SCENARIOS
            # -----------------------------------------------------------------
            transports = _sorted_transports(product)
            if transports:
                target_t = transports[0]  # First checkpoint
                transport_scenarios = [
                    # Single-field mutations
                    ("single_temperature", "TRANSPORT", "temperature", lambda t: setattr(t, "temperature", "26.8 °C (Spoiled)")),
                    ("single_location", "TRANSPORT", "current_location", lambda t: setattr(t, "current_location", "Unauthorized Black Market Depot")),
                    ("single_notes", "TRANSPORT", "notes", lambda t: setattr(t, "notes", "Cooling malfunction occurred")),
                    ("single_status", "TRANSPORT", "status", lambda t: setattr(t, "status", "Rejected by Port Inspector")),
                    ("single_vehicle_number", "TRANSPORT", "vehicle_number", lambda t: setattr(t, "vehicle_number", "UNAUTH-TRK-000")),
                    ("single_transporter_id", "TRANSPORT", "transporter_id", lambda t: setattr(t, "transporter_id", 9999)),
                    # Multi-field mutations
                    ("multi_temp_location", "TRANSPORT", "temp+location", lambda t: (setattr(t, "temperature", "32.0 °C"), setattr(t, "current_location", "Rerouted Siding"))),
                    ("multi_status_vehicle", "TRANSPORT", "status+vehicle", lambda t: (setattr(t, "status", "Impounded"), setattr(t, "vehicle_number", "GHOST-VAN-1"))),
                    ("multi_all_transport", "TRANSPORT", "all_transport_fields", lambda t: (
                        setattr(t, "temperature", "35.5 °C"),
                        setattr(t, "current_location", "Unknown Location"),
                        setattr(t, "status", "Damaged"),
                        setattr(t, "vehicle_number", "NO-REG"),
                        setattr(t, "notes", "Complete cold-chain failure")
                    )),
                ]

                for sc_id, stage, field_label, mutate_fn in transport_scenarios:
                    restore_clean_batch_state(product.id, clean_state)
                    t_active = _sorted_transports(product)[0]
                    mutate_fn(t_active)
                    db.session.commit()

                    t0 = time.perf_counter()
                    ctx = _build_verification_context(product)
                    elapsed_ms = (time.perf_counter() - t0) * 1000.0

                    actual = ctx.get("transport_stage_status")
                    row = logger.log_trial(
                        batch_id=batch_id,
                        stage=stage,
                        scenario=f"transport_{sc_id}",
                        expected_outcome="tampered",
                        actual_outcome=actual,
                        latency_ms=elapsed_ms,
                        error_message=f"Tampered field(s): {field_label}; overall: {ctx.get('verification_status')}",
                    )
                    tampering_records.append(row)
                    restore_clean_batch_state(product.id, clean_state)

            # -----------------------------------------------------------------
            # E2.3: RETAIL TAMPERING SCENARIOS
            # -----------------------------------------------------------------
            if product.retail_data:
                retail_scenarios = [
                    # Single-field mutations
                    ("single_price", "RETAIL", "price", lambda r: setattr(r, "price", 99.99)),
                    ("single_store_name", "RETAIL", "store_name", lambda r: setattr(r, "store_name", "Bogus Grocers Outlet")),
                    ("single_store_location", "RETAIL", "store_location", lambda r: setattr(r, "store_location", "Counterfeit Strip Mall")),
                    ("single_stock_quantity", "RETAIL", "stock_quantity", lambda r: setattr(r, "stock_quantity", "5 kg (Deficit)")),
                    ("single_arrival_date", "RETAIL", "arrival_date", lambda r: setattr(r, "arrival_date", "2015-01-01")),
                    ("single_shelf_life", "RETAIL", "shelf_life", lambda r: setattr(r, "shelf_life", "Expired (0 Days)")),
                    # Multi-field mutations
                    ("multi_price_stock", "RETAIL", "price+stock", lambda r: (setattr(r, "price", 1.00), setattr(r, "stock_quantity", "99999 kg"))),
                    ("multi_store_location", "RETAIL", "store_name+location", lambda r: (setattr(r, "store_name", "Unregistered Stall"), setattr(r, "store_location", "Flea Market"))),
                    ("multi_all_retail", "RETAIL", "all_retail_fields", lambda r: (
                        setattr(r, "store_name", "Black Market Organics"),
                        setattr(r, "store_location", "Unknown Corner"),
                        setattr(r, "price", 0.05),
                        setattr(r, "stock_quantity", "0 kg"),
                        setattr(r, "arrival_date", "1999-12-31"),
                        setattr(r, "shelf_life", "Rotten")
                    )),
                ]

                for sc_id, stage, field_label, mutate_fn in retail_scenarios:
                    restore_clean_batch_state(product.id, clean_state)
                    mutate_fn(product.retail_data)
                    db.session.commit()

                    t0 = time.perf_counter()
                    ctx = _build_verification_context(product)
                    elapsed_ms = (time.perf_counter() - t0) * 1000.0

                    actual = ctx.get("retail_stage_status")
                    row = logger.log_trial(
                        batch_id=batch_id,
                        stage=stage,
                        scenario=f"retail_{sc_id}",
                        expected_outcome="tampered",
                        actual_outcome=actual,
                        latency_ms=elapsed_ms,
                        error_message=f"Tampered field(s): {field_label}; overall: {ctx.get('verification_status')}",
                    )
                    tampering_records.append(row)
                    restore_clean_batch_state(product.id, clean_state)

            # -----------------------------------------------------------------
            # E2.4: NEGATIVE CONTROLS (OUTSIDE HASH PROTECTION BOUNDARY)
            # -----------------------------------------------------------------
            # Modifying fields that are NOT included in the hash must NOT trigger
            # a hash mismatch. Expected outcome: 'verified' (system faithfully reports what is hashed).
            negative_scenarios = [
                ("neg_farmer_certifications", "HARVEST", "certifications (unhashed)", lambda p: setattr(p.farmer_data, "certifications", "Forged Fake Cert")),
                ("neg_farmer_notes", "HARVEST", "notes (unhashed)", lambda p: setattr(p.farmer_data, "notes", "Secret unauthorized chemicals used")),
                ("neg_transport_timestamp", "TRANSPORT", "timestamp (unhashed)", lambda p: setattr(_sorted_transports(p)[0], "timestamp", datetime(2010, 1, 1, tzinfo=timezone.utc))),
                ("neg_retail_updated_at", "RETAIL", "updated_at (unhashed)", lambda p: setattr(p.retail_data, "updated_at", datetime(2010, 1, 1, tzinfo=timezone.utc))),
            ]

            for sc_id, stage, field_label, mutate_fn in negative_scenarios:
                restore_clean_batch_state(product.id, clean_state)
                mutate_fn(product)
                db.session.commit()

                t0 = time.perf_counter()
                ctx = _build_verification_context(product)
                elapsed_ms = (time.perf_counter() - t0) * 1000.0

                actual_stage_status = (
                    ctx.get("harvest_status") if stage == "HARVEST"
                    else (ctx.get("transport_stage_status") if stage == "TRANSPORT" else ctx.get("retail_stage_status"))
                )

                # Because these fields are outside the hash boundary, the recalculated hash remains identical
                # Expected outcome: 'verified'
                row = logger.log_trial(
                    batch_id=batch_id,
                    stage=stage,
                    scenario=f"negative_control_{sc_id}",
                    expected_outcome="verified",
                    actual_outcome=actual_stage_status,
                    latency_ms=elapsed_ms,
                    error_message=f"Unhashed field: {field_label}; outside hash boundary",
                )
                negative_control_records.append(row)
                restore_clean_batch_state(product.id, clean_state)

        # Restore all products to clean baseline state
        for product in products:
            restore_clean_batch_state(product.id, capture_batch_state(product))

    # Calculate metrics
    tamper_metrics = compute_experiment_metrics(tampering_records, positive_label="tampered", negative_label="verified")
    neg_metrics = compute_experiment_metrics(negative_control_records, positive_label="tampered", negative_label="verified")

    # Granular summary JSON
    summary_data = {
        "metadata": {
            "experiment_id": exp_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "batches_tested": len(products),
            "total_tamper_trials": len(tampering_records),
            "total_negative_control_trials": len(negative_control_records),
        },
        "tampering_evaluation": tamper_metrics,
        "negative_controls_evaluation": neg_metrics,
    }

    summary_path = os.path.join(RESULTS_DIR, "tampering_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary_data, f, indent=2)

    print("\n" + "=" * 68)
    print("E2 TAMPERING DETECTION METRICS REPORT")
    print("=" * 68)
    print(format_metrics_summary(tamper_metrics))
    print("\nNEGATIVE CONTROLS EVALUATION (Unhashed Fields):")
    print(f"  Trials Evaluated        : {len(negative_control_records)}")
    print(f"  Correctly Kept Verified : {neg_metrics['correct_predictions']} / {len(negative_control_records)} ({neg_metrics['accuracy']*100:.2f}%)")
    print(f"  False Tamper Alarms     : {neg_metrics['confusion_matrix']['false_positives']}")
    print("=" * 68)
    print(f"Detailed CSV trial logs exported to: {output_csv}")
    print(f"Summary metrics exported to: {summary_path}")

    return tamper_metrics, neg_metrics


def main():
    parser = argparse.ArgumentParser(description="Run Phase 4 E2 Controlled Tampering Experiment.")
    parser.add_argument("--batches", type=int, default=10, help="Number of batches to evaluate (default: 10)")
    parser.add_argument(
        "--output",
        type=str,
        default=os.path.join(RESULTS_DIR, "tampering_experiments.csv"),
        help="Path to output CSV",
    )
    args = parser.parse_args()

    run_tampering_experiments(output_csv=args.output, batches_to_test=args.batches)


if __name__ == "__main__":
    main()

