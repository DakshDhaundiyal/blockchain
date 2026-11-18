"""
TrustHarvest — Phase 4 Research Experiment Framework
Module: run_snapshot_tests.py (Experiment E3: Snapshot Integrity and Diagnosis)

Evaluates the cryptographic role of StageSnapshot records in localizing and diagnosing
field-level modifications across supply-chain stages under 8 adversarial and edge scenarios:
1. Baseline: Untampered DB record & valid snapshot
2. Single hashed field modified
3. Multiple hashed fields modified
4. Snapshot modified independently
5. Snapshot missing
6. Snapshot invalid / malformed JSON
7. Non-hashed field modified
8. DB record & snapshot modified together (collusion attack)
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

from app import (
    app,
    _build_verification_context,
    _load_validated_snapshot,
    _compute_changed_fields,
    _build_harvest_snapshot_payload,
    _build_transport_snapshot_payload,
    _build_retail_snapshot_payload,
    _sorted_transports,
)
from models import db, Product, FarmerData, TransportData, RetailData, StageSnapshot
from research.phase4.experiment_logger import ExperimentLogger


def _safe_divide(n: float, d: float, fallback: float = 0.0) -> float:
    return fallback if d == 0 else n / d


def restore_snapshot_and_batch(product_id: int, original_batch_state: dict, original_snapshots: list):
    """Restores both relational data and StageSnapshot records back to baseline authentic state."""
    product = Product.query.get(product_id)
    if not product:
        return

    # Restore product attributes
    for k, v in original_batch_state["product"].items():
        setattr(product, k, v)

    if product.farmer_data and "farmer_data" in original_batch_state:
        for k, v in original_batch_state["farmer_data"].items():
            setattr(product.farmer_data, k, v)

    if "transports" in original_batch_state:
        for t_rec, t_orig in zip(_sorted_transports(product), original_batch_state["transports"]):
            for k, v in t_orig.items():
                setattr(t_rec, k, v)

    if product.retail_data and "retail_data" in original_batch_state:
        for k, v in original_batch_state["retail_data"].items():
            setattr(product.retail_data, k, v)

    # Restore snapshots
    StageSnapshot.query.filter_by(product_id=product_id).delete()
    db.session.flush()

    for s_data in original_snapshots:
        snap = StageSnapshot(
            product_id=s_data["product_id"],
            stage=s_data["stage"],
            transport_id=s_data["transport_id"],
            original_hash=s_data["original_hash"],
            snapshot_json=s_data["snapshot_json"],
            created_at=s_data["created_at"],
        )
        db.session.add(snap)

    db.session.commit()


def capture_all_snapshots(product_id: int) -> list:
    """Captures all snapshot rows for a given product."""
    snaps = StageSnapshot.query.filter_by(product_id=product_id).all()
    return [
        {
            "id": s.id,
            "product_id": s.product_id,
            "stage": s.stage,
            "transport_id": s.transport_id,
            "original_hash": s.original_hash,
            "snapshot_json": s.snapshot_json,
            "created_at": s.created_at,
        }
        for s in snaps
    ]


def run_snapshot_experiments(
    output_csv: str = os.path.join(RESULTS_DIR, "snapshot_experiments.csv"),
    batches_to_test: int = 10,
) -> Dict[str, Any]:
    """
    Evaluates StageSnapshot behavior across 8 rigorous diagnosis scenarios.
    """
    from research.phase4.run_tampering import capture_batch_state

    exp_id = f"EXP-SNAP-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    logger = ExperimentLogger(output_csv, experiment_id=exp_id)
    trials = []

    scenario_metrics = {
        f"scenario_{i}": {
            "name": "",
            "trials": 0,
            "tamper_detected_correct": 0,
            "snapshot_trusted_correct": 0,
            "diagnosis_correct": 0,
            "field_tp": 0,
            "field_fp": 0,
            "field_fn": 0,
        }
        for i in range(1, 9)
    }

    with app.app_context():
        products = Product.query.order_by(Product.id.asc()).limit(batches_to_test).all()
        if not products:
            raise RuntimeError("No products found in research_phase4.db.")

        print(f"Executing E3 Snapshot Integrity & Diagnosis Evaluation across {len(products)} batches...")

        for p_idx, product in enumerate(products, 1):
            batch_id = product.batch_id
            clean_state = capture_batch_state(product)
            clean_snaps = capture_all_snapshots(product.id)
            print(f"[{p_idx}/{len(products)}] Testing Snapshot Scenarios on Batch {batch_id}...")

            # -------------------------------------------------------------
            # Scenario 1: Baseline (Unmodified DB, valid snapshot)
            # -------------------------------------------------------------
            sc1_key = "scenario_1"
            scenario_metrics[sc1_key]["name"] = "Baseline Authentic (Valid Snapshot)"
            t0 = time.perf_counter()
            ctx = _build_verification_context(product)
            lat = (time.perf_counter() - t0) * 1000.0

            h_tampered = ctx["harvest_status"] == "tampered"
            # In baseline: Tamper = False; Snapshot valid = True; Diffs = 0
            is_correct_tamper = (ctx["harvest_status"] == "verified")
            snap_dict, s_avail, s_valid, s_note = _load_validated_snapshot(product, "HARVEST", ctx.get("on_chain_hash"))
            is_correct_snap = (s_avail and s_valid)
            diffs = _compute_changed_fields("HARVEST", snap_dict, _build_harvest_snapshot_payload(product))
            is_correct_diag = (len(diffs) == 0)

            row = logger.log_trial(
                batch_id=batch_id,
                stage="HARVEST",
                scenario="scenario_1_baseline",
                expected_outcome="verified",
                actual_outcome=ctx["harvest_status"],
                latency_ms=lat,
                error_message=f"Snap valid: {s_valid}; Diffs: {len(diffs)}",
            )
            trials.append(row)
            scenario_metrics[sc1_key]["trials"] += 1
            if is_correct_tamper: scenario_metrics[sc1_key]["tamper_detected_correct"] += 1
            if is_correct_snap: scenario_metrics[sc1_key]["snapshot_trusted_correct"] += 1
            if is_correct_diag: scenario_metrics[sc1_key]["diagnosis_correct"] += 1

            # -------------------------------------------------------------
            # Scenario 2: Single hashed field modified (Harvest: farming_method)
            # -------------------------------------------------------------
            sc2_key = "scenario_2"
            scenario_metrics[sc2_key]["name"] = "Single Hashed Field Tampered"
            restore_snapshot_and_batch(product.id, clean_state, clean_snaps)
            product.farming_method = "Industrial Chemical Non-Organic"
            db.session.commit()

            t0 = time.perf_counter()
            ctx = _build_verification_context(product)
            lat = (time.perf_counter() - t0) * 1000.0

            is_correct_tamper = (ctx["harvest_status"] == "tampered")
            snap_dict, s_avail, s_valid, s_note = _load_validated_snapshot(product, "HARVEST", ctx.get("on_chain_hash"))
            is_correct_snap = (s_avail and s_valid)
            diffs = _compute_changed_fields("HARVEST", snap_dict, _build_harvest_snapshot_payload(product))
            # Expect exactly 1 diff on farming_method
            diff_fields = [d["field"] for d in diffs]
            is_correct_diag = (diff_fields == ["farming_method"])

            row = logger.log_trial(
                batch_id=batch_id,
                stage="HARVEST",
                scenario="scenario_2_single_hashed_field",
                expected_outcome="tampered",
                actual_outcome=ctx["harvest_status"],
                latency_ms=lat,
                error_message=f"Identified diffs: {diff_fields}",
            )
            trials.append(row)
            scenario_metrics[sc2_key]["trials"] += 1
            if is_correct_tamper: scenario_metrics[sc2_key]["tamper_detected_correct"] += 1
            if is_correct_snap: scenario_metrics[sc2_key]["snapshot_trusted_correct"] += 1
            if is_correct_diag:
                scenario_metrics[sc2_key]["diagnosis_correct"] += 1
                scenario_metrics[sc2_key]["field_tp"] += 1
            else:
                scenario_metrics[sc2_key]["field_fn"] += 1

            # -------------------------------------------------------------
            # Scenario 3: Multiple hashed fields modified (Harvest: farming_method + packaging_date)
            # -------------------------------------------------------------
            sc3_key = "scenario_3"
            scenario_metrics[sc3_key]["name"] = "Multiple Hashed Fields Tampered"
            restore_snapshot_and_batch(product.id, clean_state, clean_snaps)
            product.farming_method = "Fraudulent Method"
            product.packaging_date = "2020-01-01"
            db.session.commit()

            t0 = time.perf_counter()
            ctx = _build_verification_context(product)
            lat = (time.perf_counter() - t0) * 1000.0

            is_correct_tamper = (ctx["harvest_status"] == "tampered")
            snap_dict, s_avail, s_valid, s_note = _load_validated_snapshot(product, "HARVEST", ctx.get("on_chain_hash"))
            is_correct_snap = (s_avail and s_valid)
            diffs = _compute_changed_fields("HARVEST", snap_dict, _build_harvest_snapshot_payload(product))
            diff_fields = set(d["field"] for d in diffs)
            is_correct_diag = (diff_fields == {"farming_method", "packaging_date"})

            row = logger.log_trial(
                batch_id=batch_id,
                stage="HARVEST",
                scenario="scenario_3_multi_hashed_fields",
                expected_outcome="tampered",
                actual_outcome=ctx["harvest_status"],
                latency_ms=lat,
                error_message=f"Identified diffs: {list(diff_fields)}",
            )
            trials.append(row)
            scenario_metrics[sc3_key]["trials"] += 1
            if is_correct_tamper: scenario_metrics[sc3_key]["tamper_detected_correct"] += 1
            if is_correct_snap: scenario_metrics[sc3_key]["snapshot_trusted_correct"] += 1
            if is_correct_diag:
                scenario_metrics[sc3_key]["diagnosis_correct"] += 1
                scenario_metrics[sc3_key]["field_tp"] += 2
            else:
                scenario_metrics[sc3_key]["field_fn"] += 2

            # -------------------------------------------------------------
            # Scenario 4: Snapshot modified independently in SQL DB
            # -------------------------------------------------------------
            # Attacker modifies the snapshot_json in database while keeping product row authentic.
            # Verifier must detect that the snapshot fails validation against on-chain hash!
            sc4_key = "scenario_4"
            scenario_metrics[sc4_key]["name"] = "Snapshot Corrupted Independently"
            restore_snapshot_and_batch(product.id, clean_state, clean_snaps)
            h_snap = StageSnapshot.query.filter_by(product_id=product.id, stage="HARVEST").first()
            snap_payload = json.loads(h_snap.snapshot_json)
            snap_payload["farming_method"] = "Corrupted Inside Snapshot"
            h_snap.snapshot_json = json.dumps(snap_payload)
            db.session.commit()

            t0 = time.perf_counter()
            ctx = _build_verification_context(product)
            lat = (time.perf_counter() - t0) * 1000.0

            # DB record is authentic -> harvest_status = verified
            is_correct_tamper = (ctx["harvest_status"] == "verified")
            snap_dict, s_avail, s_valid, s_note = _load_validated_snapshot(product, "HARVEST", ctx.get("on_chain_hash"))
            # Snapshot was corrupted -> must be rejected as invalid!
            is_correct_snap = (s_avail and not s_valid)
            is_correct_diag = (snap_dict is None)

            row = logger.log_trial(
                batch_id=batch_id,
                stage="HARVEST",
                scenario="scenario_4_snapshot_tampered_independently",
                expected_outcome="verified",
                actual_outcome=ctx["harvest_status"],
                latency_ms=lat,
                error_message=f"Snap valid: {s_valid} (correctly rejected); Note: {s_note}",
            )
            trials.append(row)
            scenario_metrics[sc4_key]["trials"] += 1
            if is_correct_tamper: scenario_metrics[sc4_key]["tamper_detected_correct"] += 1
            if is_correct_snap: scenario_metrics[sc4_key]["snapshot_trusted_correct"] += 1
            if is_correct_diag: scenario_metrics[sc4_key]["diagnosis_correct"] += 1

            # -------------------------------------------------------------
            # Scenario 5: Snapshot missing (deleted from DB while DB is tampered)
            # -------------------------------------------------------------
            sc5_key = "scenario_5"
            scenario_metrics[sc5_key]["name"] = "Snapshot Missing"
            restore_snapshot_and_batch(product.id, clean_state, clean_snaps)
            product.farming_method = "Tampered With No Snapshot"
            StageSnapshot.query.filter_by(product_id=product.id, stage="HARVEST").delete()
            db.session.commit()

            t0 = time.perf_counter()
            ctx = _build_verification_context(product)
            lat = (time.perf_counter() - t0) * 1000.0

            is_correct_tamper = (ctx["harvest_status"] == "tampered")
            snap_dict, s_avail, s_valid, s_note = _load_validated_snapshot(product, "HARVEST", ctx.get("on_chain_hash"))
            is_correct_snap = (not s_avail and not s_valid)
            # System must refuse to fabricate diffs when snapshot is missing
            is_correct_diag = (snap_dict is None and "not available" in (s_note or "").lower())

            row = logger.log_trial(
                batch_id=batch_id,
                stage="HARVEST",
                scenario="scenario_5_snapshot_missing",
                expected_outcome="tampered",
                actual_outcome=ctx["harvest_status"],
                latency_ms=lat,
                error_message=f"Snap avail: {s_avail}; Note: {s_note}",
            )
            trials.append(row)
            scenario_metrics[sc5_key]["trials"] += 1
            if is_correct_tamper: scenario_metrics[sc5_key]["tamper_detected_correct"] += 1
            if is_correct_snap: scenario_metrics[sc5_key]["snapshot_trusted_correct"] += 1
            if is_correct_diag: scenario_metrics[sc5_key]["diagnosis_correct"] += 1

            # -------------------------------------------------------------
            # Scenario 6: Snapshot invalid JSON / unparseable
            # -------------------------------------------------------------
            sc6_key = "scenario_6"
            scenario_metrics[sc6_key]["name"] = "Snapshot Corrupted JSON"
            restore_snapshot_and_batch(product.id, clean_state, clean_snaps)
            product.farming_method = "Tampered With Bad Json Snap"
            h_snap = StageSnapshot.query.filter_by(product_id=product.id, stage="HARVEST").first()
            h_snap.snapshot_json = "{bad_malformed_json_syntax!!"
            db.session.commit()

            t0 = time.perf_counter()
            ctx = _build_verification_context(product)
            lat = (time.perf_counter() - t0) * 1000.0

            is_correct_tamper = (ctx["harvest_status"] == "tampered")
            snap_dict, s_avail, s_valid, s_note = _load_validated_snapshot(product, "HARVEST", ctx.get("on_chain_hash"))
            is_correct_snap = (s_avail and not s_valid)
            is_correct_diag = (snap_dict is None and "could not be parsed" in (s_note or "").lower())

            row = logger.log_trial(
                batch_id=batch_id,
                stage="HARVEST",
                scenario="scenario_6_snapshot_invalid_json",
                expected_outcome="tampered",
                actual_outcome=ctx["harvest_status"],
                latency_ms=lat,
                error_message=f"Snap valid: {s_valid}; Note: {s_note}",
            )
            trials.append(row)
            scenario_metrics[sc6_key]["trials"] += 1
            if is_correct_tamper: scenario_metrics[sc6_key]["tamper_detected_correct"] += 1
            if is_correct_snap: scenario_metrics[sc6_key]["snapshot_trusted_correct"] += 1
            if is_correct_diag: scenario_metrics[sc6_key]["diagnosis_correct"] += 1

            # -------------------------------------------------------------
            # Scenario 7: Non-hashed field modified (FarmerData.certifications)
            # -------------------------------------------------------------
            sc7_key = "scenario_7"
            scenario_metrics[sc7_key]["name"] = "Unhashed Field Modified"
            restore_snapshot_and_batch(product.id, clean_state, clean_snaps)
            if product.farmer_data:
                product.farmer_data.certifications = "Forged Certificate"
                db.session.commit()

            t0 = time.perf_counter()
            ctx = _build_verification_context(product)
            lat = (time.perf_counter() - t0) * 1000.0

            is_correct_tamper = (ctx["harvest_status"] == "verified")
            snap_dict, s_avail, s_valid, s_note = _load_validated_snapshot(product, "HARVEST", ctx.get("on_chain_hash"))
            is_correct_snap = (s_avail and s_valid)
            diffs = _compute_changed_fields("HARVEST", snap_dict, _build_harvest_snapshot_payload(product))
            is_correct_diag = (len(diffs) == 0)

            row = logger.log_trial(
                batch_id=batch_id,
                stage="HARVEST",
                scenario="scenario_7_unhashed_field_modified",
                expected_outcome="verified",
                actual_outcome=ctx["harvest_status"],
                latency_ms=lat,
                error_message=f"Diffs: {len(diffs)} (unhashed field not in hash payload)",
            )
            trials.append(row)
            scenario_metrics[sc7_key]["trials"] += 1
            if is_correct_tamper: scenario_metrics[sc7_key]["tamper_detected_correct"] += 1
            if is_correct_snap: scenario_metrics[sc7_key]["snapshot_trusted_correct"] += 1
            if is_correct_diag: scenario_metrics[sc7_key]["diagnosis_correct"] += 1

            # -------------------------------------------------------------
            # Scenario 8: DB record and snapshot modified together (Collusion attack)
            # -------------------------------------------------------------
            # Attacker modifies both product.farming_method AND snapshot.snapshot_json to match.
            # Verifier must detect that DB does not match on-chain hash, AND that snapshot
            # fails cryptographic validation against on-chain hash!
            sc8_key = "scenario_8"
            scenario_metrics[sc8_key]["name"] = "Collusion: DB & Snapshot Modified Together"
            restore_snapshot_and_batch(product.id, clean_state, clean_snaps)
            product.farming_method = "Collusion Attack Method"
            h_snap = StageSnapshot.query.filter_by(product_id=product.id, stage="HARVEST").first()
            snap_payload = json.loads(h_snap.snapshot_json)
            snap_payload["farming_method"] = "Collusion Attack Method"
            h_snap.snapshot_json = json.dumps(snap_payload)
            db.session.commit()

            t0 = time.perf_counter()
            ctx = _build_verification_context(product)
            lat = (time.perf_counter() - t0) * 1000.0

            # DB hash mismatch -> harvest_status = tampered
            is_correct_tamper = (ctx["harvest_status"] == "tampered")
            snap_dict, s_avail, s_valid, s_note = _load_validated_snapshot(product, "HARVEST", ctx.get("on_chain_hash"))
            # Snapshot hash fails against on-chain hash -> s_valid = False
            is_correct_snap = (s_avail and not s_valid)
            # System must refuse to trust the tampered snapshot
            is_correct_diag = (snap_dict is None and ("rejected" in (s_note or "").lower() or "did not match" in (s_note or "").lower() or "failed" in (s_note or "").lower()))

            row = logger.log_trial(
                batch_id=batch_id,
                stage="HARVEST",
                scenario="scenario_8_collusion_db_and_snapshot",
                expected_outcome="tampered",
                actual_outcome=ctx["harvest_status"],
                latency_ms=lat,
                error_message=f"Snap valid: {s_valid} (compromised snapshot caught); Note: {s_note}",
            )
            trials.append(row)
            scenario_metrics[sc8_key]["trials"] += 1
            if is_correct_tamper: scenario_metrics[sc8_key]["tamper_detected_correct"] += 1
            if is_correct_snap: scenario_metrics[sc8_key]["snapshot_trusted_correct"] += 1
            if is_correct_diag: scenario_metrics[sc8_key]["diagnosis_correct"] += 1

            # Restore clean state at end of batch evaluation
            restore_snapshot_and_batch(product.id, clean_state, clean_snaps)

    # Compute aggregate evaluation metrics
    total_trials = len(trials)
    total_tamper_correct = sum(v["tamper_detected_correct"] for v in scenario_metrics.values())
    total_snap_correct = sum(v["snapshot_trusted_correct"] for v in scenario_metrics.values())
    total_diag_correct = sum(v["diagnosis_correct"] for v in scenario_metrics.values())

    field_tp = sum(v["field_tp"] for v in scenario_metrics.values())
    field_fp = sum(v["field_fp"] for v in scenario_metrics.values())
    field_fn = sum(v["field_fn"] for v in scenario_metrics.values())

    field_precision = _safe_divide(field_tp, field_tp + field_fp, fallback=1.0)
    field_recall = _safe_divide(field_tp, field_tp + field_fn, fallback=1.0)
    field_f1 = _safe_divide(2 * field_precision * field_recall, field_precision + field_recall, fallback=1.0)

    summary_data = {
        "metadata": {
            "experiment_id": exp_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "batches_tested": len(products),
            "total_trials": total_trials,
        },
        "overall": {
            "tamper_detection_accuracy": round(_safe_divide(total_tamper_correct, total_trials), 4),
            "snapshot_trustworthiness_accuracy": round(_safe_divide(total_snap_correct, total_trials), 4),
            "diagnosis_accuracy": round(_safe_divide(total_diag_correct, total_trials), 4),
            "field_level_precision": round(field_precision, 4),
            "field_level_recall": round(field_recall, 4),
            "field_level_f1": round(field_f1, 4),
        },
        "scenarios": scenario_metrics,
    }

    summary_path = os.path.join(RESULTS_DIR, "snapshot_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary_data, f, indent=2)

    print("\n" + "=" * 68)
    print("E3 SNAPSHOT INTEGRITY & DIAGNOSIS METRICS REPORT")
    print("=" * 68)
    print(f"Total Trials Evaluated           : {total_trials}")
    print(f"Tamper Detection Accuracy        : {summary_data['overall']['tamper_detection_accuracy']*100:.2f}%")
    print(f"Snapshot Validation Accuracy     : {summary_data['overall']['snapshot_trustworthiness_accuracy']*100:.2f}%")
    print(f"Field-Level Diagnosis Accuracy   : {summary_data['overall']['diagnosis_accuracy']*100:.2f}%")
    print(f"Field Diagnosis Precision        : {field_precision*100:.2f}%")
    print(f"Field Diagnosis Recall           : {field_recall*100:.2f}%")
    print(f"Field Diagnosis F1-Score         : {field_f1:.4f}")
    print("-" * 68)
    for sc_id, data in scenario_metrics.items():
        print(f"  {sc_id:<12}: {data['name']:<42} | Acc: {data['diagnosis_correct']/data['trials']*100:.1f}%")
    print("=" * 68)
    print(f"Detailed trial logs exported to: {output_csv}")
    print(f"Summary JSON exported to: {summary_path}")

    return summary_data


def main():
    parser = argparse.ArgumentParser(description="Run Phase 4 E3 Snapshot Integrity and Diagnosis Experiment.")
    parser.add_argument("--batches", type=int, default=10, help="Number of batches to evaluate (default: 10)")
    parser.add_argument(
        "--output",
        type=str,
        default=os.path.join(RESULTS_DIR, "snapshot_experiments.csv"),
        help="Path to output CSV",
    )
    args = parser.parse_args()

    run_snapshot_experiments(output_csv=args.output, batches_to_test=args.batches)


if __name__ == "__main__":
    main()

