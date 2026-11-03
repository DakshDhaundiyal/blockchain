# TrustHarvest: Decentralized Agricultural Supply Chain & Food Provenance Platform

TrustHarvest is an end-to-end decentralized agricultural supply chain tracking and food provenance platform. It combines a **Flask** web application with an **Ethereum smart contract** (via **Web3.py** and **Ganache**) to deliver tamper-evident tracking from farm to consumer.

Each agricultural batch is cryptographically hashed at harvest, anchored immutably onto the Ethereum blockchain, assigned a unique batch ID and dynamic QR code, and tracked across transport, retail, and consumer verification stages.

---

## Technology Stack

* **Backend Framework:** Python 3.11+, Flask 3.x, Werkzeug
* **Persistence & ORM:** Flask-SQLAlchemy 3.x (SQLite default, PostgreSQL compatible)
* **Smart Contracts & Blockchain:**
  * Solidity `^0.8.19` (`contracts/TrustHarvest.sol`)
  * Web3.py `6.15+` for JSON-RPC communication
  * Ganache (Ethereum local node running at `http://127.0.0.1:7545`)
  * `py-solc-x` for automated contract compilation
* **Security & Form Handling:** Flask-WTF (CSRF protection), scrypt password hashing, session hardening (HttpOnly, SameSite, configurable Secure flag)
* **Frontend:** Jinja2 templates, Bootstrap 5, Bootstrap Icons, responsive custom CSS
* **QR & Imaging:** `qrcode[pil]`, Pillow (PIL)

---

## Main Features

1. **Immutable Food Provenance:** Batch creation computes a canonical SHA-256 hash anchored onto the Ethereum blockchain. Any alteration to product specifications immediately triggers a cryptographic tamper alert.
2. **End-to-End Multi-Stage Workflow:** Role-based checkpoints for **Farmers**, **Transporters**, **Retailers**, and **Consumers**.
3. **Interactive Stepper & Visual Timeline:** Live status indicators and interactive timeline tracking batches from harvest through cold-chain transit to grocery shelves.
4. **Public Verification & QR Code Support:** Each batch generates a scannable QR code directing consumers to a public verification page displaying provenance and blockchain verification status.
5. **Honest Fault-Tolerant Blockchain Layer:** Distinguishes between verified authenticity, data tampering, missing on-chain records, and offline RPC nodes (graceful degradation without app crashes).
6. **Administrative Insights & Analytics:** Dedicated Admin dashboard summarizing total batches, users, stages, and farmer distribution charts.

---

## Supply Chain Workflow

```
[ Farmer ]                [ Transporter ]             [ Retailer ]              [ Consumer ]
 Harvest & Register  ───►  Cold-Chain Transit   ───►   Stock & Supermarket  ───►  Scan QR Code &
 Batch SHA-256 Hash        Log Temp & Vehicle         Price & Shelf-Life         Verify Provenance
 Anchored On-Chain         Checkpoints                Inventory Tracking         Against Blockchain
```

### 1. Farmer / Producer
* Logs in and accesses the **Farmer Dashboard** or the **Multi-Stage Workflow**.
* Enters crop name, quantity, farming method (e.g., Organic), packaging date, and farm origin.
* Uploads product photo (validated for mime type, extension, and file size).
* The platform:
  * Generates a unique batch identifier (`TH-XXXXXXXX`).
  * Computes a canonical SHA-256 hash across immutable attributes.
  * Sends an Ethereum transaction invoking `storeHash(batchId, hash)` on the smart contract.
  * Generates a branded QR code linked to `/verify/<batch_id>`.

### 2. Transporter / Logistics
* Receives produce from the farm.
* Records transit checkpoints: current location, storage temperature (e.g., cold chain at 4.0 °C), vehicle number, and shipment inspection notes.
* Updates batch status to *In Transit*.

### 3. Retailer / Supermarket
* Receives shipment at the store or distribution center.
* Records retail arrival date, retail price per unit, remaining shelf life, and stock quantity.
* Updates batch status to *In Stock* or *Available for Sale*.

