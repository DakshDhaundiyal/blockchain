import os
import pytest
from solcx import compile_standard, install_solc, set_solc_version

def test_trustharvest_v2_solidity_compilation():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    v2_path = os.path.join(base_dir, "contracts", "TrustHarvestV2.sol")
    assert os.path.exists(v2_path), "TrustHarvestV2.sol contract file must exist"

    with open(v2_path, "r", encoding="utf-8") as f:
        source = f.read()

    try:
        install_solc("0.8.19")
    except Exception:
        pass
    set_solc_version("0.8.19")

    compiled = compile_standard(
        {
            "language": "Solidity",
            "sources": {"TrustHarvestV2.sol": {"content": source}},
            "settings": {
                "outputSelection": {
                    "*": {"*": ["abi", "evm.bytecode"]}
                }
            },
        },
        solc_version="0.8.19",
    )

    assert "contracts" in compiled
    assert "TrustHarvestV2.sol" in compiled["contracts"]
    contract_data = compiled["contracts"]["TrustHarvestV2.sol"]["TrustHarvestV2"]
    
    abi = contract_data["abi"]
    bytecode = contract_data["evm"]["bytecode"]["object"]

    assert len(bytecode) > 0, "Compiled bytecode must not be empty"

    # Verify ABI compatibility with V1 methods
    function_names = [item["name"] for item in abi if item.get("type") == "function"]
    assert "storeHash" in function_names, "V2 must preserve storeHash for backwards compatibility"
    assert "getHash" in function_names, "V2 must preserve getHash for backwards compatibility"
    assert "getRecord" in function_names, "V2 provides enhanced getRecord provenance inspection"
    assert "owner" in function_names, "V2 provides owner inspection"

    # Verify error types for gas-efficient immutability
    error_names = [item["name"] for item in abi if item.get("type") == "error"]
    assert "AlreadyRegistered" in error_names, "AlreadyRegistered error prevents hash tampering"
    assert "EmptyBatchId" in error_names
    assert "EmptyHash" in error_names
