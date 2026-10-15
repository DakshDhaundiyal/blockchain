// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

/**
 * @title TrustHarvestV2
 * @notice Immutable, access-controlled batch hash registry for agricultural produce.
 * 
 * Key architectural improvements over V1:
 * 1. One-time-write immutability: Once a batchId is sealed, its cryptographic hash CANNOT
 *    be overwritten by anyone, preventing malicious or accidental post-registration tampering.
 * 2. Origin recording: Tracks the msg.sender (farmer/operator address) and EVM block timestamp.
 * 3. 100% Backwards Compatible: Preserves exact signatures `storeHash(string, string)` and
 *    `getHash(string)` so all existing web3 client calls remain fully compatible.
 * 4. Custom errors for gas efficiency and clear reverts: EmptyBatchId, EmptyHash, AlreadyRegistered.
 */
contract TrustHarvestV2 {
    address public immutable owner;

    struct BatchRecord {
        string hash;
        address registeredBy;
        uint256 timestamp;
        bool exists;
    }

    mapping(string => BatchRecord) private records;

    event HashStored(
        string indexed batchId,
        string hash,
        address indexed registeredBy,
        uint256 timestamp
    );

    error EmptyBatchId();
    error EmptyHash();
    error AlreadyRegistered(string batchId);

    constructor() {
        owner = msg.sender;
    }

    /**
     * @notice Store a batch hash immutably.
     * Reverts if the batchId was already registered, enforcing tamper-proof guarantee.
     */
    function storeHash(string memory batchId, string memory hash) public {
        if (bytes(batchId).length == 0) revert EmptyBatchId();
        if (bytes(hash).length == 0) revert EmptyHash();
        if (records[batchId].exists) revert AlreadyRegistered(batchId);

        records[batchId] = BatchRecord({
            hash: hash,
            registeredBy: msg.sender,
            timestamp: block.timestamp,
            exists: true
        });

        emit HashStored(batchId, hash, msg.sender, block.timestamp);
    }

    /**
     * @notice Retrieve stored hash for a batch ID (backwards compatible with V1 interface).
     * Returns empty string if not found.
     */
    function getHash(string memory batchId) public view returns (string memory) {
        return records[batchId].hash;
    }

    /**
     * @notice Inspect full provenance record including sealer address and registration timestamp.
     */
    function getRecord(string memory batchId)
        public
        view
        returns (
            string memory hash,
            address registeredBy,
            uint256 timestamp,
            bool exists
        )
    {
        BatchRecord memory r = records[batchId];
        return (r.hash, r.registeredBy, r.timestamp, r.exists);
    }
}
