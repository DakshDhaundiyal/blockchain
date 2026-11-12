import json
import os
import sys
import hashlib
from datetime import datetime, timezone
from web3 import Web3
from solcx import compile_standard, install_solc, set_solc_version

from utils import sanitize_error_text

GANACHE_URL = os.environ.get("ETH_RPC_URL") or os.environ.get("GANACHE_URL") or "http://127.0.0.1:7545"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
CONTRACT_PATH = os.path.join(BASE_DIR, "contracts", "TrustHarvestV2.sol")
CONTRACT_NAME = "TrustHarvestV2"
CONTRACT_VERSION = "V2"
MAX_ONCHAIN_STAGES = 200

_ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
_V2_ARTIFACT_CACHE = {}


def get_rpc_url():
    return (os.environ.get("ETH_RPC_URL") or os.environ.get("GANACHE_URL") or GANACHE_URL or "http://127.0.0.1:7545").strip()


def get_w3(die_on_error=True):
    rpc_url = get_rpc_url()
    try:
        w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 4}))
        if not w3.is_connected():
            if die_on_error:
                print(f"Error: Unable to connect to Ethereum node at {sanitize_error_text(rpc_url)}.", file=sys.stderr)
                sys.exit(1)
            return None
        return w3
    except Exception:
        if die_on_error:
            print(f"Error: Unable to connect to Ethereum node at {sanitize_error_text(rpc_url)}.", file=sys.stderr)
            sys.exit(1)
        return None


def _get_private_key_for_role(role="farmer"):
    role_l = (role or "farmer").strip().lower()
    env_map = {
        "admin": "DEPLOYER_PRIVATE_KEY",
        "deployer": "DEPLOYER_PRIVATE_KEY",
        "farmer": "FARMER_PRIVATE_KEY",
        "transporter": "TRANSPORTER_PRIVATE_KEY",
        "retailer": "RETAILER_PRIVATE_KEY",
    }
    key_var = env_map.get(role_l)
    raw = (os.environ.get(key_var) if key_var else None) or os.environ.get("SIGNER_PRIVATE_KEY")
    if raw and raw.strip():
        return raw.strip()
    return None


def get_signer_account(w3, role="farmer"):
    """
    Resolves the signing Ethereum address for a stakeholder role.
    Uses server-held private keys from environment variables first,
    then falls back to unlocked local Ganache accounts in dev mode.
    """
    pk = _get_private_key_for_role(role)
    if pk:
        from eth_account import Account
        return Account.from_key(pk).address

    accounts = getattr(w3.eth, "accounts", []) or []
    if not accounts:
        raise BlockchainUnavailableError("No server signing key or local blockchain account is configured.")

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
    """
    Returns runtime configuration sourced from environment variables first,
    with optional local config.json fallback for local Ganache development.
    """
    cfg = {}
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f) or {}
        except Exception:
            cfg = {}

    hist_list = []
    env_hist = os.environ.get("HISTORICAL_CONTRACT_ADDRESSES", "").strip()
    if env_hist:
        if env_hist.startswith("["):
            try:
                parsed = json.loads(env_hist)
                if isinstance(parsed, list):
                    hist_list = [str(x).strip() for x in parsed if str(x).strip()]
            except Exception:
                pass
        if not hist_list:
            hist_list = [p.strip() for p in env_hist.replace(";", ",").split(",") if p.strip()]
    else:
        hist_list = [str(x).strip() for x in (cfg.get("historical_contract_addresses") or []) if str(x).strip()]

    active_addr = (os.environ.get("CONTRACT_ADDRESS") or cfg.get("contract_address") or "").strip()
    base_url = (os.environ.get("BASE_URL") or cfg.get("BASE_URL") or "").strip()

    return {
        "BASE_URL": base_url,
        "contract_version": CONTRACT_VERSION,
        "contract_address": active_addr,
        "historical_contract_addresses": hist_list,
    }


