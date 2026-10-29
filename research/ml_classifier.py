"""ARGUS-EYE Machine Learning Motion & Clutter Classifier.

Trains and evaluates an environment-invariant classifier to distinguish:
0: QUIET_ROOM
1: AMBIENT_CLUTTER_FAN
2: HUMAN_WALKING
3: HUMAN_GESTURE

Extracts spectral and statistical micro-Doppler features that remain robust
across changing room acoustics, ceiling fans, and electromagnetic noise.
"""
from __future__ import annotations

import glob
import json
import os
import pickle
import sys
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

import numpy as np
import pandas as pd
from scipy import stats
from scipy import signal as sp_signal
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.model_selection import train_test_split

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

CLASS_NAMES = [
    "QUIET_ROOM",
    "AMBIENT_CLUTTER_FAN",
    "HUMAN_WALKING",
    "HUMAN_GESTURE",
]

MODEL_PATH = REPO_ROOT / "data" / "radar_ml_model.pkl"


def extract_window_features(ac_sig: np.ndarray, env_sig: np.ndarray, fs: float = 200.0) -> np.ndarray:
    """Extract ambient-invariant statistical and spectral features from a window.
    
    Returns a 12-dimensional feature vector.
    """
    n = len(ac_sig)
    if n < 4:
        return np.zeros(12, dtype=float)

    # 1. Statistical Amplitude Features
    rms = float(np.sqrt(np.mean(ac_sig**2)))
    env_mean = float(np.mean(env_sig))
    env_max = float(np.max(env_sig))
    env_std = float(np.std(env_sig))
    
    # Skewness and Kurtosis (captures bursty limb spikes vs flat steady hum)
    env_skew = float(stats.skew(env_sig)) if env_std > 1e-4 else 0.0
    env_kurt = float(stats.kurtosis(env_sig)) if env_std > 1e-4 else 0.0

    # 2. Zero-Crossing Rate
    zcr = float(np.mean(np.diff(np.sign(ac_sig) != 0)))

    # 3. Frequency / Spectral Features (Welch PSD)
    nperseg = min(n, 64)
    freqs, pxx = sp_signal.welch(ac_sig, fs=fs, nperseg=nperseg)
    pxx_sum = np.sum(pxx) + 1e-12

    # Spectral Centroid (Center of Mass of frequencies)
    spectral_centroid = float(np.sum(freqs * pxx) / pxx_sum)

    # Spectral Spread (Variance around centroid)
    spectral_spread = float(np.sqrt(np.sum(((freqs - spectral_centroid)**2) * pxx) / pxx_sum))

    # Spectral Flatness (Geometric Mean / Arithmetic Mean)
    # White noise ~ 1.0; pure harmonic tone / fan line << 0.1
    log_pxx = np.log(np.maximum(pxx, 1e-12))
    geometric_mean = np.exp(np.mean(log_pxx))
    arithmetic_mean = np.mean(pxx) + 1e-12
    spectral_flatness = float(geometric_mean / arithmetic_mean)

    # Spectral Crest Factor (Peak to Average Ratio)
    # Motor/fan has high crest (sharp discrete spikes); human walking has distributed power
    spectral_crest = float(np.max(pxx) / arithmetic_mean)

    # Peak Frequency
    peak_freq = float(freqs[np.argmax(pxx)])

    return np.array([
        rms,
        env_mean,
        env_max,
        env_std,
        env_skew,
        env_kurt,
        zcr,
        spectral_centroid,
        spectral_spread,
        spectral_flatness,
        spectral_crest,
        peak_freq,
    ], dtype=float)


FEATURE_NAMES = [
    "rms_energy",
    "envelope_mean",
    "envelope_max",
    "envelope_std",
    "envelope_skew",
    "envelope_kurt",
    "zero_crossing_rate",
    "spectral_centroid",
    "spectral_spread",
    "spectral_flatness",
    "spectral_crest",
    "peak_frequency",
]


def map_filename_to_class(filename: str, meta: Dict[str, Any]) -> Optional[int]:
    """Map a recording session to one of the 4 target classes."""
    name_lower = (filename + " " + meta.get("experiment_name", "") + " " + meta.get("condition", "")).lower()

    if "quite" in name_lower or "quiet" in name_lower:
        return 0  # QUIET_ROOM
    elif "fanson" in name_lower or "noisyroom" in name_lower or "clutter" in name_lower:
        return 1  # AMBIENT_CLUTTER_FAN
    elif "walk" in name_lower:
        return 2  # HUMAN_WALKING
    elif "hand" in name_lower or "gesture" in name_lower:
        return 3  # HUMAN_GESTURE
    return None


