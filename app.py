import os
import uuid
import time
from datetime import datetime, timezone, timedelta
from functools import wraps
from flask import (
    Flask, render_template, request, redirect, url_for, flash, session, jsonify
)
from flask_wtf.csrf import CSRFProtect, CSRFError
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

# Load local environment configuration if present
load_dotenv()

from models import (
    db, User, Product, FarmerData, TransportData, RetailData, Feedback,
    utcnow, ensure_schema_columns
)
from blockchain import (
    store_hash, store_hash_detailed, store_stage_hash, get_hash,
    compute_batch_hash, compute_transport_hash, compute_retail_hash,
    load_config, fetch_on_chain_status, fetch_v2_provenance_details,
    get_admin_blockchain_overview, get_w3
)
from utils import (
    generate_batch_qr, validate_image_file, evaluate_temperature,
    compute_trust_score, logger
)

app = Flask(__name__)

# Security: Move secret configuration to environment variables
SECRET_KEY = os.environ.get('SECRET_KEY')
if not SECRET_KEY:
    if os.environ.get('FLASK_ENV') == 'production' or os.environ.get('PRODUCTION') == 'true':
        raise RuntimeError("FATAL: SECRET_KEY environment variable must be set in production mode.")
    SECRET_KEY = 'trustharvest-dev-only-secret-key-change-in-production'
app.config['SECRET_KEY'] = SECRET_KEY

# Database Configuration
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///trustharvest.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Security: Session Cookie Hardening
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('SESSION_COOKIE_SECURE', 'false').lower() in ('true', '1')
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=4)

# Security: Restrict maximum upload size to 5 MB
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024

# Security: Initialize CSRF Protection
csrf = CSRFProtect(app)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
QR_FOLDER = os.path.join(BASE_DIR, 'static', 'qr')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(QR_FOLDER, exist_ok=True)

db.init_app(app)

with app.app_context():
    db.create_all()
    ensure_schema_columns()