def _save_local_contract_address(address: str):
    """Best-effort local Ganache dev persistence of deployed contract address."""
    if os.environ.get("CONTRACT_ADDRESS") or os.environ.get("RENDER") or os.environ.get("PRODUCTION") == "true":
        return
    cfg = {}
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f) or {}
        except Exception:
            cfg = {}
    cfg["contract_version"] = CONTRACT_VERSION
    cfg["contract_address"] = address
    cfg.setdefault("historical_contract_addresses", [])
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def compile_contract_if_needed():
    if "abi" in _V2_ARTIFACT_CACHE and "bytecode" in _V2_ARTIFACT_CACHE:
        return _V2_ARTIFACT_CACHE["abi"], _V2_ARTIFACT_CACHE["bytecode"]

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
    _V2_ARTIFACT_CACHE["abi"] = abi
    _V2_ARTIFACT_CACHE["bytecode"] = bytecode
    return abi, bytecode


def _send_tx_with_signer(w3, tx_callable, role="farmer"):
    """
    Executes a contract transaction using server-side private-key signing when configured,
    or local Ganache unlocked accounts during local development.
    """
    pk = _get_private_key_for_role(role)
    signer = get_signer_account(w3, role)

    if pk:
        chain_id_env = os.environ.get("CHAIN_ID")
        chain_id = int(chain_id_env) if (chain_id_env and chain_id_env.strip().isdigit()) else w3.eth.chain_id
        checksum_signer = Web3.to_checksum_address(signer)
        nonce = w3.eth.get_transaction_count(checksum_signer, "pending")
        tx_params = {
            "from": checksum_signer,
            "nonce": nonce,
            "chainId": chain_id,
            "gasPrice": w3.eth.gas_price,
        }
        try:
            est = tx_callable.estimate_gas({"from": checksum_signer})
            tx_params["gas"] = int(est * 1.2)
        except Exception:
            tx_params["gas"] = 450000
        built = tx_callable.build_transaction(tx_params)
        signed = w3.eth.account.sign_transaction(built, private_key=pk)
        raw_tx = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction")
        tx_hash = w3.eth.send_raw_transaction(raw_tx)
        return tx_hash, checksum_signer

    # Local Ganache dev unlocked account path
    tx_hash = tx_callable.transact({"from": signer})
    return tx_hash, signer


def get_or_deploy_contract(w3=None):
    if w3 is None:
        w3 = get_w3()
    if w3 is None:
        raise BlockchainUnavailableError("Ethereum node is unreachable.")

    cfg = load_config()
    address = cfg.get("contract_address")

    if address:
        try:
            checksum_addr = Web3.to_checksum_address(address)
            code = w3.eth.get_code(checksum_addr)
            if code and code not in (b"", b"\x00", b"0x", "0x"):
                test_contract = w3.eth.contract(address=checksum_addr, abi=_V2_RUNTIME_ABI)
                test_contract.functions.getStageCount("__probe__").call()
                return test_contract
        except Exception:
            pass

    # If auto-deploy is disabled on configured public networks, never invoke solc or spend ETH
    if os.environ.get("CONTRACT_ADDRESS") and os.environ.get("ALLOW_AUTO_DEPLOY", "false").lower() != "true":
        raise BlockchainContractMissingCodeError(
            "Configured CONTRACT_ADDRESS has no TrustHarvestV2 bytecode on the connected network."
        )

    abi, bytecode = compile_contract_if_needed()
    Contract = w3.eth.contract(abi=abi, bytecode=bytecode)
    tx_hash, _ = _send_tx_with_signer(w3, Contract.constructor(), role="deployer")
    tx_receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=90)
    if getattr(tx_receipt, "status", None) != 1:
        raise BlockchainError("Contract deployment transaction failed.")
    deployed_address = tx_receipt.get("contractAddress") if isinstance(tx_receipt, dict) else getattr(tx_receipt, "contractAddress", None)
    if not deployed_address:
        raise BlockchainError("Contract deployment receipt did not include a contract address.")
    _save_local_contract_address(str(deployed_address))

    final_addr = Web3.to_checksum_address(str(deployed_address))
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
        "contract_version": CONTRACT_VERSION,
        "signer_address": signer_address,
        "gas_used": int(gas_used) if gas_used is not None else None,
    }


def _is_quota_or_rate_error(exc: Exception) -> bool:
    s = str(exc).lower()
    return any(tok in s for tok in ("429", "too many requests", "rate limit", "compute unit", "quota"))


