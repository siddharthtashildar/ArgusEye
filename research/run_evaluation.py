"""ARGUS-EYE Quantitative Research Evaluation CLI.
Runs comparative evaluations across benchmark recordings and outputs metrics tables.

Usage:
    python research/run_evaluation.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Dict, Any
import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from research.recorder import load_recording
from research.dsp_pipeline import RadarDSPPipeline
from research.evaluation import evaluate_detections, EvaluationResult


def run_full_evaluation(data_dir: str | Path = "data/experiments") -> Dict[str, Dict[str, EvaluationResult]]:
    exp_dir = Path(data_dir).resolve()
    csv_files = sorted(exp_dir.glob("*.csv"))

    if not csv_files:
        print(f"No CSV recordings found in {exp_dir}")
        return {}

    all_results: Dict[str, Dict[str, EvaluationResult]] = {}

    print("=" * 80)
    print("ARGUS-EYE DOPPLER RADAR QUANTITATIVE EVALUATION BENCHMARK")
    print("=" * 80)
    print(f"Dataset directory: {exp_dir}")
    print(f"Recordings found:  {len(csv_files)}\n")

    header_fmt = "{:<30} {:<18} {:<8} {:<8} {:<8} {:<10} {:<10}"
    print(header_fmt.format("SCENARIO / DETECTOR", "PRECISION", "RECALL", "F1", "FAR/MIN", "LATENCY", "TARGETS"))
    print("-" * 100)

    for csv_path in csv_files:
        signals, meta = load_recording(csv_path)
        if not signals or "raw_adc" not in signals:
            continue

        scenario_name = meta.condition if meta and meta.condition else csv_path.stem.replace("benchmark_", "")
        fs = meta.nominal_sample_rate_hz if meta else 200.0

        pipeline = RadarDSPPipeline(fs=fs)
        results = pipeline.run(signals["raw_adc"], timestamps_s=signals["elapsed_s"])

        gt_motion = signals.get("ground_truth_motion", np.zeros_like(signals["raw_adc"], dtype=bool))

        eval_legacy = evaluate_detections(
            signals["elapsed_s"],
            gt_motion,
            results["legacy_motion"],
            detector_name="Legacy Baseline",
            tolerance_s=0.4,
        )
        eval_adaptive = evaluate_detections(
            signals["elapsed_s"],
            gt_motion,
            results["adaptive_motion"],
            detector_name="Adaptive Causal",
            tolerance_s=0.4,
        )

        all_results[scenario_name] = {
            "legacy": eval_legacy,
            "adaptive": eval_adaptive,
        }

        # Print rows
        for det_label, ev in [("Adaptive Causal", eval_adaptive), ("Legacy Baseline", eval_legacy)]:
            prec_str = f"{ev.precision * 100:.1f}%" if ev.total_ground_truth_events > 0 or ev.false_positives > 0 else "N/A"
            rec_str = f"{ev.recall * 100:.1f}%" if ev.total_ground_truth_events > 0 else "N/A"
            f1_str = f"{ev.f1_score * 100:.1f}%" if ev.total_ground_truth_events > 0 else "N/A"
            far_str = f"{ev.false_alarms_per_minute:.2f}"
            lat_str = f"{ev.median_latency_ms:.0f} ms" if ev.latencies_ms else "—"

            # Check targets: Prec>=90, Rec>=90, FAR<=1.0, Lat<=300
            targets_pass = all(ev.meets_targets.values())
            pass_str = "PASS [ALL]" if targets_pass else "FAIL"

            name_col = f"{scenario_name[:18]} [{det_label[:8]}]"
            print(f"{name_col:<30} {prec_str:<18} {rec_str:<8} {f1_str:<8} {far_str:<10} {lat_str:<10} {pass_str}")

        print("-" * 100)

    print("\nTarget Requirements:")
    print("  • Precision: >= 90.0%")
    print("  • Recall:    >= 90.0%")
    print("  • False Alarms during stationary: <= 1.0 per minute")
    print("  • Median Detection Latency: <= 300 ms")
    print("=" * 80)

    return all_results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ARGUS-EYE Radar Evaluation Benchmark")
    parser.add_argument("--data-dir", default="data/experiments", help="Path to recording directory")
    args = parser.parse_args()
    run_full_evaluation(args.data_dir)
