import json
from datetime import datetime, timedelta, timezone
import uuid

from models import (
    db, User, Product, FarmerData, TransportData, RetailData, StageSnapshot
)
from app import (
    _build_verification_context,
    _register_harvest_batch,
    _record_transport_checkpoint,
    _record_retail_listing,
)
from blockchain import (
    compute_batch_hash,
    compute_transport_hash,
    compute_retail_hash,
)


def _seed_full_batch_with_snapshots(
    app,
    batch_id="TH-PROOF-001",
    temp_values=("3.8 °C", "4.0 °C"),
):
    """Creates a full 3-stage batch with real SHA-256 hashes and immutable StageSnapshots."""
    with app.app_context():
        farmer = User.query.filter_by(username="farmer_test").first()
        transporter = User.query.filter_by(username="transporter_test").first()
        retailer = User.query.filter_by(username="retailer_test").first()

        h_hash = compute_batch_hash(
            batch_id=batch_id,
            name="Organic Fuji Apples",
            quantity="250 kg",
            farming_method="100% Certified Organic",
            packaging_date="2026-10-18",
            farmer_id=farmer.id,
            image="organic_apples.jpg",
        )
        prod = Product(
            batch_id=batch_id,
            name="Organic Fuji Apples",
            quantity="250 kg",
            farming_method="100% Certified Organic",
            packaging_date="2026-10-18",
            farmer_id=farmer.id,
            image="organic_apples.jpg",
            qr_code=f"qr_{batch_id}.png",
            on_chain_hash=h_hash,
            contract_address="0x1111111111111111111111111111111111111111",
            contract_version="V2",
            signer_address="0xfarmer0001",
            status="In Stock",
        )
        db.session.add(prod)
        db.session.flush()

        db.session.add(FarmerData(
            product_id=prod.id,
            farm_name="Evergreen Orchard",
            farm_location="Yakima Valley, WA",
            harvest_date="2026-10-18",
            certifications="USDA Organic",
        ))
        db.session.add(StageSnapshot(
            product_id=prod.id,
            stage="HARVEST",
            original_hash=h_hash,
            snapshot_json=json.dumps({
                "batch_id": batch_id,
                "farmer_id": farmer.id,
                "farming_method": "100% Certified Organic",
                "image": "organic_apples.jpg",
                "name": "Organic Fuji Apples",
                "packaging_date": "2026-10-18",
                "quantity": "250 kg",
            }, sort_keys=True),
        ))

        base_ts = datetime(2026, 10, 19, 9, 0, tzinfo=timezone.utc)
        t_stages = []
        for idx, temp in enumerate(temp_values):
            st = "Picked Up" if idx == 0 else "In Transit"
            loc = f"Hub #{idx + 1}"
            veh = "TRK-404"
            notes = f"Checkpoint {idx + 1}"
            th = compute_transport_hash(batch_id, st, loc, temp, veh, notes, transporter.id)
            ts = base_ts + timedelta(hours=idx * 4)
            tr = TransportData(
                product_id=prod.id,
                transporter_id=transporter.id,
                status=st,
                current_location=loc,
                temperature=temp,
                vehicle_number=veh,
                notes=notes,
                on_chain_hash=th,
                signer_address="0xtrans0001",
                timestamp=ts,
            )
            db.session.add(tr)
            db.session.flush()
            db.session.add(StageSnapshot(
                product_id=prod.id,
                stage="TRANSPORT",
                transport_id=tr.id,
                original_hash=th,
                snapshot_json=json.dumps({
                    "batch_id": batch_id,
                    "current_location": loc,
                    "notes": notes,
                    "stage": "TRANSPORT",
                    "status": st,
                    "temperature": temp,
                    "transporter_id": transporter.id,
                    "vehicle_number": veh,
                }, sort_keys=True),
            ))
            t_stages.append({
                "index": idx,
                "stage": "TRANSPORT",
                "hash": th,
                "recorded_by": "0xtrans0001",
                "timestamp": ts,
            })

        rh = compute_retail_hash(
            batch_id,
            "Green Valley Market",
            "Seattle, WA",
            4.99,
            "200 kg",
            "2026-10-20",
            "14 Days",
            retailer.id,
        )
        rr = RetailData(
            product_id=prod.id,
            retailer_id=retailer.id,
            store_name="Green Valley Market",
            store_location="Seattle, WA",
            price=4.99,
            stock_quantity="200 kg",
            arrival_date="2026-10-20",
            shelf_life="14 Days",
            on_chain_hash=rh,
            signer_address="0xretail0001",
        )
        db.session.add(rr)
        db.session.add(StageSnapshot(
            product_id=prod.id,
            stage="RETAIL",
            original_hash=rh,
            snapshot_json=json.dumps({
                "arrival_date": "2026-10-20",
                "batch_id": batch_id,
                "price": "4.99",
                "retailer_id": retailer.id,
                "shelf_life": "14 Days",
                "stage": "RETAIL",
                "stock_quantity": "200 kg",
                "store_location": "Seattle, WA",
                "store_name": "Green Valley Market",
            }, sort_keys=True),
        ))
        db.session.commit()

        chain_payload = {
            "status": "ok",
            "hash": h_hash,
            "contract_address": prod.contract_address,
            "contract_version": "V2",
            "registered_by": "0xfarmer0001",
            "timestamp": base_ts - timedelta(days=1),
            "stages": t_stages + [{
                "index": len(t_stages),
                "stage": "RETAIL",
                "hash": rh,
                "recorded_by": "0xretail0001",
                "timestamp": base_ts + timedelta(days=1),
            }],
            "truncated": False,
            "expected_signers": None,
            "conflict_details": None,
            "error": None,
        }
        return prod.id, h_hash, chain_payload


