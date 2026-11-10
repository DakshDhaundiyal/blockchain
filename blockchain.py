import json
import os
import sys
import hashlib
from datetime import datetime, timezone
from web3 import Web3
from solcx import compile_standard, install_solc, set_solc_version

GANACHE_URL = os.environ.get("GANACHE_URL") or os.environ.get("ETH_RPC_URL") or "http://127.0.0.1:7545"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
CONTRACT_PATH = os.path.join(BASE_DIR, "contracts", "TrustHarvestV2.sol")
CONTRACT_NAME = "TrustHarvestV2"
CONTRACT_VERSION = "V2"


def get_w3(die_on_error=True):
    try:
        w3 = Web3(Web3.HTTPProvider(GANACHE_URL, request_kwargs={"timeout": 2}))
        if not w3.is_connected():
            if die_on_error:
                print(f"Error: Unable to connect to Ethereum/Ganache at {GANACHE_URL}. Please ensure node is running.", file=sys.stderr)
                sys.exit(1)
            return None
        return w3
    except Exception:
        if die_on_error:
            print(f"Error: Unable to connect to Ethereum/Ganache at {GANACHE_URL}. Please ensure node is running.", file=sys.stderr)
            sys.exit(1)
        return None


def get_signer_account(w3, role="farmer"):
    """
    Maps stakeholder roles to distinct Ganache accounts for realistic multi-actor
    on-chain provenance signatures. Falls back to accounts[0] when fewer accounts exist.
    """
    accounts = getattr(w3.eth, "accounts", []) or []
    if not accounts:
        raise BlockchainUnavailableError("No accounts available in Ethereum/Ganache node.")

    role_index_map = {
        "admin": 0,
        "deployer": 0,
        "farmer": 1,
        "transporter": 2,
        "retailer": 3,
        "customer": 4,
    }
    idx = role_index_map.get((role or "").lower(), 0)
    return accounts[idx] if idx < len(accounts) else accounts[0]


def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "BASE_URL": "http://localhost:5000",
        "contract_version": CONTRACT_VERSION,
        "contract_address": "",
        "abi": [],
        "bytecode": "",
        "historical_contract_addresses": [],
    }


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def _has_v2_abi(abi):
    if not isinstance(abi, list):
        return False
    fn_names = {item.get("name") for item in abi if item.get("type") == "function"}
    return {"storeHash", "getHash", "getRecord", "addStageHash", "getStageCount", "getStageRecord"}.issubset(fn_names)


def compile_contract_if_needed():
    cfg = load_config()
    abi = cfg.get("abi")
    bytecode = cfg.get("bytecode")
    version = cfg.get("contract_version")

    if not abi or not bytecode or version != CONTRACT_VERSION or not _has_v2_abi(abi):
        try:
            install_solc("0.8.19")
        except Exception:
            pass
        set_solc_version("0.8.19")

        with open(CONTRACT_PATH, "r", encoding="utf-8") as f:
            sol_source = f.read()

        compiled_sol = compile_standard(
            {
                "language": "Solidity",
                "sources": {f"{CONTRACT_NAME}.sol": {"content": sol_source}},
                "settings": {
                    "outputSelection": {
                        "*": {"*": ["abi", "metadata", "evm.bytecode", "evm.sourceMap"]}
                    }
                },
            },
            solc_version="0.8.19",
        )

        contract_data = compiled_sol["contracts"][f"{CONTRACT_NAME}.sol"][CONTRACT_NAME]
        abi = contract_data["abi"]
        bytecode = contract_data["evm"]["bytecode"]["object"]

        # Archive prior V1 address into historical list so legacy batches remain readable
        prev_addr = cfg.get("contract_address")
        if prev_addr and version != CONTRACT_VERSION:
            hist = cfg.get("historical_contract_addresses") or []
            if prev_addr not in hist:
                hist.append(prev_addr)
            cfg["historical_contract_addresses"] = hist
            cfg["contract_address"] = ""

        cfg["contract_version"] = CONTRACT_VERSION
        cfg["abi"] = abi
        cfg["bytecode"] = bytecode
        save_config(cfg)

    return abi, bytecode


