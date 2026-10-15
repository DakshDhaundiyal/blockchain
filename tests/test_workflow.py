import pytest
from models import db, User, Product, TransportData, RetailData, Feedback

def create_sample_product(app):
    with app.app_context():
        farmer = User.query.filter_by(username="farmer_test").first()
        prod = Product(
            batch_id="TH-WORKFLOW-01",
            name="Hydroponic Tomatoes",
            quantity="200 boxes",
            farming_method="Hydroponic Controlled",
            packaging_date="2026-10-15",
            farmer_id=farmer.id,
            image="default.jpg",
            qr_code="qr_TH-WORKFLOW-01.png",
            on_chain_hash="aabbccddeeff11223344556677889900aabbccddeeff11223344556677889900",
            status="Harvested"
        )
        db.session.add(prod)
        db.session.commit()
        return prod.id

def test_transporter_checkpoint_workflow(client, app):
    prod_id = create_sample_product(app)

    with client.session_transaction() as sess:
        sess["user_id"] = 2
        sess["username"] = "transporter_test"
        sess["role"] = "transporter"

    res = client.post("/transporter/add", data={
        "product_id": prod_id,
        "status": "In Transit (Cold-Storage)",
        "current_location": "Spokane Cold Hub",
        "temperature": "3.5 C",
        "vehicle_number": "TRK-9900",
        "notes": "Optimal temperature maintained."
    }, follow_redirects=True)
    assert res.status_code == 200
    assert b"Transport checkpoint recorded" in res.data

    with app.app_context():
        prod = Product.query.get(prod_id)
        assert prod.status == "In Transit (Cold-Storage)"
        rec = TransportData.query.filter_by(product_id=prod_id).first()
        assert rec is not None
        assert rec.current_location == "Spokane Cold Hub"
        assert rec.temperature == "3.5 C"

def test_retailer_stock_workflow(client, app):
    prod_id = create_sample_product(app)

    with client.session_transaction() as sess:
        sess["user_id"] = 3
        sess["username"] = "retailer_test"
        sess["role"] = "retailer"

    res = client.post("/retailer/add", data={
        "product_id": prod_id,
        "store_name": "Whole Harvest Market",
        "store_location": "Seattle, WA",
        "price": "4.99",
        "stock_quantity": "180 boxes",
        "arrival_date": "2026-10-16",
        "shelf_life": "14 days"
    }, follow_redirects=True)
    assert res.status_code == 200
    assert b"Retail stock and price details updated" in res.data

    with app.app_context():
        prod = Product.query.get(prod_id)
        assert prod.status == "In Stock"
        ret = RetailData.query.filter_by(product_id=prod_id).first()
        assert ret is not None
        assert ret.price == 4.99
        assert ret.store_name == "Whole Harvest Market"

def test_retailer_negative_price_rejected(client, app):
    prod_id = create_sample_product(app)

    with client.session_transaction() as sess:
        sess["user_id"] = 3
        sess["username"] = "retailer_test"
        sess["role"] = "retailer"

    res = client.post("/retailer/add", data={
        "product_id": prod_id,
        "store_name": "Whole Harvest Market",
        "store_location": "Seattle, WA",
        "price": "-5.00",
        "stock_quantity": "50",
        "arrival_date": "2026-10-16",
        "shelf_life": "10 days"
    }, follow_redirects=True)
    assert b"Price must be a positive value" in res.data

def test_customer_lookup_and_feedback(client, app):
    prod_id = create_sample_product(app)

    # Customer search by batch ID
    res = client.get("/customer?batch_id=TH-WORKFLOW-01")
    assert res.status_code == 302
    assert "/verify/TH-WORKFLOW-01" in res.headers["Location"]

    # Customer submits feedback
    res = client.post("/verify/TH-WORKFLOW-01/feedback", data={
        "customer_name": "Alice Buyer",
        "rating": "5",
        "comment": "Crisp, flavorful and verified fresh!"
    }, follow_redirects=True)
    assert res.status_code == 200
    assert b"Feedback submitted successfully" in res.data

    with app.app_context():
        fb = Feedback.query.filter_by(product_id=prod_id).first()
        assert fb is not None
        assert fb.rating == 5
        assert fb.comment == "Crisp, flavorful and verified fresh!"
