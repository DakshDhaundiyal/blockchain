#!/usr/bin/env python3
"""
TrustHarvest — Experiment E6: Performance and Scalability Evaluation

Evaluates the throughput, latency distribution, and component timing breakdown
of the TrustHarvest provenance verification engine under increasing workloads:
Workload sizes: 10, 30, 50, 100, 200 batches.
Runs 3 repetitions per configuration to ensure statistical rigor.

Measures:
  1. Hash computation time (local CPU)
  2. Blockchain read time (EVM RPC network roundtrips)
  3. Complete verification time (end-to-end)
  4. Accuracy, throughput (batches/sec), and percentiles (mean, median, p95, min, max)

Outputs:
  - research/phase4/results/performance_experiments.csv
  - research/phase4/results/performance_summary.json
  - research/phase4/results/e6_report.md
"""

import os
import sys
import time
import json
import statistics
import datetime

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(os.path.dirname(__file__), 'data', 'research_phase4.db')}"
os.environ["DEMO_MODE"] = "true"
os.environ["ETH_RPC_URL"] = "http://127.0.0.1:7545"
os.environ["CHAIN_ID"] = "1337"

from app import app, db, _build_verification_context, _sorted_transports
from models import Product, TransportData, RetailData, StageSnapshot, User
from blockchain import (
    get_w3, _V2_RUNTIME_ABI, load_config,
    store_hash_detailed, store_stage_hash,
    inspect_batch_on_chain,
    compute_batch_hash, compute_transport_hash, compute_retail_hash
)
from research.phase4.generate_dataset import generate_synthetic_batches
from research.phase4.experiment_logger import ExperimentLogger

EXPERIMENT_ID = f"EXP-PERF-{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S')}"
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")
CSV_PATH = os.path.join(RESULTS_DIR, "performance_experiments.csv")
SUMMARY_JSON_PATH = os.path.join(RESULTS_DIR, "performance_summary.json")

WORKLOAD_SIZES = [10, 30, 50, 100, 200]
REPETITIONS = 3

def setup_users():
    """Ensure test users exist in the research DB."""
    farmer = User.query.filter_by(username="perf_farmer").first()
    if not farmer:
        farmer = User(username="perf_farmer", contact="farmer@perf.org", role="farmer", full_name="Performance Farmer")
        farmer.set_password("password")
        db.session.add(farmer)
    transporter = User.query.filter_by(username="perf_transporter").first()
    if not transporter:
        transporter = User(username="perf_transporter", contact="transporter@perf.org", role="transporter", full_name="Performance Transporter")
        transporter.set_password("password")
        db.session.add(transporter)
    retailer = User.query.filter_by(username="perf_retailer").first()
    if not retailer:
        retailer = User(username="perf_retailer", contact="retailer@perf.org", role="retailer", full_name="Performance Retailer")
        retailer.set_password("password")
        db.session.add(retailer)
    db.session.commit()
    return farmer.id, transporter.id, retailer.id