def test_workflow_handlers_create_validated_snapshots_on_anchor(app, monkeypatch):
    monkeypatch.setattr("app.fetch_on_chain_status", lambda batch_id: {"status": "not_found"})
    monkeypatch.setattr("app.store_hash_detailed", lambda batch_id, h, role="farmer": {
        "tx_hash": "0x" + "11" * 32,
        "block_number": 10,
        "contract_address": "0x2222222222222222222222222222222222222222",
        "contract_version": "V2",
        "signer_address": "0xFarmerAddr",
    })
    monkeypatch.setattr("app.store_stage_hash", lambda batch_id, stage, h, role="transporter", contract_address=None: {
        "status": "anchored",
        "tx_hash": "0x" + "22" * 32,
        "block_number": 11,
        "signer_address": f"0x{role.capitalize()}Addr",
    })

    with app.app_context():
        farmer = User.query.filter_by(username="farmer_test").first()
        transporter = User.query.filter_by(username="transporter_test").first()
        retailer = User.query.filter_by(username="retailer_test").first()

        prod, err = _register_harvest_batch(farmer, {
            "name": "Anchored Peaches",
            "quantity": "100 kg",
            "farming_method": "100% Certified Organic",
            "packaging_date": "2026-10-25",
            "farm_location": "Oregon Farm",
            "certifications": "Organic",
        }, None)
        assert err is None

        tr, t_res, t_err = _record_transport_checkpoint(transporter, prod, {
            "status": "In Transit",
            "current_location": "Portland Hub",
            "temperature": "4.0 °C",
            "vehicle_number": "TRK-777",
            "notes": "Cold hold active",
        })
        assert t_err is None
        assert t_res["status"] == "anchored"

        rt, r_res, r_err = _record_retail_listing(retailer, prod, {
            "store_name": "Fresh Store",
            "store_location": "Portland, OR",
            "price": "5.50",
            "stock_quantity": "95 kg",
            "arrival_date": "2026-10-26",
            "shelf_life": "10 Days",
        })
        assert r_err is None
        assert r_res["status"] == "anchored"

        snaps = StageSnapshot.query.filter_by(product_id=prod.id).all()
        assert {s.stage for s in snaps} == {"HARVEST", "TRANSPORT", "RETAIL"}
        h_snap = StageSnapshot.query.filter_by(product_id=prod.id, stage="HARVEST").first()
        t_snap = StageSnapshot.query.filter_by(product_id=prod.id, stage="TRANSPORT", transport_id=tr.id).first()
        r_snap = StageSnapshot.query.filter_by(product_id=prod.id, stage="RETAIL").first()
        assert h_snap.original_hash == prod.on_chain_hash
        assert json.loads(t_snap.snapshot_json)["temperature"] == "4.0 °C"
        assert json.loads(r_snap.snapshot_json)["price"] == "5.50"


