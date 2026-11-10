// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

/**
 * @title TrustHarvestV2
 * @notice Immutable, multi-stage provenance & batch hash registry for agricultural produce.
 *
 * Key architectural improvements over V1:
 * 1. One-time-write harvest immutability: Once a batchId is sealed, its harvest hash CANNOT
 *    be overwritten by anyone, preventing malicious or accidental post-registration tampering.
 * 2. Multi-stage supply chain anchoring: Supports append-only cryptographic anchoring for
 *    Transport checkpoints and Retail listings via `addStageHash(batchId, stage, dataHash)`.
 * 3. Origin & actor recording: Tracks msg.sender (farmer/transporter/retailer wallet) and
 *    EVM block.timestamp for every harvest seal and supply-chain event.
 * 4. 100% Backwards Compatible: Preserves exact signatures `storeHash(string, string)` and
 *    `getHash(string)` so all existing web3 client calls remain fully compatible.
 * 5. Custom errors for gas efficiency and clear reverts.
 */
contract TrustHarvestV2 {
    address public immutable owner;

    struct BatchRecord {
        string hash;
        address registeredBy;
        uint256 timestamp;
        bool exists;
    }

    struct StageRecord {
        string stage;
        string dataHash;
        address recordedBy;
        uint256 timestamp;
    }

    mapping(string => BatchRecord) private records;
    mapping(string => StageRecord[]) private stageHistory;

    event HashStored(
        string indexed batchId,
        string hash,
        address indexed registeredBy,
        uint256 timestamp
    );

    event StageAnchored(
        string indexed batchId,
        string stage,
        string dataHash,
        address indexed recordedBy,
        uint256 timestamp
    );

    error EmptyBatchId();
    error EmptyHash();
    error EmptyStage();
    error AlreadyRegistered(string batchId);
    error BatchNotFound(string batchId);

    constructor() {
        owner = msg.sender;
    }

    /**
     * @notice Store a batch harvest-origin hash immutably.
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
     * @notice Anchor an append-only supply-chain stage hash (e.g., TRANSPORT or RETAIL)
     * linked to an already-registered harvest batch.
     */
    function addStageHash(
        string memory batchId,
        string memory stage,
        string memory dataHash
    ) public {
        if (bytes(batchId).length == 0) revert EmptyBatchId();
        if (!records[batchId].exists) revert BatchNotFound(batchId);
        if (bytes(stage).length == 0) revert EmptyStage();
        if (bytes(dataHash).length == 0) revert EmptyHash();

        stageHistory[batchId].push(
            StageRecord({
                stage: stage,
                dataHash: dataHash,
                recordedBy: msg.sender,
                timestamp: block.timestamp
            })
        );

        emit StageAnchored(batchId, stage, dataHash, msg.sender, block.timestamp);
    }

    /**
     * @notice Retrieve stored harvest hash for a batch ID (backwards compatible with V1 interface).
     * Returns empty string if not found.
     */
    function getHash(string memory batchId) public view returns (string memory) {
        return records[batchId].hash;
    }

    /**
     * @notice Inspect full harvest provenance record including sealer address and registration timestamp.
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

    /**
     * @notice Return total number of on-chain stage records anchored for a batch.
     */
    function getStageCount(string memory batchId) public view returns (uint256) {
        return stageHistory[batchId].length;
    }

    /**
     * @notice Retrieve an anchored stage record by index for a batch.
     */
    function getStageRecord(string memory batchId, uint256 index)
        public
        view
        returns (
            string memory stage,
            string memory dataHash,
            address recordedBy,
            uint256 timestamp
        )
    {
        StageRecord memory s = stageHistory[batchId][index];
        return (s.stage, s.dataHash, s.recordedBy, s.timestamp);
    }
}
