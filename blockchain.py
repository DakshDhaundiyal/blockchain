import json
import os
import sys
import hashlib
from web3 import Web3
from solcx import compile_standard, install_solc, set_solc_version

GANACHE_URL = "http://127.0.0.1:7545"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
CONTRACT_PATH = os.path.join(BASE_DIR, "contracts", "TrustHarvest.sol")

def get_w3():
    try:
        w3 = Web3(Web3.HTTPProvider(GANACHE_URL, request_kwargs={"timeout": 5}))
        if not w3.is_connected():
            print(f"Error: Unable to connect to Ganache at {GANACHE_URL}. Please ensure Ganache is running.", file=sys.stderr)
            sys.exit(1)
        return w3
    except Exception:
        print(f"Error: Unable to connect to Ganache at {GANACHE_URL}. Please ensure Ganache is running.", file=sys.stderr)
        sys.exit(1)

def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    return {
        "BASE_URL": "http://localhost:5000",
        "contract_address": "",
        "abi": [],
        "bytecode": ""
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
        address = tx_receipt.contractAddress
        cfg["contract_address"] = address
        save_config(cfg)

    return w3.eth.contract(address=Web3.to_checksum_address(address), abi=abi)

def store_hash(batch_id, hash_val):
    w3 = get_w3()
    contract = get_or_deploy_contract(w3)
    deployer = w3.eth.accounts[0]
    tx_hash = contract.functions.storeHash(batch_id, hash_val).transact({"from": deployer})
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    return receipt.transactionHash.hex()

def get_hash(batch_id):
    w3 = get_w3()
    contract = get_or_deploy_contract(w3)
    return contract.functions.getHash(batch_id).call()

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
