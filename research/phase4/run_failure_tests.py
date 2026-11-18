"""
TrustHarvest — Phase 4 Research Experiment Framework
Module: run_failure_tests.py (Experiment E4: Failure and Security Scenarios)

Evaluates system behavior under missing evidence, network outages, and protocol anomalies:
- E4.1 RPC and network failures (offline node, invalid endpoint, timeouts)
- E4.2 Database and provenance failures (missing DB row, unanchored batch, missing snapshot)
- E4.3 Signer and stage anomalies (unexpected signer, unrecognized stage, extra on-chain stages)
- E4.4 Consistency failures (DB write succeeds but chain fails; chain anchored but DB missing)
Crucial requirement: RPC failures must NEVER be reported as tampering; must return 'cannot_verify'.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple
from unittest.mock import MagicMock, patch

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
from models import db, Product, StageSnapshot
from blockchain import BlockchainUnavailableError, BlockchainError
from research.phase4.experiment_logger import ExperimentLogger


def _safe_divide(n: float, d: float, fallback: float = 0.0) -> float:
    return fallback if d == 0 else n / d


def run_failure_experiments(
    output_csv: str = os.path.join(RESULTS_DIR, "failure_experiments.csv"),
    batches_to_test: int = 5,
) -> Dict[str, Any]:
    """
    Executes all failure and security test scenarios and logs trial records.
    """
    exp_id = f"EXP-FAIL-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    logger = ExperimentLogger(output_csv, experiment_id=exp_id)
    trials = []

    scenario_stats = {}

    def log_result(batch_id, stage, scenario, expected, actual, lat_ms, err_msg):
        # Crucial: verify that the system did NOT falsely report 'tampered' or 'verified' when failure occurred
        is_success = bool(str(expected).strip().lower() == str(actual).strip().lower())
        row = logger.log_trial(
            batch_id=batch_id,
            stage=stage,
            scenario=scenario,
            expected_outcome=expected,
            actual_outcome=actual,
            latency_ms=lat_ms,
            error_message=err_msg,
        )
        trials.append(row)
        if scenario not in scenario_stats:
            scenario_stats[scenario] = {
                "category": scenario.split("_")[0],
                "expected": expected,
                "trials": 0,
                "passed": 0,
                "falsely_claimed_tampered": 0,
                "falsely_claimed_verified": 0,
            }
        scenario_stats[scenario]["trials"] += 1
        if is_success:
            scenario_stats[scenario]["passed"] += 1
        if actual == "tampered" and expected != "tampered":
            scenario_stats[scenario]["falsely_claimed_tampered"] += 1
        if actual == "verified" and expected != "verified":
            scenario_stats[scenario]["falsely_claimed_verified"] += 1
        return row

    with app.app_context():
        products = Product.query.order_by(Product.id.asc()).limit(batches_to_test).all()
        if not products:
            raise RuntimeError("No products found in research_phase4.db.")

        print(f"Executing E4 Failure & Security Evaluation across {len(products)} batches...")

        for p_idx, product in enumerate(products, 1):
            batch_id = product.batch_id
            print(f"[{p_idx}/{len(products)}] Running Failure Scenarios for Batch {batch_id}...")

            # =================================================================
            # E4.1: RPC & NETWORK FAILURES
            # =================================================================

            # Scenario 1: Ganache RPC offline
            with patch("app.inspect_batch_on_chain") as mock_inspect:
                mock_inspect.return_value = {
                    "status": "rpc_offline",
                    "hash": None,
                    "contract_address": None,
                    "error": "Connection to http://127.0.0.1:7545 refused.",
                }
                t0 = time.perf_counter()
                ctx = _build_verification_context(product)
                lat = (time.perf_counter() - t0) * 1000.0
                log_result(
                    batch_id=batch_id,
                    stage="OVERALL",
                    scenario="e4_1_rpc_node_offline",
                    expected="cannot_verify",
                    actual=ctx.get("verification_status"),
                    lat_ms=lat,
                    err_msg="RPC node offline; must return cannot_verify",
                )

            # Scenario 2: Invalid RPC Endpoint URL
            with patch("app.inspect_batch_on_chain") as mock_inspect:
                mock_inspect.return_value = {
                    "status": "rpc_offline",
                    "hash": None,
                    "contract_address": None,
                    "error": "Invalid URL or DNS failure: http://invalid-rpc-node.internal:8545",
                }
                t0 = time.perf_counter()
                ctx = _build_verification_context(product)
                lat = (time.perf_counter() - t0) * 1000.0
                log_result(
                    batch_id=batch_id,
                    stage="OVERALL",
                    scenario="e4_1_rpc_invalid_endpoint",
                    expected="cannot_verify",
                    actual=ctx.get("verification_status"),
                    lat_ms=lat,
                    err_msg="Invalid RPC endpoint; must return cannot_verify",
                )

            # Scenario 3: RPC Read Timeout
            with patch("app.inspect_batch_on_chain") as mock_inspect:
                mock_inspect.return_value = {
                    "status": "rpc_offline",
                    "hash": None,
                    "contract_address": None,
                    "error": "HTTPProvider request timed out after 4 seconds.",
                }
                t0 = time.perf_counter()
                ctx = _build_verification_context(product)
                lat = (time.perf_counter() - t0) * 1000.0
                log_result(
                    batch_id=batch_id,
                    stage="OVERALL",
                    scenario="e4_1_rpc_timeout",
                    expected="cannot_verify",
                    actual=ctx.get("verification_status"),
                    lat_ms=lat,
                    err_msg="RPC timeout; must return cannot_verify",
                )

            # Scenario 4: Smart Contract View Call Reverted
            with patch("app.inspect_batch_on_chain") as mock_inspect:
                mock_inspect.return_value = {
                    "status": "rpc_offline",
                    "hash": None,
                    "contract_address": None,
                    "error": "Contract call reverted: execution reverted.",
                }
                t0 = time.perf_counter()
                ctx = _build_verification_context(product)
                lat = (time.perf_counter() - t0) * 1000.0
                log_result(
                    batch_id=batch_id,
                    stage="OVERALL",
                    scenario="e4_1_contract_read_revert",
                    expected="cannot_verify",
                    actual=ctx.get("verification_status"),
                    lat_ms=lat,
                    err_msg="Contract read revert; must return cannot_verify",
                )

            # =================================================================
            # E4.2: DATABASE & PROVENANCE FAILURES
            # =================================================================

            # Scenario 5: Missing Blockchain Anchor (Batch exists in DB, not on-chain)
            with patch("app.inspect_batch_on_chain") as mock_inspect:
                mock_inspect.return_value = {
                    "status": "not_found",
                    "hash": None,
                    "contract_address": product.contract_address,
                    "error": "Batch not found on-chain.",
                    "stages": [],
                }
                t0 = time.perf_counter()
                ctx = _build_verification_context(product)
                lat = (time.perf_counter() - t0) * 1000.0
                log_result(
                    batch_id=batch_id,
                    stage="OVERALL",
                    scenario="e4_2_missing_blockchain_anchor",
                    expected="cannot_verify",
                    actual=ctx.get("verification_status"),
                    lat_ms=lat,
                    err_msg="Batch unrecorded on-chain; must return cannot_verify",
                )

            # Scenario 6: Database record exists but on-chain history is empty
            with patch("app.inspect_batch_on_chain") as mock_inspect:
                mock_inspect.return_value = {
                    "status": "ok",
                    "hash": product.on_chain_hash,
                    "contract_address": product.contract_address,
                    "contract_version": "V2",
                    "stages": [],  # No transport or retail stages on-chain
                    "expected_signers": None,
                }
                t0 = time.perf_counter()
                ctx = _build_verification_context(product)
                lat = (time.perf_counter() - t0) * 1000.0
                # DB has transport/retail, but chain has zero stages -> cannot verify pending stages
                log_result(
                    batch_id=batch_id,
                    stage="OVERALL",
                    scenario="e4_2_stages_missing_onchain",
                    expected="cannot_verify",
                    actual=ctx.get("verification_status"),
                    lat_ms=lat,
                    err_msg="Transport checkpoints exist in DB but missing on-chain; must return cannot_verify",
                )

            # =================================================================
            # E4.3: SIGNER AND STAGE ANOMALIES
            # =================================================================

            # Scenario 7: Unexpected Transporter Signer Wallet
            with patch("app.inspect_batch_on_chain") as mock_inspect:
                # Transporter signer is unauthorized (e.g. 0xBadActor)
                mock_inspect.return_value = {
                    "status": "ok",
                    "hash": product.on_chain_hash,
                    "contract_address": product.contract_address,
                    "contract_version": "V2",
                    "expected_signers": {"transporter": {"0xexpectedtransporter000000000000000000"}},
                    "stages": [
                        {
                            "stage": "TRANSPORT",
                            "hash": product.transport_data[0].on_chain_hash if product.transport_data else "0x123",
                            "recorded_by": "0xunauthorizedsigner999999999999999999",
                            "timestamp": datetime.now(timezone.utc),
                        }
                    ],
                }
                t0 = time.perf_counter()
                ctx = _build_verification_context(product)
                lat = (time.perf_counter() - t0) * 1000.0
                log_result(
                    batch_id=batch_id,
                    stage="TRANSPORT",
                    scenario="e4_3_unexpected_transporter_signer",
                    expected="cannot_verify",
                    actual=ctx.get("transport_stage_status"),
                    lat_ms=lat,
                    err_msg="Unexpected signer; must flag conflict and report cannot_verify",
                )

            # Scenario 8: Unexpected Stage Entry (e.g. "POISON" / "JUNK" stage on-chain)
            with patch("app.inspect_batch_on_chain") as mock_inspect:
                mock_inspect.return_value = {
                    "status": "ok",
                    "hash": product.on_chain_hash,
                    "contract_address": product.contract_address,
                    "contract_version": "V2",
                    "stages": [
                        {
                            "stage": "POISON_JUNK_STAGE",
                            "hash": "0x9999999999999999999999999999999999999999999999999999999999999999",
                            "recorded_by": product.signer_address,
                            "timestamp": datetime.now(timezone.utc),
                        }
                    ],
                    "expected_signers": None,
                }
                t0 = time.perf_counter()
                ctx = _build_verification_context(product)
                lat = (time.perf_counter() - t0) * 1000.0
                log_result(
                    batch_id=batch_id,
                    stage="OVERALL",
                    scenario="e4_3_unexpected_stage_onchain",
                    expected="cannot_verify",
                    actual=ctx.get("verification_status"),
                    lat_ms=lat,
                    err_msg="Unrecognized stage on-chain; must return cannot_verify",
                )

            # Scenario 9: Extra Transport Entry On-Chain (On-chain stages > DB checkpoints)
            # Evaluates positional matching vulnerability: Does extra on-chain stages cause index shift / false tamper?
            with patch("app.inspect_batch_on_chain") as mock_inspect:
                extra_stages = []
                for s in range(len(product.transport_data) + 3):
                    extra_stages.append({
                        "stage": "TRANSPORT",
                        "hash": f"0x{'ab'*32}",
                        "recorded_by": product.signer_address,
                        "timestamp": datetime.now(timezone.utc),
                    })
                mock_inspect.return_value = {
                    "status": "ok",
                    "hash": product.on_chain_hash,
                    "contract_address": product.contract_address,
                    "contract_version": "V2",
                    "stages": extra_stages,
                    "expected_signers": None,
                }
                t0 = time.perf_counter()
                ctx = _build_verification_context(product)
                lat = (time.perf_counter() - t0) * 1000.0
                # In positional matching: extra on-chain entries with foreign hashes cause false tamper classification
                actual_status = ctx.get("verification_status")
                log_result(
                    batch_id=batch_id,
                    stage="TRANSPORT",
                    scenario="e4_3_extra_transport_onchain",
                    expected="cannot_verify",  # Ideal system should be inconclusive; actual reports tampered due to index shift
                    actual=actual_status,
                    lat_ms=lat,
                    err_msg=f"Extra stages on-chain: actual={actual_status}; reasons={'; '.join(ctx.get('cannot_verify_reasons', []))}",
                )

            # =================================================================
            # E4.4: CONSISTENCY FAILURES
            # =================================================================

            # Scenario 10: DB saved, but blockchain write failed / missing on-chain hash
            # Simulates transaction failure where DB committed but on_chain_hash is None
            original_h = product.on_chain_hash
            product.on_chain_hash = None
            db.session.commit()

            with patch("app.inspect_batch_on_chain") as mock_inspect:
                mock_inspect.return_value = {
                    "status": "not_found",
                    "hash": None,
                    "contract_address": product.contract_address,
                    "stages": [],
                }
                t0 = time.perf_counter()
                ctx = _build_verification_context(product)
                lat = (time.perf_counter() - t0) * 1000.0
                log_result(
                    batch_id=batch_id,
                    stage="OVERALL",
                    scenario="e4_4_db_saved_chain_reverted",
                    expected="cannot_verify",
                    actual=ctx.get("verification_status"),
                    lat_ms=lat,
                    err_msg="Database saved without blockchain confirmation; must return cannot_verify",
                )

            # Restore original on-chain hash
            product.on_chain_hash = original_h
            db.session.commit()

    total_trials = len(trials)
    total_passed = sum(1 for t in trials if t["success"])
    total_false_tamper = sum(s["falsely_claimed_tampered"] for s in scenario_stats.values())
    total_false_verified = sum(s["falsely_claimed_verified"] for s in scenario_stats.values())

    summary_data = {
        "metadata": {
            "experiment_id": exp_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "batches_tested": len(products),
            "total_trials": total_trials,
        },
        "overall": {
            "passed_trials": total_passed,
            "accuracy": round(_safe_divide(total_passed, total_trials), 4),
            "false_tamper_alarms": total_false_tamper,
            "false_verified_leaks": total_false_verified,
            "honest_inconclusive_rate": round(_safe_divide(total_passed, total_trials), 4),
        },
        "scenario_breakdown": scenario_stats,
    }

    summary_path = os.path.join(RESULTS_DIR, "failure_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary_data, f, indent=2)

    print("\n" + "=" * 68)
    print("E4 FAILURE AND SECURITY SCENARIOS METRICS REPORT")
    print("=" * 68)
    print(f"Total Failure Trials Evaluated   : {total_trials}")
    print(f"Correct Honest Handling Rate     : {total_passed} / {total_trials} ({summary_data['overall']['accuracy']*100:.2f}%)")
    print(f"False Tamper Alarms (on failure) : {total_false_tamper} (Must be 0)")
    print(f"False Verified Leaks             : {total_false_verified} (Must be 0)")
    print("-" * 68)
    for sc, data in scenario_stats.items():
        print(f"  {sc:<35} | Pass: {data['passed']}/{data['trials']} | False Tamper: {data['falsely_claimed_tampered']}")
    print("=" * 68)
    print(f"Detailed trial logs exported to: {output_csv}")
    print(f"Summary JSON exported to: {summary_path}")

    return summary_data


def main():
    parser = argparse.ArgumentParser(description="Run Phase 4 E4 Failure and Security Experiment.")
    parser.add_argument("--batches", type=int, default=5, help="Number of batches to evaluate (default: 5)")
    parser.add_argument(
        "--output",
        type=str,
        default=os.path.join(RESULTS_DIR, "failure_experiments.csv"),
        help="Path to output CSV",
    )
    args = parser.parse_args()

    run_failure_experiments(output_csv=args.output, batches_to_test=args.batches)


if __name__ == "__main__":
    main()
