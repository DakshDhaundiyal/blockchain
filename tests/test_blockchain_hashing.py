import pytest
from blockchain import compute_batch_hash, fetch_on_chain_status
from models import db, Product, User

def test_compute_batch_hash_deterministic():
    hash1 = compute_batch_hash(
        batch_id="TH-TEST-001",
        name="Organic Apples",
        quantity="100 kg",
        farming_method="Organic",
        packaging_date="2026-10-15",
        farmer_id=1,
        image="default.jpg"
    )
    hash2 = compute_batch_hash(
        batch_id="TH-TEST-001",
        name="Organic Apples",
        quantity="100 kg",
        farming_method="Organic",
        packaging_date="2026-10-15",
        farmer_id=1,
        image="default.jpg"
    )
    assert hash1 == hash2
    assert len(hash1) == 64  # SHA-256 hex string

def test_compute_batch_hash_tamper_sensitivity():
    original_hash = compute_batch_hash(
        batch_id="TH-TEST-001",
        name="Organic Apples",
        quantity="100 kg",
        farming_method="Organic",
        packaging_date="2026-10-15",
        farmer_id=1,
        image="default.jpg"
    )

    # Tampering with name
    tampered_name = compute_batch_hash(
        batch_id="TH-TEST-001",
        name="Non-Organic Apples",  # Altered!
        quantity="100 kg",
        farming_method="Organic",
        packaging_date="2026-10-15",
        farmer_id=1,
        image="default.jpg"
    )
    assert original_hash != tampered_name

    # Tampering with quantity
    tampered_qty = compute_batch_hash(
        batch_id="TH-TEST-001",
        name="Organic Apples",
        quantity="500 kg",  # Altered!
        farming_method="Organic",
        packaging_date="2026-10-15",
        farmer_id=1,
        image="default.jpg"
    )
    assert original_hash != tampered_qty

def test_fetch_on_chain_status_graceful_rpc_offline():
    # When Ganache is not running or node is offline, fetch_on_chain_status must return
    # status 'rpc_offline' without throwing unhandled exceptions
    result = fetch_on_chain_status("TH-NONEXISTENT")
    assert isinstance(result, dict)
    assert "status" in result
    assert result["status"] in ["rpc_offline", "not_found", "ok"]

def test_verification_route_shows_honest_offline_state(client, app):
    with app.app_context():
        farmer = User.query.filter_by(username="farmer_test").first()
        prod = Product(
            batch_id="TH-OFFLINE-TEST",
            name="Sweet Cherries",
            quantity="50 kg",
            farming_method="Organic",
            packaging_date="2026-10-15",
            farmer_id=farmer.id,
            image="default.jpg",
            qr_code="qr_TH-OFFLINE-TEST.png",
            on_chain_hash="11223344556677889900aabbccddeeff11223344556677889900aabbccddeeff",
            status="Harvested"
        )
        db.session.add(prod)
        db.session.commit()

    # Access verify route
    res = client.get("/verify/TH-OFFLINE-TEST")
    assert res.status_code == 200
    # Must never falsely show "TAMPER DETECTED" just because the RPC is down!
    # If RPC is offline, it should show "RPC OFFLINE" banner
    if b"BLOCKCHAIN RPC OFFLINE" in res.data:
        assert b"TAMPER DETECTED" not in res.data
        assert b"Live Ethereum node is currently unreachable" in res.data
