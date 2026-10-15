import io
import pytest
from PIL import Image
from utils import validate_image_file

class DummyFile:
    def __init__(self, filename, content_bytes):
        self.filename = filename
        self._bytes = content_bytes
        self._io = io.BytesIO(content_bytes)

    def read(self):
        return self._io.read()

    def seek(self, pos):
        return self._io.seek(pos)

def test_validate_image_disallowed_extension():
    f = DummyFile("exploit.php", b"<?php echo 'hack'; ?>")
    is_valid, reason = validate_image_file(f)
    assert is_valid is False
    assert "not permitted" in reason

def test_validate_image_fake_extension():
    # File named .jpg, but containing arbitrary script text
    f = DummyFile("malware.jpg", b"<script>alert('xss')</script>")
    is_valid, reason = validate_image_file(f)
    assert is_valid is False
    assert "Invalid or corrupted image" in reason

def test_validate_image_valid_png():
    # Generate genuine 10x10 PNG bytes using Pillow
    img = Image.new("RGB", (10, 10), color="green")
    out = io.BytesIO()
    img.save(out, format="PNG")
    valid_bytes = out.getvalue()

    f = DummyFile("produce.png", valid_bytes)
    is_valid, reason = validate_image_file(f)
    assert is_valid is True
    assert reason == ""

def test_csrf_protection_enabled(app):
    # Enable CSRF explicitly to test protection behavior
    app.config["WTF_CSRF_ENABLED"] = True
    client = app.test_client()

    # POST to /login without CSRF token must trigger CSRF error handler
    res = client.post("/login", data={
        "username": "farmer_test",
        "password": "farmerpass123"
    }, follow_redirects=True)
    assert b"invalid form submission token" in res.data or b"Security session expired" in res.data
    app.config["WTF_CSRF_ENABLED"] = False
