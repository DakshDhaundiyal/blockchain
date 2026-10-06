import os
from datetime import datetime, timedelta
import qrcode
from app import app
from models import db, User, Product, FarmerData, TransportData, RetailData, Feedback
from blockchain import store_hash, compute_batch_hash, load_config

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
QR_FOLDER = os.path.join(BASE_DIR, 'static', 'qr')

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(QR_FOLDER, exist_ok=True)

def generate_qr(batch_id):
    cfg = load_config()
    base_url = cfg.get('BASE_URL', 'http://localhost:5000').rstrip('/')
    verify_url = f"{base_url}/verify/{batch_id}"

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=3,
    )
    qr.add_data(verify_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#1b4332", back_color="white")
    filename = f"qr_{batch_id}.png"
    img.save(os.path.join(QR_FOLDER, filename))
    return filename

def seed():
    with app.app_context():
        print("Resetting database...")
        db.drop_all()
        db.create_all()

        print("Seeding users...")
        # 1 Admin, 1 Farmer, 1 Transporter, 1 Retailer, 1 Customer
        admin = User(username='admin', role='admin', full_name='Global Admin', contact='admin@trustharvest.org')
        admin.set_password('admin123')

        farmer = User(username='farmer_john', role='farmer', full_name='John Evergreen', contact='+1-509-555-0192')
        farmer.set_password('farmer123')

        transporter = User(username='transporter_dan', role='transporter', full_name='Dan Logistics Ltd', contact='+1-206-555-0144')
        transporter.set_password('transit123')

        retailer = User(username='retailer_sarah', role='retailer', full_name='Whole Harvest Market', contact='+1-206-555-0188')
        retailer.set_password('retail123')

        customer = User(username='customer_amy', role='customer', full_name='Amy Chen', contact='amy.c@example.com')
        customer.set_password('customer123')

        db.session.add_all([admin, farmer, transporter, retailer, customer])
        db.session.commit()

        print("Seeding sample batches & publishing hashes to Ethereum blockchain...")

        # Batch 1: Organic Honeycrisp Apples
        batch1_id = "TH-APPLES-001"
        batch1_name = "Organic Honeycrisp Apples"
        batch1_qty = "500 kg"
        batch1_method = "100% Certified Organic"
        batch1_date = "2026-10-01"
        batch1_img = "organic_apples.jpg"

        hash1 = compute_batch_hash(
            batch_id=batch1_id,
            name=batch1_name,
            quantity=batch1_qty,
            farming_method=batch1_method,
            packaging_date=batch1_date,
            farmer_id=farmer.id,
            image=batch1_img
        )

        print(f"Storing Hash for {batch1_id} on-chain: {hash1}")
        store_hash(batch1_id, hash1)
        qr1 = generate_qr(batch1_id)

        p1 = Product(
            batch_id=batch1_id,
            name=batch1_name,
            quantity=batch1_qty,
            farming_method=batch1_method,
            packaging_date=batch1_date,
            farmer_id=farmer.id,
            image=batch1_img,
            qr_code=qr1,
            on_chain_hash=hash1,
            status="In Stock",
            created_at=datetime.utcnow() - timedelta(days=5)
        )
        db.session.add(p1)
        db.session.flush()

        fd1 = FarmerData(
            product_id=p1.id,
            farm_name="Evergreen Orchard",
            farm_location="Yakima Valley, Washington",
            harvest_date=batch1_date,
            certifications="USDA Organic, Non-GMO Project Verified",
            notes="Hand-picked at sunrise. Temperature controlled storage within 2 hours."
        )
        db.session.add(fd1)

        t1_1 = TransportData(
            product_id=p1.id,
            transporter_id=transporter.id,
            status="Picked Up from Farm",
            current_location="Yakima Valley Depot, WA",
            temperature="3.8 °C",
            vehicle_number="TRK-104",
            notes="Cold-chain temperature verified before departure.",
            timestamp=datetime.utcnow() - timedelta(days=4)
        )
        t1_2 = TransportData(
            product_id=p1.id,
            transporter_id=transporter.id,
            status="In Transit (Cold-Storage)",
            current_location="Portland Cross-Dock Hub, OR",
            temperature="4.0 °C",
            vehicle_number="TRK-104",
            notes="Reefer unit optimal.",
            timestamp=datetime.utcnow() - timedelta(days=3)
        )
        t1_3 = TransportData(
            product_id=p1.id,
            transporter_id=transporter.id,
            status="Delivered to Retailer",
            current_location="Whole Harvest Market, Seattle, WA",
            temperature="3.9 °C",
            vehicle_number="TRK-104",
            notes="Delivered in prime condition.",
            timestamp=datetime.utcnow() - timedelta(days=2)
        )
        db.session.add_all([t1_1, t1_2, t1_3])

        rd1 = RetailData(
            product_id=p1.id,
            retailer_id=retailer.id,
            store_name="Whole Harvest Organic Market",
            store_location="500 Pine St, Seattle, WA",
            price=4.99,
            stock_quantity="420 kg",
            arrival_date="2026-10-03",
            shelf_life="21 Days"
        )
        db.session.add(rd1)

        fb1 = Feedback(
            product_id=p1.id,
            customer_name="Amy Chen",
            rating=5,
            comment="Remarkable freshness and crunch! Scanned the QR right off the display carton.",
            created_at=datetime.utcnow() - timedelta(days=1)
        )
        db.session.add(fb1)

        # Batch 2: Heirloom Vine Tomatoes
        batch2_id = "TH-TOMATO-002"
        batch2_name = "Heirloom Vine Tomatoes"
        batch2_qty = "300 kg"
        batch2_method = "Regenerative Agriculture"
        batch2_date = "2026-10-04"
        batch2_img = "heirloom_tomatoes.jpg"

        hash2 = compute_batch_hash(
            batch_id=batch2_id,
            name=batch2_name,
            quantity=batch2_qty,
            farming_method=batch2_method,
            packaging_date=batch2_date,
            farmer_id=farmer.id,
            image=batch2_img
        )

        print(f"Storing Hash for {batch2_id} on-chain: {hash2}")
        store_hash(batch2_id, hash2)
        qr2 = generate_qr(batch2_id)

        p2 = Product(
            batch_id=batch2_id,
            name=batch2_name,
            quantity=batch2_qty,
            farming_method=batch2_method,
            packaging_date=batch2_date,
            farmer_id=farmer.id,
            image=batch2_img,
            qr_code=qr2,
            on_chain_hash=hash2,
            status="In Transit",
            created_at=datetime.utcnow() - timedelta(days=2)
        )
        db.session.add(p2)
        db.session.flush()

        fd2 = FarmerData(
            product_id=p2.id,
            farm_name="Sun Valley Eco Farms",
            farm_location="Salinas Valley, California",
            harvest_date=batch2_date,
            certifications="Regenerative Organic Certified (ROC)",
            notes="No synthetic fertilizers used. Drip-irrigated with solar-powered pumps."
        )
        db.session.add(fd2)

        t2_1 = TransportData(
            product_id=p2.id,
            transporter_id=transporter.id,
            status="Picked Up from Farm",
            current_location="Salinas Packing Station, CA",
            temperature="11.8 °C",
            vehicle_number="TRK-881",
            notes="Ambient ventilated transport loaded.",
            timestamp=datetime.utcnow() - timedelta(days=1)
        )
        t2_2 = TransportData(
            product_id=p2.id,
            transporter_id=transporter.id,
            status="In Transit (Cold-Storage)",
            current_location="Bay Area Transit Interchange, CA",
            temperature="11.5 °C",
            vehicle_number="TRK-881",
            notes="En route to Northern distribution center.",
            timestamp=datetime.utcnow() - timedelta(hours=6)
        )
        db.session.add_all([t2_1, t2_2])

        fb2 = Feedback(
            product_id=p2.id,
            customer_name="Local Foodie",
            rating=5,
            comment="Excited to see regenerative produce traced with cryptographic certainty!",
            created_at=datetime.utcnow() - timedelta(hours=2)
        )
        db.session.add(fb2)

        db.session.commit()
        print("Database and blockchain seed complete!")

if __name__ == '__main__':
    seed()