def store_hash_detailed(batch_id, hash_val, role="farmer"):
    w3 = get_w3()
    if w3 is None:
        raise BlockchainUnavailableError("Ethereum node is unreachable.")
    try:
        contract = get_or_deploy_contract(w3)
        tx_hash, signer = _send_tx_with_signer(
            w3,
            contract.functions.storeHash(batch_id, hash_val),
            role=role,
        )
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=90)
        status = receipt.get("status") if isinstance(receipt, dict) else getattr(receipt, "status", None)
        if status != 1:
            raise RuntimeError("Transaction failed or reverted on blockchain.")
        return _extract_receipt_meta(receipt, tx_hash, contract.address, signer)
    except Exception as exc:
        if _is_quota_or_rate_error(exc):
            raise BlockchainUnavailableError("Blockchain free-tier request limit reached. Please retry shortly.")
        raise BlockchainError(sanitize_error_text(str(exc)))


def store_hash(batch_id, hash_val):
    meta = store_hash_detailed(batch_id, hash_val, role="farmer")
    return meta["tx_hash"]


def store_stage_hash(batch_id, stage, hash_val, role="transporter", contract_address=None):
    """
    Best-effort / safe stage anchoring on TrustHarvestV2 for TRANSPORT and RETAIL stages.
    Returns dict with 'status': 'anchored' | 'rpc_offline' | 'batch_not_registered' | 'error'.
    """
    try:
        w3 = get_w3(die_on_error=False)
        if not w3 or not w3.is_connected():
            return {"status": "rpc_offline", "error": "Blockchain node offline."}

        if contract_address:
            checksum_addr = Web3.to_checksum_address(contract_address)
            contract = w3.eth.contract(address=checksum_addr, abi=_V2_RUNTIME_ABI)
        else:
            contract = get_or_deploy_contract(w3)
        # Ensure harvest batch exists in active V2 contract before appending stage
        try:
            _, _, _, exists = contract.functions.getRecord(str(batch_id)).call()
            if not exists:
                return {
                    "status": "batch_not_registered",
                    "error": f"Batch {batch_id} is not registered on the active V2 contract.",
                }
        except Exception as check_err:
            return {"status": "error", "error": sanitize_error_text(str(check_err))}

        tx_hash, signer = _send_tx_with_signer(
            w3,
            contract.functions.addStageHash(str(batch_id), str(stage).upper(), str(hash_val)),
            role=role,
        )
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=90)
        tx_status = receipt.get("status") if isinstance(receipt, dict) else getattr(receipt, "status", None)
        if tx_status != 1:
            return {"status": "error", "error": "Stage anchoring transaction reverted."}

        meta = _extract_receipt_meta(receipt, tx_hash, contract.address, signer)
        meta["status"] = "anchored"
        return meta
    except Exception as exc:
        if is_transport_or_connection_error(exc) or _is_quota_or_rate_error(exc):
            return {"status": "rpc_offline", "error": sanitize_error_text(str(exc))}
        return {"status": "error", "error": sanitize_error_text(str(exc))}


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

# Read-only V2 inspection ABI + events so historical or rotated V2 contracts work without compiling Solidity
_READ_V2_ABI = [
    {
        "inputs": [{"internalType": "string", "name": "batchId", "type": "string"}],
        "name": "getHash",
        "outputs": [{"internalType": "string", "name": "", "type": "string"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "string", "name": "batchId", "type": "string"}],
        "name": "getRecord",
        "outputs": [
            {"internalType": "string", "name": "hash", "type": "string"},
            {"internalType": "address", "name": "registeredBy", "type": "address"},
            {"internalType": "uint256", "name": "timestamp", "type": "uint256"},
            {"internalType": "bool", "name": "exists", "type": "bool"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "string", "name": "batchId", "type": "string"}],
        "name": "getStageCount",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "string", "name": "batchId", "type": "string"},
            {"internalType": "uint256", "name": "index", "type": "uint256"},
        ],
        "name": "getStageRecord",
        "outputs": [
            {"internalType": "string", "name": "stage", "type": "string"},
            {"internalType": "string", "name": "dataHash", "type": "string"},
            {"internalType": "address", "name": "recordedBy", "type": "address"},
            {"internalType": "uint256", "name": "timestamp", "type": "uint256"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "string", "name": "batchId", "type": "string"},
            {"indexed": False, "internalType": "string", "name": "hash", "type": "string"},
            {"indexed": True, "internalType": "address", "name": "registeredBy", "type": "address"},
            {"indexed": False, "internalType": "uint256", "name": "timestamp", "type": "uint256"},
        ],
        "name": "HashStored",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "string", "name": "batchId", "type": "string"},
            {"indexed": False, "internalType": "string", "name": "stage", "type": "string"},
            {"indexed": False, "internalType": "string", "name": "dataHash", "type": "string"},
            {"indexed": True, "internalType": "address", "name": "recordedBy", "type": "address"},
            {"indexed": False, "internalType": "uint256", "name": "timestamp", "type": "uint256"},
        ],
        "name": "StageAnchored",
        "type": "event",
    },
]

