import os
import uuid
import pytest
from solcx import compile_standard, install_solc, set_solc_version

from app import app as flask_app
from models import (
    db, User, Product, FarmerData, TransportData, RetailData, ensure_schema_columns
)
from blockchain import (
    get_w3, get_or_deploy_contract, store_hash_detailed, store_stage_hash,
    fetch_v2_provenance_details, compute_batch_hash, compute_transport_hash,
    compute_retail_hash, get_signer_account
)
from utils import evaluate_temperature, compute_trust_score


def _ganache_up():
    try:
        w3 = get_w3(die_on_error=False)
        return bool(w3 and w3.is_connected())
    except Exception:
        return False


def test_v2_multistage_abi_and_events():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    v2_path = os.path.join(base_dir, "contracts", "TrustHarvestV2.sol")
    with open(v2_path, "r", encoding="utf-8") as f:
        source = f.read()

    try:
        install_solc("0.8.19")
    except Exception:
        pass
    set_solc_version("0.8.19")

    compiled = compile_standard(
        {
            "language": "Solidity",
            "sources": {"TrustHarvestV2.sol": {"content": source}},
            "settings": {"outputSelection": {"*": {"*": ["abi", "evm.bytecode"]}}},
        },
        solc_version="0.8.19",
    )
    abi = compiled["contracts"]["TrustHarvestV2.sol"]["TrustHarvestV2"]["abi"]
    fns = {item["name"] for item in abi if item.get("type") == "function"}
    events = {item["name"] for item in abi if item.get("type") == "event"}
    errors = {item["name"] for item in abi if item.get("type") == "error"}

    assert {"storeHash", "getHash", "getRecord", "addStageHash", "getStageCount", "getStageRecord"}.issubset(fns)
    assert {"HashStored", "StageAnchored"}.issubset(events)
    assert {"EmptyBatchId", "EmptyHash", "EmptyStage", "AlreadyRegistered", "BatchNotFound"}.issubset(errors)


def test_transport_and_retail_hash_determinism_and_tamper_sensitivity():
    t1 = compute_transport_hash("TH-1", "In Transit", "Seattle Hub", "3.8 C", "TRK-1", "Cool", 2)
    t2 = compute_transport_hash("TH-1", "In Transit", "Seattle Hub", "3.8 C", "TRK-1", "Cool", 2)
    t_tampered = compute_transport_hash("TH-1", "In Transit", "Seattle Hub", "18.5 C", "TRK-1", "Cool", 2)
    assert t1 == t2
    assert len(t1) == 64
    assert t1 != t_tampered

    r1 = compute_retail_hash("TH-1", "Fresh Market", "Downtown", 4.99, "100 kg", "2026-10-03", "14 Days", 3)
    r2 = compute_retail_hash("TH-1", "Fresh Market", "Downtown", "4.990", "100 kg", "2026-10-03", "14 Days", 3)
    r_tampered = compute_retail_hash("TH-1", "Fresh Market", "Downtown", 7.99, "100 kg", "2026-10-03", "14 Days", 3)
    assert r1 == r2
    assert len(r1) == 64
    assert r1 != r_tampered


def test_temperature_telemetry_classification():
    opt = evaluate_temperature("3.8 °C")
    assert opt["status"] == "optimal"
    assert opt["celsius"] == 3.8

    elev = evaluate_temperature("11.5 C")
    assert elev["status"] == "elevated"

    breach = evaluate_temperature("24.0 °C")
    assert breach["status"] == "breach"

    unk = evaluate_temperature(None)
    assert unk["status"] == "unknown"


def test_trust_score_calculation():
    full = compute_trust_score(
        harvest_verified=True,
        transport_count=2,
        transport_verified_count=2,
        has_retail=True,
        retail_verified=True,
        has_temp_breach=False,
    )
    assert full["score"] == 100
    assert full["tier"] == "Excellent"

    breach = compute_trust_score(
        harvest_verified=True,
        transport_count=1,
        transport_verified_count=1,
        has_retail=True,
        retail_verified=True,
        has_temp_breach=True,
    )
    assert breach["score"] == 85
    assert breach["tier"] == "Good"

    unverified = compute_trust_score(
        harvest_verified=False,
        transport_count=0,
        transport_verified_count=0,
        has_retail=False,
        retail_verified=False,
        has_temp_breach=False,
    )
    assert unverified["score"] == 0
    assert unverified["tier"] == "Unverified / Alert"