def test_independent_stage_verification_all_verified_and_isolated_transport_tamper(app, monkeypatch):
    prod_id, h_hash, chain_payload = _seed_full_batch_with_snapshots(
        app, batch_id="TH-PROOF-ISO-01", temp_values=("4.0 °C",)
    )
    monkeypatch.setattr("app.inspect_batch_on_chain", lambda *a, **kw: chain_payload)
    monkeypatch.setenv("DEMO_MODE", "true")

    # 1. Clean state: all 3 stages verified, zero diffs
    with app.app_context():
        prod = db.session.get(Product, prod_id)
        ctx = _build_verification_context(prod)
        assert ctx["verification_status"] == "verified"
        assert ctx["harvest_verification"]["status"] == "verified"
        assert ctx["harvest_verification"]["changed_fields"] == []
        assert ctx["transport_verifications"][0]["stage_status"] == "verified"
        assert ctx["transport_verifications"][0]["changed_fields"] == []
        assert ctx["retail_verification"]["stage_status"] == "verified"
        assert ctx["retail_verification"]["changed_fields"] == []

    # 2. Tamper transport via DEMO route from Client A
    client_a = app.test_client()
    res = client_a.post("/verify/TH-PROOF-ISO-01/toggle-transport-tamper", follow_redirects=True)
    assert res.status_code == 200

    # 3. Inspect from completely separate browser Client B (no session cookies)
    client_b = app.test_client()
    with app.app_context():
        prod = db.session.get(Product, prod_id)
        # Snapshot row itself remains untouched with original 4.0 °C
        t_snap = StageSnapshot.query.filter_by(product_id=prod.id, stage="TRANSPORT").first()
        assert json.loads(t_snap.snapshot_json)["temperature"] == "4.0 °C"

        ctx_tampered = _build_verification_context(prod)
        assert ctx_tampered["verification_status"] == "tampered"
        # Farmer & Retailer stay independently VERIFIED
        assert ctx_tampered["harvest_verification"]["status"] == "verified"
        assert ctx_tampered["retail_verification"]["stage_status"] == "verified"
        # Transporter shows TAMPERED with exact hashes and diff
        tv = ctx_tampered["transport_verifications"][0]
        assert tv["stage_status"] == "tampered"
        assert tv["original_hash"] != tv["recomputed_hash"]
        assert tv["snapshot_available"] is True
        assert tv["snapshot_valid"] is True
        assert len(tv["changed_fields"]) == 1
        diff = tv["changed_fields"][0]
        assert diff["field"] == "temperature"
        assert diff["label"] == "Temperature"
        assert diff["original"] == "4.0 °C"
        assert diff["modified"] == "24.5 °C (Tampered)"
        assert diff["clean_modified"] == "24.5 °C"

    # 4. Restore from Client B (no session cookie at all!) -> restores exact 4.0 °C
    res_restore = client_b.post("/verify/TH-PROOF-ISO-01/toggle-transport-tamper", follow_redirects=True)
    assert res_restore.status_code == 200
    with app.app_context():
        t_row = TransportData.query.filter_by(product_id=prod_id).first()
        assert t_row.temperature == "4.0 °C"
        ctx_restored = _build_verification_context(db.session.get(Product, prod_id))
        assert ctx_restored["verification_status"] == "verified"


