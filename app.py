import os
import uuid
import time
from datetime import datetime, timezone, timedelta
from functools import wraps
from flask import (
    Flask, render_template, request, redirect, url_for, flash, session, abort
)
from flask_wtf.csrf import CSRFProtect, CSRFError
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

# Load local environment configuration if present
load_dotenv()

from models import db, User, Product, FarmerData, TransportData, RetailData, Feedback, utcnow
from blockchain import (
    store_hash, get_hash, compute_batch_hash, load_config, fetch_on_chain_status
)
from utils import generate_batch_qr, validate_image_file, logger

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
    from blockchain import get_w3
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
    from blockchain import get_w3, load_config
    product_count = Product.query.count()
    user_count = User.query.count()
    transport_count = TransportData.query.count()
    feedback_count = Feedback.query.count()
    recent_products = Product.query.order_by(Product.created_at.desc()).limit(8).all()

    # Blockchain network status (best-effort)
    network_block = None
    contract_address = None
    raw_contract_address = ""
    try:
        cfg = load_config()
        raw_contract_address = cfg.get('contract_address', '')
        if raw_contract_address:
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
    )

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        role = request.form.get('role', '').strip().lower()
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        full_name = request.form.get('full_name', '').strip()
        contact = request.form.get('contact', '').strip()

        # Admin is not allowed via registration
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
    Seamlessly switches the active dashboard and persona without credentials.
    Supports role names, aliases (e.g. 'producer', 'logistics'), and auto-provisions
    the persona user in the database if it doesn't already exist.
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
    farmer_id = session['user_id']
    name = request.form.get('name', '').strip()
    quantity = request.form.get('quantity', '').strip()
    farming_method = request.form.get('farming_method', '').strip()
    packaging_date = request.form.get('packaging_date', '').strip()
    farm_location = request.form.get('farm_location', '').strip()
    certifications = request.form.get('certifications', '').strip()

    if not name or not quantity or not farming_method or not packaging_date:
        flash('Please fill in all required product fields.', 'danger')
        return redirect(url_for('farmer_dashboard'))

    if len(name) > 120 or len(quantity) > 50 or len(farming_method) > 100:
        flash('Input field exceeds allowed character limit.', 'danger')
        return redirect(url_for('farmer_dashboard'))

    if len(farm_location) > 150 or len(certifications) > 200:
        flash('Location or certifications details exceed character limit.', 'danger')
        return redirect(url_for('farmer_dashboard'))

    # Auto-generate unique Batch ID
    batch_id = f"TH-{uuid.uuid4().hex[:8].upper()}"

    # Handle image upload with content validation
    image_file = request.files.get('image')
    image_filename = 'default.jpg'
    if image_file and image_file.filename:
        is_valid, err_msg = validate_image_file(image_file, ALLOWED_EXTENSIONS)
        if not is_valid:
            flash(f'Upload rejected: {err_msg}', 'danger')
            return redirect(url_for('farmer_dashboard'))
        ext = secure_filename(image_file.filename).rsplit('.', 1)[1].lower()
        image_filename = f"{batch_id}.{ext}"
        image_file.save(os.path.join(UPLOAD_FOLDER, image_filename))

    # Generate QR Code using shared utility
    cfg = load_config()
    base_url = cfg.get('BASE_URL', 'http://localhost:5000')
    qr_filename = generate_batch_qr(batch_id, QR_FOLDER, base_url)

    # Compute SHA-256 hash of immutable harvest data
    product_hash = compute_batch_hash(
        batch_id=batch_id,
        name=name,
        quantity=quantity,
        farming_method=farming_method,
        packaging_date=packaging_date,
        farmer_id=farmer_id,
        image=image_filename
    )

    # Store on Ethereum smart contract
    try:
        store_hash(batch_id, product_hash)
        logger.info("Batch %s hash stored on blockchain: %s", batch_id, product_hash)
    except Exception as e:
        logger.error("Blockchain error storing batch %s: %s", batch_id, e)
        flash(f'Blockchain error: {str(e)}', 'danger')
        return redirect(url_for('farmer_dashboard'))

    # Save Product & FarmerData to database
    product = Product(
        batch_id=batch_id,
        name=name,
        quantity=quantity,
        farming_method=farming_method,
        packaging_date=packaging_date,
        farmer_id=farmer_id,
        image=image_filename,
        qr_code=qr_filename,
        on_chain_hash=product_hash,
        status='Harvested'
    )
    db.session.add(product)
    db.session.flush()

    farmer_data = FarmerData(
        product_id=product.id,
        farm_name=session.get('username'),
        farm_location=farm_location,
        harvest_date=packaging_date,
        certifications=certifications,
        notes=f"Harvested and packed by {session.get('username')}"
    )
    db.session.add(farmer_data)
    db.session.commit()

    flash(f'Batch {batch_id} registered and hashed onto blockchain successfully!', 'success')
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
    status = request.form.get('status', '').strip()
    current_location = request.form.get('current_location', '').strip()
    temperature = request.form.get('temperature', '').strip()
    vehicle_number = request.form.get('vehicle_number', '').strip()
    notes = request.form.get('notes', '').strip()

    if not product_id or not status or not current_location:
        flash('Please fill in required logistics checkpoint fields.', 'danger')
        return redirect(url_for('transporter_dashboard'))

    if len(current_location) > 150 or len(temperature) > 50 or len(vehicle_number) > 50 or len(notes) > 2000:
        flash('Logistics field exceeds maximum character length.', 'danger')
        return redirect(url_for('transporter_dashboard'))

    product = Product.query.get_or_404(product_id)

    transport_record = TransportData(
        product_id=product.id,
        transporter_id=session['user_id'],
        status=status,
        current_location=current_location,
        temperature=temperature,
        vehicle_number=vehicle_number,
        notes=notes
    )
    product.status = status
    db.session.add(transport_record)
    db.session.commit()

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
    store_name = request.form.get('store_name', '').strip()
    store_location = request.form.get('store_location', '').strip()
    price_val = request.form.get('price')
    stock_quantity = request.form.get('stock_quantity', '').strip()
    arrival_date = request.form.get('arrival_date', '').strip()
    shelf_life = request.form.get('shelf_life', '').strip()

    if not product_id or not store_name or not store_location:
        flash('Please provide required store details.', 'danger')
        return redirect(url_for('retailer_dashboard'))

    if len(store_name) > 120 or len(store_location) > 150 or len(stock_quantity) > 50 or len(shelf_life) > 50:
        flash('Input field exceeds allowed character length.', 'danger')
        return redirect(url_for('retailer_dashboard'))

    parsed_price = 0.0
    if price_val:
        try:
            parsed_price = float(price_val)
            if parsed_price < 0:
                flash('Price must be a positive value.', 'danger')
                return redirect(url_for('retailer_dashboard'))
        except ValueError:
            flash('Invalid numeric format for retail price.', 'danger')
            return redirect(url_for('retailer_dashboard'))

    product = Product.query.get_or_404(product_id)

    retail_entry = RetailData.query.filter_by(product_id=product.id).first()
    if not retail_entry:
        retail_entry = RetailData(product_id=product.id, retailer_id=session['user_id'])
        db.session.add(retail_entry)

    retail_entry.store_name = store_name
    retail_entry.store_location = store_location
    retail_entry.price = parsed_price
    retail_entry.stock_quantity = stock_quantity
    retail_entry.arrival_date = arrival_date
    retail_entry.shelf_life = shelf_life
    product.status = 'In Stock'
    db.session.commit()

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

