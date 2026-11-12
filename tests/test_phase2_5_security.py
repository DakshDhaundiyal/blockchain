import os
from unittest.mock import MagicMock
from eth_account import Account

import blockchain as bc
import seed as seed_mod
from models import db, User, Product
from utils import resolve_qr_base_url, generate_batch_qr_bytes, sanitize_error_text


def test_dynamic_qr_png_and_never_localhost(client, app, monkeypatch):
    with app.app_context():
        farmer = User.query.filter_by(username="farmer_test").first()
        db.session.add(Product(
            batch_id="TH-QR-DYN-01",
            name="Dynamic QR Apples",
            quantity="50 kg",
            farming_method="Organic",
            packaging_date="2026-10-20",
            farmer_id=farmer.id,
            image="default.jpg",
            qr_code="qr_TH-QR-DYN-01.png",
            on_chain_hash="1" * 64,
            status="Harvested",
        ))
        db.session.commit()

    monkeypatch.setenv("BASE_URL", "http://localhost:5000")
    assert resolve_qr_base_url("http://127.0.0.1:5000/") == ""

    monkeypatch.setenv("BASE_URL", "https://trustharvest.onrender.com/")
    assert resolve_qr_base_url("http://127.0.0.1:5000/") == "https://trustharvest.onrender.com"

    buf = generate_batch_qr_bytes("TH-QR-DYN-01", "https://trustharvest.onrender.com")
    raw_png = buf.getvalue()
    assert raw_png[:8] == b"\x89PNG\r\n\x1a\n"

    resp = client.get("/qr/TH-QR-DYN-01.png")
    assert resp.status_code == 200
    assert resp.mimetype == "image/png"
    assert resp.data[:8] == b"\x89PNG\r\n\x1a\n"


def test_public_verify_hides_wallets_contracts_and_tx_hashes(client, app, monkeypatch):
    monkeypatch.delenv("DEMO_MODE", raising=False)
    fake_tx = "0x" + "ab" * 32
    fake_contract = "0x9999999999999999999999999999999999999999"
    fake_signer = "0x8888888888888888888888888888888888888888"

    with app.app_context():
        farmer = User.query.filter_by(username="farmer_test").first()
        prod = Product(
            batch_id="TH-PRIV-001",
            name="Privacy Kale",
            quantity="30 kg",
            farming_method="Organic",
            packaging_date="2026-10-20",
            farmer_id=farmer.id,
            image="default.jpg",
            qr_code="qr_TH-PRIV-001.png",
            on_chain_hash="c" * 64,
            tx_hash=fake_tx,
            block_number=987654,
            contract_address=fake_contract,
            contract_version="V2",
            signer_address=fake_signer,
            status="Harvested",
        )
        db.session.add(prod)
        db.session.commit()

    monkeypatch.setattr(
        "app.inspect_batch_on_chain",
        lambda batch_id, **kw: {
            "status": "ok",
            "hash": "c" * 64,
            "contract_address": fake_contract,
            "contract_version": "V2",
            "registered_by": fake_signer,
            "timestamp": None,
            "stages": [],
            "truncated": False,
            "expected_signers": None,
            "conflict_details": None,
            "error": None,
        },
    )

    resp = client.get("/verify/TH-PRIV-001")
    assert resp.status_code == 200
    html = resp.data.decode("utf-8")
    assert fake_tx not in html
    assert fake_contract not in html
    assert fake_signer not in html
    assert "987654" not in html
    assert "Technical Blockchain Proof" in html
    assert "TH-PRIV-001" in html


def test_admin_blockchain_explorer_gated_by_admin_and_demo_mode(client, app, monkeypatch):
    # Non-admin customer redirected away from /admin
    with client.session_transaction() as sess:
        sess["user_id"] = 4
        sess["username"] = "customer_test"
        sess["role"] = "customer"
    assert client.get("/admin", follow_redirects=False).status_code == 302

    # Admin with DEMO_MODE off does not see Demo Blockchain Explorer
    with app.app_context():
        admin_u = User.query.filter_by(role="admin").first()
        admin_id = admin_u.id
    with client.session_transaction() as sess:
        sess["user_id"] = admin_id
        sess["username"] = "admin_test"
        sess["role"] = "admin"

    monkeypatch.setenv("DEMO_MODE", "false")
    res_off = client.get("/admin")
    assert res_off.status_code == 200
    assert b"Demo Blockchain Explorer" not in res_off.data

    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setattr(
        "app.get_admin_blockchain_overview",
        lambda prods: {
            "online": False,
            "chain_id": None,
            "block_number": None,
            "contract_address": "0x1234",
            "contract_version": "V2",
            "wallets": [],
            "events": [],
            "audit_map": {},
        },
    )
    res_on = client.get("/admin")
    assert res_on.status_code == 200
    assert b"Demo Blockchain Explorer" in res_on.data


def test_sanitize_error_text_masks_secrets(monkeypatch):
    monkeypatch.setenv("FARMER_PRIVATE_KEY", "0x" + ("ef" * 32))
    leaked_rpc = (
        "Connection failed at https://eth-sepolia.g.alchemy.com/v2/mySecretAlchemyApiKey123456 "
        "with key 0x" + ("de" * 32) + " and farmer signer 0x" + ("ef" * 32)
    )
    cleaned = sanitize_error_text(leaked_rpc)
    assert "mySecretAlchemyApiKey123456" not in cleaned
    assert ("de" * 32) not in cleaned
    assert ("ef" * 32) not in cleaned
    assert "***REDACTED***" in cleaned


def test_seed_without_demo_creates_zero_demo_users(app, monkeypatch):
    import pytest
    monkeypatch.setenv("DEMO_MODE", "false")
    with app.app_context():
        before_count = User.query.count()
        with pytest.raises(SystemExit) as excinfo:
            seed_mod.main([])
        assert excinfo.value.code == 1
        assert User.query.count() == before_count
        assert User.query.filter_by(username="farmer_john").first() is None


def test_private_key_transaction_signing_path(monkeypatch):
    # Throwaway ephemeral test key (never holds real funds)
    acct = Account.create("test-entropy-for-unit-test-only")
    monkeypatch.setenv("FARMER_PRIVATE_KEY", acct.key.hex())
    monkeypatch.setenv("CHAIN_ID", "11155111")

    fake_w3 = MagicMock()
    fake_w3.eth.get_transaction_count.return_value = 7
    fake_w3.eth.gas_price = 1_000_000_000
    fake_w3.eth.account.sign_transaction = lambda built, private_key: Account.sign_transaction(built, private_key)
    fake_w3.eth.send_raw_transaction.return_value = b"\xaa" * 32

    fake_fn = MagicMock()
    fake_fn.estimate_gas.return_value = 100000
    fake_fn.build_transaction.side_effect = lambda params: {
        **params,
        "to": acct.address,
        "value": 0,
        "data": b"",
    }

    tx_hash, signer = bc._send_tx_with_signer(fake_w3, fake_fn, role="farmer")
    assert tx_hash == b"\xaa" * 32
    assert signer.lower() == acct.address.lower()
    fake_w3.eth.send_raw_transaction.assert_called_once()

