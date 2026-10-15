import pytest
from models import User

def test_switch_role_farmer(client, app):
    res = client.get("/switch-role/farmer", follow_redirects=True)
    assert res.status_code == 200
    assert b"Farmer Management Portal" in res.data or b"Farmer" in res.data

    with client.session_transaction() as sess:
        assert sess.get("role") == "farmer"
        assert sess.get("user_id") is not None
        assert sess.get("username") is not None

def test_switch_role_transporter(client, app):
    res = client.get("/switch-role/transporter", follow_redirects=True)
    assert res.status_code == 200
    assert b"Transporter" in res.data or b"Logistics" in res.data

    with client.session_transaction() as sess:
        assert sess.get("role") == "transporter"
        assert sess.get("user_id") is not None

def test_switch_role_retailer(client, app):
    res = client.get("/switch-role/retailer", follow_redirects=True)
    assert res.status_code == 200
    assert b"Retailer" in res.data or b"Store" in res.data

    with client.session_transaction() as sess:
        assert sess.get("role") == "retailer"
        assert sess.get("user_id") is not None

def test_switch_role_customer(client, app):
    res = client.get("/switch-role/customer", follow_redirects=True)
    assert res.status_code == 200
    assert b"Consumer" in res.data or b"Customer" in res.data

    with client.session_transaction() as sess:
        assert sess.get("role") == "customer"
        assert sess.get("user_id") is not None

def test_switch_role_admin(client, app):
    res = client.get("/switch-role/admin", follow_redirects=True)
    assert res.status_code == 200
    assert b"Administrator" in res.data or b"Admin" in res.data

    with client.session_transaction() as sess:
        assert sess.get("role") == "admin"
        assert sess.get("user_id") is not None

def test_switch_role_aliases(client, app):
    # producer -> farmer
    res = client.get("/switch-role/producer", follow_redirects=False)
    assert res.status_code == 302
    assert "/farmer" in res.headers["Location"]

    # logistics -> transporter
    res = client.get("/switch-role/logistics", follow_redirects=False)
    assert res.status_code == 302
    assert "/transporter" in res.headers["Location"]

    # supermarket -> retailer
    res = client.get("/switch-role/supermarket", follow_redirects=False)
    assert res.status_code == 302
    assert "/retailer" in res.headers["Location"]

    # consumer -> customer
    res = client.get("/switch-role/consumer", follow_redirects=False)
    assert res.status_code == 302
    assert "/customer" in res.headers["Location"]

def test_switch_role_invalid(client, app):
    res = client.get("/switch-role/unknown_role", follow_redirects=True)
    assert res.status_code == 200
    assert b"Unknown dashboard type" in res.data

def test_switch_role_next_url(client, app):
    res = client.get("/switch-role/farmer?next=/customer", follow_redirects=False)
    assert res.status_code == 302
    assert res.headers["Location"] == "/customer"

def test_navbar_renders_switcher(client):
    res = client.get("/")
    assert res.status_code == 200
    # Must contain switcher dropdown and persona links
    assert b"dashboardSwitcherDropdown" in res.data
    assert b"/switch-role/farmer" in res.data
    assert b"/switch-role/transporter" in res.data
    assert b"/switch-role/retailer" in res.data
    assert b"/switch-role/customer" in res.data
    assert b"/switch-role/admin" in res.data