### 4. Consumer / Public Verifier
* Scans the QR code on the physical package or enters the Batch ID on `/verify/<batch_id>`.
* The system recalculates the SHA-256 hash from database attributes and queries the smart contract via `getHash(batchId)`.
* **Verification States:**
  * **Verified Authentic (Green):** On-chain hash matches computed database hash.
  * **Tampered (Red):** Database record has been modified after on-chain anchoring.
  * **RPC Offline (Yellow):** Ganache node is not reachable; displays cached database hash with offline notice.
  * **Not Found:** Batch ID does not exist on-chain.

---

## Project Structure

```
blockchain/
├── contracts/
│   ├── TrustHarvest.sol          # Active Solidity 0.8.19 smart contract
│   └── TrustHarvestV2.sol        # Proposed V2 smart contract with access control
├── static/
│   ├── css/style.css             # Agricultural green identity & responsive theme
│   ├── img/                      # Static branding and role imagery
│   ├── qr/                       # Generated batch QR codes (.gitkeep preserved)
│   └── uploads/                  # Uploaded produce images (default.jpg fallback)
├── templates/
│   ├── base.html                 # Navigation, persona switcher & blockchain pill
│   ├── landing.html              # Public landing page with timeline preview
│   ├── login.html                # Secure authentication form
│   ├── register.html             # User registration form
│   ├── farmer.html               # Farmer produce management
│   ├── transporter.html          # Logistics tracking dashboard
│   ├── retailer.html             # Supermarket inventory dashboard
│   ├── customer.html             # Consumer batch lookup portal
│   ├── admin.html                # Admin statistics and charts
│   ├── verify.html               # Public batch verification & tamper demo
│   ├── workflow.html             # Multi-stage supply chain stepper
│   └── workflow_stepper.html     # Reusable workflow progress bar partial
├── tests/
│   ├── conftest.py               # Isolated in-memory SQLite fixtures
│   ├── test_auth.py              # Authentication & password hashing tests
│   ├── test_blockchain_hashing.py# Hash computation & consistency tests
│   ├── test_contract_proposal.py # Contract logic & verification tests
│   ├── test_role_switcher.py     # Role authorization & persona switcher tests
│   ├── test_security_uploads.py  # File upload validation & CSRF tests
│   └── test_workflow.py          # Complete multi-stage workflow tests
├── app.py                        # Core Flask application & routing
├── blockchain.py                 # Web3.py wrapper, compilation & deployment logic
├── config.example.json           # Sample template for contract ABI, bytecode & address
├── models.py                     # SQLAlchemy database models (User, Product, Stages)
├── pytest.ini                    # Pytest configuration
├── requirements.txt              # Production and development dependencies
├── seed.py                       # Demo data population utility
├── utils.py                      # QR generation, hashing & file validation helpers
├── .env.example                  # Environment configuration template
├── .gitignore                    # Comprehensive exclusion rules
└── README.md                     # Project documentation
```

---

## Installation & Setup Instructions

### Prerequisites
* **Python:** 3.11 or higher
* **Ganache:** Ganache GUI (v2.7.1+) or Ganache CLI (`npm install -g ganache`)
* **Git**

### Step 1: Clone the Repository
```bash
git clone https://github.com/DakshDhaundiyal/blockchain.git
cd blockchain
```

### Step 2: Create and Activate Virtual Environment
* **Windows (PowerShell):**
  ```powershell
  python -m venv venv
  .\venv\Scripts\Activate.ps1
  ```
* **Linux / macOS:**
  ```bash
  python3 -m venv venv
  source venv/bin/activate
  ```

### Step 3: Install Dependencies
```bash
pip install -r requirements.txt
```

### Step 4: Configure Environment Variables
Copy `.env.example` to `.env`:
* **Windows (PowerShell):**
  ```powershell
  Copy-Item .env.example .env
  ```
* **Linux / macOS:**
  ```bash
  cp .env.example .env
  ```
*Open `.env` and configure your settings:*
```ini
SECRET_KEY=your-custom-secret-key-for-development
FLASK_ENV=development
DATABASE_URL=sqlite:///trustharvest.db
GANACHE_URL=http://127.0.0.1:7545
BASE_URL=http://localhost:5000
MAX_CONTENT_LENGTH=5242880
```