def get_or_deploy_contract(w3=None):
    if w3 is None:
        w3 = get_w3()
    if w3 is None:
        raise BlockchainUnavailableError("Ethereum node is unreachable.")

    abi, bytecode = compile_contract_if_needed()
    cfg = load_config()
    address = cfg.get("contract_address")

    needs_deploy = False
    if not address:
        needs_deploy = True
    else:
        try:
            checksum_addr = Web3.to_checksum_address(address)
            code = w3.eth.get_code(checksum_addr)
            if not code or code in (b"", b"\x00", b"0x", "0x"):
                needs_deploy = True
            else:
                # Verify deployed bytecode actually exposes V2's getStageCount view function
                try:
                    test_contract = w3.eth.contract(address=checksum_addr, abi=abi)
                    test_contract.functions.getStageCount("__probe__").call()
                except Exception:
                    hist = cfg.get("historical_contract_addresses") or []
                    if address not in hist:
                        hist.append(address)
                        cfg["historical_contract_addresses"] = hist
                    needs_deploy = True
        except Exception:
            needs_deploy = True

    if needs_deploy:
        deployer = get_signer_account(w3, "deployer")
        Contract = w3.eth.contract(abi=abi, bytecode=bytecode)
        tx_hash = Contract.constructor().transact({"from": deployer})
        tx_receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        if getattr(tx_receipt, "status", None) != 1:
            raise BlockchainError(f"Contract deployment transaction failed with status: {getattr(tx_receipt, 'status', None)}")
        address = tx_receipt.get("contractAddress") if isinstance(tx_receipt, dict) else getattr(tx_receipt, "contractAddress", None)
        if not address:
            raise BlockchainError("Contract deployment receipt did not include a contract address.")
        checksum_address = Web3.to_checksum_address(str(address))
        code = w3.eth.get_code(checksum_address)
        if not code or code in (b"", b"\x00", "0x", b"0x"):
            raise BlockchainError(f"No deployed bytecode found at new contract address: {address}")
        cfg["contract_address"] = address
        cfg["contract_version"] = CONTRACT_VERSION
        save_config(cfg)

    final_addr = Web3.to_checksum_address(str(address))
    return w3.eth.contract(address=final_addr, abi=abi)


def _extract_receipt_meta(receipt, tx_hash, contract_address, signer_address):
    tx_hash_val = receipt.get("transactionHash") if isinstance(receipt, dict) else getattr(receipt, "transactionHash", tx_hash)
    tx_hex = tx_hash_val.hex() if hasattr(tx_hash_val, "hex") else str(tx_hash_val or "")
    if tx_hex and not tx_hex.startswith("0x"):
        tx_hex = "0x" + tx_hex
    block_num = receipt.get("blockNumber") if isinstance(receipt, dict) else getattr(receipt, "blockNumber", None)
    gas_used = receipt.get("gasUsed") if isinstance(receipt, dict) else getattr(receipt, "gasUsed", None)
    return {
        "tx_hash": tx_hex,
        "block_number": int(block_num) if block_num is not None else None,
        "contract_address": contract_address,
        "signer_address": signer_address,
        "gas_used": int(gas_used) if gas_used is not None else None,
    }


def store_hash_detailed(batch_id, hash_val, role="farmer"):
    w3 = get_w3()
    if w3 is None:
        raise BlockchainUnavailableError("Ethereum / Ganache node is unreachable.")
    contract = get_or_deploy_contract(w3)
    signer = get_signer_account(w3, role)
    tx_hash = contract.functions.storeHash(batch_id, hash_val).transact({"from": signer})
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    status = receipt.get("status") if isinstance(receipt, dict) else getattr(receipt, "status", None)
    if status != 1:
        tx_hex = tx_hash.hex() if hasattr(tx_hash, "hex") else str(tx_hash)
        raise RuntimeError(f"Transaction failed or reverted on blockchain: {tx_hex}")
    return _extract_receipt_meta(receipt, tx_hash, contract.address, signer)


def store_hash(batch_id, hash_val):
    meta = store_hash_detailed(batch_id, hash_val, role="farmer")
    return meta["tx_hash"]