_V2_RUNTIME_ABI = _READ_V2_ABI + [
    {
        "inputs": [
            {"internalType": "string", "name": "batchId", "type": "string"},
            {"internalType": "string", "name": "hash", "type": "string"},
        ],
        "name": "storeHash",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "string", "name": "batchId", "type": "string"},
            {"internalType": "string", "name": "stage", "type": "string"},
            {"internalType": "string", "name": "dataHash", "type": "string"},
        ],
        "name": "addStageHash",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
]


def _parse_csv_addresses(raw_val: str | None) -> set[str]:
    if not raw_val:
        return set()
    items = []
    for part in str(raw_val).replace(";", ",").split(","):
        s = part.strip()
        if s:
            items.append(s.lower())
    return set(items)


def _address_from_private_key(pk: str | None) -> str | None:
    if not pk or not str(pk).strip():
        return None
    try:
        from eth_account import Account
        return Account.from_key(str(pk).strip()).address.lower()
    except Exception:
        return None


def get_expected_role_signers(w3=None) -> dict[str, set[str]] | None:
    """
    Returns lowercase allowlisted signer addresses per role ('farmer', 'transporter', 'retailer')
    from server-side keys / environment allowlists, or active local Ganache role accounts.
    Returns None if no signer policy can be determined safely.
    """
    role_map: dict[str, set[str]] = {
        "farmer": set(),
        "transporter": set(),
        "retailer": set(),
    }

    env_explicit = {
        "farmer": os.environ.get("EXPECTED_FARMER_SIGNERS"),
        "transporter": os.environ.get("EXPECTED_TRANSPORTER_SIGNERS"),
        "retailer": os.environ.get("EXPECTED_RETAILER_SIGNERS"),
    }
    env_keys = {
        "farmer": os.environ.get("FARMER_PRIVATE_KEY") or os.environ.get("SIGNER_PRIVATE_KEY"),
        "transporter": os.environ.get("TRANSPORTER_PRIVATE_KEY") or os.environ.get("SIGNER_PRIVATE_KEY"),
        "retailer": os.environ.get("RETAILER_PRIVATE_KEY") or os.environ.get("SIGNER_PRIVATE_KEY"),
    }

    has_env_config = False
    for role in ("farmer", "transporter", "retailer"):
        parsed = _parse_csv_addresses(env_explicit[role])
        if parsed:
            role_map[role].update(parsed)
            has_env_config = True
        derived = _address_from_private_key(env_keys[role])
        if derived:
            role_map[role].add(derived)
            has_env_config = True

    if has_env_config:
        return role_map

    # Fallback on local Ganache: use deterministic role accounts[1..3] (or [0] if single-account node)
    if w3 is not None:
        try:
            accounts = list(getattr(w3.eth, "accounts", []) or [])
            if accounts:
                role_map["farmer"].add((accounts[1] if 1 < len(accounts) else accounts[0]).lower())
                role_map["transporter"].add((accounts[2] if 2 < len(accounts) else accounts[0]).lower())
                role_map["retailer"].add((accounts[3] if 3 < len(accounts) else accounts[0]).lower())
                return role_map
        except Exception:
            pass

    return None


def _collect_configured_contract_addresses() -> tuple[str | None, list[str]]:
    cfg = load_config()
    active_addr = (os.environ.get("CONTRACT_ADDRESS") or cfg.get("contract_address") or "").strip() or None

    historical: list[str] = []
    env_hist = os.environ.get("HISTORICAL_CONTRACT_ADDRESSES")
    if env_hist:
        for item in env_hist.replace(";", ",").split(","):
            s = item.strip()
            if s and s not in historical:
                historical.append(s)

    for item in (cfg.get("historical_contract_addresses") or []):
        s = str(item).strip()
        if s and s not in historical:
            historical.append(s)

    return active_addr, historical


