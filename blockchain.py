import json
import os
import sys
import hashlib
from web3 import Web3
from solcx import compile_standard, install_solc, set_solc_version

GANACHE_URL = os.environ.get("GANACHE_URL") or os.environ.get("ETH_RPC_URL") or "http://127.0.0.1:7545"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
CONTRACT_PATH = os.path.join(BASE_DIR, "contracts", "TrustHarvest.sol")

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

def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    return {
        "BASE_URL": "http://localhost:5000",
        "contract_address": "",
        "abi": [],
        "bytecode": "",
        "historical_contract_addresses": []
    }

def save_config(cfg):
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)

def compile_contract_if_needed():
    cfg = load_config()
    abi = cfg.get("abi")
    bytecode = cfg.get("bytecode")

    if not abi or not bytecode:
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
                "sources": {"TrustHarvest.sol": {"content": sol_source}},
                "settings": {
                    "outputSelection": {
                        "*": {"*": ["abi", "metadata", "evm.bytecode", "evm.sourceMap"]}
                    }
                },
            },
            solc_version="0.8.19",
        )

        contract_data = compiled_sol["contracts"]["TrustHarvest.sol"]["TrustHarvest"]
        abi = contract_data["abi"]
        bytecode = contract_data["evm"]["bytecode"]["object"]
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
            if not code or code == b"" or code == b"\x00" or code == b"0x" or code == "0x":
                needs_deploy = True
        except Exception:
            needs_deploy = True

    if needs_deploy:
        accounts = w3.eth.accounts
        if not accounts:
            print("Error: No accounts found in Ganache.", file=sys.stderr)
            sys.exit(1)
        deployer = accounts[0]
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
        save_config(cfg)

    final_addr = Web3.to_checksum_address(str(address))
    return w3.eth.contract(address=final_addr, abi=abi)

def store_hash(batch_id, hash_val):
    w3 = get_w3()
    if w3 is None:
        raise BlockchainUnavailableError("Ethereum / Ganache node is unreachable.")
    contract = get_or_deploy_contract(w3)
    deployer = w3.eth.accounts[0]
    tx_hash = contract.functions.storeHash(batch_id, hash_val).transact({"from": deployer})
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    status = receipt.get("status") if isinstance(receipt, dict) else getattr(receipt, "status", None)
    if status != 1:
        tx_hex = tx_hash.hex() if hasattr(tx_hash, "hex") else str(tx_hash)
        raise RuntimeError(f"Transaction failed or reverted on blockchain: {tx_hex}")
    tx_hash_val = receipt.get("transactionHash") if isinstance(receipt, dict) else getattr(receipt, "transactionHash", None)
    if tx_hash_val is not None and hasattr(tx_hash_val, "hex"):
        return tx_hash_val.hex()
    return str(tx_hash_val or "")

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

def fetch_on_chain_status(batch_id):
    """
    Safely and strictly read-only retrieves the on-chain hash for a given batch ID
    across both active and historical contracts without ever triggering deployment.

    Returns a dict with:
      - 'status': 'ok' | 'not_found' | 'conflict' | 'rpc_offline'
      - 'hash': str or None
      - 'contract_address': str or None
      - 'conflict_details': dict or None
      - 'error': str or None
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
        abi = cfg.get("abi")
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

        def query_single_contract(addr, c_type):
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
                contract_obj = w3.eth.contract(address=checksum_addr, abi=abi)
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

        # 1. Query Active Contract
        if active_address:
            try:
                active_val = query_single_contract(active_address, "active")
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

        # 2. Query Historical Contracts
        for h_addr in historical_addresses:
            if not h_addr or (active_address and h_addr.lower() == active_address.lower()):
                continue
            try:
                h_val = query_single_contract(h_addr, "historical")
                if h_val:
                    found_entries.append(("historical", h_addr, h_val))
            except BlockchainContractMissingCodeError:
                # Explicitly known that historical address has no code in this workspace; skip gracefully
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

        # 3. Analyze Findings & Errors
        if not found_entries:
            # If any non-ignorable contract query failed, we must NOT report NOT_FOUND
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

        # If all successful queries returned the same hash, but one or more other configured
        # contracts failed with an unexpected error, conflict detection is incomplete.
        # We must NOT report an unqualified "ok" / "FOUND".
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

        c_type, addr, h_val = found_entries[0]
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

def get_hash(batch_id, detailed=False):
    """
    Retrieves the stored hash for a batch_id across active and historical contracts.

    If detailed=False:
        Returns on-chain hash string if found, else None.
    If detailed=True:
        Returns dict:
            - status: "FOUND" | "NOT_FOUND" | "CONFLICT"
            - hash: str or None
            - contract_address: str or None
            - conflict_details: dict or None

    Raises:
        BlockchainUnavailableError: if Ganache RPC is offline or unreachable.
        BlockchainInvalidAddressError: if address format is invalid.
        BlockchainContractMissingCodeError: if contract address has no deployed bytecode.
        BlockchainContractCallError: if contract call fails or reverts unexpectedly.
    """
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
    else:  # not_found
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