def store_stage_hash(batch_id, stage, hash_val, role="transporter"):
    """
    Best-effort / safe stage anchoring on TrustHarvestV2 for TRANSPORT and RETAIL stages.
    Returns dict with 'status': 'anchored' | 'rpc_offline' | 'batch_not_registered' | 'error'.
    """
    try:
        w3 = get_w3(die_on_error=False)
        if not w3 or not w3.is_connected():
            return {"status": "rpc_offline", "error": "Ethereum/Ganache node offline."}

        contract = get_or_deploy_contract(w3)
        # Ensure harvest batch exists in active V2 contract before appending stage
        try:
            _, _, _, exists = contract.functions.getRecord(str(batch_id)).call()
            if not exists:
                return {
                    "status": "batch_not_registered",
                    "error": f"Batch {batch_id} is not registered on active V2 contract.",
                }
        except Exception as check_err:
            return {"status": "error", "error": str(check_err)}

        signer = get_signer_account(w3, role)
        tx_hash = contract.functions.addStageHash(str(batch_id), str(stage).upper(), str(hash_val)).transact({"from": signer})
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        tx_status = receipt.get("status") if isinstance(receipt, dict) else getattr(receipt, "status", None)
        if tx_status != 1:
            return {"status": "error", "error": "Stage anchoring transaction reverted."}

        meta = _extract_receipt_meta(receipt, tx_hash, contract.address, signer)
        meta["status"] = "anchored"
        return meta
    except Exception as exc:
        if is_transport_or_connection_error(exc):
            return {"status": "rpc_offline", "error": str(exc)}
        return {"status": "error", "error": str(exc)}


class BlockchainError(Exception):
    """Base exception for all blockchain errors."""
    pass


class BlockchainUnavailableError(BlockchainError):
    """Raised when Ganache or HTTP RPC is unreachable, refused, or timed out."""
    pass


class BlockchainInvalidAddressError(BlockchainError):
    """Raised when a configured contract address format is invalid."""
    pass


class BlockchainContractMissingCodeError(BlockchainError):
    """Raised when an address has no deployed bytecode on Ganache."""
    pass


class BlockchainContractCallError(BlockchainError):
    """Raised when an EVM call fails, reverts, or fails ABI decoding."""
    pass


def is_transport_or_connection_error(exc: Exception) -> bool:
    """Robustly checks whether an exception represents a transport/connectivity failure."""
    import socket
    exc_str = str(exc).lower()
    exc_type = type(exc).__name__.lower()
    if isinstance(exc, (ConnectionRefusedError, socket.error, TimeoutError)):
        return True
    return any(k in exc_type or k in exc_str for k in [
        "connection refused", "connect failed", "max retries exceeded", "timeout",
        "socket", "connection error", "remotedisconnected", "failed to establish",
        "httperror", "connectionerror"
    ])


# Minimal V1-compatible ABI subset used strictly for querying historical read-only contracts
_READ_HASH_ABI = [
    {
        "inputs": [{"internalType": "string", "name": "batchId", "type": "string"}],
        "name": "getHash",
        "outputs": [{"internalType": "string", "name": "", "type": "string"}],
        "stateMutability": "view",
        "type": "function",
    }
]


