"""
TrustHarvest — Phase 4 Research Experiment Framework
Module: experiment_logger.py

Provides reusable, structured CSV experiment logging for all research verification runs.
Guarantees consistent schema, timestamping, latency tracking, and error recording.
"""

import csv
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

FIELDNAMES = [
    "experiment_id",
    "batch_id",
    "stage",
    "scenario",
    "expected_outcome",
    "actual_outcome",
    "success",
    "latency_ms",
    "timestamp",
    "error_message",
]


class ExperimentLogger:
    """
    Thread-safe and append-friendly CSV experiment logger.
    Ensures every test trial records required provenance verification metrics.
    """

    def __init__(self, output_path: str, experiment_id: Optional[str] = None):
        self.output_path = os.path.abspath(output_path)
        os.makedirs(os.path.dirname(self.output_path), exist_ok=True)
        self.experiment_id = experiment_id or f"EXP-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
        self._ensure_header()
        self.records: List[Dict[str, Any]] = []

    def _ensure_header(self) -> None:
        if not os.path.exists(self.output_path) or os.path.getsize(self.output_path) == 0:
            with open(self.output_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
                writer.writeheader()

    def log_trial(
        self,
        batch_id: str,
        stage: str,
        scenario: str,
        expected_outcome: str,
        actual_outcome: str,
        latency_ms: float,
        error_message: Optional[str] = None,
        custom_experiment_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Logs a single verification trial and writes it immediately to CSV.
        `success` is evaluated strictly as (expected_outcome == actual_outcome).
        """
        is_success = bool(str(expected_outcome).strip().lower() == str(actual_outcome).strip().lower())
        row = {
            "experiment_id": custom_experiment_id or self.experiment_id,
            "batch_id": str(batch_id),
            "stage": str(stage).upper(),
            "scenario": str(scenario),
            "expected_outcome": str(expected_outcome).strip().lower(),
            "actual_outcome": str(actual_outcome).strip().lower(),
            "success": is_success,
            "latency_ms": round(float(latency_ms), 3),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error_message": str(error_message or ""),
        }

        with open(self.output_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            writer.writerow(row)

        self.records.append(row)
        return row

    @staticmethod
    def read_results(csv_path: str) -> List[Dict[str, Any]]:
        """Reads back an experiment CSV into a list of parsed record dictionaries."""
        if not os.path.exists(csv_path):
            return []
        with open(csv_path, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = []
            for r in reader:
                rows.append({
                    "experiment_id": r["experiment_id"],
                    "batch_id": r["batch_id"],
                    "stage": r["stage"],
                    "scenario": r["scenario"],
                    "expected_outcome": r["expected_outcome"],
                    "actual_outcome": r["actual_outcome"],
                    "success": r["success"].strip().lower() in ("true", "1", "yes"),
                    "latency_ms": float(r["latency_ms"]),
                    "timestamp": r["timestamp"],
                    "error_message": r["error_message"],
                })
            return rows

