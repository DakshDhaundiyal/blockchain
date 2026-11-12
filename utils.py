import os
import re
import logging
from io import BytesIO
import qrcode
from qrcode.constants import ERROR_CORRECT_M
from PIL import Image

# Configure logging
logger = logging.getLogger("trustharvest")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)s in %(module)s: %(message)s"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def _is_localhost_url(url: str) -> bool:
    low = (url or "").strip().lower()
    return any(tok in low for tok in ("//localhost", "//127.0.0.1", "localhost:", "127.0.0.1:"))


def resolve_qr_base_url(request_url_root: str | None = None) -> str:
    """
    Resolves public BASE_URL from environment (BASE_URL or RENDER_EXTERNAL_URL) first,
    then non-localhost request origin. Never returns a localhost URL.
    """
    for candidate in (
        os.environ.get("BASE_URL", ""),
        os.environ.get("RENDER_EXTERNAL_URL", ""),
        request_url_root or "",
    ):
        clean = str(candidate).strip().rstrip("/")
        if clean and not _is_localhost_url(clean):
            return clean
    return ""


def generate_batch_qr_bytes(batch_id: str, base_url: str = "") -> BytesIO:
    """
    Generates a QR code PNG in memory (no local disk persistence required)
    pointing to <base_url>/verify/<batch_id>. Never encodes localhost.
    """
    clean_base = str(base_url or "").strip().rstrip("/")
    if _is_localhost_url(clean_base):
        clean_base = ""
    verify_url = f"{clean_base}/verify/{batch_id}" if clean_base else f"/verify/{batch_id}"

    qr = qrcode.QRCode(
        version=1,
        error_correction=ERROR_CORRECT_M,
        box_size=8,
        border=3,
    )
    qr.add_data(verify_url)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="#1b4332", back_color="white")

    buf = BytesIO()
    qr_img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def generate_batch_qr(batch_id: str, qr_folder: str, base_url: str = "") -> str:
    """
    Optional local helper returning the QR filename; production serves QR codes dynamically via /qr/<batch_id>.png.
    """
    os.makedirs(qr_folder, exist_ok=True)
    resolved = base_url if (base_url and not _is_localhost_url(base_url)) else resolve_qr_base_url()
    buf = generate_batch_qr_bytes(batch_id, resolved)
    qr_filename = f"qr_{batch_id}.png"
    dest_path = os.path.join(qr_folder, qr_filename)
    with open(dest_path, "wb") as f:
        f.write(buf.getvalue())
    logger.info("Generated QR code for batch %s -> %s", batch_id, dest_path)
    return qr_filename


def sanitize_error_text(msg: str) -> str:
    """
    Redacts RPC provider API keys, DB passwords, and private keys from error text before logging or display.
    """
    text = str(msg or "")
    # Mask explicit private-key values configured in environment variables
    for env_key in (
        "SECRET_KEY",
        "DEPLOYER_PRIVATE_KEY",
        "FARMER_PRIVATE_KEY",
        "TRANSPORTER_PRIVATE_KEY",
        "RETAILER_PRIVATE_KEY",
        "SIGNER_PRIVATE_KEY",
    ):
        secret_val = (os.environ.get(env_key) or "").strip()
        if len(secret_val) >= 8 and secret_val in text:
            text = text.replace(secret_val, "***REDACTED***")
    # Mask Alchemy / Infura style RPC API keys in URLs
    text = re.sub(r"(https?://[^\s/]+/(?:v2|v3)/)[A-Za-z0-9_-]{8,}", r"\1***REDACTED***", text)
    # Mask database URI userinfo passwords
    text = re.sub(r"(postgresql(?:\+psycopg2)?://[^:\s]+:)[^@\s]+(@)", r"\1***REDACTED***\2", text)
    # Mask explicit private_key / key assignments or key 0x... patterns
    text = re.sub(
        r"((?:private[_-]?)?key\s*(?:[:=]\s*|\s+))(?:0x)?[0-9a-fA-F]{32,}",
        r"\1***REDACTED***",
        text,
        flags=re.IGNORECASE,
    )
    return text