def fetch_on_chain_status(batch_id):
    """
    Safely and strictly read-only retrieves the on-chain hash for a given batch ID
    across both active and historical contracts without ever triggering deployment.
    """
    from web3.exceptions import InvalidAddress, BadFunctionCallOutput, ContractLogicError

    try:
        w3 = get_w3(die_on_error=False)
        if not w3 or not w3.is_connected():
            return {
                "status": "rpc_offline",
                "hash": None,
                "contract_address": None,
                "conflict_details": None,
                "error": "RPC node unavailable"
            }

        cfg = load_config()
        abi = cfg.get("abi") or _READ_HASH_ABI
        active_address = cfg.get("contract_address")
        historical_addresses = cfg.get("historical_contract_addresses", [])

        if not active_address and not historical_addresses:
            exc = BlockchainContractMissingCodeError("No active or historical contract addresses configured.")
            return {
                "status": "error",
                "hash": None,
                "contract_address": None,
                "conflict_details": None,
                "error": str(exc),
                "exception": exc
            }

        found_entries = []
        contract_errors = []

        def query_single_contract(addr, c_type, query_abi):
            try:
                checksum_addr = Web3.to_checksum_address(addr)
            except (InvalidAddress, ValueError, TypeError) as err:
                raise BlockchainInvalidAddressError(f"Invalid {c_type} address '{addr}': {err}")

            try:
                code = w3.eth.get_code(checksum_addr)
            except Exception as exc:
                if is_transport_or_connection_error(exc):
                    raise BlockchainUnavailableError(f"RPC communication failed reading bytecode at {addr}: {exc}")
                raise BlockchainError(f"Error checking code at {addr}: {exc}")

            if not code or code in (b'', b'\x00', '0x', b'0x'):
                raise BlockchainContractMissingCodeError(f"No bytecode deployed at {c_type} address: {addr}")

            try:
                contract_obj = w3.eth.contract(address=checksum_addr, abi=query_abi)
                raw_val = contract_obj.functions.getHash(str(batch_id)).call()
                return raw_val.strip() if (raw_val and isinstance(raw_val, str)) else ""
            except BadFunctionCallOutput as err:
                raise BlockchainContractCallError(f"Contract call failed or ABI mismatch at {addr}: {err}")
            except ContractLogicError as err:
                raise BlockchainContractCallError(f"Execution reverted while calling getHash at {addr}: {err}")
            except Exception as exc:
                if is_transport_or_connection_error(exc):
                    raise BlockchainUnavailableError(f"RPC connection dropped while calling getHash at {addr}: {exc}")
                raise BlockchainContractCallError(f"Unexpected contract call error at {addr}: {exc}")

        if active_address:
            try:
                active_val = query_single_contract(active_address, "active", abi)
                if active_val:
                    found_entries.append(("active", active_address, active_val))
            except BlockchainUnavailableError as e:
                return {
                    "status": "rpc_offline",
                    "hash": None,
                    "contract_address": None,
                    "conflict_details": None,
                    "error": str(e),
                    "exception": e
                }
            except Exception as e:
                contract_errors.append(("active", active_address, e))

        for h_addr in historical_addresses:
            if not h_addr or (active_address and h_addr.lower() == active_address.lower()):
                continue
            try:
                h_val = query_single_contract(h_addr, "historical", _READ_HASH_ABI)
                if h_val:
                    found_entries.append(("historical", h_addr, h_val))
            except BlockchainContractMissingCodeError:
                continue
            except BlockchainUnavailableError as e:
                return {
                    "status": "rpc_offline",
                    "hash": None,
                    "contract_address": None,
                    "conflict_details": None,
                    "error": str(e),
                    "exception": e
                }
            except Exception as e:
                contract_errors.append(("historical", h_addr, e))

        if not found_entries:
            if contract_errors:
                first_err = contract_errors[0][2]
                if is_transport_or_connection_error(first_err) or isinstance(first_err, BlockchainUnavailableError):
                    return {
                        "status": "rpc_offline",
                        "hash": None,
                        "contract_address": None,
                        "conflict_details": None,
                        "error": str(first_err),
                        "exception": first_err
                    }
                return {
                    "status": "error",
                    "hash": None,
                    "contract_address": None,
                    "conflict_details": None,
                    "error": str(first_err),
                    "exception": first_err
                }

            return {
                "status": "not_found",
                "hash": None,
                "contract_address": None,
                "conflict_details": None,
                "error": "Batch not recorded on-chain"
            }

        unique_hashes = set(e[2] for e in found_entries)
        if len(unique_hashes) > 1:
            conflict_info = {
                "entries": [{"type": e[0], "address": e[1], "hash": e[2]} for e in found_entries]
            }
            if contract_errors:
                conflict_info["query_errors"] = [
                    {"type": err[0], "address": err[1], "error": str(err[2])} for err in contract_errors
                ]
            return {
                "status": "conflict",
                "hash": None,
                "contract_address": None,
                "conflict_details": conflict_info,
                "error": f"Conflicting on-chain hashes detected for batch {batch_id}"
            }

        if contract_errors:
            first_err = contract_errors[0][2]
            failed_addr = contract_errors[0][1]
            if is_transport_or_connection_error(first_err) or isinstance(first_err, BlockchainUnavailableError):
                return {
                    "status": "rpc_offline",
                    "hash": None,
                    "contract_address": None,
                    "conflict_details": None,
                    "error": f"RPC error while checking contract {failed_addr}: {first_err}",
                    "exception": first_err
                }
            return {
                "status": "error",
                "hash": None,
                "contract_address": None,
                "conflict_details": None,
                "error": f"Incomplete verification: contract query failed at {failed_addr} ({first_err})",
                "exception": first_err
            }

        _, addr, h_val = found_entries[0]
        return {
            "status": "ok",
            "hash": h_val,
            "contract_address": addr,
            "conflict_details": None,
            "error": None
        }
    except Exception as e:
        if is_transport_or_connection_error(e) or isinstance(e, BlockchainUnavailableError):
            return {
                "status": "rpc_offline",
                "hash": None,
                "contract_address": None,
                "conflict_details": None,
                "error": str(e),
                "exception": e
            }
        return {
            "status": "error",
            "hash": None,
            "contract_address": None,
            "conflict_details": None,
            "error": str(e),
            "exception": e
        }