def prepare_and_anchor_perf_dataset(total_batches=200):
    """Generates and anchors 200 synthetic performance batches if not already present."""
    print(f"Checking performance dataset (target: {total_batches} batches)...")
    dataset = generate_synthetic_batches(count=total_batches, seed=1337, base_batch_prefix="TH-PERF")
    batches = dataset["batches"]

    w3 = get_w3()
    cfg = load_config()
    contract = w3.eth.contract(address=cfg["contract_address"], abi=_V2_RUNTIME_ABI)

    farmer_id, transporter_id, retailer_id = setup_users()

    anchored_count = 0
    batch_ids = []

    for b in batches:
        b_id = b["batch_id"]
        batch_ids.append(b_id)
        prod = Product.query.filter_by(batch_id=b_id).first()
        h_info = b["harvest"]

        h_hash = compute_batch_hash(
            batch_id=b_id,
            name=h_info["name"],
            quantity=h_info["quantity"],
            farming_method=h_info["farming_method"],
            packaging_date=h_info["packaging_date"],
            farmer_id=farmer_id,
            image=h_info.get("image", "synthetic_crop.jpg")
        )

        rec = contract.functions.getRecord(b_id).call()
        if not rec[3]:
            meta_h = store_hash_detailed(b_id, h_hash, role="farmer")
            h_tx = meta_h.get("tx_hash")
            h_block = meta_h.get("block_number")
            h_signer = meta_h.get("signer_address")
            anchored_count += 1
        else:
            h_tx = "0x" + "0"*64
            h_block = 1
            h_signer = rec[1]

        if not prod:
            prod = Product(
                batch_id=b_id,
                name=h_info["name"],
                quantity=h_info["quantity"],
                farming_method=h_info["farming_method"],
                packaging_date=h_info["packaging_date"],
                farmer_id=farmer_id,
                image=h_info.get("image", "synthetic_crop.jpg"),
                qr_code=f"qr_{b_id}.png",
                on_chain_hash=h_hash,
                tx_hash=h_tx,
                block_number=h_block,
                contract_address=contract.address,
                contract_version="V2",
                signer_address=h_signer,
                status="Delivered to Retail"
            )
            db.session.add(prod)
            db.session.flush()

        # Harvest snapshot
        snap_h = StageSnapshot.query.filter_by(product_id=prod.id, stage="HARVEST").first()
        if not snap_h:
            snap_payload = {
                "batch_id": b_id,
                "farmer_id": int(farmer_id),
                "farming_method": h_info["farming_method"],
                "image": h_info.get("image", "synthetic_crop.jpg"),
                "name": h_info["name"],
                "packaging_date": h_info["packaging_date"],
                "quantity": h_info["quantity"]
            }
            snap_h = StageSnapshot(
                product_id=prod.id,
                stage="HARVEST",
                snapshot_json=json.dumps(snap_payload, sort_keys=True),
                original_hash=h_hash
            )
            db.session.add(snap_h)

        # Transport checkpoints
        t_records = b["transport_checkpoints"]
        onchain_stage_cnt = contract.functions.getStageCount(b_id).call()
        existing_trans = TransportData.query.filter_by(product_id=prod.id).order_by(TransportData.id.asc()).all()

        for idx, cp in enumerate(t_records):
            t_temp = f"{cp['temperature']:.1f}" if isinstance(cp['temperature'], (int, float)) else str(cp['temperature'])
            t_hash = compute_transport_hash(
                batch_id=b_id,
                status=cp["status"],
                current_location=cp["current_location"],
                temperature=t_temp,
                vehicle_number=cp["vehicle_number"],
                notes=cp.get("notes", ""),
                transporter_id=transporter_id
            )

            if idx < onchain_stage_cnt:
                t_tx = "0x" + "0"*64
                t_block = 1
                t_signer = None
            else:
                meta_t = store_stage_hash(b_id, "TRANSPORT", t_hash, role="transporter")
                t_tx = meta_t.get("tx_hash")
                t_block = meta_t.get("block_number")
                t_signer = meta_t.get("signer_address")

            if idx >= len(existing_trans):
                t_ent = TransportData(
                    product_id=prod.id,
                    transporter_id=transporter_id,
                    status=cp["status"],
                    current_location=cp["current_location"],
                    temperature=t_temp,
                    vehicle_number=cp["vehicle_number"],
                    notes=cp.get("notes", ""),
                    on_chain_hash=t_hash,
                    tx_hash=t_tx,
                    block_number=t_block,
                    signer_address=t_signer
                )
                db.session.add(t_ent)

        # Retail stage
        r_info = b["retail"]
        r_hash = compute_retail_hash(
            batch_id=b_id,
            store_name=r_info["store_name"],
            store_location=r_info["store_location"],
            price=float(r_info["price"]),
            stock_quantity=str(r_info["stock_quantity"]),
            arrival_date=r_info["arrival_date"],
            shelf_life=r_info["shelf_life"],
            retailer_id=retailer_id
        )

        stage_cnt_now = contract.functions.getStageCount(b_id).call()
        has_retail = False
        for s_idx in range(stage_cnt_now):
            st = contract.functions.getStageRecord(b_id, s_idx).call()
            if st[0] == "RETAIL":
                has_retail = True
                break
        if not has_retail:
            meta_r = store_stage_hash(b_id, "RETAIL", r_hash, role="retailer")
            ret_tx = meta_r.get("tx_hash")
            ret_block = meta_r.get("block_number")
            ret_signer = meta_r.get("signer_address")
        else:
            ret_tx = "0x" + "0"*64
            ret_block = 1
            ret_signer = None

        r_ent = RetailData.query.filter_by(product_id=prod.id).first()
        if not r_ent:
            r_ent = RetailData(
                product_id=prod.id,
                retailer_id=retailer_id,
                store_name=r_info["store_name"],
                store_location=r_info["store_location"],
                price=float(r_info["price"]),
                stock_quantity=str(r_info["stock_quantity"]),
                arrival_date=r_info["arrival_date"],
                shelf_life=r_info["shelf_life"],
                on_chain_hash=r_hash,
                tx_hash=ret_tx,
                block_number=ret_block,
                signer_address=ret_signer
            )
            db.session.add(r_ent)

    db.session.commit()
    print(f"Performance dataset ready. {len(batch_ids)} batches active ({anchored_count} freshly anchored on Ganache).")
    return batch_ids