def test_tampered_snapshot_rejected_and_refuses_to_restore(app, monkeypatch):
    prod_id, _, chain_payload = _seed_full_batch_with_snapshots(
        app, batch_id="TH-BAD-SNAP-01", temp_values=("4.0 °C",)
    )
    monkeypatch.setattr("app.inspect_batch_on_chain", lambda *a, **kw: chain_payload)
    monkeypatch.setenv("DEMO_MODE", "true")

    with app.app_context():
        tr = TransportData.query.filter_by(product_id=prod_id).first()
        tr.temperature = "24.5 °C (Tampered)"
        snap = StageSnapshot.query.filter_by(product_id=prod_id, stage="TRANSPORT").first()
        fake_payload = json.loads(snap.snapshot_json)
        fake_payload["temperature"] = "1.0 °C (Corrupted Snapshot)"
        snap.snapshot_json = json.dumps(fake_payload, sort_keys=True)
        db.session.commit()

        ctx = _build_verification_context(db.session.get(Product, prod_id))
        tv = ctx["transport_verifications"][0]
        assert tv["stage_status"] == "tampered"
        assert tv["snapshot_available"] is True
        assert tv["snapshot_valid"] is False
        assert tv["changed_fields"] == []
        assert "did not match the blockchain hash" in tv["snapshot_note"]

    # Attempt restore must refuse and keep DB value unchanged rather than restoring unvalidated snapshot
    client = app.test_client()
    client.post("/verify/TH-BAD-SNAP-01/toggle-transport-tamper", follow_redirects=True)
    with app.app_context():
        assert TransportData.query.filter_by(product_id=prod_id).first().temperature == "24.5 °C (Tampered)"


def test_multi_field_diff_and_multiple_checkpoints_individual_mapping(app, monkeypatch):
    prod_id, _, chain_payload = _seed_full_batch_with_snapshots(
        app, batch_id="TH-MULTI-DIFF-01", temp_values=("3.5 °C", "4.0 °C")
    )
    monkeypatch.setattr("app.inspect_batch_on_chain", lambda *a, **kw: chain_payload)

    with app.app_context():
        transports = TransportData.query.filter_by(product_id=prod_id).order_by(TransportData.id.asc()).all()
        # Tamper multiple fields on checkpoint #2 only; keep checkpoint #1 authentic
        transports[1].temperature = "19.8 °C"
        transports[1].vehicle_number = "TRK-FAKE"
        transports[1].notes = "Edited notes"
        db.session.commit()

        ctx = _build_verification_context(db.session.get(Product, prod_id))
        assert ctx["harvest_verification"]["status"] == "verified"
        assert ctx["retail_verification"]["stage_status"] == "verified"
        assert ctx["transport_verifications"][0]["stage_status"] == "verified"
        assert ctx["transport_verifications"][0]["changed_fields"] == []

        cp2 = ctx["transport_verifications"][1]
        assert cp2["stage_status"] == "tampered"
        changed_by_field = {d["field"]: d for d in cp2["changed_fields"]}
        assert set(changed_by_field.keys()) == {"temperature", "vehicle_number", "notes"}
        assert changed_by_field["temperature"]["original"] == "4.0 °C"
        assert changed_by_field["temperature"]["modified"] == "19.8 °C"
        assert changed_by_field["vehicle_number"]["original"] == "TRK-404"
        assert changed_by_field["vehicle_number"]["modified"] == "TRK-FAKE"
        assert changed_by_field["notes"]["modified"] == "Edited notes"


