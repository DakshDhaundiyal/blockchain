import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.environ['DATABASE_URL'] = f"sqlite:///{os.path.join(BASE_DIR, 'test_smoke.db')}"

from datetime import datetime
from app import app, db
from models import User, Product, TransportData, RetailData
from blockchain import get_w3, get_hash, compute_batch_hash

def run_smoke_test():
    print("=" * 60)
    print("TrustHarvest Comprehensive End-to-End Smoke Test")
    print("=" * 60)

    # Force isolated test database so production/development database is never touched
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('TEST_DATABASE_URI', 'sqlite:///test_smoke.db')
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False

    # 1. Ganache Connectivity
    print("\n[Step 1] Verifying connection to Ganache (http://127.0.0.1:7545)...")
    w3 = get_w3()
    print(f" Connected to Ganache! Block Number: {w3.eth.block_number}")
    print(f" Active Ganache accounts: {len(w3.eth.accounts)}")

    client = app.test_client()

    with app.app_context():
        # Clean setup for smoke test
        print("\n[Step 2] Initializing isolated test database & stakeholders...")
        db.drop_all()
        db.create_all()

        farmer = User(username='test_farmer', role='farmer', full_name='Test Farmer Bob', contact='555-001')
        farmer.set_password('farmpass')

        transporter = User(username='test_transporter', role='transporter', full_name='Speedy Transit', contact='555-002')
        transporter.set_password('transitpass')

        retailer = User(username='test_retailer', role='retailer', full_name='Organic Mart', contact='555-003')
        retailer.set_password('retailpass')

        customer = User(username='test_customer', role='customer', full_name='Alice Buyer', contact='555-004')
        customer.set_password('custpass')

        db.session.add_all([farmer, transporter, retailer, customer])
        db.session.commit()
        farmer_id = farmer.id
        transporter_id = transporter.id
        retailer_id = retailer.id

    # 3. Farmer creates a Product
    print("\n[Step 3] Farmer registers produce batch, generates QR and stores hash on-chain...")
    with client.session_transaction() as sess:
        sess['user_id'] = farmer_id
        sess['username'] = 'test_farmer'
        sess['role'] = 'farmer'

    prod_payload = {
        'name': 'Smoke Test Organic Avocados',
        'quantity': '200 kg',
        'farming_method': '100% Certified Organic',
        'packaging_date': '2026-10-06',
        'farm_location': 'San Diego, CA',
        'certifications': 'USDA Organic'
    }

    resp = client.post('/farmer/add_product', data=prod_payload, follow_redirects=True)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"

    with app.app_context():
        product = Product.query.filter_by(name='Smoke Test Organic Avocados').first()
        assert product is not None, "Product was not found in DB!"
        batch_id = product.batch_id
        print(f" Created Product: {product.name} (Batch ID: {batch_id})")

        # Check dynamic in-memory QR Code endpoint returns PNG
        qr_resp = client.get(f'/qr/{batch_id}.png')
        assert qr_resp.status_code == 200, f"QR endpoint failed: {qr_resp.status_code}"
        assert qr_resp.mimetype == 'image/png'
        assert qr_resp.data[:8] == b'\x89PNG\r\n\x1a\n'
        print(f" Dynamic in-memory QR PNG verified at /qr/{batch_id}.png")

        # Check On-Chain Hash
        expected_hash = compute_batch_hash(
            batch_id=batch_id,
            name=product.name,
            quantity=product.quantity,
            farming_method=product.farming_method,
            packaging_date=product.packaging_date,
            farmer_id=farmer_id,
            image=product.image
        )
        on_chain_hash = get_hash(batch_id)
        print(f" Expected SHA-256 Hash: {expected_hash}")
        print(f" On-Chain Retrieved Hash: {on_chain_hash}")
        assert on_chain_hash.lower() == expected_hash.lower(), "On-chain hash does not match computed hash!"
        product_id = product.id

    # 4. Transporter logs transit update
    print("\n[Step 4] Transporter records checkpoint and updates shipment status...")
    with client.session_transaction() as sess:
        sess['user_id'] = transporter_id
        sess['username'] = 'test_transporter'
        sess['role'] = 'transporter'

    transit_payload = {
        'product_id': product_id,
        'status': 'In Transit (Cold-Storage)',
        'current_location': 'Interstate 5 Highway Hub, CA',
        'temperature': '4.2 °C',
        'vehicle_number': 'TRK-990',
        'notes': 'Optimal temperature maintain continuous chill chain.'
    }
    resp = client.post('/transporter/add', data=transit_payload, follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        t_record = TransportData.query.filter_by(product_id=product_id).first()
        assert t_record is not None, "Transport checkpoint was not recorded!"
        assert t_record.status == 'In Transit (Cold-Storage)'
        assert t_record.tx_hash is not None, "Transport stage should anchor tx_hash on TrustHarvestV2!"
        p_check = db.session.get(Product, product_id)
        assert p_check.status == 'In Transit (Cold-Storage)'
        print(f" Transport checkpoint verified: {t_record.status} at {t_record.current_location} (Block #{t_record.block_number})")

    # 5. Retailer updates stock & price
    print("\n[Step 5] Retailer logs stock arrival and sets pricing...")
    with client.session_transaction() as sess:
        sess['user_id'] = retailer_id
        sess['username'] = 'test_retailer'
        sess['role'] = 'retailer'

    retail_payload = {
        'product_id': product_id,
        'store_name': 'Downtown Fresh Grocers',
        'store_location': '123 Market St, San Francisco, CA',
        'price': '3.49',
        'stock_quantity': '180 kg',
        'arrival_date': '2026-10-06',
        'shelf_life': '10 Days'
    }
    resp = client.post('/retailer/add', data=retail_payload, follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        r_record = RetailData.query.filter_by(product_id=product_id).first()
        assert r_record is not None, "Retail data was not recorded!"
        assert r_record.price == 3.49
        assert r_record.tx_hash is not None, "Retail stage should anchor tx_hash on TrustHarvestV2!"
        print(f" Retail record verified: ${r_record.price}/unit at {r_record.store_name} (Block #{r_record.block_number})")

    # 6. Verify shows "Verified" + JSON API Check
    print("\n[Step 6] Customer accesses /verify/<batch_id> & /api/verify/<batch_id> (Clean Authentic State)...")
    resp = client.get(f'/verify/{batch_id}')
    assert resp.status_code == 200
    html_content = resp.data.decode('utf-8')
    assert 'Verified' in html_content, "Expected Verified status label!"
    assert 'Integrity Score: 100/100' in html_content, "Expected full multi-stage Integrity Score: 100/100!"
    assert 'Farm' in html_content
    assert 'Transport' in html_content
    assert 'Shop' in html_content

    api_resp = client.get(f'/api/verify/{batch_id}')
    assert api_resp.status_code == 200
    api_data = api_resp.get_json()
    assert api_data['verification_status'] == 'verified'
    assert api_data['result_label'] == 'Verified'
    assert api_data['trust_score']['score'] == 100
    assert api_data['timeline']['transport'][0]['verification'] == 'verified'
    assert api_data['timeline']['shop']['verification'] == 'verified'
    print(" Authentic Verification & JSON Proof API succeeded!")

    # 7. Tamper with one DB field and verify it shows "Changed after recording"
    print("\n[Step 7] Tampering with one database field (changing farming_method to fake data)...")
    with app.app_context():
        p_to_tamper = db.session.get(Product, product_id)
        original_method = p_to_tamper.farming_method
        p_to_tamper.farming_method = "Chemically Treated Non-Organic"
        db.session.commit()
        print(f" Tampered field: farming_method '{original_method}' -> '{p_to_tamper.farming_method}'")

    print("\n[Step 8] Customer accesses /verify/<batch_id> (Tampered State)...")
    resp = client.get(f'/verify/{batch_id}')
    assert resp.status_code == 200
    html_content = resp.data.decode('utf-8')
    assert 'Changed after recording' in html_content, "Expected Changed after recording status after database tampering!"
    assert 'All farm, transport, and store details match' not in html_content
    print(" Tamper detection succeeded! 'TAMPER DETECTED' badge confirmed.")

    print("\n" + "=" * 60)
    print("All smoke test assertions PASSED successfully!")
    print("=" * 60)

if __name__ == '__main__':
    run_smoke_test()
