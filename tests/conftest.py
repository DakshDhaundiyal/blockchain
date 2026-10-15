import os
import sys
import tempfile

# Ensure workspace root is in sys.path
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import pytest
from app import app as flask_app
from models import db, User

@pytest.fixture
def app():
    # Setup temporary database file for test isolation
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    flask_app.config.update({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_path}",
        "WTF_CSRF_ENABLED": False,  # Disabled for automated client calls
        "SECRET_KEY": "test-secret-key-for-pytest-suite",
        "SERVER_NAME": "localhost.localdomain"
    })

    with flask_app.app_context():
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

    os.close(db_fd)
    try:
        os.unlink(db_path)
    except OSError:
        pass

@pytest.fixture
def client(app):
    return app.test_client()

@pytest.fixture
def runner(app):
    return app.test_cli_runner()
