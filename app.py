import os
import json
import uuid
import time
from datetime import datetime, timezone, timedelta
from functools import wraps
from flask import (
    Flask, render_template, request, redirect, url_for, flash, session, jsonify,
    abort, send_file
)
from flask_wtf.csrf import CSRFProtect, CSRFError
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

# Load local environment configuration if present
load_dotenv()

from models import (
    db, User, Product, FarmerData, TransportData, RetailData,
    StageSnapshot, utcnow, ensure_schema_columns
)
from blockchain import (
    store_hash, store_hash_detailed, store_stage_hash, get_hash,
    compute_batch_hash, compute_transport_hash, compute_retail_hash,
    fetch_on_chain_status, fetch_v2_provenance_details,
    inspect_batch_on_chain, get_admin_blockchain_overview, get_w3
)
from utils import (
    generate_batch_qr_bytes, resolve_qr_base_url, sanitize_error_text,
    validate_image_file, evaluate_temperature, compute_trust_score, logger
)

app = Flask(__name__)


def is_production_mode() -> bool:
    return (
        os.environ.get('FLASK_ENV', '').strip().lower() == 'production'
        or os.environ.get('PRODUCTION', 'false').strip().lower() in ('true', '1', 'yes')
        or os.environ.get('RENDER', 'false').strip().lower() in ('true', '1', 'yes')
    )


def is_demo_mode() -> bool:
    return os.environ.get('DEMO_MODE', 'false').strip().lower() in ('true', '1', 'yes', 'on')


def allow_image_uploads() -> bool:
    return os.environ.get('ALLOW_IMAGE_UPLOADS', 'false').strip().lower() in ('true', '1', 'yes', 'on')


# Security: Move secret configuration to environment variables
SECRET_KEY = os.environ.get('SECRET_KEY')
if not SECRET_KEY:
    if is_production_mode():
        raise RuntimeError("FATAL: SECRET_KEY environment variable must be set in production mode.")
    SECRET_KEY = 'trustharvest-dev-only-secret-key-change-in-production'
app.config['SECRET_KEY'] = SECRET_KEY

# Database Configuration (SQLite locally, Neon/PostgreSQL in production)
raw_db_url = (os.environ.get('DATABASE_URL') or os.environ.get('DATABASE_URI') or 'sqlite:///trustharvest.db').strip()
if raw_db_url.startswith('postgres://'):
    raw_db_url = 'postgresql://' + raw_db_url[len('postgres://'):]
app.config['SQLALCHEMY_DATABASE_URI'] = raw_db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
if raw_db_url.startswith('postgresql'):
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'pool_pre_ping': True, 'pool_recycle': 300}

# Security: Session Cookie Hardening
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
cookie_secure_env = os.environ.get('SESSION_COOKIE_SECURE')
if cookie_secure_env is not None:
    app.config['SESSION_COOKIE_SECURE'] = cookie_secure_env.strip().lower() in ('true', '1', 'yes')
else:
    app.config['SESSION_COOKIE_SECURE'] = is_production_mode()
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=4)

# Security: Restrict maximum upload size (default 5 MB)
try:
    app.config['MAX_CONTENT_LENGTH'] = int(os.environ.get('MAX_CONTENT_LENGTH', 5 * 1024 * 1024))
except (TypeError, ValueError):
    app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024

# Security: Initialize CSRF Protection
csrf = CSRFProtect(app)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
STATIC_PRODUCE_IMAGES = [
    ('default.jpg', 'Fresh Harvest Crate (Default)'),
    ('organic_apples.jpg', 'Crisp Orchard Apples'),
    ('heirloom_tomatoes.jpg', 'Vine-Ripened Tomatoes'),
]
ALLOWED_STATIC_IMAGE_NAMES = {item[0] for item in STATIC_PRODUCE_IMAGES}

db.init_app(app)

with app.app_context():
    db.create_all()
    ensure_schema_columns()


def product_image_url(image_name: str | None) -> str:
    clean = (image_name or 'default.jpg').strip() or 'default.jpg'
    img_path = os.path.join(BASE_DIR, 'static', 'img', clean)
    if os.path.exists(img_path):
        return url_for('static', filename=f'img/{clean}')
    up_path = os.path.join(UPLOAD_FOLDER, clean)
    if os.path.exists(up_path):
        return url_for('static', filename=f'uploads/{clean}')
    return url_for('static', filename='img/default.jpg')


# Make helpers available across Jinja templates
app.jinja_env.globals['evaluate_temperature'] = evaluate_temperature
app.jinja_env.globals['product_image_url'] = product_image_url
app.jinja_env.globals['STATIC_PRODUCE_IMAGES'] = STATIC_PRODUCE_IMAGES

# In-memory rate limiting for login attempts
FAILED_LOGINS = {}
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_WINDOW_SECONDS = 300

def is_login_rate_limited(username):
    now = time.time()
    attempts = FAILED_LOGINS.get(username, [])
    recent_attempts = [t for t in attempts if now - t < LOCKOUT_WINDOW_SECONDS]
    FAILED_LOGINS[username] = recent_attempts
    return len(recent_attempts) >= MAX_FAILED_ATTEMPTS

def record_failed_login(username):
    now = time.time()
    attempts = FAILED_LOGINS.get(username, [])
    attempts.append(now)
    FAILED_LOGINS[username] = attempts

def clear_failed_logins(username):
    FAILED_LOGINS.pop(username, None)

@app.errorhandler(CSRFError)
def handle_csrf_error(e):
    logger.warning("CSRF validation failed: %s from %s", getattr(e, 'description', e), request.remote_addr)
    flash('Security session expired or invalid form submission token. Please try again.', 'warning')
    return redirect(request.referrer or url_for('landing'))

@app.errorhandler(413)
def request_entity_too_large(error):
    flash('The uploaded file is too large. Maximum permitted file size is 5MB.', 'danger')
    return redirect(request.referrer or url_for('landing'))

@app.context_processor
def inject_system_status():
    """Provides honest verification availability and active persona info to templates without leaking internal chain details."""
    is_online = False
    try:
        w3 = get_w3(die_on_error=False)
        if w3 and w3.is_connected():
            is_online = True
    except Exception:
        pass
    role = session.get('role', None)
    return {
        'blockchain_online': is_online,
        'demo_mode': is_demo_mode(),
        'allow_uploads': allow_image_uploads(),
        'DEFAULT_PERSONAS': DEFAULT_PERSONAS,
        'current_role': role,
        'current_username': session.get('username', None),
        'current_persona': DEFAULT_PERSONAS.get(role, None),
    }

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

