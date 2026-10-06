import os
import sys
from datetime import datetime
from app import app, db
from models import User, Product, TransportData, RetailData
from blockchain import get_w3, get_hash, compute_batch_hash

def run_smoke_test():
    print("=" * 60)
    print("TrustHarvest Comprehensive End-to-End Smoke Test")
    print("=" * 60)

    # 1. Ganache Connectivity
    print("\n[Step 1] Verifying connection to Ganache (http://127.0.0.1:7545)...")
    w3 = get_w3()
    print(f" Connected to Ganache! Block Number: {w3.eth.block_number}")
    print(f" Active Ganache accounts: {len(w3.eth.accounts)}")

    client = app.test_client()

    with app.app_context():
        # Clean setup for smoke test
        print("\n[Step 2] Initializing test database & stakeholders...")
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

        # Check QR Code exists
        qr_path = os.path.join(app.root_path, 'static', 'qr', f"qr_{batch_id}.png")
        assert os.path.exists(qr_path), f"QR code file not found at {qr_path}"
        print(f" Generated QR code verified at {qr_path}")

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
        p_check = Product.query.get(product_id)
        assert p_check.status == 'In Transit (Cold-Storage)'
        print(f" Transport checkpoint verified: {t_record.status} at {t_record.current_location}")

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
        print(f" Retail record verified: ${r_record.price}/unit at {r_record.store_name}")

    # 6. Verify shows "BLOCKCHAIN VERIFIED"
    print("\n[Step 6] Customer accesses /verify/<batch_id> (Clean Authentic State)...")
    resp = client.get(f'/verify/{batch_id}')
    assert resp.status_code == 200
    html_content = resp.data.decode('utf-8')
    assert 'BLOCKCHAIN VERIFIED' in html_content, "Expected BLOCKCHAIN VERIFIED badge!"
    assert 'Stage 1: Farm Harvest & Stamping' in html_content
    assert 'Stage 2: Transport' in html_content
    assert 'Stage 3: Retail Stock & Distribution' in html_content
    print(" Authentic Verification succeeded! 'BLOCKCHAIN VERIFIED' badge confirmed.")

    # 7. Tamper with one DB field and verify it shows "TAMPER DETECTED"
    print("\n[Step 7] Tampering with one database field (changing farming_method to fake data)...")
    with app.app_context():
        p_to_tamper = Product.query.get(product_id)
        original_method = p_to_tamper.farming_method
        p_to_tamper.farming_method = "Chemically Treated Non-Organic"
        db.session.commit()
        print(f" Tampered field: farming_method '{original_method}' -> '{p_to_tamper.farming_method}'")

    print("\n[Step 8] Customer accesses /verify/<batch_id> (Tampered State)...")
    resp = client.get(f'/verify/{batch_id}')
    assert resp.status_code == 200
    html_content = resp.data.decode('utf-8')
    assert 'TAMPER DETECTED' in html_content, "Expected TAMPER DETECTED badge after database tampering!"
    assert 'BLOCKCHAIN VERIFIED' not in html_content, "Did not expect BLOCKCHAIN VERIFIED on tampered record!"
    print(" Tamper detection succeeded! 'TAMPER DETECTED' badge confirmed.")

    print("\n" + "=" * 60)
    print("All smoke test assertions PASSED successfully!")
    print("=" * 60)

if __name__ == '__main__':
    run_smoke_test()