def fetch_v2_provenance_details(batch_id):
    """
    Read-only queries TrustHarvestV2 `getRecord` and `getStageHistory` for a batch.
    Returns { 'available': bool, 'registered_by': str|None, 'timestamp': datetime|None, 'stages': [...] }.
    """
    try:
        w3 = get_w3(die_on_error=False)
        if not w3 or not w3.is_connected():
            return {"available": False, "registered_by": None, "timestamp": None, "stages": []}

        cfg = load_config()
        abi = cfg.get("abi")
        addr = cfg.get("contract_address")
        if not addr or not abi or not _has_v2_abi(abi):
            return {"available": False, "registered_by": None, "timestamp": None, "stages": []}

        checksum_addr = Web3.to_checksum_address(addr)
        code = w3.eth.get_code(checksum_addr)
        if not code or code in (b"", b"\x00", "0x", b"0x"):
            return {"available": False, "registered_by": None, "timestamp": None, "stages": []}

        contract = w3.eth.contract(address=checksum_addr, abi=abi)
        _, reg_by, ts, exists = contract.functions.getRecord(str(batch_id)).call()
        if not exists:
            return {"available": False, "registered_by": None, "timestamp": None, "stages": []}

        stage_count = contract.functions.getStageCount(str(batch_id)).call()
        stages = []
        for idx in range(stage_count):
            stg, d_hash, rec_by, s_ts = contract.functions.getStageRecord(str(batch_id), idx).call()
            stages.append({
                "index": idx,
                "stage": stg,
                "hash": d_hash,
                "recorded_by": rec_by,
                "timestamp": datetime.fromtimestamp(s_ts, tz=timezone.utc) if s_ts else None,
            })

        return {
            "available": True,
            "registered_by": reg_by,
            "timestamp": datetime.fromtimestamp(ts, tz=timezone.utc) if ts else None,
            "stages": stages,
        }
    except Exception:
        return {"available": False, "registered_by": None, "timestamp": None, "stages": []}


def get_hash(batch_id, detailed=False):
    status_info = fetch_on_chain_status(batch_id)
    status = status_info.get("status")

    if not detailed:
        if status == "ok":
            return status_info.get("hash")
        return None

    if status == "rpc_offline":
        raise BlockchainUnavailableError(status_info.get("error") or f"Unable to reach Ethereum/Ganache provider at {GANACHE_URL}.")
    elif status == "error":
        exc = status_info.get("exception")
        if isinstance(exc, BlockchainError):
            raise exc
        raise BlockchainContractCallError(status_info.get("error") or "Smart contract call error occurred.")
    elif status == "conflict":
        return {
            "status": "CONFLICT",
            "hash": None,
            "contract_address": None,
            "conflict_details": status_info.get("conflict_details")
        }
    elif status == "ok":
        return {
            "status": "FOUND",
            "hash": status_info.get("hash"),
            "contract_address": status_info.get("contract_address"),
            "conflict_details": None
        }
    else:
        return {
            "status": "NOT_FOUND",
            "hash": None,
            "contract_address": None,
            "conflict_details": None
        }


