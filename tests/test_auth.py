import pytest
from models import User
from app import is_login_rate_limited, record_failed_login, clear_failed_logins

def test_register_success(client, app):
    res = client.post("/register", data={
        "role": "farmer",
        "username": "new_farmer",
        "password": "securepassword123",
        "full_name": "New Farmer Jane",
        "contact": "555-999"
    }, follow_redirects=True)
    assert res.status_code == 200
    assert b"Registration successful" in res.data

    with app.app_context():
        user = User.query.filter_by(username="new_farmer").first()
        assert user is not None
        assert user.role == "farmer"
        assert user.check_password("securepassword123")

def test_register_short_password_rejected(client, app):
    res = client.post("/register", data={
        "role": "customer",
        "username": "short_pw_user",
        "password": "123",  # < 8 characters
        "full_name": "Short Pass",
        "contact": "555"
    }, follow_redirects=True)
    assert res.status_code == 200
    assert b"Password must be at least 8 characters" in res.data

    with app.app_context():
        user = User.query.filter_by(username="short_pw_user").first()
        assert user is None

def test_register_admin_role_rejected(client, app):
    res = client.post("/register", data={
        "role": "admin",
        "username": "hacker_admin",
        "password": "password12345",
        "full_name": "Hacker",
        "contact": "evil"
    }, follow_redirects=True)
    assert res.status_code == 200
    assert b"Invalid role selected" in res.data

def test_login_success(client):
    res = client.post("/login", data={
        "username": "farmer_test",
        "password": "farmerpass123"
    }, follow_redirects=True)
    assert res.status_code == 200
    assert b"Welcome back, farmer_test" in res.data
    with client.session_transaction() as sess:
        assert sess.get("user_id") is not None
        assert sess.get("role") == "farmer"

def test_login_invalid_password(client):
    res = client.post("/login", data={
        "username": "farmer_test",
        "password": "wrongpassword"
    }, follow_redirects=True)
    assert res.status_code == 200
    assert b"Invalid username or password" in res.data
    with client.session_transaction() as sess:
        assert "user_id" not in sess

def test_login_rate_limiting(client):
    username = "brute_force_target"
    clear_failed_logins(username)
    # Simulate 5 failed attempts
    for _ in range(5):
        record_failed_login(username)
    
    assert is_login_rate_limited(username) is True

    res = client.post("/login", data={
        "username": username,
        "password": "any"
    }, follow_redirects=True)
    assert b"temporarily locked" in res.data

    clear_failed_logins(username)

def test_role_access_control(client):
    # Unauthenticated access to /farmer redirects to login
    res = client.get("/farmer", follow_redirects=True)
    assert b"Please log in to continue" in res.data or b"Sign In" in res.data

    # Log in as customer and try to access /farmer
    with client.session_transaction() as sess:
        sess["user_id"] = 4
        sess["username"] = "customer_test"
        sess["role"] = "customer"

    res = client.get("/farmer", follow_redirects=True)
    assert b"Access denied for your user role" in res.data

def test_logout_session_cleared(client):
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["username"] = "farmer_test"
        sess["role"] = "farmer"

    res = client.post("/logout", follow_redirects=True)
    assert res.status_code == 200
    assert b"securely signed out" in res.data
    with client.session_transaction() as sess:
        assert "user_id" not in sess