def _probe_contract_readonly(w3, addr: str, batch_id: str, hint_version: str | None = None) -> dict:
    """
    Strictly read-only probes a single contract address for batch_id.
    Automatically handles both TrustHarvestV2 and legacy V1 contracts without writes/deployments.
    """
    from web3.exceptions import InvalidAddress, BadFunctionCallOutput, ContractLogicError

    try:
        checksum_addr = Web3.to_checksum_address(addr)
    except (InvalidAddress, ValueError, TypeError) as err:
        raise BlockchainInvalidAddressError(f"Invalid contract address '{addr}': {err}")

    try:
        code = w3.eth.get_code(checksum_addr)
    except Exception as exc:
        if is_transport_or_connection_error(exc):
            raise BlockchainUnavailableError(f"RPC communication failed reading bytecode at {addr}: {exc}")
        raise BlockchainError(f"Error checking code at {addr}: {exc}")

    if not code or code in (b"", b"\x00", "0x", b"0x"):
        raise BlockchainContractMissingCodeError(f"No bytecode deployed at address: {addr}")

    # Probe V2 first unless explicitly tagged V1
    if (hint_version or "").upper() != "V1":
        try:
            v2_contract = w3.eth.contract(address=checksum_addr, abi=_READ_V2_ABI)
            h_val, reg_by, ts, exists = v2_contract.functions.getRecord(str(batch_id)).call()
            # Also confirm getStageCount is supported on this contract (distinguishes V2 from V1)
            stage_count = int(v2_contract.functions.getStageCount(str(batch_id)).call())
            stages = []
            truncated = False
            if exists:
                read_limit = min(stage_count, MAX_ONCHAIN_STAGES)
                truncated = stage_count > MAX_ONCHAIN_STAGES
                for idx in range(read_limit):
                    stg, d_hash, rec_by, s_ts = v2_contract.functions.getStageRecord(str(batch_id), idx).call()
                    stages.append({
                        "index": idx,
                        "stage": str(stg or "").upper(),
                        "hash": (d_hash or "").strip(),
                        "recorded_by": rec_by,
                        "timestamp": datetime.fromtimestamp(s_ts, tz=timezone.utc) if s_ts else None,
                    })
            return {
                "contract_address": checksum_addr,
                "contract_version": "V2",
                "exists": bool(exists),
                "hash": (h_val or "").strip() if exists else "",
                "registered_by": reg_by if exists else None,
                "timestamp": datetime.fromtimestamp(ts, tz=timezone.utc) if (exists and ts) else None,
                "stages": stages,
                "stage_count": stage_count,
                "truncated": truncated,
            }
        except (BadFunctionCallOutput, ContractLogicError):
            # Not a V2 contract -> fall through cleanly to V1 read-only getHash()
            pass
        except Exception as exc:
            if is_transport_or_connection_error(exc):
                raise BlockchainUnavailableError(f"RPC connection dropped while reading V2 contract at {addr}: {exc}")
            # Fall through cleanly to V1 attempt before failing

    # Read-only V1 contract query
    try:
        v1_contract = w3.eth.contract(address=checksum_addr, abi=_READ_HASH_ABI)
        raw_val = v1_contract.functions.getHash(str(batch_id)).call()
        clean_hash = raw_val.strip() if (raw_val and isinstance(raw_val, str)) else ""
        return {
            "contract_address": checksum_addr,
            "contract_version": "V1",
            "exists": bool(clean_hash),
            "hash": clean_hash,
            "registered_by": None,
            "timestamp": None,
            "stages": [],
            "stage_count": 0,
            "truncated": False,
        }
    except BadFunctionCallOutput as err:
        raise BlockchainContractCallError(f"Contract call failed or ABI mismatch at {addr}: {err}")
    except ContractLogicError as err:
        raise BlockchainContractCallError(f"Execution reverted while calling getHash at {addr}: {err}")
    except Exception as exc:
        if is_transport_or_connection_error(exc):
            raise BlockchainUnavailableError(f"RPC connection dropped while calling getHash at {addr}: {exc}")
        raise BlockchainContractCallError(f"Unexpected contract call error at {addr}: {exc}")