DEFAULT_PERSONAS = {
    'farmer': {
        'role': 'farmer',
        'username': 'farmer_john',
        'full_name': 'John Evergreen',
        'contact': '+1-509-555-0192',
        'route': 'farmer_dashboard',
        'title': 'Farmer / Producer',
        'short_title': 'Farmer',
        'icon': 'bi-tree',
        'badge_color': '#16a34a'
    },
    'transporter': {
        'role': 'transporter',
        'username': 'transporter_dan',
        'full_name': 'Dan Logistics Ltd',
        'contact': '+1-206-555-0144',
        'route': 'transporter_dashboard',
        'title': 'Transporter / Logistics',
        'short_title': 'Transporter',
        'icon': 'bi-truck',
        'badge_color': '#2563eb'
    },
    'retailer': {
        'role': 'retailer',
        'username': 'retailer_sarah',
        'full_name': 'Whole Harvest Market',
        'contact': '+1-206-555-0188',
        'route': 'retailer_dashboard',
        'title': 'Retailer / Supermarket',
        'short_title': 'Retailer',
        'icon': 'bi-shop',
        'badge_color': '#9333ea'
    },
    'customer': {
        'role': 'customer',
        'username': 'customer_amy',
        'full_name': 'Amy Chen',
        'contact': 'amy.c@example.com',
        'route': 'customer_dashboard',
        'title': 'Consumer / Verify Produce',
        'short_title': 'Consumer',
        'icon': 'bi-person-check',
        'badge_color': '#0891b2'
    },
    'admin': {
        'role': 'admin',
        'username': 'admin',
        'full_name': 'Global Admin',
        'contact': 'admin@trustharvest.org',
        'route': 'admin_dashboard',
        'title': 'System Administrator',
        'short_title': 'Admin',
        'icon': 'bi-shield-shaded',
        'badge_color': '#ea580c'
    },
}

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def role_required(*allowed_roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                flash('Please log in to continue.', 'warning')
                return redirect(url_for('login'))
            if session.get('role') not in allowed_roles:
                flash('Access denied for your user role.', 'danger')
                return redirect(url_for('landing'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

@app.route('/')
def landing():
    product_count = Product.query.count()
    user_count = User.query.count()
    transport_count = TransportData.query.count()
    recent_products = Product.query.order_by(Product.created_at.desc()).limit(8).all()

    return render_template(
        'landing.html',
        product_count=product_count,
        user_count=user_count,
        transport_count=transport_count,
        recent_products=recent_products,
    )

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        role = request.form.get('role', '').strip().lower()
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        full_name = request.form.get('full_name', '').strip()
        contact = request.form.get('contact', '').strip()

        if role not in ['farmer', 'transporter', 'retailer', 'customer']:
            flash('Invalid role selected.', 'danger')
            return redirect(url_for('register'))

        if not username or not password:
            flash('Username and password are required.', 'danger')
            return redirect(url_for('register'))

        if len(password) < 8:
            flash('Password must be at least 8 characters long for security.', 'danger')
            return redirect(url_for('register'))

        if len(username) < 3 or len(username) > 80:
            flash('Username must be between 3 and 80 characters.', 'danger')
            return redirect(url_for('register'))

        if len(full_name) > 120 or len(contact) > 120:
            flash('Full name or contact details exceed maximum allowed length.', 'danger')
            return redirect(url_for('register'))

        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            flash('Username already registered. Please sign in.', 'warning')
            return redirect(url_for('login'))

        user = User(
            username=username,
            role=role,
            full_name=full_name,
            contact=contact
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        flash('Registration successful! Please log in.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        if not username or not password:
            flash('Please enter both username and password.', 'danger')
            return render_template('login.html')

        if is_login_rate_limited(username):
            logger.warning("Rate limited login attempt for user '%s'", username)
            flash('Too many failed attempts. For your security, this account is temporarily locked for 5 minutes.', 'danger')
            return render_template('login.html')

        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            clear_failed_logins(username)
            session['user_id'] = user.id
            session['username'] = user.username
            session['role'] = user.role
            session.permanent = True
            flash(f'Welcome back, {user.username}!', 'success')

            next_url = request.args.get('next') or request.form.get('next')
            if next_url and next_url.startswith('/') and not next_url.startswith('//'):
                return redirect(next_url)

            if user.role == 'farmer':
                return redirect(url_for('farmer_dashboard'))
            elif user.role == 'transporter':
                return redirect(url_for('transporter_dashboard'))
            elif user.role == 'retailer':
                return redirect(url_for('retailer_dashboard'))
            elif user.role == 'admin':
                return redirect(url_for('admin_dashboard'))
            else:
                return redirect(url_for('customer_dashboard'))

        record_failed_login(username)
        flash('Invalid username or password.', 'danger')
    return render_template('login.html')

@app.route('/logout', methods=['GET', 'POST'])
def logout():
    session.clear()
    flash('You have been securely signed out.', 'info')
    return redirect(url_for('landing'))

@app.route('/switch-role/<role>')
def switch_role(role):
    """
    Demo-only helper to switch roles cleanly without credentials.
    Returns 404 when DEMO_MODE is off.
    """
    if not is_demo_mode():
        abort(404)

    target_role = role.strip().lower()
    alias_map = {
        'producer': 'farmer',
        'farm': 'farmer',
        'agriculture': 'farmer',
        'transport': 'transporter',
        'logistics': 'transporter',
        'supermarket': 'retailer',
        'retail': 'retailer',
        'store': 'retailer',
        'consumer': 'customer',
        'client': 'customer',
        'buyer': 'customer',
    }
    target_role = alias_map.get(target_role, target_role)

    if target_role not in DEFAULT_PERSONAS:
        flash(f"Unknown dashboard type '{role}'.", 'warning')
        return redirect(url_for('landing'))

    persona = DEFAULT_PERSONAS[target_role]
    user = User.query.filter_by(role=target_role).first()
    if not user:
        existing_username = User.query.filter_by(username=persona['username']).first()
        uname = persona['username'] if not existing_username else f"{persona['username']}_{int(time.time())}"
        user = User(
            username=uname,
            role=target_role,
            full_name=persona['full_name'],
            contact=persona['contact']
        )
        user.set_password(f"{target_role}12345")
        db.session.add(user)
        db.session.commit()

    session['user_id'] = user.id
    session['username'] = user.username
    session['role'] = user.role
    session.permanent = True
    flash(f"Active Dashboard: {persona['title']} ({user.full_name or user.username})", 'success')

    next_url = request.args.get('next')
    if next_url and next_url.startswith('/'):
        return redirect(next_url)
    return redirect(url_for(persona['route']))


# ═══════════════════════════════════════════════════════════════════
# STAGE SNAPSHOTS & FIELD DIFF HELPERS
# ═══════════════════════════════════════════════════════════════════

_STAGE_DIFF_FIELDS = {
    "HARVEST": [
        ("name", "Produce Name"),
        ("quantity", "Quantity"),
        ("farming_method", "Farming Method"),
        ("packaging_date", "Packaging Date"),
        ("image", "Product Image"),
        ("farmer_id", "Farmer ID"),
    ],
    "TRANSPORT": [
        ("status", "Shipment Status"),
        ("current_location", "Location"),
        ("temperature", "Temperature"),
        ("vehicle_number", "Vehicle Number"),
        ("notes", "Notes"),
        ("transporter_id", "Transporter ID"),
    ],
    "RETAIL": [
        ("store_name", "Store Name"),
        ("store_location", "Store Location"),
        ("price", "Retail Price"),
        ("stock_quantity", "Stock Quantity"),
        ("arrival_date", "Arrival Date"),
        ("shelf_life", "Shelf Life"),
        ("retailer_id", "Retailer ID"),
    ],
}


def _sorted_transports(product):
    return sorted(
        list(product.transport_data or []),
        key=lambda t: (
            t.timestamp.replace(tzinfo=timezone.utc) if (t.timestamp and t.timestamp.tzinfo is None) else (t.timestamp or utcnow()),
            t.id or 0,
        ),
    )


def _format_proof_timestamp(dt_val, fallback_str=None):
    if dt_val is not None:
        if dt_val.tzinfo is None:
            dt_utc = dt_val.replace(tzinfo=timezone.utc)
        else:
            dt_utc = dt_val.astimezone(timezone.utc)
        return dt_utc.strftime("%Y-%m-%d %H:%M UTC")
    if fallback_str:
        return str(fallback_str)
    return "Timestamp unavailable"


def _build_harvest_snapshot_payload(product):
    return {
        "batch_id": str(product.batch_id),
        "farmer_id": int(product.farmer_id),
        "farming_method": str(product.farming_method),
        "image": str(product.image),
        "name": str(product.name),
        "packaging_date": str(product.packaging_date),
        "quantity": str(product.quantity),
    }


def _build_transport_snapshot_payload(product, transport_record):
    return {
        "batch_id": str(product.batch_id),
        "current_location": str(transport_record.current_location or ""),
        "notes": str(transport_record.notes or ""),
        "stage": "TRANSPORT",
        "status": str(transport_record.status or ""),
        "temperature": str(transport_record.temperature or ""),
        "transporter_id": int(transport_record.transporter_id),
        "vehicle_number": str(transport_record.vehicle_number or ""),
    }


def _build_retail_snapshot_payload(product, retail_record):
    norm_price = f"{float(retail_record.price):.2f}" if retail_record.price is not None else "0.00"
    return {
        "arrival_date": str(retail_record.arrival_date or ""),
        "batch_id": str(product.batch_id),
        "price": norm_price,
        "retailer_id": int(retail_record.retailer_id),
        "shelf_life": str(retail_record.shelf_life or ""),
        "stage": "RETAIL",
        "stock_quantity": str(retail_record.stock_quantity or ""),
        "store_location": str(retail_record.store_location or ""),
        "store_name": str(retail_record.store_name or ""),
    }


def _compute_hash_from_snapshot(stage, payload_dict):
    if not isinstance(payload_dict, dict):
        return None
    try:
        if stage == "HARVEST":
            return compute_batch_hash(
                batch_id=payload_dict["batch_id"],
                name=payload_dict["name"],
                quantity=payload_dict["quantity"],
                farming_method=payload_dict["farming_method"],
                packaging_date=payload_dict["packaging_date"],
                farmer_id=payload_dict["farmer_id"],
                image=payload_dict["image"],
            )
        if stage == "TRANSPORT":
            return compute_transport_hash(
                batch_id=payload_dict["batch_id"],
                status=payload_dict.get("status", ""),
                current_location=payload_dict.get("current_location", ""),
                temperature=payload_dict.get("temperature", ""),
                vehicle_number=payload_dict.get("vehicle_number", ""),
                notes=payload_dict.get("notes", ""),
                transporter_id=payload_dict["transporter_id"],
            )
        if stage == "RETAIL":
            return compute_retail_hash(
                batch_id=payload_dict["batch_id"],
                store_name=payload_dict.get("store_name", ""),
                store_location=payload_dict.get("store_location", ""),
                price=payload_dict.get("price", "0.00"),
                stock_quantity=payload_dict.get("stock_quantity", ""),
                arrival_date=payload_dict.get("arrival_date", ""),
                shelf_life=payload_dict.get("shelf_life", ""),
                retailer_id=payload_dict["retailer_id"],
            )
    except (KeyError, TypeError, ValueError):
        return None
    return None


def _save_stage_snapshot_once(product_id, stage, payload_dict, original_hash, transport_id=None):
    """
    Persists the original hashed stage payload strictly once at initial anchoring.
    Never overwrites existing immutable snapshots.
    """
    if stage == "HARVEST":
        existing = StageSnapshot.query.filter_by(product_id=product_id, stage="HARVEST").first()
        if existing:
            return existing
    elif stage == "TRANSPORT":
        existing = StageSnapshot.query.filter_by(
            product_id=product_id,
            stage="TRANSPORT",
            transport_id=transport_id,
        ).first()
        if existing:
            return existing
    elif stage == "RETAIL":
        existing = StageSnapshot.query.filter_by(
            product_id=product_id,
            stage="RETAIL",
            original_hash=str(original_hash),
        ).first()
        if existing:
            return existing

    snap = StageSnapshot(
        product_id=product_id,
        stage=stage,
        transport_id=transport_id,
        original_hash=str(original_hash),
        snapshot_json=json.dumps(payload_dict, sort_keys=True),
    )
    db.session.add(snap)
    return snap


def _load_validated_snapshot(product, stage, original_blockchain_hash, transport_record=None):
    """
    Loads the stored StageSnapshot and validates it by recomputing the stage SHA-256 hash
    and requiring it to match the actual blockchain hash.
    Returns (snapshot_dict | None, snapshot_available: bool, snapshot_valid: bool, note: str | None).
    """
    if not original_blockchain_hash:
        return None, False, False, "Blockchain record hash is unavailable to validate the original snapshot."

    target_hash_low = str(original_blockchain_hash).strip().lower()
    if stage == "HARVEST":
        candidates = (
            StageSnapshot.query.filter_by(product_id=product.id, stage="HARVEST")
            .order_by(StageSnapshot.id.asc())
            .all()
        )
    elif stage == "TRANSPORT":
        if not transport_record or not transport_record.id:
            candidates = []
        else:
            candidates = (
                StageSnapshot.query.filter_by(
                    product_id=product.id,
                    stage="TRANSPORT",
                    transport_id=transport_record.id,
                )
                .order_by(StageSnapshot.id.asc())
                .all()
            )
    elif stage == "RETAIL":
        all_retail_snaps = (
            StageSnapshot.query.filter_by(product_id=product.id, stage="RETAIL")
            .order_by(StageSnapshot.id.desc())
            .all()
        )
        exact = [s for s in all_retail_snaps if (s.original_hash or "").strip().lower() == target_hash_low]
        candidates = exact if exact else all_retail_snaps
    else:
        candidates = []

    if not candidates:
        return (
            None,
            False,
            False,
            "Original field values snapshot is not available for this historical record.",
        )

    snap = candidates[0]
    try:
        parsed = json.loads(snap.snapshot_json)
    except (TypeError, ValueError):
        return (
            None,
            True,
            False,
            "Stored original snapshot could not be parsed and failed cryptographic validation.",
        )

    recomputed = _compute_hash_from_snapshot(stage, parsed)
    if not recomputed or recomputed.lower() != target_hash_low:
        return (
            None,
            True,
            False,
            "Stored original snapshot did not match the blockchain hash and was rejected.",
        )

    return parsed, True, True, None


def _compute_changed_fields(stage, validated_snapshot_dict, current_payload_dict):
    """Compares every hashed field between the validated original snapshot and current database row."""
    if not validated_snapshot_dict or not current_payload_dict:
        return []
    diffs = []
    for field_key, label in _STAGE_DIFF_FIELDS.get(stage, []):
        orig_raw = validated_snapshot_dict.get(field_key, "")
        curr_raw = current_payload_dict.get(field_key, "")
        orig_str = "" if orig_raw is None else str(orig_raw)
        curr_str = "" if curr_raw is None else str(curr_raw)
        if orig_str != curr_str:
            is_demo_marker = (" (Tampered)" in curr_str) or ("(Simulated Tamper)" in curr_str)
            clean_mod = curr_str.replace(" (Tampered)", "").replace(" (Simulated Tamper)", "")
            diffs.append({
                "field": field_key,
                "label": label,
                "original": orig_str,
                "modified": curr_str,
                "clean_modified": clean_mod,
                "is_demo_marker": is_demo_marker,
            })
    return diffs


# ═══════════════════════════════════════════════════════════════════
# SHARED SUPPLY-CHAIN SERVICE HELPERS (USED BY DASHBOARDS & WORKFLOW)
# ═══════════════════════════════════════════════════════════════════

def _register_harvest_batch(user, form_data, image_file):
    """
    Shared handler for Stage 2 / Farmer harvest registration.
    Returns (product, error_msg).
    """
    name = form_data.get('name', '').strip()
    quantity = form_data.get('quantity', '').strip()
    farming_method = form_data.get('farming_method', '').strip()
    packaging_date = form_data.get('packaging_date', '').strip()
    farm_location = form_data.get('farm_location', '').strip()
    certifications = form_data.get('certifications', '').strip()

    if not name or not quantity or not farming_method or not packaging_date:
        return None, 'Please fill in all required product fields.'

    if len(name) > 120 or len(quantity) > 50 or len(farming_method) > 100:
        return None, 'Input field exceeds allowed character limit.'

    if len(farm_location) > 150 or len(certifications) > 200:
        return None, 'Location or certifications details exceed character limit.'

    batch_id = f"TH-{uuid.uuid4().hex[:8].upper()}"

    # Guard against unlikely collision on-chain
    existing_chain = fetch_on_chain_status(batch_id)
    if existing_chain.get("status") == "ok":
        return None, f'Batch ID collision on blockchain for {batch_id}. Please resubmit.'

    image_filename = 'default.jpg'
    image_preset = (form_data.get('image_preset') or '').strip()
    if image_preset in ALLOWED_STATIC_IMAGE_NAMES:
        image_filename = image_preset

    if allow_image_uploads() and image_file and image_file.filename:
        is_valid, err_msg = validate_image_file(image_file, ALLOWED_EXTENSIONS)
        if not is_valid:
            return None, f'Upload rejected: {err_msg}'
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)
        ext = secure_filename(image_file.filename).rsplit('.', 1)[1].lower()
        image_filename = f"{batch_id}.{ext}"
        image_file.save(os.path.join(UPLOAD_FOLDER, image_filename))

    # QR codes are generated dynamically in-memory via /qr/<batch_id>.png
    qr_filename = f"qr_{batch_id}.png"

    product_hash = compute_batch_hash(
        batch_id=batch_id,
        name=name,
        quantity=quantity,
        farming_method=farming_method,
        packaging_date=packaging_date,
        farmer_id=user.id,
        image=image_filename
    )

    try:
        receipt_meta = store_hash_detailed(batch_id, product_hash, role="farmer")
        logger.info("Batch %s hash stored on blockchain: %s", batch_id, product_hash)
    except Exception as e:
        safe_err = sanitize_error_text(str(e))
        logger.error("Blockchain error storing batch %s: %s", batch_id, safe_err)
        return None, f'Unable to record harvest on verification network right now ({safe_err}).'

    product = Product(
        batch_id=batch_id,
        name=name,
        quantity=quantity,
        farming_method=farming_method,
        packaging_date=packaging_date,
        farmer_id=user.id,
        image=image_filename,
        qr_code=qr_filename,
        on_chain_hash=product_hash,
        tx_hash=receipt_meta.get("tx_hash"),
        block_number=receipt_meta.get("block_number"),
        contract_address=receipt_meta.get("contract_address"),
        contract_version=receipt_meta.get("contract_version", "V2"),
        signer_address=receipt_meta.get("signer_address"),
        status='Harvested'
    )
    db.session.add(product)
    db.session.flush()

    farmer_data = FarmerData(
        product_id=product.id,
        farm_name=user.username,
        farm_location=farm_location,
        harvest_date=packaging_date,
        certifications=certifications,
        notes=f"Harvested and packed by {user.username}"
    )
    db.session.add(farmer_data)

    _save_stage_snapshot_once(
        product.id,
        "HARVEST",
        _build_harvest_snapshot_payload(product),
        product_hash,
    )

    try:
        db.session.commit()
    except Exception as db_err:
        db.session.rollback()
        logger.error("CRITICAL DESYNC: Batch %s sealed on blockchain (tx: %s), but SQLite commit failed: %s", batch_id, receipt_meta.get("tx_hash"), db_err)
        return None, (
            f'CRITICAL: Batch {batch_id} was successfully sealed on the Ethereum blockchain, '
            f'but saving to local database failed ({str(db_err)}).'
        )

    return product, None


def _record_transport_checkpoint(user, product, form_data):
    """
    Shared handler for Stage 3 / Transporter logistics checkpoint.
    Computes SHA-256 hash of checkpoint telemetry and anchors it onto TrustHarvestV2
    when Ethereum node and V2 batch registration are active.
    """
    status = form_data.get('status', '').strip()
    current_location = form_data.get('current_location', '').strip()
    temperature = form_data.get('temperature', '').strip()
    vehicle_number = form_data.get('vehicle_number', '').strip()
    notes = form_data.get('notes', '').strip()

    if not status or not current_location:
        return None, None, 'Please fill in required logistics checkpoint fields.'

    if len(current_location) > 150 or len(temperature) > 50 or len(vehicle_number) > 50 or len(notes) > 2000:
        return None, None, 'Logistics field exceeds maximum character length.'

    stage_hash = compute_transport_hash(
        batch_id=product.batch_id,
        status=status,
        current_location=current_location,
        temperature=temperature,
        vehicle_number=vehicle_number,
        notes=notes,
        transporter_id=user.id,
    )

    anchor_result = store_stage_hash(
        product.batch_id,
        "TRANSPORT",
        stage_hash,
        role="transporter",
        contract_address=product.contract_address,
    )

    is_anchored = (anchor_result.get("status") == "anchored")
    transport_record = TransportData(
        product_id=product.id,
        transporter_id=user.id,
        status=status,
        current_location=current_location,
        temperature=temperature,
        vehicle_number=vehicle_number,
        notes=notes,
        on_chain_hash=stage_hash if is_anchored else None,
        tx_hash=anchor_result.get("tx_hash") if is_anchored else None,
        block_number=anchor_result.get("block_number") if is_anchored else None,
        signer_address=anchor_result.get("signer_address") if is_anchored else None,
    )
    product.status = status
    db.session.add(transport_record)
    db.session.flush()

    if is_anchored:
        _save_stage_snapshot_once(
            product.id,
            "TRANSPORT",
            _build_transport_snapshot_payload(product, transport_record),
            stage_hash,
            transport_id=transport_record.id,
        )

    try:
        db.session.commit()
    except Exception as db_err:
        db.session.rollback()
        logger.error("Failed saving transport checkpoint for batch %s: %s", product.batch_id, db_err)
        return None, anchor_result, f'Unable to save transport checkpoint to database ({str(db_err)}).'

    return transport_record, anchor_result, None


def _record_retail_listing(user, product, form_data, require_price_stock=False):
    """
    Shared handler for Stage 4 / Retailer store & pricing entry.
    Computes SHA-256 hash of retail fields and anchors onto TrustHarvestV2 when active.
    """
    store_name = form_data.get('store_name', '').strip()
    store_location = form_data.get('store_location', '').strip()
    price_val = form_data.get('price')
    stock_quantity = form_data.get('stock_quantity', '').strip()
    arrival_date = form_data.get('arrival_date', '').strip()
    shelf_life = form_data.get('shelf_life', '').strip()

    if require_price_stock:
        if not store_name or not store_location or not price_val or not stock_quantity:
            return None, None, 'Please provide required store name, location, price, and stock quantity.'
    else:
        if not store_name or not store_location:
            return None, None, 'Please provide required store details.'

    if len(store_name) > 120 or len(store_location) > 150 or len(stock_quantity) > 50 or len(shelf_life) > 50:
        return None, None, 'Input field exceeds allowed character length.'

    parsed_price = 0.0
    if price_val:
        try:
            parsed_price = float(price_val)
            if parsed_price < 0:
                return None, None, 'Price must be a positive value.'
        except ValueError:
            return None, None, 'Invalid numeric format for retail price.'

    retail_hash = compute_retail_hash(
        batch_id=product.batch_id,
        store_name=store_name,
        store_location=store_location,
        price=parsed_price,
        stock_quantity=stock_quantity,
        arrival_date=arrival_date,
        shelf_life=shelf_life,
        retailer_id=user.id,
    )

    anchor_result = store_stage_hash(
        product.batch_id,
        "RETAIL",
        retail_hash,
        role="retailer",
        contract_address=product.contract_address,
    )

    is_anchored = (anchor_result.get("status") == "anchored")
    retail_entry = RetailData.query.filter_by(product_id=product.id).first()
    if not retail_entry:
        retail_entry = RetailData(product_id=product.id, retailer_id=user.id)
        db.session.add(retail_entry)

    retail_entry.retailer_id = user.id
    retail_entry.store_name = store_name
    retail_entry.store_location = store_location
    retail_entry.price = parsed_price
    retail_entry.stock_quantity = stock_quantity
    retail_entry.arrival_date = arrival_date
    retail_entry.shelf_life = shelf_life
    retail_entry.on_chain_hash = retail_hash if is_anchored else None
    if is_anchored:
        retail_entry.tx_hash = anchor_result.get("tx_hash")
        retail_entry.block_number = anchor_result.get("block_number")
        retail_entry.signer_address = anchor_result.get("signer_address")

    product.status = 'In Stock'
    db.session.flush()

    if is_anchored:
        _save_stage_snapshot_once(
            product.id,
            "RETAIL",
            _build_retail_snapshot_payload(product, retail_entry),
            retail_hash,
        )

    try:
        db.session.commit()
    except Exception as db_err:
        db.session.rollback()
        logger.error("Failed saving retail listing for batch %s: %s", product.batch_id, db_err)
        return None, anchor_result, f'Unable to save retail listing to database ({str(db_err)}).'

    return retail_entry, anchor_result, None


# ═══════════════════════════════════════════════════════════════════
# GUIDED SEQUENTIAL SUPPLY-CHAIN WORKFLOW CONTROLLER & HANDLERS
# ═══════════════════════════════════════════════════════════════════

@app.route('/workflow')
def workflow_entry():
    if 'user_id' not in session:
        flash('Please sign in with your stakeholder account to access the guided supply-chain workflow.', 'info')
        return redirect(url_for('login', next=request.full_path if request.query_string else request.path))

    user = db.session.get(User, session['user_id'])
    if not user:
        session.clear()
        flash('Session invalid. Please log in again.', 'warning')
        return redirect(url_for('login', next=request.path))

    batch_id = request.args.get('batch_id', '').strip()
    stage = request.args.get('stage', '').strip().lower()

    product = None
    if batch_id:
        product = Product.query.filter_by(batch_id=batch_id).first()
        if not product:
            flash(f'Batch ID "{batch_id}" not found in database.', 'warning')
            batch_id = ''

    start_new = request.args.get('new') == '1'
    if not product and not start_new:
        latest = Product.query.order_by(Product.created_at.desc()).first()
        if latest:
            product = latest
            batch_id = product.batch_id

    if product and not stage:
        if user.role == 'farmer':
            stage = 'harvest'
        elif user.role == 'transporter':
            stage = 'transport'
        elif user.role == 'retailer':
            stage = 'retail'
        elif not product.transport_data:
            stage = 'transport'
        elif not product.retail_data:
            stage = 'retail'
        else:
            stage = 'harvest'

    if not stage:
        stage = 'harvest'

    step_map = {'harvest': 2, 'transport': 3, 'retail': 4}
    current_step = step_map.get(stage, 2)

    required_role = None
    handover_needed = False
    if stage == 'harvest':
        required_role = 'farmer'
        if user.role not in ('farmer', 'admin'):
            handover_needed = True
    elif stage == 'transport':
        required_role = 'transporter'
        if user.role not in ('transporter', 'admin'):
            handover_needed = True
    elif stage == 'retail':
        required_role = 'retailer'
        if user.role not in ('retailer', 'admin'):
            handover_needed = True

    registered_role_users = []
    if handover_needed and required_role:
        registered_role_users = User.query.filter_by(role=required_role).all()

    existing_batches = Product.query.order_by(Product.created_at.desc()).limit(8).all()
    today_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')

    return render_template(
        'workflow.html',
        stage=stage,
        current_step=current_step,
        batch_id=batch_id,
        product=product,
        user=user,
        handover_needed=handover_needed,
        required_role=required_role,
        registered_role_users=registered_role_users,
        existing_batches=existing_batches,
        today_str=today_str,
    )


@app.route('/workflow/harvest', methods=['POST'])
def workflow_harvest():
    if 'user_id' not in session:
        flash('Please sign in to register a harvest batch.', 'warning')
        return redirect(url_for('login', next=url_for('workflow_entry', stage='harvest')))

    user = db.session.get(User, session['user_id'])
    if not user or user.role not in ('farmer', 'admin'):
        flash('Access denied: Harvest registration requires Farmer authorization.', 'danger')
        return redirect(url_for('workflow_entry', stage='harvest'))

    if not request.form.get('farm_location', '').strip():
        flash('Please fill in all required harvest fields (Produce Name, Quantity, Farming Method, Date, Farm Location).', 'danger')
        return redirect(url_for('workflow_entry', stage='harvest'))

    product, err = _register_harvest_batch(user, request.form, request.files.get('image'))
    if err:
        flash(err, 'danger')
        return redirect(url_for('workflow_entry', stage='harvest'))

    flash(f'Farm harvest recorded and sealed for batch {product.batch_id}!', 'success')
    return redirect(url_for('workflow_entry', stage='transport', batch_id=product.batch_id))


@app.route('/workflow/transport', methods=['POST'])
def workflow_transport():
    if 'user_id' not in session:
        flash('Please sign in to record logistics checkpoints.', 'warning')
        return redirect(url_for('login', next=request.referrer or url_for('workflow_entry')))

    user = db.session.get(User, session['user_id'])
    batch_id = request.form.get('batch_id', '').strip()
    if not user or user.role not in ('transporter', 'admin'):
        flash('Access denied: Logistics checkpoints require Transporter authorization.', 'danger')
        return redirect(url_for('workflow_entry', stage='transport', batch_id=batch_id))

    if not batch_id:
        flash('Batch ID is missing from transport submission.', 'danger')
        return redirect(url_for('workflow_entry', stage='harvest'))

    if not request.form.get('vehicle_number', '').strip():
        flash('Please fill in required logistics checkpoint fields (status, facility/location, vehicle ID).', 'danger')
        return redirect(url_for('workflow_entry', stage='transport', batch_id=batch_id))

    product = Product.query.filter_by(batch_id=batch_id).first_or_404()
    _, _, err = _record_transport_checkpoint(user, product, request.form)
    if err:
        flash(err, 'danger')
        return redirect(url_for('workflow_entry', stage='transport', batch_id=batch_id))

    flash(f'Transport checkpoint recorded ("{product.status}") for batch {product.batch_id}.', 'success')
    if request.form.get('stay_on_transport') == '1':
        return redirect(url_for('workflow_entry', stage='transport', batch_id=product.batch_id))
    return redirect(url_for('workflow_entry', stage='retail', batch_id=product.batch_id))


@app.route('/workflow/retail', methods=['POST'])
def workflow_retail():
    if 'user_id' not in session:
        flash('Please sign in to update retail listing.', 'warning')
        return redirect(url_for('login', next=request.referrer or url_for('workflow_entry')))

    user = db.session.get(User, session['user_id'])
    batch_id = request.form.get('batch_id', '').strip()
    if not user or user.role not in ('retailer', 'admin'):
        flash('Access denied: Retail listings require Retailer authorization.', 'danger')
        return redirect(url_for('workflow_entry', stage='retail', batch_id=batch_id))

    if not batch_id:
        flash('Batch ID is missing from retail submission.', 'danger')
        return redirect(url_for('workflow_entry', stage='harvest'))

    product = Product.query.filter_by(batch_id=batch_id).first_or_404()
    _, _, err = _record_retail_listing(user, product, request.form, require_price_stock=True)
    if err:
        flash(err, 'danger')
        return redirect(url_for('workflow_entry', stage='retail', batch_id=batch_id))

    flash(f'Retail listing recorded for batch {product.batch_id}. Full journey completed!', 'success')
    return redirect(url_for('verify_batch', batch_id=product.batch_id, from_workflow=1))


# ═══════════════════════════════════════════════════════════════════
# STAKEHOLDER DASHBOARDS
# ═══════════════════════════════════════════════════════════════════

@app.route('/farmer')
@role_required('farmer')
def farmer_dashboard():
    farmer_id = session['user_id']
    products = Product.query.filter_by(farmer_id=farmer_id).order_by(Product.created_at.desc()).all()
    today_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    return render_template('farmer.html', products=products, today_str=today_str)

@app.route('/farmer/add_product', methods=['POST'])
@role_required('farmer')
def add_product():
    user = db.session.get(User, session['user_id'])
    product, err = _register_harvest_batch(user, request.form, request.files.get('image'))
    if err:
        flash(err, 'danger')
        return redirect(url_for('farmer_dashboard'))

    flash(f'Batch {product.batch_id} registered and hashed onto blockchain successfully!', 'success')
    return redirect(url_for('farmer_dashboard'))

@app.route('/transporter')
@role_required('transporter')
def transporter_dashboard():
    products = Product.query.order_by(Product.created_at.desc()).all()
    transport_entries = TransportData.query.filter_by(transporter_id=session['user_id']).order_by(TransportData.timestamp.desc()).all()
    return render_template('transporter.html', products=products, transport_entries=transport_entries)

@app.route('/transporter/add', methods=['POST'])
@role_required('transporter')
def add_transport_data():
    product_id = request.form.get('product_id')
    if not product_id:
        flash('Please fill in required logistics checkpoint fields.', 'danger')
        return redirect(url_for('transporter_dashboard'))

    product = db.get_or_404(Product, product_id)
    user = db.session.get(User, session['user_id'])
    _, _, err = _record_transport_checkpoint(user, product, request.form)
    if err:
        flash(err, 'danger')
        return redirect(url_for('transporter_dashboard'))

    flash(f'Transport checkpoint recorded for batch {product.batch_id}.', 'success')
    return redirect(url_for('transporter_dashboard'))

@app.route('/retailer')
@role_required('retailer')
def retailer_dashboard():
    products = Product.query.order_by(Product.created_at.desc()).all()
    retail_entries = RetailData.query.filter_by(retailer_id=session['user_id']).all()
    today_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    return render_template('retailer.html', products=products, retail_entries=retail_entries, today_str=today_str)

@app.route('/retailer/add', methods=['POST'])
@role_required('retailer')
def add_retail_data():
    product_id = request.form.get('product_id')
    if not product_id:
        flash('Please provide required store details.', 'danger')
        return redirect(url_for('retailer_dashboard'))

    product = db.get_or_404(Product, product_id)
    user = db.session.get(User, session['user_id'])
    _, _, err = _record_retail_listing(user, product, request.form, require_price_stock=False)
    if err:
        flash(err, 'danger')
        return redirect(url_for('retailer_dashboard'))

    flash(f'Retail stock and price details updated for batch {product.batch_id}.', 'success')
    return redirect(url_for('retailer_dashboard'))

@app.route('/customer')
def customer_dashboard():
    search_batch = request.args.get('batch_id', '').strip()
    if search_batch:
        product = Product.query.filter_by(batch_id=search_batch).first()
        if product:
            return redirect(url_for('verify_batch', batch_id=search_batch))
        else:
            flash(f'Batch ID "{search_batch}" not found.', 'warning')
    products = Product.query.order_by(Product.created_at.desc()).all()
    batch_statuses = {}
    for p in products:
        vctx = _build_verification_context(p, simulate_tamper=False)
        latest_tv = vctx["transport_verifications"][-1] if vctx["transport_verifications"] else None
        batch_statuses[p.batch_id] = {
            "status": vctx["verification_status"],
            "label": vctx["result_label"],
            "reason": vctx["result_reason"],
            "pending": vctx["has_pending_stages"],
            "latest_temp": latest_tv["temp_eval"] if latest_tv else None,
        }
    return render_template('customer.html', products=products, batch_statuses=batch_statuses)


# ═══════════════════════════════════════════════════════════════════
# MULTI-STAGE VERIFICATION HELPER & ROUTES
# ═══════════════════════════════════════════════════════════════════

def _build_verification_context(product, simulate_tamper=False):
    simulated_field = None
    original_value = None
    tampered_value = None
    if simulate_tamper:
        simulated_field = "Farming Method"
        original_value = product.farming_method
        tampered_value = "Chemically Treated (Simulated Tamper)"
        farming_method_for_hash = tampered_value
    else:
        farming_method_for_hash = product.farming_method

    computed_hash = compute_batch_hash(
        batch_id=product.batch_id,
        name=product.name,
        quantity=product.quantity,
        farming_method=farming_method_for_hash,
        packaging_date=product.packaging_date,
        farmer_id=product.farmer_id,
        image=product.image
    )

    chain = inspect_batch_on_chain(
        product.batch_id,
        recorded_contract_address=product.contract_address,
        recorded_contract_version=product.contract_version,
    )
    chain_status = chain.get("status")
    on_chain_hash = chain.get("hash")
    contract_source_addr = chain.get("contract_address")
    resolved_version = chain.get("contract_version") or product.contract_version
    conflict_details = chain.get("conflict_details")
    expected_signers = chain.get("expected_signers")
    v2_stages = chain.get("stages") or []

    db_transports = _sorted_transports(product)
    transport_chain_stages = [s for s in v2_stages if s["stage"] == "TRANSPORT"]
    retail_chain_stages = [s for s in v2_stages if s["stage"] == "RETAIL"]

    transport_verifications = []
    has_temp_breach = False
    transport_verified_count = 0
    transport_tampered = False
    retail_verification = None
    retail_verified = False
    retail_tampered = False

    tampered_stage_names = []
    cannot_verify_reasons = []

    h_changed_fields = []
    h_snap_avail = False
    h_snap_valid = False
    h_snap_note = None
    h_orig_hash_for_proof = on_chain_hash if chain_status == "ok" else None

    if chain_status == "rpc_offline":
        harvest_status = "rpc_offline"
        harvest_explanation = "The verification network is unreachable right now."
        cannot_verify_reasons.append(harvest_explanation)
        for idx, t in enumerate(db_transports):
            t_computed = compute_transport_hash(
                batch_id=product.batch_id,
                status=t.status,
                current_location=t.current_location,
                temperature=t.temperature,
                vehicle_number=t.vehicle_number,
                notes=t.notes,
                transporter_id=t.transporter_id,
            )
            temp_eval = evaluate_temperature(t.temperature)
            if temp_eval.get("status") == "breach":
                has_temp_breach = True
            transport_verifications.append({
                "record": t,
                "computed_hash": t_computed,
                "on_chain_hash": None,
                "status": "rpc_offline",
                "temp_eval": temp_eval,
                "recorded_by": t.signer_address,
                "on_chain_timestamp": None,
                "stage": "TRANSPORT",
                "checkpoint_number": idx + 1,
                "original_hash": None,
                "recomputed_hash": t_computed,
                "stage_status": "cannot_verify",
                "hashes_match": False,
                "snapshot_available": False,
                "snapshot_valid": False,
                "snapshot_note": None,
                "changed_fields": [],
                "explanation": "Blockchain network is offline; original on-chain hash could not be fetched.",
            })
        if product.retail_data:
            r = product.retail_data
            r_computed = compute_retail_hash(
                batch_id=product.batch_id,
                store_name=r.store_name,
                store_location=r.store_location,
                price=r.price,
                stock_quantity=r.stock_quantity,
                arrival_date=r.arrival_date,
                shelf_life=r.shelf_life,
                retailer_id=r.retailer_id,
            )
            retail_verification = {
                "record": r,
                "computed_hash": r_computed,
                "on_chain_hash": None,
                "status": "rpc_offline",
                "recorded_by": r.signer_address,
                "on_chain_timestamp": None,
                "stage": "RETAIL",
                "stage_number": 3,
                "title": "Retailer / Store",
                "original_hash": None,
                "recomputed_hash": r_computed,
                "stage_status": "cannot_verify",
                "hashes_match": False,
                "snapshot_available": False,
                "snapshot_valid": False,
                "snapshot_note": None,
                "changed_fields": [],
                "explanation": "Blockchain network is offline; original on-chain hash could not be fetched.",
            }
    elif chain_status == "not_found":
        harvest_status = "not_found"
        harvest_explanation = "This batch has not been recorded on the blockchain yet."
        cannot_verify_reasons.append(harvest_explanation)
    elif chain_status == "conflict":
        harvest_status = "conflict"
        harvest_explanation = "Conflicting records were found on the blockchain for this batch."
        cannot_verify_reasons.append(harvest_explanation)
    elif chain_status == "error":
        harvest_status = "error"
        harvest_explanation = "Unable to read the blockchain record cleanly right now."
        cannot_verify_reasons.append(harvest_explanation)
    else:
        # chain_status == "ok" -> Harvest record exists on-chain
        if chain.get("truncated"):
            cannot_verify_reasons.append("Too many blockchain entries exist for this batch to verify safely.")

        if on_chain_hash and computed_hash.lower() == str(on_chain_hash).lower():
            # Hash matches; check V2 farmer signer allowlist if available
            reg_by = (chain.get("registered_by") or "").lower()
            allowed_farmers = (expected_signers or {}).get("farmer") or set()
            if resolved_version == "V2" and allowed_farmers and reg_by and reg_by not in allowed_farmers:
                harvest_status = "conflict"
                harvest_explanation = "The farm harvest record on-chain was signed by an unexpected account."
                cannot_verify_reasons.append(harvest_explanation)
            else:
                harvest_status = "verified"
                harvest_explanation = "Recomputed SHA-256 hash matches the immutable farm harvest hash on-chain."
        else:
            harvest_status = "tampered"
            harvest_explanation = "Farm harvest data in the database no longer produces the sealed blockchain hash."
            tampered_stage_names.append("Farm harvest")
            if simulate_tamper:
                h_snap_avail = True
                h_snap_valid = True
                h_changed_fields = [{
                    "field": "farming_method",
                    "label": "Farming Method",
                    "original": str(original_value or ""),
                    "modified": str(tampered_value or ""),
                    "clean_modified": str(tampered_value or "").replace(" (Simulated Tamper)", ""),
                    "is_demo_marker": True,
                }]
            else:
                h_snap_dict, h_snap_avail, h_snap_valid, h_snap_note = _load_validated_snapshot(
                    product,
                    "HARVEST",
                    on_chain_hash,
                )
                if h_snap_valid and h_snap_dict:
                    h_changed_fields = _compute_changed_fields(
                        "HARVEST",
                        h_snap_dict,
                        _build_harvest_snapshot_payload(product),
                    )

        # Validate stage history (V2 vs V1)
        unknown_stages = [s for s in v2_stages if s["stage"] not in ("TRANSPORT", "RETAIL")]
        if unknown_stages:
            cannot_verify_reasons.append("An unrecognized stage entry exists on the blockchain for this batch.")

        # Transport checkpoints (chronological)
        db_transport_hashes = []
        for t in db_transports:
            t_computed = compute_transport_hash(
                batch_id=product.batch_id,
                status=t.status,
                current_location=t.current_location,
                temperature=t.temperature,
                vehicle_number=t.vehicle_number,
                notes=t.notes,
                transporter_id=t.transporter_id,
            )
            db_transport_hashes.append(t_computed.lower())

        allowed_transporters = (expected_signers or {}).get("transporter") or set()
        if resolved_version == "V2":
            for s_idx, s in enumerate(transport_chain_stages):
                rec_by = (s.get("recorded_by") or "").lower()
                if allowed_transporters and rec_by and rec_by not in allowed_transporters:
                    cannot_verify_reasons.append(f"Transport entry #{s_idx + 1} on-chain was signed by an unexpected account.")

            if len(transport_chain_stages) > len(db_transports):
                cannot_verify_reasons.append("Extra transport records exist on the blockchain that are missing locally.")

        onchain_transport_hashes = {s["hash"].lower() for s in transport_chain_stages if s.get("hash")}

        for idx, t in enumerate(db_transports):
            t_computed = db_transport_hashes[idx]
            temp_eval = evaluate_temperature(t.temperature)
            if temp_eval.get("status") == "breach":
                has_temp_breach = True

            t_changed_fields = []
            t_snap_avail = False
            t_snap_valid = False
            t_snap_note = None
            t_explanation = ""

            if resolved_version == "V1":
                t_status = "unrecorded"
                c_hash = None
                recorded_by = t.signer_address
                on_chain_ts = None
                t_explanation = f"Transport checkpoint #{idx + 1} was recorded on a V1 contract without stage anchoring."
                cannot_verify_reasons.append(f"Transport checkpoint #{idx + 1} exists locally but was recorded on a V1 contract without stage anchoring.")
            elif len(transport_chain_stages) == 0:
                t_status = "unrecorded"
                c_hash = None
                recorded_by = t.signer_address
                on_chain_ts = None
                t_explanation = f"Transport checkpoint #{idx + 1} has not been recorded on the blockchain yet."
                cannot_verify_reasons.append(t_explanation)
            elif idx < len(transport_chain_stages):
                chain_stage = transport_chain_stages[idx]
                c_hash = chain_stage["hash"]
                rec_by = (chain_stage.get("recorded_by") or "").lower()
                if allowed_transporters and rec_by and rec_by not in allowed_transporters:
                    t_status = "conflict"
                    t_explanation = f"Transport checkpoint #{idx + 1} on-chain was signed by an unexpected account."
                elif c_hash.lower() == t_computed:
                    t_status = "verified"
                    transport_verified_count += 1
                    t_explanation = "Recomputed SHA-256 hash matches the sealed transport checkpoint hash on-chain."
                else:
                    # Distinguish genuine mismatch/order tampering vs unanchored earlier DB row shifting indices
                    if len(transport_chain_stages) < len(db_transports) and c_hash.lower() in db_transport_hashes:
                        if t_computed not in onchain_transport_hashes and not t.tx_hash:
                            t_status = "unrecorded"
                            c_hash = None
                            t_explanation = f"Transport checkpoint #{idx + 1} has not been recorded on the blockchain yet."
                            cannot_verify_reasons.append(t_explanation)
                        else:
                            t_status = "tampered"
                            transport_tampered = True
                            tampered_stage_names.append(f"Transport checkpoint #{idx + 1}")
                            t_explanation = "Database telemetry no longer matches the immutable transport hash on-chain."
                    else:
                        t_status = "tampered"
                        transport_tampered = True
                        tampered_stage_names.append(f"Transport checkpoint #{idx + 1}")
                        t_explanation = "Database telemetry no longer matches the immutable transport hash on-chain."

                    if t_status == "tampered":
                        t_snap_dict, t_snap_avail, t_snap_valid, t_snap_note = _load_validated_snapshot(
                            product,
                            "TRANSPORT",
                            c_hash,
                            transport_record=t,
                        )
                        if t_snap_valid and t_snap_dict:
                            t_changed_fields = _compute_changed_fields(
                                "TRANSPORT",
                                t_snap_dict,
                                _build_transport_snapshot_payload(product, t),
                            )

                recorded_by = chain_stage["recorded_by"]
                on_chain_ts = chain_stage["timestamp"]
            else:
                # Database has a checkpoint that is missing on-chain
                t_status = "unrecorded"
                c_hash = None
                recorded_by = t.signer_address
                on_chain_ts = None
                t_explanation = f"Transport checkpoint #{idx + 1} has not been recorded on the blockchain yet."
                cannot_verify_reasons.append(t_explanation)

            tv_stage_status = (
                "verified" if t_status == "verified"
                else ("tampered" if t_status == "tampered" else "cannot_verify")
            )
            transport_verifications.append({
                "record": t,
                "computed_hash": t_computed,
                "on_chain_hash": c_hash,
                "status": t_status,
                "temp_eval": temp_eval,
                "recorded_by": recorded_by,
                "on_chain_timestamp": on_chain_ts,
                "stage": "TRANSPORT",
                "checkpoint_number": idx + 1,
                "original_hash": c_hash,
                "recomputed_hash": t_computed,
                "stage_status": tv_stage_status,
                "hashes_match": (tv_stage_status == "verified"),
                "snapshot_available": t_snap_avail,
                "snapshot_valid": t_snap_valid,
                "snapshot_note": t_snap_note,
                "changed_fields": t_changed_fields,
                "explanation": t_explanation,
            })

        # Retail stage check
        allowed_retailers = (expected_signers or {}).get("retailer") or set()
        if resolved_version == "V2":
            for s in retail_chain_stages:
                rec_by = (s.get("recorded_by") or "").lower()
                if allowed_retailers and rec_by and rec_by not in allowed_retailers:
                    cannot_verify_reasons.append("The store record on-chain was signed by an unexpected account.")

        if product.retail_data:
            r = product.retail_data
            r_computed = compute_retail_hash(
                batch_id=product.batch_id,
                store_name=r.store_name,
                store_location=r.store_location,
                price=r.price,
                stock_quantity=r.stock_quantity,
                arrival_date=r.arrival_date,
                shelf_life=r.shelf_life,
                retailer_id=r.retailer_id,
            )
            r_changed_fields = []
            r_snap_avail = False
            r_snap_valid = False
            r_snap_note = None
            r_explanation = ""

            if resolved_version == "V1" or not retail_chain_stages:
                r_status = "unrecorded"
                rc_hash = None
                r_recorded_by = r.signer_address
                r_ts = None
                r_explanation = "Store details exist locally but have not been recorded on the blockchain yet."
                cannot_verify_reasons.append(r_explanation)
            else:
                latest_retail_chain = retail_chain_stages[-1]
                rc_hash = latest_retail_chain["hash"]
                rec_by = (latest_retail_chain.get("recorded_by") or "").lower()
                if allowed_retailers and rec_by and rec_by not in allowed_retailers:
                    r_status = "conflict"
                    r_explanation = "The store record on-chain was signed by an unexpected account."
                elif rc_hash.lower() == r_computed.lower():
                    r_status = "verified"
                    retail_verified = True
                    r_explanation = "Recomputed SHA-256 hash matches the immutable retail hash on-chain."
                else:
                    r_status = "tampered"
                    retail_tampered = True
                    tampered_stage_names.append("Retail store listing")
                    r_explanation = "Retail store data in the database no longer matches the immutable hash on-chain."
                    r_snap_dict, r_snap_avail, r_snap_valid, r_snap_note = _load_validated_snapshot(
                        product,
                        "RETAIL",
                        rc_hash,
                    )
                    if r_snap_valid and r_snap_dict:
                        r_changed_fields = _compute_changed_fields(
                            "RETAIL",
                            r_snap_dict,
                            _build_retail_snapshot_payload(product, r),
                        )
                r_recorded_by = latest_retail_chain["recorded_by"]
                r_ts = latest_retail_chain["timestamp"]

            r_stage_status = (
                "verified" if r_status == "verified"
                else ("tampered" if r_status == "tampered" else "cannot_verify")
            )
            retail_verification = {
                "record": r,
                "computed_hash": r_computed,
                "on_chain_hash": rc_hash,
                "status": r_status,
                "recorded_by": r_recorded_by,
                "on_chain_timestamp": r_ts,
                "stage": "RETAIL",
                "stage_number": 3,
                "title": "Retailer / Store",
                "original_hash": rc_hash,
                "recomputed_hash": r_computed,
                "stage_status": r_stage_status,
                "hashes_match": (r_stage_status == "verified"),
                "snapshot_available": r_snap_avail,
                "snapshot_valid": r_snap_valid,
                "snapshot_note": r_snap_note,
                "changed_fields": r_changed_fields,
                "explanation": r_explanation,
            }
        elif resolved_version == "V2" and retail_chain_stages:
            cannot_verify_reasons.append("A store record exists on the blockchain that is missing from local records.")

    # Populate not_found/conflict/error unrecorded stage previews when not already built above
    if chain_status in ("not_found", "conflict", "error"):
        for idx, t in enumerate(db_transports):
            t_computed = compute_transport_hash(
                batch_id=product.batch_id,
                status=t.status,
                current_location=t.current_location,
                temperature=t.temperature,
                vehicle_number=t.vehicle_number,
                notes=t.notes,
                transporter_id=t.transporter_id,
            )
            temp_eval = evaluate_temperature(t.temperature)
            if temp_eval.get("status") == "breach":
                has_temp_breach = True
            transport_verifications.append({
                "record": t,
                "computed_hash": t_computed,
                "on_chain_hash": None,
                "status": "unrecorded",
                "temp_eval": temp_eval,
                "recorded_by": t.signer_address,
                "on_chain_timestamp": None,
                "stage": "TRANSPORT",
                "checkpoint_number": idx + 1,
                "original_hash": None,
                "recomputed_hash": t_computed,
                "stage_status": "cannot_verify",
                "hashes_match": False,
                "snapshot_available": False,
                "snapshot_valid": False,
                "snapshot_note": None,
                "changed_fields": [],
                "explanation": "Batch harvest record is unavailable on-chain, so this checkpoint cannot be verified.",
            })
        if product.retail_data:
            r = product.retail_data
            r_computed = compute_retail_hash(
                batch_id=product.batch_id,
                store_name=r.store_name,
                store_location=r.store_location,
                price=r.price,
                stock_quantity=r.stock_quantity,
                arrival_date=r.arrival_date,
                shelf_life=r.shelf_life,
                retailer_id=r.retailer_id,
            )
            retail_verification = {
                "record": r,
                "computed_hash": r_computed,
                "on_chain_hash": None,
                "status": "unrecorded",
                "recorded_by": r.signer_address,
                "on_chain_timestamp": None,
                "stage": "RETAIL",
                "stage_number": 3,
                "title": "Retailer / Store",
                "original_hash": None,
                "recomputed_hash": r_computed,
                "stage_status": "cannot_verify",
                "hashes_match": False,
                "snapshot_available": False,
                "snapshot_valid": False,
                "snapshot_note": None,
                "changed_fields": [],
                "explanation": "Batch harvest record is unavailable on-chain, so retail data cannot be verified.",
            }

    harvest_stage_status = (
        "verified" if harvest_status == "verified"
        else ("tampered" if harvest_status == "tampered" else "cannot_verify")
    )
    harvest_recorded_when = _format_proof_timestamp(
        chain.get("timestamp") or product.created_at,
        product.packaging_date or None,
    )
    harvest_verification = {
        "stage": "HARVEST",
        "stage_number": 1,
        "title": "Farmer / Harvest",
        "status": harvest_stage_status,
        "raw_status": harvest_status,
        "original_hash": h_orig_hash_for_proof,
        "recomputed_hash": computed_hash,
        "hashes_match": (harvest_stage_status == "verified"),
        "snapshot_available": h_snap_avail,
        "snapshot_valid": h_snap_valid,
        "snapshot_note": h_snap_note,
        "changed_fields": h_changed_fields,
        "explanation": harvest_explanation,
        "recorded_when": harvest_recorded_when,
    }

    tamper_incidents = []
    if harvest_stage_status == "tampered":
        farm_where = (
            product.farmer_data.farm_location
            if (product.farmer_data and product.farmer_data.farm_location)
            else "Registered Farm"
        )
        tamper_incidents.append({
            "stage_key": "HARVEST",
            "stage_label": "Stage 1 — Farm Harvest",
            "status_label": "Farm Origin & Registration",
            "where": farm_where,
            "when": harvest_recorded_when,
            "changed_fields": h_changed_fields,
            "snapshot_note": h_snap_note,
            "anchor_id": "journey-stage-harvest",
        })

    for tv in transport_verifications:
        t_rec = tv["record"]
        tv_when = _format_proof_timestamp(tv.get("on_chain_timestamp") or t_rec.timestamp)
        tv["recorded_when"] = tv_when
        if tv["stage_status"] == "tampered":
            t_loc = t_rec.current_location or "Transit location unavailable"
            t_where = f"{t_loc} (Vehicle {t_rec.vehicle_number})" if t_rec.vehicle_number else t_loc
            tamper_incidents.append({
                "stage_key": "TRANSPORT",
                "stage_label": f"Stage 2 — Transport (Checkpoint #{tv['checkpoint_number']})",
                "status_label": t_rec.status,
                "where": t_where,
                "when": tv_when,
                "changed_fields": tv["changed_fields"],
                "snapshot_note": tv["snapshot_note"],
                "anchor_id": f"journey-stage-transport-{tv['checkpoint_number']}",
            })

    if retail_verification:
        r_rec = retail_verification["record"]
        r_when = _format_proof_timestamp(
            retail_verification.get("on_chain_timestamp") or r_rec.updated_at,
            r_rec.arrival_date or None,
        )
        retail_verification["recorded_when"] = r_when
        if retail_verification["stage_status"] == "tampered":
            if r_rec.store_name and r_rec.store_location:
                r_where = f"{r_rec.store_name} ({r_rec.store_location})"
            else:
                r_where = r_rec.store_location or r_rec.store_name or "Retail Store"
            tamper_incidents.append({
                "stage_key": "RETAIL",
                "stage_label": "Stage 3 — Retail Store",
                "status_label": "Store Listing & Pricing",
                "where": r_where,
                "when": r_when,
                "changed_fields": retail_verification["changed_fields"],
                "snapshot_note": retail_verification["snapshot_note"],
                "anchor_id": "journey-stage-retail",
            })

    extra_transport_on_chain = (
        chain_status == "ok" and resolved_version == "V2" and len(transport_chain_stages) > len(db_transports)
    )
    if transport_verifications:
        if any(tv["stage_status"] == "tampered" for tv in transport_verifications):
            transport_stage_status = "tampered"
        elif any(tv["stage_status"] == "cannot_verify" for tv in transport_verifications) or extra_transport_on_chain:
            transport_stage_status = "cannot_verify"
        else:
            transport_stage_status = "verified"
    elif extra_transport_on_chain:
        transport_stage_status = "cannot_verify"
    else:
        transport_stage_status = "pending"

    extra_retail_on_chain = (
        chain_status == "ok" and resolved_version == "V2" and (product.retail_data is None) and bool(retail_chain_stages)
    )
    if retail_verification:
        retail_stage_status = retail_verification["stage_status"]
    elif extra_retail_on_chain:
        retail_stage_status = "cannot_verify"
    else:
        retail_stage_status = "pending"

    any_stage_tampered = (harvest_status == "tampered") or transport_tampered or retail_tampered
    has_pending_stages = (len(db_transports) == 0) or (product.retail_data is None)

    if any_stage_tampered:
        verification_status = "tampered"
        result_label = "Changed after recording"
        stages_list_str = ", ".join(tampered_stage_names)
        result_reason = f"{stages_list_str} data no longer matches the immutable blockchain record."
    elif cannot_verify_reasons:
        verification_status = "cannot_verify"
        result_label = "Can't check right now"
        result_reason = cannot_verify_reasons[0]
    else:
        verification_status = "verified"
        result_label = "Verified"
        if has_pending_stages:
            result_reason = "All recorded details so far match the blockchain. Remaining journey steps are still pending."
        else:
            result_reason = "All farm, transport, and store details match the blockchain ledger."

    # Build plain, dynamic stage-wise summary for Technical Blockchain Proof banner
    def _stage_word(st):
        if st == "verified":
            return "Verified"
        if st == "tampered":
            return "Tampered"
        if st == "pending":
            return "Pending"
        return "Unable to verify"

    tampered_cp_nums = [str(tv["checkpoint_number"]) for tv in transport_verifications if tv["stage_status"] == "tampered"]
    if transport_stage_status == "tampered" and tampered_cp_nums:
        t_word = f"Tampered (Checkpoint #{', #'.join(tampered_cp_nums)})"
    elif transport_stage_status == "verified" and len(transport_verifications) > 1:
        t_word = f"Verified ({len(transport_verifications)} checkpoints)"
    else:
        t_word = _stage_word(transport_stage_status)

    stage_summary_detail = (
        f"Farmer: {_stage_word(harvest_stage_status)} | "
        f"Transporter: {t_word} | "
        f"Retailer: {_stage_word(retail_stage_status)}"
    )
    if verification_status == "tampered":
        proof_overall_heading = "OVERALL RESULT: TAMPERING DETECTED"
    elif verification_status == "cannot_verify":
        proof_overall_heading = "OVERALL RESULT: UNABLE TO VERIFY ALL STAGES"
    elif has_pending_stages:
        proof_overall_heading = "OVERALL RESULT: RECORDED STAGES VERIFIED (JOURNEY IN PROGRESS)"
    else:
        proof_overall_heading = "OVERALL RESULT: ALL RECORDED STAGES VERIFIED"

    stage_proof_summary = {
        "result_key": verification_status,
        "heading": proof_overall_heading,
        "detail": stage_summary_detail,
        "harvest_status": harvest_stage_status,
        "transport_status": transport_stage_status,
        "retail_status": retail_stage_status,
        "extra_transport_on_chain": extra_transport_on_chain,
        "extra_retail_on_chain": extra_retail_on_chain,
    }

    trust_score = compute_trust_score(
        harvest_verified=(harvest_status == "verified"),
        transport_count=len(db_transports),
        transport_verified_count=transport_verified_count,
        has_retail=bool(product.retail_data),
        retail_verified=retail_verified,
        has_temp_breach=has_temp_breach,
    )

    v2_details = {
        "available": (resolved_version == "V2" and chain_status == "ok"),
        "registered_by": chain.get("registered_by"),
        "timestamp": chain.get("timestamp"),
        "stages": v2_stages,
        "contract_version": resolved_version,
    }

    req_root = request.url_root if request else ""
    config_base_url = resolve_qr_base_url(req_root)
    qr_verify_url = f"{config_base_url}/verify/{product.batch_id}" if config_base_url else f"/verify/{product.batch_id}"

    return {
        "product": product,
        "computed_hash": computed_hash,
        "on_chain_hash": on_chain_hash,
        "contract_source_addr": contract_source_addr or product.contract_address,
        "resolved_contract_version": resolved_version or "Unknown",
        "verification_status": verification_status,
        "result_label": result_label,
        "result_reason": result_reason,
        "harvest_status": harvest_status,
        "harvest_verification": harvest_verification,
        "transport_stage_status": transport_stage_status,
        "retail_stage_status": retail_stage_status,
        "stage_proof_summary": stage_proof_summary,
        "tamper_incidents": tamper_incidents,
        "is_verified": (verification_status == "verified"),
        "is_tampered": (verification_status == "tampered"),
        "is_cannot_verify": (verification_status == "cannot_verify"),
        "is_conflict": (chain_status == "conflict" and not any_stage_tampered),
        "is_rpc_offline": (chain_status == "rpc_offline" and not any_stage_tampered),
        "is_not_found": (chain_status == "not_found" and not any_stage_tampered),
        "conflict_details": conflict_details,
        "config_base_url": config_base_url,
        "qr_verify_url": qr_verify_url,
        "simulate_tamper": simulate_tamper,
        "simulated_field": simulated_field,
        "original_value": original_value,
        "tampered_value": tampered_value,
        "v2_details": v2_details,
        "transport_verifications": transport_verifications,
        "transport_tampered": transport_tampered,
        "retail_verification": retail_verification,
        "retail_tampered": retail_tampered,
        "has_temp_breach": has_temp_breach,
        "has_pending_stages": has_pending_stages,
        "trust_score": trust_score,
    }


@app.route('/qr/<batch_id>.png')
def batch_qr_png(batch_id):
    """Generates and streams the batch QR code PNG dynamically in memory (zero disk storage)."""
    Product.query.filter_by(batch_id=batch_id).first_or_404()
    base_url = resolve_qr_base_url(request.url_root)
    buf = generate_batch_qr_bytes(batch_id, base_url)
    download = request.args.get('download') == '1'
    return send_file(
        buf,
        mimetype='image/png',
        as_attachment=download,
        download_name=f'qr_{batch_id}.png',
    )


@app.route('/verify/<batch_id>')
def verify_batch(batch_id):
    product = Product.query.filter_by(batch_id=batch_id).first_or_404()
    simulate_tamper = is_demo_mode() and (request.args.get('simulate_tamper', '0') == '1')
    ctx = _build_verification_context(product, simulate_tamper=simulate_tamper)
    ctx['from_workflow'] = request.args.get('from_workflow') == '1'
    return render_template('verify.html', **ctx)

@app.route('/verify/<batch_id>/toggle-demo-tamper', methods=['POST'])
def toggle_demo_tamper(batch_id):
    """
    Demo-only helper: Toggles the product farming_method in the database
    to a tampered value and restores strictly from a blockchain-validated StageSnapshot.
    Returns 404 when DEMO_MODE is off.
    """
    if not is_demo_mode():
        abort(404)
    product = Product.query.filter_by(batch_id=batch_id).first_or_404()
    if 'Non-Organic' in product.farming_method or 'Chemically Treated' in product.farming_method or 'Tamper' in product.farming_method:
        chain = inspect_batch_on_chain(
            product.batch_id,
            recorded_contract_address=product.contract_address,
            recorded_contract_version=product.contract_version,
        )
        on_chain_h = chain.get("hash") if chain.get("status") == "ok" else None
        snap_dict, snap_avail, snap_valid, snap_note = _load_validated_snapshot(
            product,
            "HARVEST",
            on_chain_h,
        )
        if not snap_valid or not snap_dict or "farming_method" not in snap_dict:
            flash(
                snap_note or "Cannot restore harvest record: no validated original blockchain snapshot is available.",
                'warning',
            )
            return redirect(url_for('verify_batch', batch_id=batch_id))

        restored = str(snap_dict["farming_method"])
        product.farming_method = restored
        db.session.commit()
        flash(f'Batch {batch_id} restored to authentic state: "{restored}". Live cryptographic check passes!', 'success')
    else:
        product.farming_method = 'Chemically Treated Non-Organic'
        db.session.commit()
        flash(f'Tamper simulated on Batch {batch_id}: Farming method altered to "Chemically Treated Non-Organic". Blockchain caught the discrepancy!', 'danger')
    return redirect(url_for('verify_batch', batch_id=batch_id))


@app.route('/verify/<batch_id>/toggle-transport-tamper', methods=['POST'])
def toggle_transport_tamper(batch_id):
    """
    Demo-only helper: Simulates cold-chain temperature falsification on the latest
    transport checkpoint and restores strictly from a blockchain-validated StageSnapshot.
    Returns 404 when DEMO_MODE is off.
    """
    if not is_demo_mode():
        abort(404)
    product = Product.query.filter_by(batch_id=batch_id).first_or_404()
    sorted_t = _sorted_transports(product)
    if not sorted_t:
        flash('No transport checkpoints exist on this batch yet.', 'warning')
        return redirect(url_for('verify_batch', batch_id=batch_id))

    latest_idx = len(sorted_t) - 1
    latest_t = sorted_t[latest_idx]
    if latest_t.temperature and 'Tampered' in latest_t.temperature:
        chain = inspect_batch_on_chain(
            product.batch_id,
            recorded_contract_address=product.contract_address,
            recorded_contract_version=product.contract_version,
        )
        t_chain_hash = None
        if chain.get("status") == "ok":
            t_stages = [s for s in (chain.get("stages") or []) if s.get("stage") == "TRANSPORT"]
            if latest_idx < len(t_stages):
                t_chain_hash = t_stages[latest_idx].get("hash")

        snap_dict, snap_avail, snap_valid, snap_note = _load_validated_snapshot(
            product,
            "TRANSPORT",
            t_chain_hash,
            transport_record=latest_t,
        )
        if not snap_valid or not snap_dict or "temperature" not in snap_dict:
            flash(
                snap_note or "Cannot restore transport checkpoint: no validated original blockchain snapshot is available.",
                'warning',
            )
            return redirect(url_for('verify_batch', batch_id=batch_id))

        restored = str(snap_dict["temperature"])
        latest_t.temperature = restored
        db.session.commit()
        flash(f'Transport checkpoint for {batch_id} restored to "{restored}". Stage 2 cryptographic proof passes!', 'success')
    else:
        latest_t.temperature = '24.5 °C (Tampered)'
        db.session.commit()
        flash(f'Cold-chain tamper simulated on {batch_id}: Temperature altered in SQLite. Stage 2 on-chain hash mismatch caught!', 'danger')
    return redirect(url_for('verify_batch', batch_id=batch_id))


# ═══════════════════════════════════════════════════════════════════
# JSON REST API ENDPOINTS (IOT / MOBILE / AUDIT INTEGRATION)
# ═══════════════════════════════════════════════════════════════════

@app.route('/api/health')
def api_health():
    w3 = get_w3(die_on_error=False)
    online = bool(w3 and w3.is_connected())
    return jsonify({
        "status": "ok",
        "blockchain": {
            "online": online,
        },
        "database": {
            "products": Product.query.count(),
            "users": User.query.count(),
            "transport_checkpoints": TransportData.query.count(),
            "retail_listings": RetailData.query.count(),
        },
    })


@app.route('/api/verify/<batch_id>')
def api_verify_batch(batch_id):
    product = Product.query.filter_by(batch_id=batch_id).first()
    if not product:
        return jsonify({"error": f"Batch '{batch_id}' not found"}), 404

    ctx = _build_verification_context(product, simulate_tamper=False)
    harvest_step_status = (
        "verified" if ctx["harvest_status"] == "verified"
        else ("tampered" if ctx["harvest_status"] == "tampered" else "cannot_verify")
    )
    return jsonify({
        "batch_id": product.batch_id,
        "name": product.name,
        "quantity": product.quantity,
        "farming_method": product.farming_method,
        "packaging_date": product.packaging_date,
        "origin": product.farmer_data.farm_location if product.farmer_data else None,
        "status": product.status,
        "verification_status": ctx["verification_status"],
        "result_label": ctx["result_label"],
        "reason": ctx["result_reason"],
        "trust_score": ctx["trust_score"],
        "timeline": {
            "farm": {
                "status": harvest_step_status,
                "farmer": product.farmer.full_name or product.farmer.username,
                "origin": product.farmer_data.farm_location if product.farmer_data else None,
                "packaging_date": product.packaging_date,
                "certifications": product.farmer_data.certifications if product.farmer_data else None,
            },
            "transport": [
                {
                    "checkpoint": idx + 1,
                    "status": tv["record"].status,
                    "location": tv["record"].current_location,
                    "temperature": tv["record"].temperature,
                    "telemetry_status": tv["temp_eval"]["status"],
                    "vehicle": tv["record"].vehicle_number,
                    "timestamp": tv["record"].timestamp.isoformat() if tv["record"].timestamp else None,
                    "verification": tv["status"],
                }
                for idx, tv in enumerate(ctx["transport_verifications"])
            ] if ctx["transport_verifications"] else "Pending",
            "shop": {
                "store_name": ctx["retail_verification"]["record"].store_name,
                "store_location": ctx["retail_verification"]["record"].store_location,
                "price": ctx["retail_verification"]["record"].price,
                "stock_quantity": ctx["retail_verification"]["record"].stock_quantity,
                "arrival_date": ctx["retail_verification"]["record"].arrival_date,
                "shelf_life": ctx["retail_verification"]["record"].shelf_life,
                "verification": ctx["retail_verification"]["status"],
            } if ctx["retail_verification"] else "Pending",
        },
        "fingerprints": {
            "harvest": {
                "computed": ctx["computed_hash"],
                "recorded": ctx["on_chain_hash"],
            },
            "transport": [
                {
                    "checkpoint": idx + 1,
                    "computed": tv["computed_hash"],
                    "recorded": tv["on_chain_hash"],
                }
                for idx, tv in enumerate(ctx["transport_verifications"])
            ],
            "shop": {
                "computed": ctx["retail_verification"]["computed_hash"],
                "recorded": ctx["retail_verification"]["on_chain_hash"],
            } if ctx["retail_verification"] else None,
        },
    })


# ═══════════════════════════════════════════════════════════════════
# ADMIN OVERVIEW & DEMO-GATED EVM AUDIT
# ═══════════════════════════════════════════════════════════════════

@app.route('/admin')
@role_required('admin')
def admin_dashboard():
    total_users = User.query.count()
    total_products = Product.query.count()
    total_transports = TransportData.query.count()

    users = User.query.order_by(User.id.asc()).all()
    products = Product.query.order_by(Product.created_at.desc()).all()

    farmers = User.query.filter_by(role='farmer').all()
    farmer_labels = []
    farmer_counts = []
    for f in farmers:
        farmer_labels.append(f.full_name or f.username)
        farmer_counts.append(Product.query.filter_by(farmer_id=f.id).count())

    farmer_chart_data = {
        'labels': farmer_labels or ['No Farmers'],
        'counts': farmer_counts or [0]
    }

    status_dict = {}
    for p in products:
        status_dict[p.status] = status_dict.get(p.status, 0) + 1
    status_chart_data = {
        'labels': list(status_dict.keys()) or ['Harvested'],
        'counts': list(status_dict.values()) or [0]
    }

    batch_verifications = {}
    outcome_counts = {"verified": 0, "tampered": 0, "cannot_verify": 0}
    for p in products:
        vctx = _build_verification_context(p, simulate_tamper=False)
        vst = vctx["verification_status"]
        outcome_counts[vst] = outcome_counts.get(vst, 0) + 1
        batch_verifications[p.batch_id] = {
            "status": vst,
            "label": vctx["result_label"],
            "reason": vctx["result_reason"],
            "pending": vctx["has_pending_stages"],
        }

    chain_overview = get_admin_blockchain_overview(products) if is_demo_mode() else None

    return render_template(
        'admin.html',
        total_users=total_users,
        total_products=total_products,
        total_transports=total_transports,
        users=users,
        products=products,
        farmer_chart_data=farmer_chart_data,
        status_chart_data=status_chart_data,
        batch_verifications=batch_verifications,
        outcome_counts=outcome_counts,
        chain_overview=chain_overview,
    )

@app.route('/admin/users/<int:user_id>/delete', methods=['POST'])
@role_required('admin')
def delete_user(user_id):
    if user_id == session.get('user_id'):
        flash('Cannot delete your own admin account.', 'danger')
        return redirect(url_for('admin_dashboard'))
    user = db.get_or_404(User, user_id)
    db.session.delete(user)
    db.session.commit()
    flash(f'User "{user.username}" deleted.', 'info')
    return redirect(url_for('admin_dashboard'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        ensure_schema_columns()
    debug_mode = os.environ.get('FLASK_DEBUG', 'false').lower() in ('true', '1')
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=debug_mode)