@app.route('/verify/<batch_id>')
def verify_batch(batch_id):
    product = Product.query.filter_by(batch_id=batch_id).first_or_404()

    simulate_tamper = request.args.get('simulate_tamper', '0') == '1'

    # If simulation requested for demonstration purposes:
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

    # Recompute SHA-256 hash from database fields
    computed_hash = compute_batch_hash(
        batch_id=product.batch_id,
        name=product.name,
        quantity=product.quantity,
        farming_method=farming_method_for_hash,
        packaging_date=product.packaging_date,
        farmer_id=product.farmer_id,
        image=product.image
    )

    # Fetch on-chain status honestly
    chain_info = fetch_on_chain_status(product.batch_id)
    raw_chain_hash = chain_info.get("hash")
    chain_status = chain_info.get("status")

    if chain_status == "ok":
        on_chain_hash = raw_chain_hash
        if computed_hash.lower() == on_chain_hash.lower():
            verification_status = "verified"
        else:
            verification_status = "tampered"
    elif chain_status == "not_found":
        verification_status = "not_found"
        on_chain_hash = None
    else:
        # RPC unavailable / offline node
        verification_status = "rpc_offline"
        # Disclose local database hash with explicit offline disclaimer
        on_chain_hash = product.on_chain_hash

    is_verified = (verification_status == "verified")
    is_tampered = (verification_status == "tampered")
    is_rpc_offline = (verification_status == "rpc_offline")
    is_not_found = (verification_status == "not_found")

    cfg = load_config()
    config_base_url = cfg.get('BASE_URL', 'http://localhost:5000')

    return render_template(
        'verify.html',
        product=product,
        computed_hash=computed_hash,
        on_chain_hash=on_chain_hash,
        verification_status=verification_status,
        is_verified=is_verified,
        is_tampered=is_tampered,
        is_rpc_offline=is_rpc_offline,
        is_not_found=is_not_found,
        config_base_url=config_base_url,
        simulate_tamper=simulate_tamper,
        simulated_field=simulated_field,
        original_value=original_value,
        tampered_value=tampered_value
    )

