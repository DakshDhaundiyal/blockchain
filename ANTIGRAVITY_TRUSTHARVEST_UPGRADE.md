# TrustHarvest — Antigravity Project Upgrade Brief

## Repository
https://github.com/DakshDhaundiyal/blockchain

This is the EXISTING TrustHarvest application. Do not rebuild it from scratch or modify a separate project.

## Verified stack and architecture
- Python / Flask web application (app.py)
- Flask-SQLAlchemy persistence (models.py, SQLite by default)
- Solidity contract: contracts/TrustHarvest.sol
- Web3.py + py-solc-x integration in blockchain.py
- Local Ganache RPC default: http://127.0.0.1:7545
- QR code generation and image uploads
- Jinja HTML templates under templates/
- CSS/assets under static/
- Role-based workflows for admin, farmer, transporter, retailer, and customer
- Batch verification compares product data hashes against a value stored on-chain
- Smoke test: smoke_test.py; seed script: seed.py

## Work instructions
I have installed additional Antigravity skills. Inspect the installed/available skills, read their real instructions, and APPLY the relevant ones to this repository. Prioritize Python/Flask, application security, Solidity/Web3, testing, database, frontend/UI, accessibility, debugging, and documentation skills where available. Do not claim to use a skill if it is unavailable or not actually applied.

### Phase 1 — Baseline inspection
1. Inspect the entire repository and read app.py, models.py, blockchain.py, contracts/TrustHarvest.sol, all Jinja templates, requirements, configuration, and tests.
2. Inspect Git status and current diff first; do not discard or overwrite unrelated work.
3. Run the current tests/smoke tests if the environment permits. Record baseline outcomes and blockers.
4. Create a prioritized audit and checklist based on actual code, not generic assumptions.

### Phase 2 — Security P0
The current app.py hard-codes app.config['SECRET_KEY'] = 'trustharvest-super-secret-key-blockchain-2026'. Move secret configuration to environment variables, fail safely or clearly in production if absent, and provide a non-secret .env.example; ensure .env is ignored by Git.
Audit and fix, where confirmed:
- session cookie security flags, session lifecycle, CSRF for state-changing form routes
- password hashing and authentication flows
- role authorization on all mutation routes (including ownership checks)
- upload validation, extension/content constraints, secure filenames and file size limits
- secret/key handling and config.json bytecode/ABI/address responsibilities
- input validation and database integrity
- exception handling and information disclosure
- production debug/server defaults
Never print or commit credentials/private keys/seed phrases. Do not reset or modify real user data.

### Phase 3 — Blockchain/contract P0-P1
Review TrustHarvest.sol and blockchain.py. The present contract stores a string hash under a string batch ID and permits any sender to overwrite it. Decide whether immutable batch verification is a project requirement; if so, propose/test an access-controlled and/or one-time-write design without silently breaking compatibility with deployed contract addresses or the existing config ABI.
Validate batch IDs/hashes, handle failed or reverted transactions, verify receipts, and distinguish RPC unavailability from a genuine hash mismatch. Keep the UI honest: an RPC error must not falsely be shown as proof of tampering or verification.
Do not deploy contracts, change live chain data, transfer funds, or make irreversible changes without explicit approval. Use local/test chains for experimentation and add tests for authorized and unauthorized calls, duplicate writes, invalid values, hash consistency, and RPC failure.

### Phase 4 — Data consistency and functional tests
Trace the full batch journey: farmer creates product -> hash computed/stored -> QR points to verification URL -> transporter records checkpoints -> retailer updates stock -> customer scans and verifies.
Audit whether every field included in the original batch hash is checked consistently at verification. Ensure post-creation fields that are expected to change are deliberately excluded or separately recorded rather than accidentally causing false tamper alerts.
Add reproducible tests for authentication, permissions, product registration, upload behavior, transport/retail workflows, QR URL generation, blockchain success/failure, correct hash, and tampering. Keep test data isolated; review smoke_test.py carefully because it calls db.drop_all() and must never run against a non-test database.
Do not mark tests passed unless you ran them.

### Phase 5 — UI/UX
Use appropriate frontend/UI skills to improve the existing templates rather than replacing the app. Preserve the green agriculture/supply-chain identity where it fits. Establish consistent spacing, typography, card hierarchy, tables, status badges, accessible contrast, keyboard navigation, responsive layouts, validation, confirmations, loading/error/empty states. Prioritize:
- landing page clarity and traceability explanation
- role-specific dashboard information hierarchy
- add-product workflow
- transport checkpoint and retailer update forms
- public batch verification, QR usage, on-chain status and timeline
- admin overview
Do not create fake blockchain status or fake metrics.

### Phase 6 — Reliability and maintainability
Check dependencies, configuration, logging, error handling, database migrations strategy, duplicated code, route organization, and deployment readiness. Add or update tests and documentation as appropriate. Avoid unnecessary frameworks or architecture rewrites.

## Execution requirements
- Implement changes directly in the existing workspace incrementally, not just an audit.
- First provide a short ranked plan, then start with the highest-priority safe fix.
- Preserve current routes and behavior unless a change is necessary; document any contract/API compatibility implications.
- Before editing, inspect Git status and back up/understand affected logic.
- After each meaningful change run the relevant tests, lint/type/security/static-analysis checks available in the project; fix regressions.
- Check the Git diff and secrets before committing.
- Do not commit .env files, databases, uploaded files, generated QR codes, private keys, or generated artifacts.
- Do not deploy to production, run destructive DB operations, reset a chain, change a deployed contract, or spend funds without asking me first.

## Final report
Maintain a checklist of completed/incomplete items. At the end, report:
1. actual issues found and priority,
2. exact files changed and purpose,
3. skills available and which ones were actually applied,
4. commands/tests actually executed and results,
5. remaining risks and recommended next tasks.
Do not stop after planning; continue into implementation unless a decision or external dependency genuinely blocks progress.
