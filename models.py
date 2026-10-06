from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False) # admin, farmer, transporter, retailer, customer
    full_name = db.Column(db.String(120), nullable=True)
    contact = db.Column(db.String(120), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Product(db.Model):
    __tablename__ = 'products'
    id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(db.String(64), unique=True, nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    quantity = db.Column(db.String(50), nullable=False)
    farming_method = db.Column(db.String(100), nullable=False)
    packaging_date = db.Column(db.String(50), nullable=False)
    farmer_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    image = db.Column(db.String(255), nullable=False)
    qr_code = db.Column(db.String(255), nullable=True)
    on_chain_hash = db.Column(db.String(66), nullable=True)
    status = db.Column(db.String(50), default='Harvested') # Harvested, In Transit, Delivered to Retail, In Stock, Sold
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    farmer = db.relationship('User', foreign_keys=[farmer_id], backref='farmer_products')
    farmer_data = db.relationship('FarmerData', backref='product', uselist=False, cascade='all, delete-orphan')
    transport_data = db.relationship('TransportData', backref='product', cascade='all, delete-orphan', order_by='TransportData.timestamp.asc()')
    retail_data = db.relationship('RetailData', backref='product', uselist=False, cascade='all, delete-orphan')
    feedback = db.relationship('Feedback', backref='product', cascade='all, delete-orphan', order_by='Feedback.created_at.desc()')


class FarmerData(db.Model):
    __tablename__ = 'farmer_data'
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    farm_name = db.Column(db.String(120), nullable=True)
    farm_location = db.Column(db.String(150), nullable=True)
    harvest_date = db.Column(db.String(50), nullable=True)
    certifications = db.Column(db.String(200), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class TransportData(db.Model):
    __tablename__ = 'transport_data'
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    transporter_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    status = db.Column(db.String(50), nullable=False) # Picked Up, In Transit, Customs Cleared, Delivered
    current_location = db.Column(db.String(150), nullable=False)
    temperature = db.Column(db.String(50), nullable=True)
    vehicle_number = db.Column(db.String(50), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    transporter = db.relationship('User', foreign_keys=[transporter_id])


class RetailData(db.Model):
    __tablename__ = 'retail_data'
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    retailer_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    store_name = db.Column(db.String(120), nullable=True)
    store_location = db.Column(db.String(150), nullable=True)
    price = db.Column(db.Float, nullable=True)
    stock_quantity = db.Column(db.String(50), nullable=True)
    arrival_date = db.Column(db.String(50), nullable=True)
    shelf_life = db.Column(db.String(50), nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    retailer = db.relationship('User', foreign_keys=[retailer_id])


class Feedback(db.Model):
    __tablename__ = 'feedback'
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    customer_name = db.Column(db.String(100), nullable=True)
    rating = db.Column(db.Integer, default=5)
    comment = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