@app.route('/verify/<batch_id>/toggle-demo-tamper', methods=['POST'])
def toggle_demo_tamper(batch_id):
    """
    Demonstration helper: Toggles the product farming_method in the database
    between '100% Certified Organic' (authentic matching on-chain seal) and
    'Chemically Treated Non-Organic' (tampered state).
    """
    product = Product.query.filter_by(batch_id=batch_id).first_or_404()
    if 'Non-Organic' in product.farming_method or 'Chemically Treated' in product.farming_method or 'Tamper' in product.farming_method:
        product.farming_method = '100% Certified Organic'
        flash(f'Batch {batch_id} restored to authentic state: "100% Certified Organic". Live cryptographic check passes!', 'success')
    else:
        product.farming_method = 'Chemically Treated Non-Organic'
        flash(f'Tamper simulated on Batch {batch_id}: Farming method altered to "Chemically Treated Non-Organic". Blockchain caught the discrepancy!', 'danger')
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

@app.route('/admin')
@role_required('admin')
def admin_dashboard():
    total_users = User.query.count()
    total_products = Product.query.count()
    total_transports = TransportData.query.count()
    total_feedback = Feedback.query.count()

    users = User.query.order_by(User.id.asc()).all()
    products = Product.query.order_by(Product.created_at.desc()).all()

    # Products per farmer
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

    # Status distribution
    status_dict = {}
    for p in products:
        status_dict[p.status] = status_dict.get(p.status, 0) + 1
    status_chart_data = {
        'labels': list(status_dict.keys()) or ['Harvested'],
        'counts': list(status_dict.values()) or [0]
    }

    # Feedback ratings (1 to 5)
    rating_counts = [0, 0, 0, 0, 0]
    all_fb = Feedback.query.all()
    for fb in all_fb:
        if 1 <= fb.rating <= 5:
            rating_counts[fb.rating - 1] += 1

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
        rating_chart_data=rating_counts
    )

@app.route('/admin/users/<int:user_id>/delete', methods=['POST'])
@role_required('admin')
def delete_user(user_id):
    if user_id == session.get('user_id'):
        flash('Cannot delete your own admin account.', 'danger')
        return redirect(url_for('admin_dashboard'))
    user = User.query.get_or_404(user_id)
    db.session.delete(user)
    db.session.commit()
    flash(f'User "{user.username}" deleted.', 'info')
    return redirect(url_for('admin_dashboard'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    debug_mode = os.environ.get('FLASK_DEBUG', 'false').lower() in ('true', '1')
    app.run(host='0.0.0.0', port=5000, debug=debug_mode)
