import os
from datetime import datetime, timedelta, timezone
import pytest
from solcx import compile_standard, install_solc, set_solc_version

from app import app as flask_app, _build_verification_context
from models import db, User, Product, FarmerData, TransportData, RetailData
from blockchain import (
    compute_batch_hash, compute_transport_hash, compute_retail_hash,
    get_w3, get_or_deploy_contract, store_hash_detailed, store_stage_hash,
    get_signer_account,
)


def _ganache_up():
    try:
        w3 = get_w3(die_on_error=False)
        return bool(w3 and w3.is_connected())
    except Exception:
        return False


def _make_product(farmer_id, batch_id="TH-PH1-001", contract_address="0x1111111111111111111111111111111111111111", contract_version="V2"):
    h = compute_batch_hash(
        batch_id=batch_id,
        name="Organic Gala Apples",
        quantity="100 kg",
        farming_method="100% Certified Organic",
        packaging_date="2026-10-10",
        farmer_id=farmer_id,
        image="default.jpg",
    )
    prod = Product(
        batch_id=batch_id,
        name="Organic Gala Apples",
        quantity="100 kg",
        farming_method="100% Certified Organic",
        packaging_date="2026-10-10",
        farmer_id=farmer_id,
        image="default.jpg",
        qr_code=f"qr_{batch_id}.png",
        on_chain_hash=h,
        contract_address=contract_address,
        contract_version=contract_version,
        status="Harvested",
    )
    db.session.add(prod)
    db.session.flush()
    db.session.add(FarmerData(
        product_id=prod.id,
        farm_name="Evergreen Orchard",
        farm_location="Yakima, WA",
        harvest_date="2026-10-10",
    ))
    return prod, h


def test_three_outcomes_and_pending_incomplete_journey(app, monkeypatch):
    with app.app_context():
        farmer = User.query.filter_by(username="farmer_test").first()
        prod, h = _make_product(farmer.id, batch_id="TH-PENDING-01")
        db.session.commit()

        # Harvest verified, transport/retail not done yet -> Verified with Pending steps
        monkeypatch.setattr("app.inspect_batch_on_chain", lambda *a, **kw: {
            "status": "ok",
            "hash": h,
            "contract_address": prod.contract_address,
            "contract_version": "V2",
            "registered_by": "0xFarmer0000000000000000000000000000000001",
            "timestamp": datetime.now(timezone.utc),
            "stages": [],
            "truncated": False,
            "expected_signers": {
                "farmer": {"0xfarmer0000000000000000000000000000000001"},
                "transporter": {"0xtrans00000000000000000000000000000000002"},
                "retailer": {"0xretail0000000000000000000000000000000003"},
            },
            "conflict_details": None,
            "error": None,
        })

        ctx = _build_verification_context(prod)
        assert ctx["verification_status"] == "verified"
        assert ctx["result_label"] == "Verified"
        assert "pending" in ctx["result_reason"].lower()
        assert ctx["has_pending_stages"] is True
        assert ctx["transport_verifications"] == []
        assert ctx["retail_verification"] is None


def test_missing_record_never_says_tampered(app, monkeypatch):
    with app.app_context():
        farmer = User.query.filter_by(username="farmer_test").first()
        transporter = User.query.filter_by(username="transporter_test").first()
        prod, h = _make_product(farmer.id, batch_id="TH-MISSING-01")

        # 1. Whole batch missing on-chain -> Can't check right now (NOT tampered)
        db.session.commit()
        monkeypatch.setattr("app.inspect_batch_on_chain", lambda *a, **kw: {
            "status": "not_found",
            "hash": None,
            "contract_address": None,
            "contract_version": None,
            "registered_by": None,
            "timestamp": None,
            "stages": [],
            "truncated": False,
            "expected_signers": None,
            "conflict_details": None,
            "error": "Batch not recorded on-chain",
        })
        ctx = _build_verification_context(prod)
        assert ctx["verification_status"] == "cannot_verify"
        assert ctx["result_label"] == "Can't check right now"
        assert ctx["is_tampered"] is False
        assert "not been recorded" in ctx["result_reason"].lower()

        # 2. Harvest exists & matches, but DB Transport row missing on chain -> Can't check right now (NOT tampered, NOT pending)
        db.session.add(TransportData(
            product_id=prod.id,
            transporter_id=transporter.id,
            status="In Transit",
            current_location="Seattle Depot",
            temperature="3.9 °C",
            vehicle_number="TRK-11",
        ))
        db.session.commit()

        monkeypatch.setattr("app.inspect_batch_on_chain", lambda *a, **kw: {
            "status": "ok",
            "hash": h,
            "contract_address": prod.contract_address,
            "contract_version": "V2",
            "registered_by": "0xfarmer",
            "timestamp": datetime.now(timezone.utc),
            "stages": [],  # Missing transport stage on chain!
            "truncated": False,
            "expected_signers": None,
            "conflict_details": None,
            "error": None,
        })
        ctx_missing_stage = _build_verification_context(prod)
        assert ctx_missing_stage["verification_status"] == "cannot_verify"
        assert ctx_missing_stage["result_label"] == "Can't check right now"
        assert ctx_missing_stage["is_tampered"] is False
        assert ctx_missing_stage["transport_verifications"][0]["status"] == "unrecorded"


