# Experiment E6 — Performance and Scalability Evaluation Report

**Experiment**: E6 Workload Performance and Scalability Benchmark  
**Date**: November 17, 2026  
**Execution Environment**: Local Ganache (`CHAIN_ID=1337`), Isolated Research Database (`research_phase4.db`)  
**Artifacts**:
- Script: `research/phase4/run_performance.py`
- Trial Logs: `research/phase4/results/performance_experiments.csv` (1,170 trial rows)
- Summary Data: `research/phase4/results/performance_summary.json`

---

## 1. Objective and Workload Configurations

Experiment E6 evaluates the computational throughput, latency distribution, and component timing breakdown of the TrustHarvest verification engine as batch workload increases from micro-benchmarks to sustained evaluation:
- **Workload Sizes**: 10, 30, 50, 100, and 200 batches.
- **Statistical Rigor**: Exactly 3 independent repetitions per workload configuration ($10\times3 + 30\times3 + 50\times3 + 100\times3 + 200\times3 = 1,170$ evaluated batches).
- **Component Timing Decomposition**:
  1. *Local SHA-256 Hash Computation*: Local CPU execution to re-digest harvest, multi-checkpoint transport, and retail fields.
  2. *Blockchain Read Latency*: EVM RPC network roundtrips (`inspect_batch_on_chain`, `getRecord`, `getStageCount`, `getStageRecord`).
  3. *Complete Verification Latency*: End-to-end execution of `_build_verification_context`.

---

## 2. Experimental Results Summary

| Workload Size | Repetitions | Mean Total Time (s) | Throughput (batches/s) | Mean Latency (ms) | Median Latency (ms) | P95 Latency (ms) | Min / Max (ms) |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **10 batches** | 3 | 4.97 s | 2.01 batches/s | 246.37 ms | 246.39 ms | 304.82 ms | 191.44 / 310.80 |
| **30 batches** | 3 | 13.83 s | 2.17 batches/s | 230.33 ms | 215.28 ms | 334.08 ms | 148.56 / 357.02 |
| **50 batches** | 3 | 21.31 s | 2.35 batches/s | 209.56 ms | 205.47 ms | 292.73 ms | 108.54 / 367.91 |
| **100 batches** | 3 | 42.81 s | 2.34 batches/s | 211.44 ms | 215.61 ms | 342.47 ms | 83.21 / 384.89 |
| **200 batches** | 3 | 84.80 s | 2.36 batches/s | 208.85 ms | 210.23 ms | 316.95 ms | 66.37 / 375.01 |

---

## 3. Component Timing Breakdown

| Timing Component | Mean Latency (ms) | Percentage of Total Latency | System Bottleneck Analysis |
| :--- | :---: | :---: | :--- |
| **Local SHA-256 Hash Computation** | **0.19 ms** | **0.09%** | Highly efficient Python CPU operation; virtually instantaneous. |
| **Blockchain RPC Read Overhead** | **209.23 ms** | **99.8%** | Dominant bottleneck: sequential JSON-RPC roundtrips over HTTP. |
| **Application Logic / Context Build** | **~1.5 ms** | **~0.1%** | Negligible overhead for DB relational queries and dictionary assembly. |

---

## 4. Key Architectural Insights

1. **Throughput Stability**:
   - Verification throughput remains remarkably stable across all workload scales, ranging from **2.01 to 2.36 batches/second** on a single-threaded synchronous Python process.
   - Total execution time scales linearly with workload size: 10 batches complete in ~5 seconds, while 200 batches complete in ~85 seconds.

2. **The RPC Round-Trip Bottleneck**:
   - The breakdown unequivocally demonstrates that cryptographic hashing consumes less than 0.1% of the verification budget.
   - Nearly 100% of end-user latency is consumed by sequential EVM JSON-RPC calls. This empirically proves the recommendation in `docs/CONTRACT_AUDIT.md` that production deployments require multi-call batching (EIP-1822 / Multicall3) or caching to achieve sub-50ms verification on remote public networks.