def inspect_batch_on_chain(
    batch_id: str,
    recorded_contract_address: str | None = None,
    recorded_contract_version: str | None = None,
) -> dict:
    """
    Honest, strictly read-only on-chain verification query across the batch's recorded contract
    and configured active/historical contracts. Never compiles, writes, migrates, or deploys.
    """
    try:
        w3 = get_w3(die_on_error=False)
        if not w3 or not w3.is_connected():
            return {
                "status": "rpc_offline",
                "hash": None,
                "contract_address": None,
                "contract_version": None,
                "registered_by": None,
                "timestamp": None,
                "stages": [],
                "truncated": False,
                "expected_signers": None,
                "conflict_details": None,
                "error": "Blockchain RPC node unavailable",
            }

        active_address, historical_addresses = _collect_configured_contract_addresses()

        # Order candidates cleanly without duplicates (case-insensitive)
        candidates: list[tuple[str, str, str | None]] = []
        seen: set[str] = set()

        def _add_candidate(addr: str | None, c_type: str, hint_ver: str | None):
            if not addr:
                return
            low = addr.strip().lower()
            if low and low not in seen:
                seen.add(low)
                candidates.append((c_type, addr.strip(), hint_ver))

        if recorded_contract_address:
            _add_candidate(recorded_contract_address, "recorded", recorded_contract_version)
        _add_candidate(active_address, "active", "V2")
        for h_addr in historical_addresses:
            _add_candidate(h_addr, "historical", None)

        if not candidates:
            return {
                "status": "not_found",
                "hash": None,
                "contract_address": None,
                "contract_version": None,
                "registered_by": None,
                "timestamp": None,
                "stages": [],
                "truncated": False,
                "expected_signers": get_expected_role_signers(w3),
                "conflict_details": None,
                "error": "No contract addresses configured",
            }

        found_entries: list[tuple[str, dict]] = []
        contract_errors: list[tuple[str, str, Exception]] = []

        for c_type, addr, hint_ver in candidates:
            try:
                res = _probe_contract_readonly(w3, addr, batch_id, hint_version=hint_ver)
                if res["exists"] and res["hash"]:
                    found_entries.append((c_type, res))
            except BlockchainUnavailableError as err:
                return {
                    "status": "rpc_offline",
                    "hash": None,
                    "contract_address": None,
                    "contract_version": None,
                    "registered_by": None,
                    "timestamp": None,
                    "stages": [],
                    "truncated": False,
                    "expected_signers": None,
                    "conflict_details": None,
                    "error": str(err),
                }
            except BlockchainContractMissingCodeError as err:
                # If the batch's explicitly recorded contract has no bytecode (e.g. local node reset),
                # report not_found / missing cleanly; ignore unpopulated historical slots otherwise.
                if c_type == "recorded":
                    contract_errors.append((c_type, addr, err))
                continue
            except Exception as err:
                contract_errors.append((c_type, addr, err))

        expected_signers = get_expected_role_signers(w3)

        if not found_entries:
            if contract_errors:
                # If recorded contract simply has no bytecode on this network (chain reset / wrong network),
                # treat as not_found unless it was an actual call/address error.
                non_missing = [e for e in contract_errors if not isinstance(e[2], BlockchainContractMissingCodeError)]
                if non_missing:
                    first_err = non_missing[0][2]
                    if is_transport_or_connection_error(first_err) or isinstance(first_err, BlockchainUnavailableError):
                        return {
                            "status": "rpc_offline",
                            "hash": None,
                            "contract_address": None,
                            "contract_version": None,
                            "registered_by": None,
                            "timestamp": None,
                            "stages": [],
                            "truncated": False,
                            "expected_signers": expected_signers,
                            "conflict_details": None,
                            "error": str(first_err),
                        }
                    return {
                        "status": "error",
                        "hash": None,
                        "contract_address": None,
                        "contract_version": None,
                        "registered_by": None,
                        "timestamp": None,
                        "stages": [],
                        "truncated": False,
                        "expected_signers": expected_signers,
                        "conflict_details": None,
                        "error": str(first_err),
                    }
            return {
                "status": "not_found",
                "hash": None,
                "contract_address": None,
                "contract_version": None,
                "registered_by": None,
                "timestamp": None,
                "stages": [],
                "truncated": False,
                "expected_signers": expected_signers,
                "conflict_details": None,
                "error": "Batch not recorded on-chain",
            }

        unique_hashes = {entry[1]["hash"].lower() for entry in found_entries}
        if len(unique_hashes) > 1:
            return {
                "status": "conflict",
                "hash": None,
                "contract_address": None,
                "contract_version": None,
                "registered_by": None,
                "timestamp": None,
                "stages": [],
                "truncated": False,
                "expected_signers": expected_signers,
                "conflict_details": {
                    "entries": [
                        {
                            "type": e[0],
                            "address": e[1]["contract_address"],
                            "version": e[1]["contract_version"],
                            "hash": e[1]["hash"],
                        }
                        for e in found_entries
                    ]
                },
                "error": f"Conflicting on-chain hashes detected for batch {batch_id}",
            }

        if contract_errors:
            non_missing = [e for e in contract_errors if not isinstance(e[2], BlockchainContractMissingCodeError)]
            if non_missing:
                first_err = non_missing[0][2]
                failed_addr = non_missing[0][1]
                return {
                    "status": "error",
                    "hash": None,
                    "contract_address": None,
                    "contract_version": None,
                    "registered_by": None,
                    "timestamp": None,
                    "stages": [],
                    "truncated": False,
                    "expected_signers": expected_signers,
                    "conflict_details": None,
                    "error": f"Incomplete verification: contract query failed at {failed_addr} ({first_err})",
                }

        # Prefer recorded contract entry if present, otherwise first found
        chosen = found_entries[0][1]
        for c_type, res in found_entries:
            if c_type == "recorded":
                chosen = res
                break

        return {
            "status": "ok",
            "hash": chosen["hash"],
            "contract_address": chosen["contract_address"],
            "contract_version": chosen["contract_version"],
            "registered_by": chosen["registered_by"],
            "timestamp": chosen["timestamp"],
            "stages": chosen["stages"],
            "truncated": chosen["truncated"],
            "expected_signers": expected_signers,
            "conflict_details": None,
            "error": None,
        }
    except Exception as exc:
        if is_transport_or_connection_error(exc) or isinstance(exc, BlockchainUnavailableError):
            return {
                "status": "rpc_offline",
                "hash": None,
                "contract_address": None,
                "contract_version": None,
                "registered_by": None,
                "timestamp": None,
                "stages": [],
                "truncated": False,
                "expected_signers": None,
                "conflict_details": None,
                "error": str(exc),
            }
        return {
            "status": "error",
            "hash": None,
            "contract_address": None,
            "contract_version": None,
            "registered_by": None,
            "timestamp": None,
            "stages": [],
            "truncated": False,
            "expected_signers": None,
            "conflict_details": None,
            "error": str(exc),
        }


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
        abi = _READ_V2_ABI
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