def validate_image_file(file_storage, allowed_extensions=None) -> tuple[bool, str]:
    """
    Validates both filename extension and actual image file content using Pillow.
    Returns (is_valid, reason).
    """
    if allowed_extensions is None:
        allowed_extensions = {"png", "jpg", "jpeg", "gif", "webp"}

    filename = getattr(file_storage, "filename", "") or ""
    if "." not in filename:
        return False, "File lacks an extension."

    ext = filename.rsplit(".", 1)[1].lower()
    if ext not in allowed_extensions:
        return False, f"File extension '{ext}' is not permitted. Allowed: {', '.join(sorted(allowed_extensions))}"

    # Validate image bytes
    try:
        content = file_storage.read()
        file_storage.seek(0)  # Rewind pointer for subsequent save
        if len(content) == 0:
            return False, "Uploaded file is empty."

        image = Image.open(BytesIO(content))
        image.verify()  # Verifies file header and integrity without full decode
        return True, ""
    except Exception as e:
        return False, f"Invalid or corrupted image file ({e})."


def evaluate_temperature(temp_str: str | None) -> dict:
    """
    Parses a cold-chain temperature reading (e.g. '4.0 °C', '18.5 C') and classifies it
    against standard perishable agricultural cold-chain thresholds.
    Returns { 'celsius': float|None, 'status': str, 'label': str, 'badge_class': str }.
    """
    if not temp_str:
        return {
            "celsius": None,
            "status": "unknown",
            "label": "Ambient / Unspecified",
            "badge_class": "bg-secondary-subtle text-secondary",
        }

    match = re.search(r"(-?\d+(?:\.\d+)?)", str(temp_str))
    if not match:
        return {
            "celsius": None,
            "status": "unknown",
            "label": str(temp_str),
            "badge_class": "bg-secondary-subtle text-secondary",
        }

    celsius = float(match.group(1))
    if -2.0 <= celsius <= 8.0:
        return {
            "celsius": celsius,
            "status": "optimal",
            "label": f"{celsius:.1f} °C • Cold-Chain Optimal",
            "badge_class": "bg-success-subtle text-success border border-success-subtle",
        }
    elif 8.0 < celsius <= 15.0:
        return {
            "celsius": celsius,
            "status": "elevated",
            "label": f"{celsius:.1f} °C • Cool / Ambient",
            "badge_class": "bg-warning-subtle text-warning-emphasis border border-warning-subtle",
        }
    else:
        return {
            "celsius": celsius,
            "status": "breach",
            "label": f"{celsius:.1f} °C • Cold-Chain Breach",
            "badge_class": "bg-danger-subtle text-danger border border-danger-subtle fw-semibold",
        }


def compute_trust_score(
    harvest_verified: bool,
    transport_count: int,
    transport_verified_count: int,
    has_retail: bool,
    retail_verified: bool,
    has_temp_breach: bool,
) -> dict:
    """
    Computes an objective provenance & supply-chain integrity score (0-100)
    derived strictly from live cryptographic checks and cold-chain telemetry.
    """
    score = 0
    if harvest_verified:
        score += 50
    if transport_count > 0:
        if transport_verified_count == transport_count:
            score += 25
        elif transport_verified_count > 0:
            score += int(25 * (transport_verified_count / transport_count))
    if has_retail and retail_verified:
        score += 25
    elif has_retail:
        score += 10  # Recorded in DB only

    if has_temp_breach and score > 0:
        score = max(0, score - 15)

    if score >= 90:
        tier = ("Excellent", "success")
    elif score >= 65:
        tier = ("Good", "primary")
    elif score >= 40:
        tier = ("Partial", "warning")
    else:
        tier = ("Unverified / Alert", "danger")

    return {"score": score, "tier": tier[0], "color": tier[1]}