# Make telemetry classifier available across Jinja templates
app.jinja_env.globals['evaluate_temperature'] = evaluate_temperature

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
    """Provides honest real-time blockchain status and active persona info to all templates/navbars."""
    is_online = False
    block_num = None
    try:
        w3 = get_w3(die_on_error=False)
        if w3 and w3.is_connected():
            is_online = True
            block_num = w3.eth.block_number
    except Exception:
        pass
    role = session.get('role', None)
    return {
        'blockchain_online': is_online,
        'blockchain_block': block_num,
        'DEFAULT_PERSONAS': DEFAULT_PERSONAS,
        'current_role': role,
        'current_username': session.get('username', None),
        'current_persona': DEFAULT_PERSONAS.get(role, None)
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
    feedback_count = Feedback.query.count()
    recent_products = Product.query.order_by(Product.created_at.desc()).limit(8).all()

    network_block = None
    contract_address = None
    raw_contract_address = ""
    contract_version = "V2"
    try:
        cfg = load_config()
        contract_version = str(cfg.get('contract_version') or 'V2')
        raw_contract_address = str(cfg.get('contract_address') or '')
        if raw_contract_address and len(raw_contract_address) >= 16:
            contract_address = raw_contract_address[:10] + '…' + raw_contract_address[-6:]
    except Exception:
        pass

    try:
        w3 = get_w3(die_on_error=False)
        if w3 and w3.is_connected():
            network_block = w3.eth.block_number
    except BaseException:
        pass

    return render_template(
        'landing.html',
        product_count=product_count,
        user_count=user_count,
        transport_count=transport_count,
        feedback_count=feedback_count,
        recent_products=recent_products,
        network_block=network_block,
        contract_address=contract_address,
        raw_contract_address=raw_contract_address,
        contract_version=contract_version,
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
    Seamlessly switches the active dashboard and persona without credentials
    for quick live demonstration and stakeholder walkthroughs.
    """
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
    if image_file and image_file.filename:
        is_valid, err_msg = validate_image_file(image_file, ALLOWED_EXTENSIONS)
        if not is_valid:
            return None, f'Upload rejected: {err_msg}'
        ext = secure_filename(image_file.filename).rsplit('.', 1)[1].lower()
        image_filename = f"{batch_id}.{ext}"
        image_file.save(os.path.join(UPLOAD_FOLDER, image_filename))

    cfg = load_config()
    base_url = str(cfg.get('BASE_URL') or 'http://localhost:5000')
    qr_filename = generate_batch_qr(batch_id, QR_FOLDER, base_url)

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
        logger.info("Batch %s hash stored on blockchain: %s (tx: %s)", batch_id, product_hash, receipt_meta["tx_hash"])
    except Exception as e:
        logger.error("Blockchain error storing batch %s: %s", batch_id, e)
        return None, f'Blockchain error storing batch hash: {str(e)}'

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

    anchor_result = store_stage_hash(product.batch_id, "TRANSPORT", stage_hash, role="transporter")

    transport_record = TransportData(
        product_id=product.id,
        transporter_id=user.id,
        status=status,
        current_location=current_location,
        temperature=temperature,
        vehicle_number=vehicle_number,
        notes=notes,
        on_chain_hash=stage_hash,
        tx_hash=anchor_result.get("tx_hash") if anchor_result.get("status") == "anchored" else None,
        block_number=anchor_result.get("block_number") if anchor_result.get("status") == "anchored" else None,
        signer_address=anchor_result.get("signer_address") if anchor_result.get("status") == "anchored" else None,
    )
    product.status = status
    db.session.add(transport_record)
    db.session.commit()

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

    anchor_result = store_stage_hash(product.batch_id, "RETAIL", retail_hash, role="retailer")

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
    retail_entry.on_chain_hash = retail_hash
    if anchor_result.get("status") == "anchored":
        retail_entry.tx_hash = anchor_result.get("tx_hash")
        retail_entry.block_number = anchor_result.get("block_number")
        retail_entry.signer_address = anchor_result.get("signer_address")

    product.status = 'In Stock'
    db.session.commit()

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

    flash(f'Stage 2 Complete: Batch {product.batch_id} registered and sealed on Ethereum blockchain!', 'success')
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
    _, anchor_res, err = _record_transport_checkpoint(user, product, request.form)
    if err:
        flash(err, 'danger')
        return redirect(url_for('workflow_entry', stage='transport', batch_id=batch_id))

    if anchor_res and anchor_res.get("status") == "anchored":
        flash(f'Stage 3 Checkpoint: Transport status updated to "{product.status}" and anchored on Ethereum (Block #{anchor_res.get("block_number")}).', 'success')
    else:
        flash(f'Stage 3 Checkpoint: Transport status updated to "{product.status}" for batch {product.batch_id}.', 'success')
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
    _, anchor_res, err = _record_retail_listing(user, product, request.form, require_price_stock=True)
    if err:
        flash(err, 'danger')
        return redirect(url_for('workflow_entry', stage='retail', batch_id=batch_id))

    if anchor_res and anchor_res.get("status") == "anchored":
        flash(f'Stage 4 Complete: Retail listing sealed on Ethereum (Block #{anchor_res.get("block_number")}) for batch {product.batch_id}!', 'success')
    else:
        flash(f'Stage 4 Complete: Retail listing recorded for batch {product.batch_id}. Full journey completed!', 'success')
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
    return render_template('customer.html', products=products)


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

    chain_info = fetch_on_chain_status(product.batch_id)
    raw_chain_hash = chain_info.get("hash")
    chain_status = chain_info.get("status")
    contract_source_addr = chain_info.get("contract_address")
    conflict_details = chain_info.get("conflict_details")

    if chain_status == "ok":
        on_chain_hash = raw_chain_hash
        if on_chain_hash and computed_hash.lower() == str(on_chain_hash).lower():
            verification_status = "verified"
        else:
            verification_status = "tampered"
    elif chain_status == "conflict":
        verification_status = "conflict"
        on_chain_hash = None
    elif chain_status == "not_found":
        verification_status = "not_found"
        on_chain_hash = None
    elif chain_status == "rpc_offline":
        verification_status = "rpc_offline"
        on_chain_hash = product.on_chain_hash
    else:
        verification_status = "error"
        on_chain_hash = None

    # Fetch V2 multi-stage history & signer metadata
    v2_details = fetch_v2_provenance_details(product.batch_id)
    v2_stages = v2_details.get("stages", [])
    transport_chain_stages = [s for s in v2_stages if s["stage"] == "TRANSPORT"]
    retail_chain_stages = [s for s in v2_stages if s["stage"] == "RETAIL"]

    transport_verifications = []
    has_temp_breach = False
    transport_verified_count = 0
    transport_tampered = False

    for idx, t in enumerate(product.transport_data):
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

        if idx < len(transport_chain_stages):
            chain_stage = transport_chain_stages[idx]
            c_hash = chain_stage["hash"]
            if c_hash.lower() == t_computed.lower():
                t_status = "verified"
                transport_verified_count += 1
            else:
                t_status = "tampered"
                transport_tampered = True
            recorded_by = chain_stage["recorded_by"]
            on_chain_ts = chain_stage["timestamp"]
        elif chain_status == "rpc_offline" and t.on_chain_hash:
            t_status = "rpc_offline"
            c_hash = t.on_chain_hash
            recorded_by = t.signer_address
            on_chain_ts = None
        else:
            t_status = "db_only"
            c_hash = None
            recorded_by = t.signer_address
            on_chain_ts = None

        transport_verifications.append({
            "record": t,
            "computed_hash": t_computed,
            "on_chain_hash": c_hash,
            "status": t_status,
            "temp_eval": temp_eval,
            "recorded_by": recorded_by,
            "on_chain_timestamp": on_chain_ts,
        })

    retail_verification = None
    retail_verified = False
    retail_tampered = False
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
        if retail_chain_stages:
            latest_retail_chain = retail_chain_stages[-1]
            rc_hash = latest_retail_chain["hash"]
            if rc_hash.lower() == r_computed.lower():
                r_status = "verified"
                retail_verified = True
            else:
                r_status = "tampered"
                retail_tampered = True
            r_recorded_by = latest_retail_chain["recorded_by"]
            r_ts = latest_retail_chain["timestamp"]
        elif chain_status == "rpc_offline" and r.on_chain_hash:
            r_status = "rpc_offline"
            rc_hash = r.on_chain_hash
            r_recorded_by = r.signer_address
            r_ts = None
        else:
            r_status = "db_only"
            rc_hash = None
            r_recorded_by = r.signer_address
            r_ts = None

        retail_verification = {
            "record": r,
            "computed_hash": r_computed,
            "on_chain_hash": rc_hash,
            "status": r_status,
            "recorded_by": r_recorded_by,
            "on_chain_timestamp": r_ts,
        }

    # If either transport or retail on-chain comparison detected tampering, surface global alert too
    any_stage_tampered = (verification_status == "tampered") or transport_tampered or retail_tampered

    trust_score = compute_trust_score(
        harvest_verified=(verification_status == "verified"),
        transport_count=len(product.transport_data),
        transport_verified_count=transport_verified_count,
        has_retail=bool(product.retail_data),
        retail_verified=retail_verified,
        has_temp_breach=has_temp_breach,
    )

    cfg = load_config()
    config_base_url = str(cfg.get('BASE_URL') or 'http://localhost:5000')

    return {
        "product": product,
        "computed_hash": computed_hash,
        "on_chain_hash": on_chain_hash,
        "contract_source_addr": contract_source_addr or product.contract_address,
        "verification_status": "tampered" if any_stage_tampered else verification_status,
        "harvest_status": verification_status,
        "is_verified": (verification_status == "verified" and not any_stage_tampered),
        "is_tampered": any_stage_tampered,
        "is_conflict": (verification_status == "conflict" and not any_stage_tampered),
        "is_rpc_offline": (verification_status == "rpc_offline" and not any_stage_tampered),
        "is_not_found": (verification_status == "not_found" and not any_stage_tampered),
        "conflict_details": conflict_details,
        "config_base_url": config_base_url,
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
        "trust_score": trust_score,
    }


@app.route('/verify/<batch_id>')
def verify_batch(batch_id):
    product = Product.query.filter_by(batch_id=batch_id).first_or_404()
    simulate_tamper = request.args.get('simulate_tamper', '0') == '1'
    ctx = _build_verification_context(product, simulate_tamper=simulate_tamper)
    ctx['from_workflow'] = request.args.get('from_workflow') == '1'
    return render_template('verify.html', **ctx)

@app.route('/verify/<batch_id>/toggle-demo-tamper', methods=['POST'])
def toggle_demo_tamper(batch_id):
    """
    Demonstration helper: Toggles the product farming_method in the database
    to a tampered value and cleanly restores its exact authentic value.
    """
    product = Product.query.filter_by(batch_id=batch_id).first_or_404()
    session_key = f'orig_farming_method_{batch_id}'
    if 'Non-Organic' in product.farming_method or 'Chemically Treated' in product.farming_method or 'Tamper' in product.farming_method:
        restored = session.pop(session_key, None)
        if not restored:
            candidates = [
                '100% Certified Organic',
                'Regenerative Agriculture',
                'Hydroponic Controlled',
                'Traditional Natural',
                'Greenhouse Solar',
            ]
            restored = candidates[0]
            if product.on_chain_hash:
                for cand in candidates:
                    cand_hash = compute_batch_hash(
                        batch_id=product.batch_id,
                        name=product.name,
                        quantity=product.quantity,
                        farming_method=cand,
                        packaging_date=product.packaging_date,
                        farmer_id=product.farmer_id,
                        image=product.image,
                    )
                    if cand_hash.lower() == product.on_chain_hash.lower():
                        restored = cand
                        break
        product.farming_method = restored
        flash(f'Batch {batch_id} restored to authentic state: "{restored}". Live cryptographic check passes!', 'success')
    else:
        session[session_key] = product.farming_method
        product.farming_method = 'Chemically Treated Non-Organic'
        flash(f'Tamper simulated on Batch {batch_id}: Farming method altered to "Chemically Treated Non-Organic". Blockchain caught the discrepancy!', 'danger')
    db.session.commit()
    return redirect(url_for('verify_batch', batch_id=batch_id))


@app.route('/verify/<batch_id>/toggle-transport-tamper', methods=['POST'])
def toggle_transport_tamper(batch_id):
    """
    Demonstration helper: Simulates cold-chain temperature falsification on the latest
    transport checkpoint and restores its original value so Stage 2 proof passes again.
    """
    product = Product.query.filter_by(batch_id=batch_id).first_or_404()
    if not product.transport_data:
        flash('No transport checkpoints exist on this batch yet.', 'warning')
        return redirect(url_for('verify_batch', batch_id=batch_id))

    latest_t = product.transport_data[-1]
    session_key = f'orig_temp_{batch_id}'
    if latest_t.temperature and 'Tampered' in latest_t.temperature:
        restored = session.pop(session_key, '3.8 °C')
        latest_t.temperature = restored
        flash(f'Transport checkpoint for {batch_id} restored to "{restored}". Stage 2 cryptographic proof passes!', 'success')
    else:
        session[session_key] = latest_t.temperature or '3.8 °C'
        latest_t.temperature = '24.5 °C (Tampered)'
        flash(f'Cold-chain tamper simulated on {batch_id}: Temperature altered in SQLite. Stage 2 on-chain hash mismatch caught!', 'danger')
    db.session.commit()
    return redirect(url_for('verify_batch', batch_id=batch_id))


@app.route('/verify/<batch_id>/feedback', methods=['POST'])
def submit_feedback(batch_id):
    product = Product.query.filter_by(batch_id=batch_id).first_or_404()
    customer_name = request.form.get('customer_name', '').strip() or 'Anonymous Customer'

    try:
        rating = int(request.form.get('rating', 5))
        if rating < 1 or rating > 5:
            rating = 5
    except (ValueError, TypeError):
        rating = 5

    comment = request.form.get('comment', '').strip()
    if not comment:
        flash('Please enter a feedback comment.', 'warning')
        return redirect(url_for('verify_batch', batch_id=batch_id))

    if len(comment) > 1000 or len(customer_name) > 100:
        flash('Feedback text exceeds maximum permitted length.', 'danger')
        return redirect(url_for('verify_batch', batch_id=batch_id))

    fb = Feedback(
        product_id=product.id,
        customer_name=customer_name,
        rating=rating,
        comment=comment
    )
    db.session.add(fb)
    db.session.commit()

    flash('Feedback submitted successfully! Thank you for rating.', 'success')
    return redirect(url_for('verify_batch', batch_id=batch_id))


# ═══════════════════════════════════════════════════════════════════
# JSON REST API ENDPOINTS (IOT / MOBILE / AUDIT INTEGRATION)
# ═══════════════════════════════════════════════════════════════════

@app.route('/api/health')
def api_health():
    cfg = load_config()
    w3 = get_w3(die_on_error=False)
    online = bool(w3 and w3.is_connected())
    return jsonify({
        "status": "ok",
        "blockchain": {
            "online": online,
            "block_number": w3.eth.block_number if online else None,
            "chain_id": w3.eth.chain_id if online else None,
            "contract_version": cfg.get("contract_version", "V1"),
            "contract_address": cfg.get("contract_address") or None,
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
    return jsonify({
        "batch_id": product.batch_id,
        "name": product.name,
        "quantity": product.quantity,
        "farming_method": product.farming_method,
        "packaging_date": product.packaging_date,
        "status": product.status,
        "verification_status": ctx["verification_status"],
        "trust_score": ctx["trust_score"],
        "blockchain_proof": {
            "contract_address": ctx["contract_source_addr"],
            "tx_hash": product.tx_hash,
            "block_number": product.block_number,
            "signer_address": ctx["v2_details"].get("registered_by") or product.signer_address,
            "computed_hash": ctx["computed_hash"],
            "on_chain_hash": ctx["on_chain_hash"],
        },
        "transport_checkpoints": [
            {
                "status": tv["record"].status,
                "location": tv["record"].current_location,
                "temperature": tv["record"].temperature,
                "telemetry_status": tv["temp_eval"]["status"],
                "vehicle": tv["record"].vehicle_number,
                "verification": tv["status"],
                "computed_hash": tv["computed_hash"],
                "on_chain_hash": tv["on_chain_hash"],
                "tx_hash": tv["record"].tx_hash,
            }
            for tv in ctx["transport_verifications"]
        ],
        "retail": {
            "store_name": ctx["retail_verification"]["record"].store_name,
            "store_location": ctx["retail_verification"]["record"].store_location,
            "price": ctx["retail_verification"]["record"].price,
            "stock_quantity": ctx["retail_verification"]["record"].stock_quantity,
            "verification": ctx["retail_verification"]["status"],
            "computed_hash": ctx["retail_verification"]["computed_hash"],
            "on_chain_hash": ctx["retail_verification"]["on_chain_hash"],
            "tx_hash": ctx["retail_verification"]["record"].tx_hash,
        } if ctx["retail_verification"] else None,
    })


# ═══════════════════════════════════════════════════════════════════
# ADMIN ANALYTICS & LIVE EVM AUDIT
# ═══════════════════════════════════════════════════════════════════

@app.route('/admin')
@role_required('admin')
def admin_dashboard():
    total_users = User.query.count()
    total_products = Product.query.count()
    total_transports = TransportData.query.count()
    total_feedback = Feedback.query.count()

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

    rating_counts = [0, 0, 0, 0, 0]
    for fb in Feedback.query.all():
        if 1 <= fb.rating <= 5:
            rating_counts[fb.rating - 1] += 1

    chain_overview = get_admin_blockchain_overview(products)

    return render_template(
        'admin.html',
        total_users=total_users,
        total_products=total_products,
        total_transports=total_transports,
        total_feedback=total_feedback,
        users=users,
        products=products,
        farmer_chart_data=farmer_chart_data,
        status_chart_data=status_chart_data,
        rating_chart_data=rating_counts,
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
    app.run(host='0.0.0.0', port=5000, debug=debug_mode)