def test_missing_historical_snapshot_shows_honest_limitation_and_refuses_guess(app, monkeypatch):
    prod_id, _, chain_payload = _seed_full_batch_with_snapshots(
        app, batch_id="TH-NO-SNAP-01", temp_values=("5.2 °C",)
    )
    monkeypatch.setattr("app.inspect_batch_on_chain", lambda *a, **kw: chain_payload)
    monkeypatch.setenv("DEMO_MODE", "true")

    with app.app_context():
        # Delete snapshots to simulate pre-upgrade historical DB batch
        StageSnapshot.query.filter_by(product_id=prod_id).delete()
        tr = TransportData.query.filter_by(product_id=prod_id).first()
        tr.temperature = "24.5 °C (Tampered)"
        db.session.commit()

        ctx = _build_verification_context(db.session.get(Product, prod_id))
        tv = ctx["transport_verifications"][0]
        assert tv["stage_status"] == "tampered"
        assert tv["original_hash"] != tv["recomputed_hash"]
        assert tv["snapshot_available"] is False
        assert tv["snapshot_valid"] is False
        assert tv["changed_fields"] == []
        assert "not available" in tv["snapshot_note"].lower()

    # Restoring without snapshot must NOT guess '3.8 °C'
    client = app.test_client()
    res = client.post("/verify/TH-NO-SNAP-01/toggle-transport-tamper", follow_redirects=True)
    assert res.status_code == 200
    assert b"3.8" not in res.data
    with app.app_context():
        assert TransportData.query.filter_by(product_id=prod_id).first().temperature == "24.5 °C (Tampered)"


def test_offline_and_missing_blockchain_never_claim_tampered_and_qr_works(client, app, monkeypatch):
    prod_id, _, _ = _seed_full_batch_with_snapshots(app, batch_id="TH-OFF-QR-01")

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
    with app.app_context():
        ctx = _build_verification_context(db.session.get(Product, prod_id))
        assert ctx["verification_status"] == "cannot_verify"
        assert ctx["harvest_verification"]["status"] == "cannot_verify"
        assert ctx["transport_verifications"][0]["stage_status"] == "cannot_verify"
        assert ctx["retail_verification"]["stage_status"] == "cannot_verify"

    qr_resp = client.get("/qr/TH-OFF-QR-01.png")
    assert qr_resp.status_code == 200
    assert qr_resp.data[:8] == b"\x89PNG\r\n\x1a\n"


