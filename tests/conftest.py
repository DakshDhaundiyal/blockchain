import os
import sys

# Ensure workspace root is in sys.path
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# Ensure tests run against an isolated test SQLite database, never touching development db
TEST_DB_PATH = os.path.join(BASE_DIR, "test_trustharvest.db")
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH}"

import pytest
from app import app as flask_app
from models import db, User

@pytest.fixture
def app():
    flask_app.config.update({
        "TESTING": True,
        "WTF_CSRF_ENABLED": False,  # Disabled for automated client calls
        "SECRET_KEY": "test-secret-key-for-pytest-suite",
        "SERVER_NAME": "localhost.localdomain"
    })

    with flask_app.app_context():
        db.drop_all()
        db.create_all()
        # Seed test users
        farmer = User(username="farmer_test", role="farmer", full_name="Farmer Joe", contact="555-01")
        farmer.set_password("farmerpass123")

        transporter = User(username="transporter_test", role="transporter", full_name="Transporter Tim", contact="555-02")
        transporter.set_password("transpass123")

        retailer = User(username="retailer_test", role="retailer", full_name="Retailer Ron", contact="555-03")
        retailer.set_password("retailpass123")

        customer = User(username="customer_test", role="customer", full_name="Customer Clara", contact="555-04")
        customer.set_password("custpass123")

        admin = User(username="admin_test", role="admin", full_name="Admin Alex", contact="555-00")
        admin.set_password("adminpass123")

        db.session.add_all([farmer, transporter, retailer, customer, admin])
        db.session.commit()

        yield flask_app

        db.session.remove()
        db.drop_all()

@pytest.fixture
def client(app):
    return app.test_client()
