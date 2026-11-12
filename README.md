# TrustHarvest — Farm-to-Shop Food Provenance

TrustHarvest records produce harvest details, cold-chain transport checkpoints, and shop listings in PostgreSQL/SQLite and anchors cryptographic SHA-256 fingerprints on an Ethereum smart contract (`TrustHarvestV2.sol`).

Consumers scan a package QR code or enter a Batch ID to see one of three honest verification results:
- **Verified**: Every recorded stage matches the blockchain ledger (with upcoming steps marked **Pending**).
- **Changed after recording**: Existing database data no longer matches the recorded blockchain hash (states which stage changed).
- **Can't check right now**: The blockchain node is offline, a record is missing, or records conflict.

---

## Run Locally in 3 Steps (Free Dev: SQLite + Ganache)

1. **Install Python dependencies & start local Ganache**
   ```bash
   python -m venv venv
   # Windows: venv\Scripts\activate  |  macOS/Linux: source venv/bin/activate
   pip install -r requirements.txt
   npx --yes ganache -p 7545 -h 127.0.0.1 --chain.chainId 1337 --chain.networkId 1337
   ```

2. **Create `.env` from template**
   ```bash
   cp .env.example .env   # Windows PowerShell: Copy-Item .env.example .env
   ```
   Defaults already target SQLite (`sqlite:///trustharvest.db`) and local Ganache (`http://127.0.0.1:7545`).
   Set `DEMO_MODE=true` in `.env` **only** if you want the presentation role switcher, demo QR decoder button, and tamper simulator.

3. **Seed sample batches (optional) & start the app**
   ```bash
   python seed.py --demo
   python app.py
   ```
   Open `http://127.0.0.1:5000`. Run `pytest -v` to execute the test suite.

### One-Command Docker Start
```bash
docker compose up --build
```
*(In `.env` inside Docker on Windows/macOS, point `ETH_RPC_URL=http://host.docker.internal:7545` to reach host Ganache.)*

---

## Deploy Online at ₹0/Month (Free-Tier Stack)

This project is designed to run permanently at **₹0/month** on free-tier infrastructure:
- **App Hosting:** Render Free Web Service (`render.yaml`, `plan: free`, free `*.onrender.com` HTTPS subdomain)
- **Database:** Neon Free PostgreSQL (`DATABASE_URL`)
- **Blockchain RPC & Network:** Alchemy Free Tier connected to **Ethereum Sepolia Testnet ONLY** (`CHAIN_ID=11155111`) — **never deploy to Mainnet or use real ETH**
- **Source Control:** GitHub Free

> **Important Security Notice Before Public Deployment:**
> Review [`docs/CONTRACT_AUDIT.md`](docs/CONTRACT_AUDIT.md) first. `TrustHarvestV2.sol` currently permits any address to call `storeHash` / `addStageHash`; TrustHarvest mitigates this off-chain via per-role server signer allowlists (`EXPECTED_*_SIGNERS` / per-role private keys). Do not deploy to a public network until you approve those trade-offs or apply the proposed access-control upgrade.

### Production Secret Storage & QR HTTPS Requirement
- **Secrets:** Never commit `.env`, `config.json`, private keys, or database URLs to Git. Store `SECRET_KEY`, `DATABASE_URL`, `ETH_RPC_URL`, `CONTRACT_ADDRESS`, `FARMER_PRIVATE_KEY`, `TRANSPORTER_PRIVATE_KEY`, and `RETAILER_PRIVATE_KEY` strictly in **Render Dashboard -> Service -> Environment** (server-side environment variables only — never in templates, logs, or API responses).
- **HTTPS for Camera QR Scanning:** Modern browsers block webcam/phone-camera access on plain HTTP origins (except `localhost`). Always set `BASE_URL` to your HTTPS Render URL (`https://<your-service>.onrender.com`) so QR codes point to your live domain and phone camera scanning works out of the box.
- **Ephemeral Filesystem Compatibility:** Production sets `ALLOW_IMAGE_UPLOADS=false` (uses bundled visuals in `static/img/`) and streams batch QR PNGs dynamically in memory via `/qr/<batch_id>.png` — zero reliance on local disk persistence.
- **Free-Tier Expectations:** Render Free web services spin down after ~15 minutes of inactivity (first request takes ~30–50s to wake). Sepolia transactions require free faucet test ETH only.

---

## Repository Highlights
- `app.py` — Flask routes, honest 3-state verifier, trimmed public JSON API (`/api/health`, `/api/verify/<batch_id>`), dynamic `/qr/<batch_id>.png`, `DEMO_MODE` gating.
- `blockchain.py` — Read/write Web3 integration for `TrustHarvestV2.sol`, server-side private-key signing, V1 read-only historical verification, Alchemy free-tier log fallbacks.
- `contracts/TrustHarvestV2.sol` — Multi-stage provenance contract; `contracts/legacy/TrustHarvest.sol` — Legacy V1 contract kept strictly for read-only historical batch verification.
- `docs/CONTRACT_AUDIT.md` — Security audit and access-control proposal.
- `Dockerfile`, `docker-compose.yml`, `render.yaml` — Zero-cost container & Render Free deployment specs.
