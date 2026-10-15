import os
import logging
from io import BytesIO
import qrcode
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


def generate_batch_qr(batch_id: str, qr_folder: str, base_url: str = "http://localhost:5000") -> str:
    """
    Generates a high-quality QR code pointing to the batch verification URL.
    Returns the generated filename.
    """
    os.makedirs(qr_folder, exist_ok=True)
    clean_base = (base_url or "http://localhost:5000").rstrip("/")
    verify_url = f"{clean_base}/verify/{batch_id}"

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=3,
    )
    qr.add_data(verify_url)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="#1b4332", back_color="white")

    qr_filename = f"qr_{batch_id}.png"
    dest_path = os.path.join(qr_folder, qr_filename)
    qr_img.save(dest_path)
    logger.info("Generated QR code for batch %s -> %s", batch_id, dest_path)
    return qr_filename


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
