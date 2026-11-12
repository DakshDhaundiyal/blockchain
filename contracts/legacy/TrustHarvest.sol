// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

contract TrustHarvest {
    mapping(string => string) private batchHashes;

    event HashStored(string batchId, string hash);

    function storeHash(string memory batchId, string memory hash) public {
        require(bytes(batchHashes[batchId]).length == 0, "Batch already registered");
        batchHashes[batchId] = hash;
        emit HashStored(batchId, hash);
    }

    function getHash(string memory batchId) public view returns (string memory) {
        return batchHashes[batchId];
    }
}