def test_phase2_ui_stage_proof_timeline_pending_and_tamper_diff_rendering(app, monkeypatch):
    import pytest
    from blockchain import get_w3

    # 1. Batch with ONLY Harvest recorded (Transport & Retail Pending)
    with app.app_context():
        farmer = User.query.filter_by(username="farmer_test").first()
        h_only = compute_batch_hash(
            batch_id="TH-UI-PEND-01",
            name="Fresh Peaches",
            quantity="90 kg",
            farming_method="100% Certified Organic",
            packaging_date="2026-10-25",
            farmer_id=farmer.id,
            image="default.jpg",
        )
        p_pend = Product(
            batch_id="TH-UI-PEND-01",
            name="Fresh Peaches",
            quantity="90 kg",
            farming_method="100% Certified Organic",
            packaging_date="2026-10-25",
            farmer_id=farmer.id,
            image="default.jpg",
            qr_code="qr_TH-UI-PEND-01.png",
            on_chain_hash=h_only,
            contract_version="V2",
            status="Harvested",
        )
        db.session.add(p_pend)
        db.session.commit()

    monkeypatch.setattr("app.inspect_batch_on_chain", lambda *a, **kw: {
        "status": "ok",
        "hash": h_only,
        "contract_address": "0x1111111111111111111111111111111111111111",
        "contract_version": "V2",
        "registered_by": "0xfarmer0001",
        "timestamp": datetime.now(timezone.utc),
        "stages": [],
        "truncated": False,
        "expected_signers": None,
        "conflict_details": None,
        "error": None,
    })

    c_pend = app.test_client().get("/verify/TH-UI-PEND-01").data.decode("utf-8")
    # Collapsed by default
    assert '<details class="th-disclosure' in c_pend
    assert '<details open' not in c_pend
    assert "Technical Blockchain Proof" in c_pend
    assert "Technical details" not in c_pend
    assert c_pend.count("Stage-Wise Cryptographic Verification") == 1
    assert "Farmer: Verified | Transporter: Pending | Retailer: Pending" in c_pend
    assert "STAGE 1 &mdash; FARMER / HARVEST" in c_pend
    assert "STAGE 2 &mdash; TRANSPORTER" in c_pend
    assert "STAGE 3 &mdash; RETAILER" in c_pend
    assert h_only in c_pend

    # 2. Full batch -> Tamper Transport (4.0 °C -> 24.5 °C) -> Cross-browser HTML inspection & restore
    prod_id, h_full, chain_full = _seed_full_batch_with_snapshots(
        app, batch_id="TH-UI-TAMPER-01", temp_values=("4.0 °C",)
    )
    monkeypatch.setattr("app.inspect_batch_on_chain", lambda *a, **kw: chain_full)
    monkeypatch.setenv("DEMO_MODE", "true")

    c1 = app.test_client()
    c1.post("/verify/TH-UI-TAMPER-01/toggle-transport-tamper", follow_redirects=True)

    # Fresh unauthenticated browser session (no session cookies)
    c2 = app.test_client()
    html = c2.get("/verify/TH-UI-TAMPER-01").data.decode("utf-8")
    assert "Changed after recording" in html
    assert "Where &amp; When Record Changed" in html
    assert "Where:" in html
    assert "Hub #1 (Vehicle TRK-404)" in html
    assert "When Recorded (On-Chain / Checkpoint):" in html
    assert "UTC" in html
    assert "timeline-icon tampered" in html
    assert "Tampered at Checkpoint #1 (Hub #1" in html
    assert "OVERALL RESULT: TAMPERING DETECTED" in html
    assert "Farmer: Verified | Transporter: Tampered (Checkpoint #1) | Retailer: Verified" in html
    assert "HASH VERIFIED" in html
    assert "HASH MISMATCH" in html
    assert "ORIGINAL HASH &ne; RECOMPUTED HASH" in html
    assert "WHAT CHANGED?" in html
    assert "Temperature" in html
    assert "4.0 °C" in html
    assert "24.5 °C" in html
    assert 'command="--copy"' in html
    assert h_full in html
    assert chain_full["stages"][0]["hash"] in html

    # Clean verified batch must NOT render the tamper incident panel
    c2.post("/verify/TH-UI-TAMPER-01/toggle-transport-tamper", follow_redirects=True)
    html_clean = c2.get("/verify/TH-UI-TAMPER-01").data.decode("utf-8")
    assert "Where &amp; When Record Changed" not in html_clean
    assert "timeline-icon tampered" not in html_clean
    c2.post("/verify/TH-UI-TAMPER-01/toggle-transport-tamper", follow_redirects=True)

    # Missing snapshot still shows hash mismatch & honest note instead of invented fields
    with app.app_context():
        StageSnapshot.query.filter_by(product_id=prod_id, stage="TRANSPORT").delete()
        db.session.commit()
    html_no_snap = c2.get("/verify/TH-UI-TAMPER-01").data.decode("utf-8")
    assert "ORIGINAL HASH &ne; RECOMPUTED HASH" in html_no_snap
    assert "Original field values snapshot is not available for this historical record." in html_no_snap


