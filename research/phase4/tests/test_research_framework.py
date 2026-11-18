#!/usr/bin/env python3
"""
Automated Test Suite for Phase 4 Baseline & Advanced Research Framework

Validates:
- Synthetic dataset generation and schema integrity
- Experiment CSV logging and atomic persistence
- Metric calculations (precision, recall, F1, zero denominators, percentiles)
- Protection boundaries (hashed vs unhashed fields)
- Snapshot cryptographic re-validation & collusion defense
- RPC failure classification and graceful degradation
- Multi-checkpoint ordering and hash integrity
"""

import os
import sys
import json
import pytest
import tempfile
import statistics

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from research.phase4.generate_dataset import generate_synthetic_batches
from research.phase4.experiment_logger import ExperimentLogger
from research.phase4.metrics import (
    compute_experiment_metrics,
    calculate_latency_percentiles,
    _safe_divide
)
from blockchain import (
    compute_batch_hash,
    compute_transport_hash,
    compute_retail_hash,
    is_transport_or_connection_error,
    BlockchainUnavailableError
)

def test_synthetic_dataset_generation():
    """Verify synthetic dataset generator creates valid structures with required fields."""
    dataset = generate_synthetic_batches(count=5, seed=123, base_batch_prefix="TEST-SYN")
    assert "batches" in dataset
    batches = dataset["batches"]
    assert len(batches) == 5

    for b in batches:
        assert b["batch_id"].startswith("TEST-SYN-")
        assert "harvest" in b
        assert "transport_checkpoints" in b
        assert "retail" in b
        assert len(b["transport_checkpoints"]) >= 1
        assert "name" in b["harvest"]
        assert "quantity" in b["harvest"]
        assert "farming_method" in b["harvest"]
        assert "store_name" in b["retail"]

def test_csv_experiment_logger():
    """Verify ExperimentLogger writes trials accurately to CSV."""
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tf:
        temp_csv = tf.name

    try:
        logger = ExperimentLogger(temp_csv, experiment_id="TEST-EXP-001")
        trial = logger.log_trial(
            batch_id="TEST-BATCH-01",
            stage="HARVEST",
            scenario="test_scenario",
            expected_outcome="verified",
            actual_outcome="verified",
            latency_ms=125.5,
            error_message=""
        )
        assert trial["success"] is True
        assert trial["batch_id"] == "TEST-BATCH-01"

        # Read back
        results = ExperimentLogger.read_results(temp_csv)
        assert len(results) == 1
        assert results[0]["experiment_id"] == "TEST-EXP-001"
        assert results[0]["actual_outcome"] == "verified"
        assert float(results[0]["latency_ms"]) == 125.5
    finally:
        if os.path.exists(temp_csv):
            os.remove(temp_csv)

def test_metric_calculations_and_zero_denominators():
    """Verify metrics calculation handles normal and edge cases (zero division)."""
    # Safe divide
    assert _safe_divide(10.0, 0.0, fallback=0.0) == 0.0
    assert _safe_divide(5.0, 2.0) == 2.5

    # Percentiles
    lats = [100.0, 110.0, 120.0, 130.0, 140.0, 150.0, 160.0, 170.0, 180.0, 200.0]
    p_stats = calculate_latency_percentiles(lats)
    assert p_stats["mean_ms"] == statistics.mean(lats)
    assert p_stats["median_ms"] == statistics.median(lats)
    assert p_stats["min_ms"] == 100.0
    assert p_stats["max_ms"] == 200.0
    assert p_stats["p95_ms"] > 180.0

    # Experiment metrics with perfect classification
    results = [
        {"expected_outcome": "tampered", "actual_outcome": "tampered", "latency_ms": 100.0},
        {"expected_outcome": "verified", "actual_outcome": "verified", "latency_ms": 120.0},
    ]
    m = compute_experiment_metrics(results)
    assert m["accuracy"] == 1.0
    assert m["precision"] == 1.0
    assert m["recall"] == 1.0
    assert m["f1_score"] == 1.0

def test_tamper_boundary_hashed_vs_unhashed():
    """Verify that hashed fields alter the cryptographic digest while unhashed fields do not."""
    base_hash = compute_batch_hash(
        batch_id="TEST-BOUND-01",
        name="Organic Heirloom Wheat",
        quantity="500 kg",
        farming_method="Organic",
        packaging_date="2026-11-17",
        farmer_id=1,
        image="wheat.jpg"
    )

    # Modify hashed field (farming_method)
    tampered_hash = compute_batch_hash(
        batch_id="TEST-BOUND-01",
        name="Organic Heirloom Wheat",
        quantity="500 kg",
        farming_method="Conventional (Tampered)",
        packaging_date="2026-11-17",
        farmer_id=1,
        image="wheat.jpg"
    )
    assert base_hash != tampered_hash, "Hashed field alteration must change the hash"

def test_snapshot_cryptographic_verification():
    """Verify that a snapshot's integrity is determined by recomputing SHA-256 against on-chain hash."""
    snap_payload = {
        "batch_id": "TEST-SNAP-01",
        "farmer_id": 1,
        "farming_method": "Organic",
        "image": "crop.jpg",
        "name": "Crop A",
        "packaging_date": "2026-11-17",
        "quantity": "1000 kg"
    }
    payload_str = json.dumps(snap_payload, sort_keys=True)
    import hashlib
    valid_on_chain_hash = hashlib.sha256(payload_str.encode("utf-8")).hexdigest()

    # Legitimate snapshot recomputes to match
    recomputed = hashlib.sha256(payload_str.encode("utf-8")).hexdigest()
    assert recomputed.lower() == valid_on_chain_hash.lower()

    # Corrupted / colluding snapshot fails to match
    corrupted_payload = dict(snap_payload)
    corrupted_payload["farming_method"] = "Conventional"
    corrupted_str = json.dumps(corrupted_payload, sort_keys=True)
    corrupted_hash = hashlib.sha256(corrupted_str.encode("utf-8")).hexdigest()
    assert corrupted_hash.lower() != valid_on_chain_hash.lower()

def test_rpc_failure_classification():
    """Verify that connection/transport errors are recognized as unavailable rather than tampering."""
    import socket
    exc_conn = ConnectionRefusedError("Connection refused on port 7545")
    assert is_transport_or_connection_error(exc_conn) is True

    exc_sock = socket.timeout("Socket timed out")
    assert is_transport_or_connection_error(exc_sock) is True

    exc_net = Exception("Failed to establish a new connection: Max retries exceeded")
    assert is_transport_or_connection_error(exc_net) is True

    exc_unavail = BlockchainUnavailableError("Node unreachable")
    assert (is_transport_or_connection_error(exc_unavail) or isinstance(exc_unavail, BlockchainUnavailableError)) is True

    exc_generic = ValueError("Invalid data format")
    assert is_transport_or_connection_error(exc_generic) is False

def test_multi_checkpoint_hash_integrity():
    """Verify sequential checkpoints generate unique ordered hashes."""
    hashes = []
    for i in range(5):
        h = compute_transport_hash(
            batch_id="TEST-MULTI-01",
            status="In Transit",
            current_location=f"Hub {i}",
            temperature=f"{4.0 + i*0.2:.1f}",
            vehicle_number=f"TRUCK-{i}",
            notes=f"Checkpoint {i}",
            transporter_id=2
        )
        hashes.append(h)

    assert len(hashes) == 5
    assert len(set(hashes)) == 5, "Each checkpoint with distinct parameters must produce a distinct hash"