def test_offline_blockchain_returns_cant_check_right_now(app, monkeypatch):
    with app.app_context():
        farmer = User.query.filter_by(username="farmer_test").first()
        prod, _ = _make_product(farmer.id, batch_id="TH-OFFLINE-02")
        db.session.commit()

        monkeypatch.setattr("app.inspect_batch_on_chain", lambda *a, **kw: {
            "status": "rpc_offline",
            "hash": None,
            "contract_address": None,
            "contract_version": None,
            "registered_by": None,
            "timestamp": None,
            "stages": [],
            "truncated": False,
            "expected_signers": None,
            "conflict_details": None,
            "error": "RPC unreachable",
        })
        ctx = _build_verification_context(prod)
        assert ctx["verification_status"] == "cannot_verify"
        assert ctx["result_label"] == "Can't check right now"
        assert ctx["is_rpc_offline"] is True
        assert ctx["is_tampered"] is False


def test_genuine_mismatch_names_exact_stage_and_multiple_checkpoints(app, monkeypatch):
    with app.app_context():
        farmer = User.query.filter_by(username="farmer_test").first()
        transporter = User.query.filter_by(username="transporter_test").first()
        retailer = User.query.filter_by(username="retailer_test").first()
        prod, h = _make_product(farmer.id, batch_id="TH-MULTI-01")

        t0 = datetime(2026, 10, 11, 8, 0, tzinfo=timezone.utc)
        c1 = TransportData(
            product_id=prod.id,
            transporter_id=transporter.id,
            status="Picked Up",
            current_location="Farm Gate",
            temperature="4.0 °C",
            vehicle_number="TRK-1",
            notes="Leg 1",
            timestamp=t0,
        )
        c2 = TransportData(
            product_id=prod.id,
            transporter_id=transporter.id,
            status="Delivered",
            current_location="Cold Hub",
            temperature="3.5 °C",
            vehicle_number="TRK-1",
            notes="Leg 2",
            timestamp=t0 + timedelta(hours=3),
        )
        r = RetailData(
            product_id=prod.id,
            retailer_id=retailer.id,
            store_name="Fresh Mart",
            store_location="Seattle, WA",
            price=4.50,
            stock_quantity="90 kg",
            arrival_date="2026-10-12",
            shelf_life="14 Days",
        )
        db.session.add_all([c1, c2, r])
        db.session.commit()

        h_c1 = compute_transport_hash(prod.batch_id, c1.status, c1.current_location, c1.temperature, c1.vehicle_number, c1.notes, transporter.id)
        h_c2 = compute_transport_hash(prod.batch_id, c2.status, c2.current_location, c2.temperature, c2.vehicle_number, c2.notes, transporter.id)
        h_r = compute_retail_hash(prod.batch_id, r.store_name, r.store_location, r.price, r.stock_quantity, r.arrival_date, r.shelf_life, retailer.id)

        chain_payload = {
            "status": "ok",
            "hash": h,
            "contract_address": prod.contract_address,
            "contract_version": "V2",
            "registered_by": "0xFarmer1",
            "timestamp": t0,
            "stages": [
                {"index": 0, "stage": "TRANSPORT", "hash": h_c1, "recorded_by": "0xTrans1", "timestamp": t0},
                {"index": 1, "stage": "TRANSPORT", "hash": h_c2, "recorded_by": "0xTrans1", "timestamp": t0 + timedelta(hours=3)},
                {"index": 2, "stage": "RETAIL", "hash": h_r, "recorded_by": "0xRetail1", "timestamp": t0 + timedelta(hours=6)},
            ],
            "truncated": False,
            "expected_signers": None,
            "conflict_details": None,
            "error": None,
        }
        monkeypatch.setattr("app.inspect_batch_on_chain", lambda *a, **kw: chain_payload)

        # Clean full multi-checkpoint chain -> Verified
        ctx_clean = _build_verification_context(prod)
        assert ctx_clean["verification_status"] == "verified"
        assert ctx_clean["result_label"] == "Verified"
        assert len(ctx_clean["transport_verifications"]) == 2
        assert all(tv["status"] == "verified" for tv in ctx_clean["transport_verifications"])

        # Alter checkpoint #2 in DB -> Changed after recording, names Transport checkpoint #2
        c2.temperature = "22.0 °C"
        db.session.commit()
        ctx_bad_c2 = _build_verification_context(prod)
        assert ctx_bad_c2["verification_status"] == "tampered"
        assert ctx_bad_c2["result_label"] == "Changed after recording"
        assert "Transport checkpoint #2" in ctx_bad_c2["result_reason"]

        # Restore checkpoint #2, reorder timestamps on-chain -> mismatch detected in chronological check
        c2.temperature = "3.5 °C"
        db.session.commit()
        chain_payload["stages"][0]["hash"], chain_payload["stages"][1]["hash"] = h_c2, h_c1
        ctx_reordered = _build_verification_context(prod)
        assert ctx_reordered["verification_status"] == "tampered"
        assert ctx_reordered["result_label"] == "Changed after recording"