def test_api_health_and_verify_json_endpoints(client, app):
    res_health = client.get("/api/health")
    assert res_health.status_code == 200
    h_json = res_health.get_json()
    assert h_json["status"] == "ok"
    assert "blockchain" in h_json
    assert "database" in h_json

    res_404 = client.get("/api/verify/TH-DOES-NOT-EXIST")
    assert res_404.status_code == 404

    with app.app_context():
        farmer = User.query.filter_by(username="farmer_test").first()
        prod = Product(
            batch_id="TH-API-001",
            name="Test Blueberries",
            quantity="80 kg",
            farming_method="100% Certified Organic",
            packaging_date="2026-10-20",
            farmer_id=farmer.id,
            image="default.jpg",
            qr_code="qr_TH-API-001.png",
            on_chain_hash="0" * 64,
            status="Harvested",
        )
        db.session.add(prod)
        db.session.commit()

    res_verify = client.get("/api/verify/TH-API-001")
    assert res_verify.status_code == 200
    payload = res_verify.get_json()
    assert payload["batch_id"] == "TH-API-001"
    assert payload["verification_status"] in ("verified", "tampered", "cannot_verify")
    assert payload["result_label"] in ("Verified", "Changed after recording", "Can't check right now")
    assert "reason" in payload
    assert payload["timeline"]["transport"] == "Pending"
    assert payload["timeline"]["shop"] == "Pending"
    assert "fingerprints" in payload
    # Sensitive internal blockchain details must not be present in public API
    for forbidden in ("blockchain_proof", "contract_address", "tx_hash", "block_number", "signer_address", "v2_provenance"):
        assert forbidden not in payload

    # Health endpoint must be trimmed similarly
    assert set(h_json.keys()) == {"status", "blockchain", "database"}
    assert list(h_json["blockchain"].keys()) == ["online"]


def test_demo_tamper_toggle_routes(client, app, monkeypatch):
    from datetime import datetime, timezone
    from models import StageSnapshot
    import json

    with app.app_context():
        farmer = User.query.filter_by(username="farmer_test").first()
        transporter = User.query.filter_by(username="transporter_test").first()
        h_hash = compute_batch_hash(
            batch_id="TH-TAMPER-UI",
            name="Organic Kale",
            quantity="60 kg",
            farming_method="100% Certified Organic",
            packaging_date="2026-10-21",
            farmer_id=farmer.id,
            image="default.jpg",
        )
        prod = Product(
            batch_id="TH-TAMPER-UI",
            name="Organic Kale",
            quantity="60 kg",
            farming_method="100% Certified Organic",
            packaging_date="2026-10-21",
            farmer_id=farmer.id,
            image="default.jpg",
            qr_code="qr_TH-TAMPER-UI.png",
            on_chain_hash=h_hash,
            contract_version="V2",
            status="In Transit",
        )
        db.session.add(prod)
        db.session.flush()
        t_hash = compute_transport_hash(
            batch_id="TH-TAMPER-UI",
            status="In Transit",
            current_location="Test Depot",
            temperature="4.0 °C",
            vehicle_number="TRK-100",
            notes="",
            transporter_id=transporter.id,
        )
        t_row = TransportData(
            product_id=prod.id,
            transporter_id=transporter.id,
            status="In Transit",
            current_location="Test Depot",
            temperature="4.0 °C",
            vehicle_number="TRK-100",
            notes="",
            on_chain_hash=t_hash,
        )
        db.session.add(t_row)
        db.session.flush()
        db.session.add(StageSnapshot(
            product_id=prod.id,
            stage="HARVEST",
            original_hash=h_hash,
            snapshot_json=json.dumps({
                "batch_id": "TH-TAMPER-UI",
                "farmer_id": farmer.id,
                "farming_method": "100% Certified Organic",
                "image": "default.jpg",
                "name": "Organic Kale",
                "packaging_date": "2026-10-21",
                "quantity": "60 kg",
            }, sort_keys=True),
        ))
        db.session.add(StageSnapshot(
            product_id=prod.id,
            stage="TRANSPORT",
            transport_id=t_row.id,
            original_hash=t_hash,
            snapshot_json=json.dumps({
                "batch_id": "TH-TAMPER-UI",
                "current_location": "Test Depot",
                "notes": "",
                "stage": "TRANSPORT",
                "status": "In Transit",
                "temperature": "4.0 °C",
                "transporter_id": transporter.id,
                "vehicle_number": "TRK-100",
            }, sort_keys=True),
        ))
        db.session.commit()

    monkeypatch.setattr("app.inspect_batch_on_chain", lambda *a, **kw: {
        "status": "ok",
        "hash": h_hash,
        "contract_address": "0x1111111111111111111111111111111111111111",
        "contract_version": "V2",
        "registered_by": "0xFarmer",
        "timestamp": datetime.now(timezone.utc),
        "stages": [
            {"index": 0, "stage": "TRANSPORT", "hash": t_hash, "recorded_by": "0xTransporter", "timestamp": datetime.now(timezone.utc)},
        ],
        "truncated": False,
        "expected_signers": None,
        "conflict_details": None,
        "error": None,
    })

    # Hidden behind 404 when DEMO_MODE is off
    assert client.post("/verify/TH-TAMPER-UI/toggle-demo-tamper").status_code == 404
    assert client.post("/verify/TH-TAMPER-UI/toggle-transport-tamper").status_code == 404

    monkeypatch.setenv("DEMO_MODE", "true")

    # Toggle harvest tamper on and restore cleanly using validated StageSnapshot (even from a fresh session)
    r1 = client.post("/verify/TH-TAMPER-UI/toggle-demo-tamper", follow_redirects=True)
    assert r1.status_code == 200
    with app.app_context():
        assert Product.query.filter_by(batch_id="TH-TAMPER-UI").first().farming_method == "Chemically Treated Non-Organic"

    fresh_client = app.test_client()
    r2 = fresh_client.post("/verify/TH-TAMPER-UI/toggle-demo-tamper", follow_redirects=True)
    assert r2.status_code == 200
    with app.app_context():
        assert Product.query.filter_by(batch_id="TH-TAMPER-UI").first().farming_method == "100% Certified Organic"

    # Toggle transport tamper on and restore cleanly using validated StageSnapshot (even without session cookie)
    r3 = client.post("/verify/TH-TAMPER-UI/toggle-transport-tamper", follow_redirects=True)
    assert r3.status_code == 200
    with app.app_context():
        t_rec = TransportData.query.first()
        assert "Tampered" in t_rec.temperature

    r4 = fresh_client.post("/verify/TH-TAMPER-UI/toggle-transport-tamper", follow_redirects=True)
    assert r4.status_code == 200
    with app.app_context():
        t_rec = TransportData.query.first()
        assert t_rec.temperature == "4.0 °C"