def test_mandatory_live_ganache_acceptance_demonstration(app, monkeypatch):
    """
    End-to-end live Ganache acceptance test:
    Harvest -> Transport (4.0 °C) -> Retail -> Trigger Transport Tamper (24.5 °C (Tampered))
    -> Unauthenticated fresh browser GET /verify/<batch_id> -> Verify stage-wise proof & diff -> Restore.
    """
    from blockchain import get_w3

    try:
        w3 = get_w3(die_on_error=False)
        if not (w3 and w3.is_connected()):
            import pytest
            pytest.skip("Ganache node not reachable")
    except Exception:
        import pytest
        pytest.skip("Ganache node not reachable")

    monkeypatch.setenv("DEMO_MODE", "true")

    with app.app_context():
        farmer = User.query.filter_by(username="farmer_test").first()
        transporter = User.query.filter_by(username="transporter_test").first()
        retailer = User.query.filter_by(username="retailer_test").first()

        prod, err = _register_harvest_batch(farmer, {
            "name": "Acceptance Cryo Berries",
            "quantity": "120 kg",
            "farming_method": "100% Certified Organic",
            "packaging_date": "2026-11-12",
            "farm_location": "Yakima Valley, WA",
            "certifications": "USDA Organic",
        }, None)
        assert err is None
        batch_id = prod.batch_id

        tr, t_res, t_err = _record_transport_checkpoint(transporter, prod, {
            "status": "In Transit (Cold-Storage)",
            "current_location": "Portland Cold Dock",
            "temperature": "4.0 °C",
            "vehicle_number": "TRK-500",
            "notes": "Reefer unit steady at 4.0 C",
        })
        assert t_err is None
        assert t_res["status"] == "anchored"

        # Confirm Transport StageSnapshot stored '4.0 °C' matching blockchain hash
        t_snap = StageSnapshot.query.filter_by(product_id=prod.id, stage="TRANSPORT", transport_id=tr.id).first()
        assert t_snap is not None
        assert json.loads(t_snap.snapshot_json)["temperature"] == "4.0 °C"
        assert t_snap.original_hash == tr.on_chain_hash

        rt, r_res, r_err = _record_retail_listing(retailer, prod, {
            "store_name": "Evergreen Fresh Market",
            "store_location": "Seattle, WA",
            "price": "6.50",
            "stock_quantity": "115 kg",
            "arrival_date": "2026-11-12",
            "shelf_life": "10 Days",
        })
        assert r_err is None
        assert r_res["status"] == "anchored"

    # Trigger transport tamper from Client A
    client_a = app.test_client()
    r_tamp = client_a.post(f"/verify/{batch_id}/toggle-transport-tamper", follow_redirects=True)
    assert r_tamp.status_code == 200

    # Open from fresh unauthenticated browser Client B
    client_b = app.test_client()
    res = client_b.get(f"/verify/{batch_id}")
    assert res.status_code == 200
    html = res.data.decode("utf-8")

    assert "Technical Blockchain Proof" in html
    assert '<details class="th-disclosure' in html
    assert '<details open' not in html
    assert "Where &amp; When Record Changed" in html
    assert "Portland Cold Dock (Vehicle TRK-500)" in html
    assert "UTC" in html
    assert "timeline-icon tampered" in html
    assert "Tampered at Checkpoint #1 (Portland Cold Dock" in html
    assert "OVERALL RESULT: TAMPERING DETECTED" in html
    assert "Farmer: Verified | Transporter: Tampered (Checkpoint #1) | Retailer: Verified" in html
    assert "ORIGINAL HASH &ne; RECOMPUTED HASH" in html
    assert "WHAT CHANGED?" in html
    assert "4.0 °C" in html
    assert "24.5 °C" in html

    # Snapshot remained immutable throughout
    with app.app_context():
        p_db = Product.query.filter_by(batch_id=batch_id).first()
        t_db = TransportData.query.filter_by(product_id=p_db.id).first()
        assert t_db.temperature == "24.5 °C (Tampered)"
        snap_db = StageSnapshot.query.filter_by(product_id=p_db.id, stage="TRANSPORT").first()
        assert json.loads(snap_db.snapshot_json)["temperature"] == "4.0 °C"

    # Restore cleanly from unauthenticated Client B -> back to Verified & 4.0 °C
    r_rest = client_b.post(f"/verify/{batch_id}/toggle-transport-tamper", follow_redirects=True)
    assert r_rest.status_code == 200
    html_ok = r_rest.data.decode("utf-8")
    assert "OVERALL RESULT: ALL RECORDED STAGES VERIFIED" in html_ok
    assert "Where Grown" in html_ok
    assert "Freshness &amp; Cold Chain" in html_ok
    assert "1. Farm Origin" in html_ok
    assert "2. Cold Storage" in html_ok
    assert "3. Store Shelf" in html_ok
    with app.app_context():
        p_db = Product.query.filter_by(batch_id=batch_id).first()
        assert TransportData.query.filter_by(product_id=p_db.id).first().temperature == "4.0 °C"


