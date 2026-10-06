import os
import uuid
from datetime import datetime
from functools import wraps
from flask import (
    Flask, render_template, request, redirect, url_for, flash, session, abort
)
from werkzeug.utils import secure_filename
import qrcode
from models import db, User, Product, FarmerData, TransportData, RetailData, Feedback
from blockchain import (
    store_hash, get_hash, compute_batch_hash, load_config
)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'trustharvest-super-secret-key-blockchain-2026'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///trustharvest.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
QR_FOLDER = os.path.join(BASE_DIR, 'static', 'qr')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(QR_FOLDER, exist_ok=True)

db.init_app(app)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

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
    return render_template(
        'landing.html',
        product_count=product_count,
        user_count=user_count,
        transport_count=transport_count,
        feedback_count=feedback_count,
        recent_products=recent_products
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

        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            session['user_id'] = user.id
            session['username'] = user.username
            session['role'] = user.role
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

        flash('Invalid username or password.', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('landing'))

@app.route('/farmer')
@role_required('farmer')
def farmer_dashboard():
    farmer_id = session['user_id']
    products = Product.query.filter_by(farmer_id=farmer_id).order_by(Product.created_at.desc()).all()
    today_str = datetime.utcnow().strftime('%Y-%m-%d')
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

    # Auto-generate unique Batch ID
    batch_id = f"TH-{uuid.uuid4().hex[:8].upper()}"

    # Handle image upload
    image_file = request.files.get('image')
    image_filename = 'default.jpg'
    if image_file and image_file.filename and allowed_file(image_file.filename):
        ext = image_file.filename.rsplit('.', 1)[1].lower()
        image_filename = f"{batch_id}.{ext}"
        image_file.save(os.path.join(UPLOAD_FOLDER, image_filename))

    # Generate QR Code
    cfg = load_config()
    base_url = cfg.get('BASE_URL', 'http://localhost:5000').rstrip('/')
    verify_url = f"{base_url}/verify/{batch_id}"

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
    qr_img.save(os.path.join(QR_FOLDER, qr_filename))

    # Compute SHA-256 hash of ONLY specified fields:
    # batch_id, name, quantity, farming_method, packaging_date, farmer_id, image filename
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
    except Exception as e:
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
    today_str = datetime.utcnow().strftime('%Y-%m-%d')
    return render_template('retailer.html', products=products, retail_entries=retail_entries, today_str=today_str)

@app.route('/retailer/add', methods=['POST'])
@role_required('retailer')
def add_retail_data():
    product_id = request.form.get('product_id')
    store_name = request.form.get('store_name', '').strip()
    store_location = request.form.get('store_location', '').strip()
    price = request.form.get('price')
    stock_quantity = request.form.get('stock_quantity', '').strip()
    arrival_date = request.form.get('arrival_date', '').strip()
    shelf_life = request.form.get('shelf_life', '').strip()

    product = Product.query.get_or_404(product_id)

    retail_entry = RetailData.query.filter_by(product_id=product.id).first()
    if not retail_entry:
        retail_entry = RetailData(product_id=product.id, retailer_id=session['user_id'])
        db.session.add(retail_entry)

    retail_entry.store_name = store_name
    retail_entry.store_location = store_location
    try:
        retail_entry.price = float(price) if price else 0.0
    except ValueError:
        retail_entry.price = 0.0
    retail_entry.stock_quantity = stock_quantity
    retail_entry.arrival_date = arrival_date
    retail_entry.shelf_life = shelf_life
    product.status = 'In Stock'
    db.session.commit()

    flash(f'Retail stock & price details updated for batch {product.batch_id}.', 'success')
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

    # Recompute SHA-256 hash from DB
    computed_hash = compute_batch_hash(
        batch_id=product.batch_id,
        name=product.name,
        quantity=product.quantity,
        farming_method=product.farming_method,
        packaging_date=product.packaging_date,
        farmer_id=product.farmer_id,
        image=product.image
    )

    # Fetch on-chain hash
    on_chain_hash = get_hash(product.batch_id)

    is_verified = bool(on_chain_hash and computed_hash.lower() == on_chain_hash.lower())

    cfg = load_config()
    config_base_url = cfg.get('BASE_URL', 'http://localhost:5000')

    return render_template(
        'verify.html',
        product=product,
        computed_hash=computed_hash,
        on_chain_hash=on_chain_hash,
        is_verified=is_verified,
        config_base_url=config_base_url
    )

@app.route('/verify/<batch_id>/feedback', methods=['POST'])
def submit_feedback(batch_id):
    product = Product.query.filter_by(batch_id=batch_id).first_or_404()
    customer_name = request.form.get('customer_name', '').strip() or 'Anonymous Customer'
    rating = int(request.form.get('rating', 5))
    comment = request.form.get('comment', '').strip()

    if not comment:
        flash('Please enter a feedback comment.', 'warning')
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
    app.run(host='0.0.0.0', port=5000, debug=True)