def compute_batch_hash(batch_id, name, quantity, farming_method, packaging_date, farmer_id, image):
    data = {
        "batch_id": str(batch_id),
        "farmer_id": int(farmer_id),
        "farming_method": str(farming_method),
        "image": str(image),
        "name": str(name),
        "packaging_date": str(packaging_date),
        "quantity": str(quantity),
    }
    payload = json.dumps(data, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compute_transport_hash(batch_id, status, current_location, temperature, vehicle_number, notes, transporter_id):
    data = {
        "batch_id": str(batch_id),
        "current_location": str(current_location or ""),
        "notes": str(notes or ""),
        "stage": "TRANSPORT",
        "status": str(status or ""),
        "temperature": str(temperature or ""),
        "transporter_id": int(transporter_id),
        "vehicle_number": str(vehicle_number or ""),
    }
    payload = json.dumps(data, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compute_retail_hash(batch_id, store_name, store_location, price, stock_quantity, arrival_date, shelf_life, retailer_id):
    norm_price = f"{float(price):.2f}" if price is not None else "0.00"
    data = {
        "arrival_date": str(arrival_date or ""),
        "batch_id": str(batch_id),
        "price": norm_price,
        "retailer_id": int(retailer_id),
        "shelf_life": str(shelf_life or ""),
        "stage": "RETAIL",
        "stock_quantity": str(stock_quantity or ""),
        "store_location": str(store_location or ""),
        "store_name": str(store_name or ""),
    }
    payload = json.dumps(data, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def get_admin_blockchain_overview(products):
    """
    Retrieves live Ganache node stats, signer wallet balances, smart contract events,
    and performs a real-time DB-vs-Blockchain integrity audit across every batch.
    """
    cfg = load_config()
    active_addr = cfg.get("contract_address") or ""
    abi = cfg.get("abi") or []
    overview = {
        "online": False,
        "chain_id": None,
        "block_number": None,
        "contract_address": active_addr,
        "contract_version": cfg.get("contract_version", "V1"),
        "wallets": [],
        "events": [],
        "audit_map": {},
    }

    w3 = get_w3(die_on_error=False)
    if not w3 or not w3.is_connected():
        for p in products:
            overview["audit_map"][p.batch_id] = "rpc_offline"
        return overview

    try:
        overview["online"] = True
        overview["chain_id"] = w3.eth.chain_id
        overview["block_number"] = w3.eth.block_number

        role_names = ["Admin / Deployer", "Farmer", "Transporter", "Retailer"]
        accounts = w3.eth.accounts
        for idx, role_label in enumerate(role_names):
            if idx < len(accounts):
                addr = accounts[idx]
                bal_eth = float(w3.from_wei(w3.eth.get_balance(addr), "ether"))
                overview["wallets"].append({
                    "index": idx,
                    "role": role_label,
                    "address": addr,
                    "balance_eth": round(bal_eth, 4),
                })

        # Query live smart contract events from block 0
        if active_addr and abi:
            try:
                checksum_addr = Web3.to_checksum_address(active_addr)
                code = w3.eth.get_code(checksum_addr)
                if code and code not in (b"", b"\x00", "0x", b"0x"):
                    contract = w3.eth.contract(address=checksum_addr, abi=abi)
                    raw_events = []

                    try:
                        for ev in contract.events.HashStored.get_logs(fromBlock=0):
                            args = ev.get("args", {})
                            raw_events.append({
                                "event": "HashStored",
                                "stage": "HARVEST",
                                "block_number": ev.get("blockNumber"),
                                "tx_hash": ev.get("transactionHash").hex() if hasattr(ev.get("transactionHash"), "hex") else str(ev.get("transactionHash")),
                                "actor": args.get("registeredBy", ""),
                                "hash": args.get("hash", ""),
                            })
                    except Exception:
                        pass

                    if hasattr(contract.events, "StageAnchored"):
                        try:
                            for ev in contract.events.StageAnchored.get_logs(fromBlock=0):
                                args = ev.get("args", {})
                                raw_events.append({
                                    "event": "StageAnchored",
                                    "stage": args.get("stage", "STAGE"),
                                    "block_number": ev.get("blockNumber"),
                                    "tx_hash": ev.get("transactionHash").hex() if hasattr(ev.get("transactionHash"), "hex") else str(ev.get("transactionHash")),
                                    "actor": args.get("recordedBy", ""),
                                    "hash": args.get("dataHash", ""),
                                })
                        except Exception:
                            pass

                    raw_events.sort(key=lambda e: (e["block_number"] or 0), reverse=True)
                    overview["events"] = raw_events[:25]
            except Exception:
                pass

        # Live batch integrity audit
        for p in products:
            computed = compute_batch_hash(
                batch_id=p.batch_id,
                name=p.name,
                quantity=p.quantity,
                farming_method=p.farming_method,
                packaging_date=p.packaging_date,
                farmer_id=p.farmer_id,
                image=p.image,
            )
            chain = fetch_on_chain_status(p.batch_id)
            st = chain.get("status")
            if st == "ok":
                if str(chain.get("hash") or "").lower() == computed.lower():
                    overview["audit_map"][p.batch_id] = "verified"
                else:
                    overview["audit_map"][p.batch_id] = "tampered"
            elif st == "not_found":
                overview["audit_map"][p.batch_id] = "not_found"
            elif st == "conflict":
                overview["audit_map"][p.batch_id] = "conflict"
            else:
                overview["audit_map"][p.batch_id] = "error"
    except Exception:
        pass

    return overview