def prepare_dataset(
    data_dir: str | Path = "data/experiments",
    window_size: int = 30,
    stride: int = 10,
) -> Tuple[np.ndarray, np.ndarray, List[str]]:
    """Slice real recorded sessions into overlapping feature windows."""
    exp_dir = Path(data_dir).resolve()
    csv_files = sorted(exp_dir.glob("arguseye_*.csv"))

    x_list = []
    y_list = []
    file_records = []

    for f in csv_files:
        meta_f = f.with_suffix(".meta.json")
        meta = {}
        if meta_f.is_file():
            try:
                with open(meta_f, "r", encoding="utf-8") as fp:
                    meta = json.load(fp)
            except Exception:
                pass

        class_idx = map_filename_to_class(f.stem, meta)
        if class_idx is None:
            continue

        df = pd.read_csv(f)
        if len(df) < window_size:
            continue

        ac = df["ac_signal"].values.astype(float)
        env = df["envelope"].values.astype(float) if "envelope" in df else np.abs(ac)

        # Slide window
        windows_extracted = 0
        for start in range(0, len(df) - window_size + 1, stride):
            ac_win = ac[start : start + window_size]
            env_win = env[start : start + window_size]
            feat = extract_window_features(ac_win, env_win, fs=200.0)
            x_list.append(feat)
            y_list.append(class_idx)
            windows_extracted += 1

        file_records.append(f"{f.name} -> Class {class_idx} ({CLASS_NAMES[class_idx]}): {windows_extracted} windows")

    if not x_list:
        raise ValueError(f"No valid recording windows found in {exp_dir}")

    X = np.array(x_list, dtype=float)
    y = np.array(y_list, dtype=int)
    return X, y, file_records


def train_radar_model(data_dir: str | Path = "data/experiments") -> Dict[str, Any]:
    """Train Random Forest classifier on all available room recordings."""
    print("=" * 70)
    print("ARGUS-EYE MACHINE LEARNING MODEL TRAINING")
    print("=" * 70)

    X, y, summary = prepare_dataset(data_dir)
    print("\n[DATASET EXTRACTION]")
    for line in summary:
        print(f"  • {line}")

    print(f"\nTotal Dataset: {X.shape[0]} feature windows, {X.shape[1]} features each.")
    unique_classes, counts = np.unique(y, return_counts=True)
    for c, cnt in zip(unique_classes, counts):
        print(f"  Class {c} ({CLASS_NAMES[c]}): {cnt} samples ({cnt / len(y) * 100:.1f}%)")

    # Train / Test split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25, random_state=42, stratify=y
    )

    clf = RandomForestClassifier(
        n_estimators=100,
        max_depth=8,
        min_samples_split=4,
        random_state=42,
        class_weight="balanced",
    )
    clf.fit(X_train, y_train)

    train_acc = clf.score(X_train, y_train)
    test_acc = clf.score(X_test, y_test)

    y_pred = clf.predict(X_test)
    report = classification_report(
        y_test,
        y_pred,
        target_names=[CLASS_NAMES[i] for i in unique_classes],
        digits=3,
        zero_division=0,
    )
    cm = confusion_matrix(y_test, y_pred)

    print("\n" + "=" * 70)
    print(f"TRAINING ACCURACY:   {train_acc * 100:.2f}%")
    print(f"VALIDATION ACCURACY: {test_acc * 100:.2f}%")
    print("=" * 70)
    print("\n[CLASSIFICATION REPORT]")
    print(report)

    print("[CONFUSION MATRIX]")
    print(cm)

    # Feature Importance
    importances = clf.feature_importances_
    sorted_idx = np.argsort(importances)[::-1]
    print("\n[TOP DISCRIMINATIVE FEATURES]")
    for i in sorted_idx[:6]:
        print(f"  {FEATURE_NAMES[i]:<22}: {importances[i] * 100:.1f}% importance")

    # Save trained model to disk
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MODEL_PATH, "wb") as fp:
        pickle.dump({"model": clf, "classes": CLASS_NAMES, "feature_names": FEATURE_NAMES}, fp)
    print(f"\nSaved trained model to: {MODEL_PATH}")

    return {
        "train_accuracy": train_acc,
        "test_accuracy": test_acc,
        "confusion_matrix": cm,
        "model_path": str(MODEL_PATH),
    }


class LiveRadarMLClassifier:
    """Thread-safe live inference engine for the GUI dashboard."""
    def __init__(self, model_path: Optional[str | Path] = None):
        self.path = Path(model_path) if model_path else MODEL_PATH
        self.model = None
        self.classes = CLASS_NAMES
        self.load()

    def load(self) -> bool:
        if self.path.is_file():
            try:
                with open(self.path, "rb") as fp:
                    data = pickle.load(fp)
                    self.model = data["model"]
                    self.classes = data.get("classes", CLASS_NAMES)
                return True
            except Exception:
                self.model = None
                return False
        return False

    def predict(self, ac_sig: np.ndarray, env_sig: np.ndarray) -> Tuple[str, float]:
        """Predict class and confidence score for a live signal window."""
        if self.model is None or len(ac_sig) < 15:
            return "ML_IDLE", 0.0

        feat = extract_window_features(ac_sig, env_sig, fs=200.0).reshape(1, -1)
        probs = self.model.predict_proba(feat)[0]
        best_idx = int(np.argmax(probs))
        confidence = float(probs[best_idx])
        pred_label = self.classes[best_idx] if best_idx < len(self.classes) else "UNKNOWN"
        return pred_label, confidence


if __name__ == "__main__":
    train_radar_model()