def fetch_v2_provenance_details(batch_id, contract_address=None):
    """
    Read-only queries TrustHarvestV2 `getRecord` and `getStageHistory` for a batch.
    Returns { 'available': bool, 'registered_by': str|None, 'timestamp': datetime|None, 'stages': [...] }.
    """
    try:
        w3 = get_w3(die_on_error=False)
        if not w3 or not w3.is_connected():
            return {"available": False, "registered_by": None, "timestamp": None, "stages": []}

        cfg = load_config()
        addr = (contract_address or cfg.get("contract_address") or "").strip()
        if not addr:
            return {"available": False, "registered_by": None, "timestamp": None, "stages": []}

        checksum_addr = Web3.to_checksum_address(addr)
        code = w3.eth.get_code(checksum_addr)
        if not code or code in (b"", b"\x00", "0x", b"0x"):
            return {"available": False, "registered_by": None, "timestamp": None, "stages": []}

        contract = w3.eth.contract(address=checksum_addr, abi=_READ_V2_ABI)
        _, reg_by, ts, exists = contract.functions.getRecord(str(batch_id)).call()
        if not exists:
            return {"available": False, "registered_by": None, "timestamp": None, "stages": []}

        stage_count = int(contract.functions.getStageCount(str(batch_id)).call())
        stages = []
        for idx in range(min(stage_count, MAX_ONCHAIN_STAGES)):
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
        raise BlockchainUnavailableError(
            sanitize_error_text(
                status_info.get("error") or f"Unable to reach Ethereum node at {get_rpc_url()}."
            )
        )
    elif status == "error":
        exc = status_info.get("exception")
        if isinstance(exc, BlockchainError):
            raise exc
        raise BlockchainContractCallError(sanitize_error_text(status_info.get("error") or "Smart contract call error occurred."))
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