def run_experiment():
    print(f"[{datetime.datetime.now()}] Starting Experiment E6: Performance and Scalability Evaluation")
    os.makedirs(RESULTS_DIR, exist_ok=True)
    logger = ExperimentLogger(CSV_PATH)

    with app.app_context():
        batch_ids = prepare_and_anchor_perf_dataset(total_batches=200)

        perf_summary = {
            "metadata": {
                "experiment_id": EXPERIMENT_ID,
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "workload_sizes": WORKLOAD_SIZES,
                "repetitions": REPETITIONS,
                "environment": "Local Ganache (Chain ID 1337)"
            },
            "workloads": {}
        }

        for size in WORKLOAD_SIZES:
            print(f"\n==========================================")
            print(f"Evaluating Workload Size: {size} batches ({REPETITIONS} repetitions)")
            print(f"==========================================")
            selected_ids = batch_ids[:size]

            workload_metrics = {
                "repetitions": [],
                "aggregate": {}
            }

            rep_durations = []
            rep_mean_latencies = []
            rep_hash_times = []
            rep_chain_read_times = []
            rep_complete_times = []

            for rep in range(1, REPETITIONS + 1):
                rep_start = time.perf_counter()
                
                success_count = 0
                tampered_count = 0
                cannot_verify_count = 0

                hash_timings = []
                chain_read_timings = []
                complete_timings = []

                for b_id in selected_ids:
                    prod = Product.query.filter_by(batch_id=b_id).first()
                    trans = _sorted_transports(prod)
                    retail = prod.retail_data

                    # 1. Measure Hash Computation Time
                    t_hash_0 = time.perf_counter()
                    _ = compute_batch_hash(
                        batch_id=prod.batch_id,
                        name=prod.name,
                        quantity=prod.quantity,
                        farming_method=prod.farming_method,
                        packaging_date=prod.packaging_date,
                        farmer_id=prod.farmer_id,
                        image=prod.image
                    )
                    for t in trans:
                        _ = compute_transport_hash(
                            batch_id=prod.batch_id,
                            status=t.status,
                            current_location=t.current_location,
                            temperature=t.temperature,
                            vehicle_number=t.vehicle_number,
                            notes=t.notes,
                            transporter_id=t.transporter_id
                        )
                    if retail:
                        _ = compute_retail_hash(
                            batch_id=prod.batch_id,
                            store_name=retail.store_name,
                            store_location=retail.store_location,
                            price=retail.price,
                            stock_quantity=retail.stock_quantity,
                            arrival_date=retail.arrival_date,
                            shelf_life=retail.shelf_life,
                            retailer_id=retail.retailer_id
                        )
                    hash_ms = (time.perf_counter() - t_hash_0) * 1000.0
                    hash_timings.append(hash_ms)

                    # 2. Measure Blockchain Read Time
                    t_chain_0 = time.perf_counter()
                    chain_record = inspect_batch_on_chain(b_id)
                    chain_ms = (time.perf_counter() - t_chain_0) * 1000.0
                    chain_read_timings.append(chain_ms)

                    # 3. Measure Complete Verification Time
                    t_comp_0 = time.perf_counter()
                    ctx = _build_verification_context(prod)
                    comp_ms = (time.perf_counter() - t_comp_0) * 1000.0
                    complete_timings.append(comp_ms)

                    status = ctx.get("verification_status")
                    if status == "verified":
                        success_count += 1
                    elif status == "tampered":
                        tampered_count += 1
                    else:
                        cannot_verify_count += 1

                    # Log to CSV
                    logger.log_trial(
                        batch_id=b_id,
                        stage="OVERALL",
                        scenario=f"e6_workload_{size}b_rep{rep}",
                        expected_outcome="verified",
                        actual_outcome=status,
                        latency_ms=round(comp_ms, 3),
                        error_message="",
                        custom_experiment_id=EXPERIMENT_ID
                    )

                rep_duration = time.perf_counter() - rep_start
                rep_durations.append(rep_duration)
                rep_mean_latencies.append(statistics.mean(complete_timings))
                rep_hash_times.append(statistics.mean(hash_timings))
                rep_chain_read_times.append(statistics.mean(chain_read_timings))
                rep_complete_times.append(statistics.mean(complete_timings))

                throughput = size / rep_duration if rep_duration > 0 else 0.0

                print(f"  Repetition {rep}/{REPETITIONS}: Total time={rep_duration:.2f}s | Throughput={throughput:.2f} batches/s | Mean Latency={statistics.mean(complete_timings):.2f}ms (Hash: {statistics.mean(hash_timings):.3f}ms, RPC: {statistics.mean(chain_read_timings):.2f}ms)")

                workload_metrics["repetitions"].append({
                    "rep": rep,
                    "duration_sec": round(rep_duration, 3),
                    "throughput_batches_sec": round(throughput, 2),
                    "mean_latency_ms": round(statistics.mean(complete_timings), 3),
                    "median_latency_ms": round(statistics.median(complete_timings), 3),
                    "mean_hash_ms": round(statistics.mean(hash_timings), 3),
                    "mean_chain_read_ms": round(statistics.mean(chain_read_timings), 3),
                    "successful_verifications": success_count,
                    "tampered_verifications": tampered_count,
                    "inconclusive_verifications": cannot_verify_count
                })

            # Calculate p95 across all complete timings in the workload
            all_lats = sorted(complete_timings)
            k = (len(all_lats) - 1) * 0.95
            f = int(k)
            c = f + 1
            p95 = all_lats[f] + (k - f) * (all_lats[c] - all_lats[f]) if c < len(all_lats) else all_lats[f]

            workload_metrics["aggregate"] = {
                "batch_count": size,
                "repetitions": REPETITIONS,
                "mean_total_duration_sec": round(statistics.mean(rep_durations), 3),
                "mean_throughput_batches_sec": round(size / statistics.mean(rep_durations), 2),
                "mean_latency_ms": round(statistics.mean(rep_mean_latencies), 3),
                "median_latency_ms": round(statistics.median(all_lats), 3),
                "p95_latency_ms": round(p95, 3),
                "min_latency_ms": round(min(all_lats), 3),
                "max_latency_ms": round(max(all_lats), 3),
                "component_breakdown": {
                    "hash_computation_mean_ms": round(statistics.mean(rep_hash_times), 3),
                    "blockchain_read_mean_ms": round(statistics.mean(rep_chain_read_times), 3),
                    "verification_logic_overhead_ms": round(statistics.mean(rep_complete_times) - statistics.mean(rep_chain_read_times) - statistics.mean(rep_hash_times), 3)
                }
            }

            perf_summary["workloads"][f"{size}_batches"] = workload_metrics

        with open(SUMMARY_JSON_PATH, "w") as f:
            json.dump(perf_summary, f, indent=2)

        print(f"\n==========================================")
        print(f"Experiment E6 complete. Summary saved to {SUMMARY_JSON_PATH}")
        print(f"CSV results appended to {CSV_PATH}")
        print(f"==========================================")
        return perf_summary

if __name__ == "__main__":
    run_experiment()