def test_unexpected_signer_treated_as_cant_check_right_now(app, monkeypatch):
    with app.app_context():
        farmer = User.query.filter_by(username="farmer_test").first()
        prod, h = _make_product(farmer.id, batch_id="TH-SIGNER-01")
        db.session.commit()

        monkeypatch.setattr("app.inspect_batch_on_chain", lambda *a, **kw: {
            "status": "ok",
            "hash": h,
            "contract_address": prod.contract_address,
            "contract_version": "V2",
            "registered_by": "0xAttackerWallet99999999999999999999999999",
            "timestamp": datetime.now(timezone.utc),
            "stages": [],
            "truncated": False,
            "expected_signers": {
                "farmer": {"0xfarmer0000000000000000000000000000000001"},
                "transporter": {"0xtrans00000000000000000000000000000000002"},
                "retailer": {"0xretail0000000000000000000000000000000003"},
            },
            "conflict_details": None,
            "error": None,
        })
        ctx = _build_verification_context(prod)
        assert ctx["verification_status"] == "cannot_verify"
        assert ctx["result_label"] == "Can't check right now"
        assert ctx["is_tampered"] is False
        assert "unexpected account" in ctx["result_reason"].lower()


@pytest.mark.skipif(not _ganache_up(), reason="Ganache node not reachable")
def test_v1_historical_batch_readonly_verification_live(app):
    """Deploys a genuine V1 TrustHarvest contract directly in test and verifies read-only V1 compatibility."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    v1_path = os.path.join(base_dir, "contracts", "legacy", "TrustHarvest.sol")
    with open(v1_path, "r", encoding="utf-8") as f:
        v1_src = f.read()

    try:
        install_solc("0.8.19")
    except Exception:
        pass
    set_solc_version("0.8.19")

    compiled = compile_standard(
        {
            "language": "Solidity",
            "sources": {"TrustHarvest.sol": {"content": v1_src}},
            "settings": {"outputSelection": {"*": {"*": ["abi", "evm.bytecode"]}}},
        },
        solc_version="0.8.19",
    )
    v1_data = compiled["contracts"]["TrustHarvest.sol"]["TrustHarvest"]
    w3 = get_w3()
    deployer = get_signer_account(w3, "deployer")
    V1Contract = w3.eth.contract(abi=v1_data["abi"], bytecode=v1_data["evm"]["bytecode"]["object"])
    tx_hash = V1Contract.constructor().transact({"from": deployer})
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    v1_addr = receipt["contractAddress"]
    v1_instance = w3.eth.contract(address=v1_addr, abi=v1_data["abi"])

    batch_id = "TH-LEGACY-V1-001"
    with app.app_context():
        farmer = User.query.filter_by(username="farmer_test").first()
        prod, h = _make_product(farmer.id, batch_id=batch_id, contract_address=v1_addr, contract_version=None)
        db.session.commit()

        s_tx = v1_instance.functions.storeHash(batch_id, h).transact({"from": deployer})
        w3.eth.wait_for_transaction_receipt(s_tx)

        ctx = _build_verification_context(prod)
        assert ctx["verification_status"] == "verified"
        assert ctx["result_label"] == "Verified"
        assert ctx["resolved_contract_version"] == "V1"
        assert ctx["contract_source_addr"].lower() == v1_addr.lower()