def test_ensure_schema_columns_idempotent(app):
    with app.app_context():
        ensure_schema_columns()
        ensure_schema_columns()


def test_customer_qr_scanner_ui_present(client, app, monkeypatch):
    with app.app_context():
        farmer = User.query.filter_by(username="farmer_test").first()
        db.session.add(Product(
            batch_id="TH-SCAN-UI",
            name="Crisp Pears",
            quantity="120 kg",
            farming_method="Organic",
            packaging_date="2026-10-22",
            farmer_id=farmer.id,
            image="default.jpg",
            qr_code="qr_TH-SCAN-UI.png",
            on_chain_hash="a" * 64,
            status="In Stock",
        ))
        db.session.commit()

    res = client.get("/customer")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert 'role="tablist"' in html
    assert 'id="tab-qr-scan"' in html
    assert 'id="btn-start-cam"' in html
    assert 'id="qr-file-input"' in html
    assert 'id="btn-demo-qr-scan"' not in html

    monkeypatch.setenv("DEMO_MODE", "true")
    res_demo = client.get("/customer")
    assert res_demo.status_code == 200
    assert 'id="btn-demo-qr-scan"' in res_demo.data.decode("utf-8")


@pytest.mark.skipif(not _ganache_up(), reason="Ganache node not reachable on configured RPC URL")
def test_live_ganache_v2_multistage_immutability_and_tamper(client, app):
    w3 = get_w3()
    contract = get_or_deploy_contract(w3)
    batch_id = f"TH-LIVE-{uuid.uuid4().hex[:8].upper()}"

    with app.app_context():
        farmer = User.query.filter_by(username="farmer_test").first()
        transporter = User.query.filter_by(username="transporter_test").first()
        retailer = User.query.filter_by(username="retailer_test").first()

        h_hash = compute_batch_hash(
            batch_id=batch_id,
            name="Live V2 Strawberries",
            quantity="150 kg",
            farming_method="100% Certified Organic",
            packaging_date="2026-10-25",
            farmer_id=farmer.id,
            image="default.jpg",
        )
        h_meta = store_hash_detailed(batch_id, h_hash, role="farmer")
        assert h_meta["tx_hash"].startswith("0x")
        assert h_meta["block_number"] >= 1
        assert h_meta["signer_address"].lower() == get_signer_account(w3, "farmer").lower()

        # Re-writing the same batch_id MUST revert with AlreadyRegistered
        with pytest.raises(Exception):
            contract.functions.storeHash(batch_id, h_hash).transact({"from": get_signer_account(w3, "farmer")})

        # Calling addStageHash on an unregistered batch MUST revert with BatchNotFound
        with pytest.raises(Exception):
            contract.functions.addStageHash("TH-NO-SUCH-BATCH", "TRANSPORT", "abc").transact(
                {"from": get_signer_account(w3, "transporter")}
            )

        t_hash = compute_transport_hash(
            batch_id=batch_id,
            status="In Transit (Cold-Storage)",
            current_location="Olympia Reefer Hub",
            temperature="3.5 °C",
            vehicle_number="TRK-V2",
            notes="Cold-chain unbroken",
            transporter_id=transporter.id,
        )
        t_meta = store_stage_hash(batch_id, "TRANSPORT", t_hash, role="transporter")
        assert t_meta["status"] == "anchored"
        assert t_meta["signer_address"].lower() == get_signer_account(w3, "transporter").lower()

        r_hash = compute_retail_hash(
            batch_id=batch_id,
            store_name="Green Valley Co-op",
            store_location="Portland, OR",
            price=5.49,
            stock_quantity="140 kg",
            arrival_date="2026-10-26",
            shelf_life="7 Days",
            retailer_id=retailer.id,
        )
        r_meta = store_stage_hash(batch_id, "RETAIL", r_hash, role="retailer")
        assert r_meta["status"] == "anchored"
        assert r_meta["signer_address"].lower() == get_signer_account(w3, "retailer").lower()

        v2_details = fetch_v2_provenance_details(batch_id)
        assert v2_details["available"] is True
        assert len(v2_details["stages"]) == 2
        assert v2_details["stages"][0]["stage"] == "TRANSPORT"
        assert v2_details["stages"][1]["stage"] == "RETAIL"

        prod = Product(
            batch_id=batch_id,
            name="Live V2 Strawberries",
            quantity="150 kg",
            farming_method="100% Certified Organic",
            packaging_date="2026-10-25",
            farmer_id=farmer.id,
            image="default.jpg",
            qr_code=f"qr_{batch_id}.png",
            on_chain_hash=h_hash,
            tx_hash=h_meta["tx_hash"],
            block_number=h_meta["block_number"],
            contract_address=h_meta["contract_address"],
            signer_address=h_meta["signer_address"],
            status="In Stock",
        )
        db.session.add(prod)
        db.session.flush()
        db.session.add(FarmerData(
            product_id=prod.id,
            farm_name="Evergreen Berry Farm",
            farm_location="Skagit Valley, WA",
            harvest_date="2026-10-25",
            certifications="USDA Organic",
        ))
        t_row = TransportData(
            product_id=prod.id,
            transporter_id=transporter.id,
            status="In Transit (Cold-Storage)",
            current_location="Olympia Reefer Hub",
            temperature="3.5 °C",
            vehicle_number="TRK-V2",
            notes="Cold-chain unbroken",
            on_chain_hash=t_hash,
            tx_hash=t_meta["tx_hash"],
            block_number=t_meta["block_number"],
            signer_address=t_meta["signer_address"],
        )
        db.session.add(t_row)
        r_row = RetailData(
            product_id=prod.id,
            retailer_id=retailer.id,
            store_name="Green Valley Co-op",
            store_location="Portland, OR",
            price=5.49,
            stock_quantity="140 kg",
            arrival_date="2026-10-26",
            shelf_life="7 Days",
            on_chain_hash=r_hash,
            tx_hash=r_meta["tx_hash"],
            block_number=r_meta["block_number"],
            signer_address=r_meta["signer_address"],
        )
        db.session.add(r_row)
        db.session.commit()

    # Clean verified JSON & HTML verification check
    api_clean = client.get(f"/api/verify/{batch_id}").get_json()
    assert api_clean["verification_status"] == "verified"
    assert api_clean["result_label"] == "Verified"
    assert api_clean["trust_score"]["score"] == 100
    assert api_clean["timeline"]["transport"][0]["verification"] == "verified"
    assert api_clean["timeline"]["shop"]["verification"] == "verified"

    # Falsify cold-chain temperature in DB -> Stage 2 tamper detected even though Harvest wasn't touched
    with app.app_context():
        tr = TransportData.query.filter_by(vehicle_number="TRK-V2").first()
        tr.temperature = "26.0 °C (Falsified)"
        db.session.commit()

    api_tampered = client.get(f"/api/verify/{batch_id}").get_json()
    assert api_tampered["verification_status"] == "tampered"
    assert api_tampered["result_label"] == "Changed after recording"
    assert api_tampered["timeline"]["transport"][0]["verification"] == "tampered"

    html_tampered = client.get(f"/verify/{batch_id}").data.decode("utf-8")
    assert "Changed after recording" in html_tampered
    assert "Transport checkpoint #1" in html_tampered