def _fetch_event_logs(event_cls, latest_block):
    """Fetches logs safely across both Web3 v8 (from_block) and older providers."""
    try:
        return list(event_cls.get_logs(from_block=0))
    except TypeError:
        try:
            return list(event_cls.get_logs(fromBlock=0))
        except Exception:
            pass
    except Exception:
        pass
    # Fallback for free-tier RPC providers that restrict block ranges (e.g. Alchemy 10-block or 2k-block cap)
    if latest_block is not None:
        try:
            start_blk = max(0, int(latest_block) - 500)
            return list(event_cls.get_logs(from_block=start_blk, to_block="latest"))
        except Exception:
            pass
    return []


def get_admin_blockchain_overview(products):
    """
    Retrieves live Ethereum node stats, public signer addresses/balances (never private keys),
    smart contract events, and performs a DB-vs-Blockchain integrity audit across every batch.
    """
    cfg = load_config()
    active_addr = cfg.get("contract_address") or ""
    overview = {
        "online": False,
        "chain_id": None,
        "block_number": None,
        "contract_address": active_addr,
        "contract_version": cfg.get("contract_version", "V2"),
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
        latest_block = w3.eth.block_number
        overview["block_number"] = latest_block

        role_defs = [
            ("deployer", "Admin / Deployer"),
            ("farmer", "Farmer"),
            ("transporter", "Transporter"),
            ("retailer", "Retailer"),
        ]
        try:
            ganache_accounts = list(getattr(w3.eth, "accounts", []) or [])
        except Exception:
            ganache_accounts = []

        for idx, (r_key, role_label) in enumerate(role_defs):
            pk = _get_private_key_for_role(r_key)
            addr = None
            if pk:
                from eth_account import Account
                addr = Account.from_key(pk).address
            elif idx < len(ganache_accounts):
                addr = ganache_accounts[idx]

            if addr:
                try:
                    bal_eth = round(float(w3.from_wei(w3.eth.get_balance(addr), "ether")), 4)
                except Exception:
                    bal_eth = 0.0
                overview["wallets"].append({
                    "index": idx,
                    "role": role_label,
                    "address": addr,
                    "balance_eth": bal_eth,
                })

        # Query live smart contract events cleanly without compiling Solidity
        if active_addr:
            try:
                checksum_addr = Web3.to_checksum_address(active_addr)
                code = w3.eth.get_code(checksum_addr)
                if code and code not in (b"", b"\x00", "0x", b"0x"):
                    contract = w3.eth.contract(address=checksum_addr, abi=_READ_V2_ABI)
                    raw_events = []

                    for ev in _fetch_event_logs(contract.events.HashStored, latest_block):
                        args = ev.get("args", {})
                        txh = ev.get("transactionHash")
                        raw_events.append({
                            "event": "HashStored",
                            "stage": "HARVEST",
                            "block_number": ev.get("blockNumber"),
                            "tx_hash": txh.hex() if hasattr(txh, "hex") else str(txh),
                            "actor": args.get("registeredBy", ""),
                            "hash": args.get("hash", ""),
                        })

                    for ev in _fetch_event_logs(contract.events.StageAnchored, latest_block):
                        args = ev.get("args", {})
                        txh = ev.get("transactionHash")
                        raw_events.append({
                            "event": "StageAnchored",
                            "stage": args.get("stage", "STAGE"),
                            "block_number": ev.get("blockNumber"),
                            "tx_hash": txh.hex() if hasattr(txh, "hex") else str(txh),
                            "actor": args.get("recordedBy", ""),
                            "hash": args.get("dataHash", ""),
                        })

                    raw_events.sort(key=lambda e: (e["block_number"] or 0), reverse=True)
                    overview["events"] = raw_events[:25]
            except Exception:
                pass

        # Live batch integrity audit respecting V1 & V2 recorded contracts
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
            chain = inspect_batch_on_chain(
                p.batch_id,
                recorded_contract_address=p.contract_address,
                recorded_contract_version=p.contract_version,
            )
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
            elif st == "rpc_offline":
                overview["audit_map"][p.batch_id] = "rpc_offline"
            else:
                overview["audit_map"][p.batch_id] = "error"
    except Exception:
        pass

    return overview