### Step 5: Configure Blockchain Settings
Copy `config.example.json` to `config.json`:
* **Windows (PowerShell):**
  ```powershell
  Copy-Item config.example.json config.json
  ```
* **Linux / macOS:**
  ```bash
  cp config.example.json config.json
  ```
*(Note: `config.json` is ignored by Git to keep your local contract addresses and network state private.)*

---

## Running Ganache and Deploying the Smart Contract

1. **Start Ganache:**
   * Open the **Ganache GUI** and click **Quickstart (Ethereum)**.
   * Or run Ganache CLI:
     ```bash
     ganache --port 7545 --chainId 1337
     ```
   * Ensure the RPC server is listening at `http://127.0.0.1:7545`.

2. **Automatic Contract Deployment:**
   * TrustHarvest automatically manages contract deployment. When you add your first product or trigger blockchain initialization, `blockchain.py` detects whether bytecode exists at `config.json`'s configured address.
   * If empty or unconfigured, it automatically compiles `contracts/TrustHarvest.sol` (using `solc 0.8.19`), deploys the contract using Ganache Account 0, and writes the newly deployed address to `config.json`.

---

## Running the Application

1. **(Optional) Seed Demo Accounts and Stages:**
   ```bash
   python seed.py
   ```
   *Default Demo Accounts (Password: `password123`):*
   * **Farmer:** `farmer_demo17`
   * **Transporter:** `transporter_dan`
   * **Retailer:** `retailer_sarah`
   * **Customer:** `customer_amy`
   * **Admin:** `admin`

2. **Start the Flask Development Server:**
   ```bash
   python app.py
   ```

3. **Access the Application:**
   * Open your browser and navigate to: **`http://localhost:5000`**
   * The top navbar features a live **Blockchain Status Pill** showing whether Ganache is online and displaying current block height.
   * In development mode, use the **Persona Switcher** in the top navbar to instantly test different roles without repeatedly logging in and out.

---

## How Blockchain Verification Works

### 1. Canonical Hash Calculation
When a farmer registers a batch, `compute_batch_hash()` canonicalizes product attributes into a JSON payload with sorted keys:
```python
payload = json.dumps({
    "batch_id": batch_id,
    "farmer_id": farmer_id,
    "farming_method": farming_method,
    "image": image_filename,
    "name": name,
    "packaging_date": packaging_date,
    "quantity": quantity
}, sort_keys=True)
return hashlib.sha256(payload.encode("utf-8")).hexdigest()
```

### 2. On-Chain Smart Contract Anchoring
The computed hash is sent to the Ethereum contract:
```solidity
function storeHash(string memory batchId, string memory hash) public {
    require(bytes(batchHashes[batchId]).length == 0, "Batch already registered");
    batchHashes[batchId] = hash;
    emit HashStored(batchId, hash);
}
```
* **Immutability Protection:** The contract enforces that a hash for a given batch ID can only be written once. Any attempt to overwrite an existing batch reverts.

### 3. Public Verification & Tamper Detection
When a user scans the QR code or navigates to `/verify/<batch_id>`:
1. The app recomputes the SHA-256 hash from the current database attributes.
2. The app calls `getHash(batchId)` on the deployed contract via Web3.py.
3. If the computed hash matches the blockchain hash, authenticity is guaranteed.
4. If an unauthorized actor altered any record in the database (e.g. changing farming method or harvest date), the hash mismatch triggers an immediate **Tamper Warning**.

---

## Running Automated Tests

The test suite runs with isolated in-memory SQLite instances to protect development and production databases:

```bash
pytest
```

To run with verbose output:
```bash
pytest -v
```

---

## Security & Best Practices

* **Zero Credentials in Git:** `.env` and `config.json` are excluded via `.gitignore`. Always use `.env.example` and `config.example.json`.
* **Database Isolation:** Test suites use in-memory SQLite fixtures (`sqlite:///:memory:`) to guarantee zero accidental writes to disk databases.
* **Upload Safety:** Image uploads are validated for allowed image extensions, maximum file size (5MB), and sanitised with `secure_filename`.
* **CSRF Protection:** Enabled across all state-changing POST forms via Flask-WTF.
