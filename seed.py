import argparse
import os
import sys
from datetime import timedelta
from app import (
    app, is_demo_mode,
    _build_harvest_snapshot_payload, _build_transport_snapshot_payload,
    _build_retail_snapshot_payload, _save_stage_snapshot_once,
)
from models import db, User, Product, FarmerData, TransportData, RetailData, utcnow
from blockchain import (
    store_hash_detailed, store_stage_hash,
    compute_batch_hash, compute_transport_hash, compute_retail_hash,
)


def seed():
    with app.app_context():
        print("Resetting database...")
        db.drop_all()
        db.create_all()

        print("Seeding demo users (DEMO_MODE enabled)...")
        admin = User(username='admin', role='admin', full_name='Global Admin', contact='admin@trustharvest.org')
        admin.set_password(os.environ.get('DEMO_ADMIN_PASSWORD', 'admin123'))

        farmer = User(username='farmer_john', role='farmer', full_name='John Evergreen', contact='+1-509-555-0192')
        farmer.set_password(os.environ.get('DEMO_FARMER_PASSWORD', 'farmer123'))

        transporter = User(username='transporter_dan', role='transporter', full_name='Dan Logistics Ltd', contact='+1-206-555-0144')
        transporter.set_password(os.environ.get('DEMO_TRANSPORTER_PASSWORD', 'transit123'))

        retailer = User(username='retailer_sarah', role='retailer', full_name='Whole Harvest Market', contact='+1-206-555-0188')
        retailer.set_password(os.environ.get('DEMO_RETAILER_PASSWORD', 'retail123'))

        customer = User(username='customer_amy', role='customer', full_name='Amy Chen', contact='amy.c@example.com')
        customer.set_password(os.environ.get('DEMO_CUSTOMER_PASSWORD', 'customer123'))

        db.session.add_all([admin, farmer, transporter, retailer, customer])
        db.session.commit()

        print("Seeding sample batches & anchoring multi-stage hashes on-chain...")

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

        print(f"Storing Harvest Hash for {batch1_id} on-chain: {hash1}")
        meta1 = store_hash_detailed(batch1_id, hash1, role="farmer")

        p1 = Product(
            batch_id=batch1_id,
            name=batch1_name,
            quantity=batch1_qty,
            farming_method=batch1_method,
            packaging_date=batch1_date,
            farmer_id=farmer.id,
            image=batch1_img,
            qr_code=f"qr_{batch1_id}.png",
            on_chain_hash=hash1,
            tx_hash=meta1.get("tx_hash"),
            block_number=meta1.get("block_number"),
            contract_address=meta1.get("contract_address"),
            contract_version=meta1.get("contract_version", "V2"),
            signer_address=meta1.get("signer_address"),
            status="In Stock",
            created_at=utcnow() - timedelta(days=5)
        )
        db.session.add(p1)
        db.session.flush()
        _save_stage_snapshot_once(p1.id, "HARVEST", _build_harvest_snapshot_payload(p1), hash1)

        fd1 = FarmerData(
            product_id=p1.id,
            farm_name="Evergreen Orchard",
            farm_location="Yakima Valley, Washington",
            harvest_date=batch1_date,
            certifications="USDA Organic, Non-GMO Project Verified",
            notes="Hand-picked at sunrise. Temperature controlled storage within 2 hours."
        )
        db.session.add(fd1)

        t1_specs = [
            ("Picked Up from Farm", "Yakima Valley Depot, WA", "3.8 °C", "TRK-104", "Cold-chain temperature verified before departure.", 4),
            ("In Transit (Cold-Storage)", "Portland Cross-Dock Hub, OR", "4.0 °C", "TRK-104", "Reefer unit optimal.", 3),
            ("Delivered to Retailer", "Whole Harvest Market, Seattle, WA", "3.9 °C", "TRK-104", "Delivered in prime condition.", 2),
        ]
        for st, loc, temp, veh, note, days_ago in t1_specs:
            th = compute_transport_hash(batch1_id, st, loc, temp, veh, note, transporter.id)
            tm = store_stage_hash(batch1_id, "TRANSPORT", th, role="transporter")
            t_rec = TransportData(
                product_id=p1.id,
                transporter_id=transporter.id,
                status=st,
                current_location=loc,
                temperature=temp,
                vehicle_number=veh,
                notes=note,
                on_chain_hash=th,
                tx_hash=tm.get("tx_hash"),
                block_number=tm.get("block_number"),
                signer_address=tm.get("signer_address"),
                timestamp=utcnow() - timedelta(days=days_ago)
            )
            db.session.add(t_rec)
            db.session.flush()
            if tm.get("status") == "anchored":
                _save_stage_snapshot_once(p1.id, "TRANSPORT", _build_transport_snapshot_payload(p1, t_rec), th, transport_id=t_rec.id)

        rh1 = compute_retail_hash(
            batch1_id, "Whole Harvest Organic Market", "500 Pine St, Seattle, WA",
            4.99, "420 kg", "2026-10-03", "21 Days", retailer.id
        )
        rm1 = store_stage_hash(batch1_id, "RETAIL", rh1, role="retailer")
        rd1 = RetailData(
            product_id=p1.id,
            retailer_id=retailer.id,
            store_name="Whole Harvest Organic Market",
            store_location="500 Pine St, Seattle, WA",
            price=4.99,
            stock_quantity="420 kg",
            arrival_date="2026-10-03",
            shelf_life="21 Days",
            on_chain_hash=rh1,
            tx_hash=rm1.get("tx_hash"),
            block_number=rm1.get("block_number"),
            signer_address=rm1.get("signer_address"),
        )
        db.session.add(rd1)
        db.session.flush()
        if rm1.get("status") == "anchored":
            _save_stage_snapshot_once(p1.id, "RETAIL", _build_retail_snapshot_payload(p1, rd1), rh1)

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

        print(f"Storing Harvest Hash for {batch2_id} on-chain: {hash2}")
        meta2 = store_hash_detailed(batch2_id, hash2, role="farmer")

        p2 = Product(
            batch_id=batch2_id,
            name=batch2_name,
            quantity=batch2_qty,
            farming_method=batch2_method,
            packaging_date=batch2_date,
            farmer_id=farmer.id,
            image=batch2_img,
            qr_code=f"qr_{batch2_id}.png",
            on_chain_hash=hash2,
            tx_hash=meta2.get("tx_hash"),
            block_number=meta2.get("block_number"),
            contract_address=meta2.get("contract_address"),
            contract_version=meta2.get("contract_version", "V2"),
            signer_address=meta2.get("signer_address"),
            status="In Transit",
            created_at=utcnow() - timedelta(days=2)
        )
        db.session.add(p2)
        db.session.flush()
        _save_stage_snapshot_once(p2.id, "HARVEST", _build_harvest_snapshot_payload(p2), hash2)

        fd2 = FarmerData(
            product_id=p2.id,
            farm_name="Sun Valley Eco Farms",
            farm_location="Salinas Valley, California",
            harvest_date=batch2_date,
            certifications="Regenerative Organic Certified (ROC)",
            notes="No synthetic fertilizers used. Drip-irrigated with solar-powered pumps."
        )
        db.session.add(fd2)

        t2_specs = [
            ("Picked Up from Farm", "Salinas Packing Station, CA", "11.8 °C", "TRK-881", "Ambient ventilated transport loaded.", timedelta(days=1)),
            ("In Transit (Cold-Storage)", "Bay Area Transit Interchange, CA", "11.5 °C", "TRK-881", "En route to Northern distribution center.", timedelta(hours=6)),
        ]
        for st, loc, temp, veh, note, delta in t2_specs:
            th = compute_transport_hash(batch2_id, st, loc, temp, veh, note, transporter.id)
            tm = store_stage_hash(batch2_id, "TRANSPORT", th, role="transporter")
            t2_rec = TransportData(
                product_id=p2.id,
                transporter_id=transporter.id,
                status=st,
                current_location=loc,
                temperature=temp,
                vehicle_number=veh,
                notes=note,
                on_chain_hash=th,
                tx_hash=tm.get("tx_hash"),
                block_number=tm.get("block_number"),
                signer_address=tm.get("signer_address"),
                timestamp=utcnow() - delta
            )
            db.session.add(t2_rec)
            db.session.flush()
            if tm.get("status") == "anchored":
                _save_stage_snapshot_once(p2.id, "TRANSPORT", _build_transport_snapshot_payload(p2, t2_rec), th, transport_id=t2_rec.id)

        db.session.commit()
        print("Database and TrustHarvestV2 multi-stage blockchain seed complete!")


def main(argv=None):
    parser = argparse.ArgumentParser(description='Seed TrustHarvest demo data (requires DEMO_MODE=true or --demo).')
    parser.add_argument('--demo', action='store_true', help='Explicitly allow creating demo logins and sample batches.')
    args = parser.parse_args(argv)
    if not (args.demo or is_demo_mode()):
        print(
            'Refusing to seed demo passwords while DEMO_MODE is off. '
            'Run with "--demo" or set DEMO_MODE=true for local demonstrations.',
            file=sys.stderr,
        )
        sys.exit(1)
    seed()


if __name__ == '__main__':
    main()
