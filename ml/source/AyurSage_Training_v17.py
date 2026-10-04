"""
==========================================================================
AYUR-SAGE ML TRAINING PIPELINE — v17
Multi-Output Ayurvedic Treatment & Diet Recommendation System
Team: Yash Vasagadekar, Shreya Sidanale, Sania Makandar
Guide: Dr. S.C. Sagare | D.K.T.E. T&E Institute, Ichalkaranji
==========================================================================

CHANGELOG v16 → v17:
  [ARCH]  REMOVED per-output algorithm selection (best_model_per_output).
          Every output was previously allowed to pick a DIFFERENT winning
          algorithm (e.g. Herbal→GB, Lifestyle→CB, Yoga→GB, Follow-up→XGB).
          This produced a mixed ensemble of unrelated algorithm families,
          which is harder to justify, harder to maintain, and harder to
          explain than a single unified model family.
  [ARCH]  NEW: best_overall_model — ONE algorithm family is selected
          GLOBALLY by aggregating its performance across ALL FOUR outputs,
          then that single family's four (still single-output) classifiers
          are used for every output at inference time.
  [CAF]   Global CustomAIFramework: each algorithm (RF/ET/GB/XGB/CB) is
          scored once via a global hybrid score built from the MEAN of its
          per-output metrics (train acc, test acc, macro F1, weighted F1,
          CV macro F1, CV std, overfit gap) across the 4 outputs.
  [CV]    NEW fold-safe cross-validation: SMOTE is now applied ONLY inside
          each CV training fold, never to the CV validation fold and never
          to the held-out test set. Previous versions ran cross_val_score()
          directly on non-SMOTE data, scoring a different (non-SMOTE-trained)
          clone than the classifier actually being trained/deployed.
  [SMOTE] Per-output SMOTE for FINAL classifier training is preserved
          unchanged — each output still gets its own SMOTE-balanced training
          set because each output has its own class distribution. This is
          independent of, and not to be confused with, the removed
          per-output ALGORITHM selection.
  [EVAL]  FINAL UNIFIED MODEL EVALUATION replaces the old mixed
          best-per-output ensemble evaluation — all 4 outputs are now
          evaluated using the same winning algorithm family.
  [KEEP]  Bucket functions, bucket thresholds, random probabilities,
          dataset structure, model hyperparameters, Lifestyle engine,
          Yoga engine, Dynamic Clinical Reasoning Engine, and Doctor HITL
          architecture are all UNCHANGED from v16.

OUTPUT ARCHITECTURE (v17 — unchanged from v14/v16):
  ML Outputs (4):
    1. Herbal Therapy Strategy
    2. Lifestyle Recommendations
    3. Therapeutic Yoga Module
    4. Follow-up Recommendation
  Non-ML (HITL only):
    • Doctor Prescription & Care Notes  ← manual doctor entry in Flask UI

PIPELINE STEPS (v17):
  1.  Load dataset + fill nulls
  2.  Label normalization (input columns)
  3.  Output bucketing (4 output columns only)
  4.  Train/test split AFTER bucketing, BEFORE encoding
      — stratified on 'Lifestyle Recommendations'
  5.  LabelEncode outputs (fit on full Y for class stability)
  6.  Fit shared ColumnTransformer on X_train → X_train_pre, X_test_pre
  7.  For EACH of the 4 outputs independently:
        a. Apply SMOTE on (X_train_pre, y_i) → balanced (X_bal, y_bal)
        b. Train RF, ET, GB, XGB, CB on balanced data (final classifiers)
  8.  For EACH algorithm × EACH output: fold-safe 5-fold CV
        (SMOTE applied only inside the CV training fold)
  9.  Aggregate per-output metrics into per-algorithm mean metrics
  10. Global CustomAIFramework hybrid scoring → best_overall_model
  11. FINAL UNIFIED MODEL EVALUATION using best_overall_model for all 4
      outputs: Acc, Macro F1, Weighted F1, CM, ClassReport
  12. Save training_results.json + feature-importance plots
  13. Save joblib bundle (shared_pre + classifiers + engines) for Flask
==========================================================================
"""

import pandas as pd
import numpy as np
import joblib
import json
import os
import sys
import time
import random
import traceback
import warnings
import platform
import logging
import sklearn
from datetime import datetime, timezone
warnings.filterwarnings('ignore')

import matplotlib
matplotlib.use('Agg')           # non-interactive backend — safe for servers
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

from sklearn.ensemble import (
    RandomForestClassifier,
    ExtraTreesClassifier,
    GradientBoostingClassifier,
)
from sklearn.preprocessing import LabelEncoder, OneHotEncoder
from sklearn.compose import ColumnTransformer
from sklearn.model_selection import train_test_split, cross_val_score, StratifiedKFold
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    confusion_matrix,
    classification_report,
)
from sklearn.utils.class_weight import compute_sample_weight

# ── Optional boosting libraries with graceful fallback ──────────────────────
try:
    from xgboost import XGBClassifier
    XGB_AVAILABLE = True
except ImportError:
    XGB_AVAILABLE = False
    print("[WARN] xgboost not installed — XGB skipped. pip install xgboost")

try:
    from catboost import CatBoostClassifier
    CAT_AVAILABLE = True
except ImportError:
    CAT_AVAILABLE = False
    print("[WARN] catboost not installed — CB skipped. pip install catboost")

# ── Optional SHAP explainability library with graceful fallback ─────────────
# [Production Readiness — Task 2] SHAP is purely an EXPLAINABILITY add-on.
# It never influences training, predictions, or model selection — if it's
# unavailable or fails for a given algorithm, training continues unaffected.
try:
    import shap
    SHAP_AVAILABLE = True
except ImportError:
    SHAP_AVAILABLE = False
    print("[WARN] shap not installed — SHAP explanations skipped. pip install shap")

# ── SMOTE for minority-class oversampling ────────────────────────────────────
# WHY imbalance hurts Macro F1:
#   When one class has 78% of samples and another has 10%, the model learns
#   to mostly predict the majority class. Accuracy stays high (it guesses the
#   majority often) but Macro F1 collapses because minority classes are rarely
#   predicted, so their precision/recall → 0. The average of F1 per class
#   (Macro F1) is then dragged down to near-zero by those ignored classes.
#
# WHY SMOTE improves minority learning:
#   SMOTE (Synthetic Minority Over-sampling Technique) generates synthetic
#   samples for underrepresented classes by interpolating between existing
#   minority neighbours in feature space. This re-balances the class
#   distribution so every class appears equally during training, forcing the
#   model to learn decision boundaries for ALL classes — directly improving
#   minority-class recall and Macro F1.
#
# WHY per-output SMOTE (not joint):
#   Each output column has its own independent class distribution. Applying
#   SMOTE jointly on the multi-output matrix would require all outputs to
#   be balanced simultaneously, which is unsolvable — a sample that is a
#   minority for output A may be majority for output B. Per-output SMOTE
#   solves each imbalance independently without interference.

# ── Auto-install imbalanced-learn if missing ─────────────────────────────────
# SMOTE is critical for Macro F1 improvement. If the library is absent we
# install it automatically rather than silently skipping and producing the
# same poor Macro F1 as before.
try:
    from imblearn.over_sampling import SMOTE
    from imblearn.pipeline import Pipeline as ImbPipeline
    SMOTE_AVAILABLE = True
except ImportError:
    print("[SMOTE] imbalanced-learn not found — attempting auto-install...")
    import subprocess
    _result = subprocess.run(
        [sys.executable, '-m', 'pip', 'install', 'imbalanced-learn', '-q'],
        capture_output=True, text=True
    )
    if _result.returncode == 0:
        try:
            from imblearn.over_sampling import SMOTE
            from imblearn.pipeline import Pipeline as ImbPipeline
            SMOTE_AVAILABLE = True
            print("[SMOTE] imbalanced-learn installed and imported successfully.")
        except ImportError:
            SMOTE_AVAILABLE = False
            print("[SMOTE] Install succeeded but import still failed — SMOTE disabled.")
    else:
        SMOTE_AVAILABLE = False
        print(f"[SMOTE] Auto-install failed: {_result.stderr.strip()}")
        print("[SMOTE] Run manually:  pip install imbalanced-learn")
        print("[SMOTE] SMOTE disabled — Macro F1 will remain low without it.")

if not SMOTE_AVAILABLE:
    ImbPipeline = None   # referenced only inside SMOTE_AVAILABLE-guarded code paths

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 1 — FEATURE DEFINITIONS
# ─────────────────────────────────────────────────────────────────────────────

# Signal features confirmed by Mutual Information analysis
# Noise features removed: Symptoms, Diagnosis & Tests, Medical History,
# Risk Factors, Environmental Factors, Current Medications, Family History,
# Occupation & Lifestyle
CATEGORICAL_COLS = [
    'Disease',
    'Symptom Severity',
    'Nadi Reading',
    'Constitution/Prakriti',
    'Stress Levels',
    'Sleep Patterns',
    'Age Group',
    'Physical Activity Levels',
]

NUMERIC_COLS = [
    'BP Systolic',
    'BP Diastolic',
    'Pulse Rate',
    'Weight (kg)',
]

INPUT_FEATURES = CATEGORICAL_COLS + NUMERIC_COLS   # 12 features total

# ── OUTPUT ARCHITECTURE (unchanged since v14) ─────────────────────────────────
# 4 ML outputs only.  "Doctor Prescription & Care Notes" is REMOVED from ML
# and will be entered manually by a licensed doctor in the Flask HITL UI.
# WHY: Doctor prescriptions require clinical judgment that cannot be safely
# automated. Removing it also simplifies the class space for the remaining
# 4 outputs, improving their own Macro F1 by reducing label confusion.
OUTPUT_TARGETS = [
    'Herbal Therapy Strategy',
    'Lifestyle Recommendations',
    'Therapeutic Yoga Module',
    'Follow-up Recommendation',
]

# Stratification proxy: use the most balanced output column for split quality.
# Updated from old 'Diet and Lifestyle Recommendations' (removed in v14).
STRATIFY_ON = 'Lifestyle Recommendations'

# Algorithms available
ALL_ALGOS = ['RF', 'ET', 'GB']
if XGB_AVAILABLE:
    ALL_ALGOS.append('XGB')
if CAT_AVAILABLE:
    ALL_ALGOS.append('CB')

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION — single source of truth for every previously-scattered
# literal (Architecture Audit, Task 4). Values are UNCHANGED from v17 —
# this section only gives them names and one location; it does not alter
# any threshold, weight, seed, or methodology.
# ─────────────────────────────────────────────────────────────────────────────

class Config:
    """Central configuration for the AyurSage V17 training pipeline."""

    # ── Identity ──────────────────────────────────────────────────────────
    PIPELINE_VERSION   = 'AyurSage_v17'
    DEFAULT_DATASET    = 'AyurSage_10k_Synthetic.csv'

    # ── Reproducibility ──────────────────────────────────────────────────
    RANDOM_SEED        = 42     # sklearn/imblearn random_state, used verbatim
                                 # everywhere it already appeared in v17

    # ── Cross-validation ─────────────────────────────────────────────────
    CV_N_SPLITS         = 5     # StratifiedKFold folds (outer split + fold-safe CV)

    # ── SMOTE ─────────────────────────────────────────────────────────────
    SMOTE_MAX_K_NEIGHBORS = 5   # cap used by apply_smote() and fold_safe_cv_macro_f1()

    # ── Global CAF hybrid-score weights (UNCHANGED formula/values) ──────────
    CAF_WEIGHT_CV_MACRO_F1   = 0.40
    CAF_WEIGHT_MACRO_F1      = 0.25
    CAF_WEIGHT_WEIGHTED_F1   = 0.15
    CAF_WEIGHT_TEST_ACCURACY = 0.10
    CAF_WEIGHT_STABILITY     = 0.10
    CAF_OVERFIT_PENALTY_CAP    = 0.20   # min(mean_overfit_gap, this)
    CAF_OVERFIT_PENALTY_WEIGHT = 0.15   # applied to the capped overfit_penalty

    # ── Tie-breaking policy (Task 2 — NEW, additive to v17 selection) ───────
    # If the top-scoring algorithms' global_hybrid_score are within this
    # absolute margin of the best score, they are treated as a near-tie and
    # disambiguated using the secondary criteria below (in priority order)
    # instead of the raw score alone. Set to 0.0 to disable tie-breaking and
    # fall back to pure argmax (identical to original v17 behaviour).
    TIE_BREAK_SCORE_THRESHOLD = 0.01

    # Deployment-simplicity ranking (lower = simpler to deploy). Built-in
    # scikit-learn estimators ship with sklearn itself (already a hard
    # dependency); XGBoost/CatBoost require an additional optional package.
    DEPLOYMENT_SIMPLICITY_RANK = {'RF': 0, 'ET': 0, 'GB': 0, 'XGB': 1, 'CB': 1}

    # Model-complexity ranking (lower = simpler model family), used only as
    # a tie-break criterion — never affects which algorithms are trained or
    # how they are scored.
    MODEL_COMPLEXITY_RANK = {'RF': 0, 'ET': 0, 'GB': 1, 'XGB': 2, 'CB': 2}

    # ── Output locations ─────────────────────────────────────────────────
    RESULTS_DIR            = './results'
    FEATURE_IMPORTANCE_DIR = './feature_importance'
    SHAP_DIR                = './shap_explanations'
    TRAINING_RESULTS_PATH  = f'{RESULTS_DIR}/training_results.json'
    METADATA_PATH          = f'{RESULTS_DIR}/metadata.json'
    RESEARCH_SUMMARY_PATH  = f'{RESULTS_DIR}/architecture_summary.md'
    PRODUCTION_BUNDLE_PATH = 'ayursage_model.pkl'
    RESEARCH_BUNDLE_PATH   = 'ayursage_model_research.pkl'

    # ── Feature importance / SHAP plotting ───────────────────────────────
    FEATURE_IMPORTANCE_TOP_N = 15
    SHAP_MAX_SAMPLES         = 100   # cap test-set rows used for SHAP (speed)


def _ensure_output_dirs():
    """Centralized folder creation (Task 5) — replaces scattered os.makedirs
    calls with one function used by every stage that writes artifacts."""
    os.makedirs(Config.RESULTS_DIR, exist_ok=True)
    os.makedirs(Config.FEATURE_IMPORTANCE_DIR, exist_ok=True)
    os.makedirs(Config.SHAP_DIR, exist_ok=True)


# ── Centralized runtime logging (Task 5 / Task 6) ───────────────────────────
# Lightweight wrapper around the standard `logging` module. Console output
# format for the existing detailed tables/prints throughout the pipeline is
# left untouched (changing hundreds of hand-aligned f-strings to logger
# calls would risk altering visible behaviour for no methodological gain);
# this logger is used for the NEW stage-boundary and experiment-tracking
# messages introduced in this refactor, and is available for any future
# consolidation of the existing print() calls.
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger('ayursage')


def log_stage(message: str):
    """Logs a pipeline stage-boundary message (INFO level)."""
    logger.info(message)

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 2 — LABEL NORMALIZATION MAPS
# Same concept, different string forms → canonical form
# ─────────────────────────────────────────────────────────────────────────────

STRESS_MAP = {
    'high stress'      : 'High Stress',
    'very high stress' : 'High Stress',
    'moderate stress'  : 'Moderate Stress',
    'low stress'       : 'Low Stress',
}

SLEEP_MAP = {
    'irregular sleep'   : 'Irregular Sleep',
    'disrupted sleep'   : 'Irregular Sleep',
    'poor sleep'        : 'Poor Sleep',
    'poor sleep quality': 'Poor Sleep',
    'extreme fatigue'   : 'Poor Sleep',
    'regular sleep'     : 'Regular Sleep',
}

ACTIVITY_MAP = {
    'low'              : 'Low',
    'low to moderate'  : 'Low',
    'moderate to low'  : 'Low',
    'moderate'         : 'Moderate',
    'moderate to high' : 'Moderate',
    'high'             : 'High',
}

SEVERITY_MAP = {
    'mild'    : 'Mild',
    'moderate': 'Moderate',
    'severe'  : 'Severe',
    'high'    : 'High',
}


def normalize_labels(df: pd.DataFrame) -> pd.DataFrame:
    """
    Step 2: Apply canonical normalization to input columns.
    Must happen BEFORE output bucketing.
    Rule: val.lower().strip() → lookup in map → canonical form.
    Unrecognized values are left as-is; OHE handle_unknown='ignore' handles them.
    """
    def map_col(series, mapping):
        return series.apply(lambda v: mapping.get(str(v).lower().strip(), v))

    df = df.copy()
    df['Stress Levels']            = map_col(df['Stress Levels'],            STRESS_MAP)
    df['Sleep Patterns']           = map_col(df['Sleep Patterns'],            SLEEP_MAP)
    df['Physical Activity Levels'] = map_col(df['Physical Activity Levels'],  ACTIVITY_MAP)
    df['Symptom Severity']         = map_col(df['Symptom Severity'],          SEVERITY_MAP)
    return df


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 3 — OUTPUT BUCKETING FUNCTIONS  (v16 softened determinism, retained in v17)
#
# v15 PROBLEM: Labels were perfectly deterministic — if High Stress + Poor Sleep
#   → always exactly 'Stress Reduction Yoga'. Models learned the bucket rules
#   instead of generalized healthcare intelligence, producing unrealistically
#   high scores and near-perfect separability on synthetic data.
#
# v16 FIX — CONTROLLED PROBABILISTIC OVERLAP:
#   • HIGH-CONFIDENCE cases (clear single disease, critical vitals, unambiguous
#     Prakriti+disease compound) remain fully deterministic. The ML model should
#     still learn strong signal → output associations for these.
#   • BORDERLINE cases (moderate stress, mild obesity, overlapping symptoms)
#     use seeded random.choice() across 2–3 semantically valid options.
#     This mimics real clinical variability: two doctors seeing the same
#     borderline patient may legitimately recommend different protocols.
#   • Randomization uses a per-row seed derived from hash(row values) so that
#     the same dataset row always generates the same label (reproducibility),
#     but different rows with similar features can get different labels.
#
# DESIGN RULES:
#   • random.seed() called at the start of each bucket function per row.
#   • Seed = hash of a stable row identifier (Disease + Stress + Weight string).
#   • Only BORDERLINE branches use random.choice() — never primary disease gates.
#   • Class balance is preserved: random.choice weights are equal, so over a
#     large dataset the borderline pool distributes uniformly.
#   • Target distribution: 15%–35% per class. No class > 40%.
# ─────────────────────────────────────────────────────────────────────────────

def _row_seed(row) -> int:
    """
    Derive a deterministic integer seed from stable row content.
    Using hash of concatenated key fields ensures the SAME row always generates
    the SAME label across multiple runs (reproducibility), while different rows
    with identical input feature values but different Disease strings get
    different random choices — creating realistic within-profile variation.
    """
    seed_str = (
        str(row.get('Disease', '')) +
        str(row.get('Stress Levels', '')) +
        str(row.get('Sleep Patterns', '')) +
        str(row.get('Weight (kg)', '')) +
        str(row.get('BP Systolic', '')) +
        str(row.get('Constitution/Prakriti', ''))
    )
    # Python's built-in hash is not stable across processes; use a simple
    # djb2-style hash that IS deterministic within and across runs.
    h = 5381
    for c in seed_str:
        h = ((h << 5) + h) + ord(c)
    return h & 0x7FFFFFFF   # ensure positive int


# ── Internal signal extraction (unchanged from v15) ───────────────────────────
def _sig(row) -> dict:
    """
    Extract clean boolean + numeric signals from a normalized DataFrame row.
    Called once per bucket function per row. All comparisons use lowercase.
    Returns a flat dict of boolean flags and numeric vitals.
    """
    disease  = str(row.get('Disease',                  '')).lower()
    stress   = str(row.get('Stress Levels',            '')).lower()
    sleep    = str(row.get('Sleep Patterns',           '')).lower()
    severity = str(row.get('Symptom Severity',         '')).lower()
    activity = str(row.get('Physical Activity Levels', '')).lower()
    prakriti = str(row.get('Constitution/Prakriti',    '')).lower()
    nadi     = str(row.get('Nadi Reading',             '')).lower()

    try: bp_s = float(row.get('BP Systolic',  120))
    except: bp_s = 120.0
    try: bp_d = float(row.get('BP Diastolic',  80))
    except: bp_d = 80.0
    try: wt   = float(row.get('Weight (kg)',   70))
    except: wt = 70.0
    try: pr   = float(row.get('Pulse Rate',    75))
    except: pr = 75.0

    hi_stress  = 'high stress'     in stress
    mod_stress = 'moderate stress' in stress
    any_stress = hi_stress or mod_stress
    poor_sleep = 'poor sleep'      in sleep
    irr_sleep  = 'irregular sleep' in sleep
    bad_sleep  = poor_sleep or irr_sleep

    sev_severe   = severity in ('severe', 'high')
    sev_moderate = severity == 'moderate'
    sev_mild     = severity == 'mild'

    low_act  = activity == 'low'
    mod_act  = activity == 'moderate'
    high_act = activity == 'high'

    kapha = 'kapha' in prakriti or 'kapha' in nadi
    vata  = 'vata'  in prakriti or 'vata'  in nadi
    pitta = 'pitta' in prakriti or 'pitta' in nadi

    bp_critical = bp_s >= 160 or bp_d >= 100
    bp_high     = bp_s >= 140 or bp_d >= 90
    bp_elevated = bp_s >= 130 or bp_d >= 85
    obese       = wt >= 95
    overweight  = wt >= 80
    tachycardia = pr >= 100

    metabolic = any(k in disease for k in [
        'diabetes mellitus', 'type 2 diabetes', 'type 1 diabetes', 'prediabet',
        'obesity', 'hyperlipidaemia', 'dyslipidaemia', 'hypothyroid',
        'hyperthyroid', 'metabolic syndrome', 'pcod', 'pcos', 'insulin resist',
    ])
    hypertension = any(k in disease for k in [
        'hypertension', 'high blood pressure', 'elevated blood pressure',
    ])
    digestive = any(k in disease for k in [
        'irritable bowel', 'ibs', 'crohn', 'colitis', 'gastritis',
        'gastroesophageal', 'gerd', 'acid reflux', 'peptic ulcer',
        'liver disease', 'hepatitis', 'fatty liver', 'pancreatitis',
        'constipation', 'bloating', 'indigestion', 'dyspepsia',
    ])
    respiratory = any(k in disease for k in [
        'asthma', 'copd', 'chronic obstructive', 'bronchitis', 'sinusitis',
        'allergic rhinitis', 'sleep apnoea', 'sleep apnea', 'pneumonia',
        'pulmonary', 'respiratory', 'emphysema',
    ])
    joint = any(k in disease for k in [
        'arthritis', 'rheumatoid', 'osteoarthritis', 'gout', 'fibromyalgia',
        'spondylitis', 'spondylosis', 'ankylosing', 'lupus', 'back pain',
        'neck pain', 'sciatica', 'disc herniation', 'joint pain',
    ])
    immune_fatigue = any(k in disease for k in [
        'chronic fatigue', 'anaemia', 'anemia', 'low immunity',
        'immunodeficiency', 'recurrent infection', 'viral fever',
        'weakness', 'fibromyalgia', 'autoimmune',
    ])
    mental = any(k in disease for k in [
        'anxiety disorder', 'generalised anxiety', 'panic disorder',
        'major depressive', 'depression', 'stress disorder', 'ptsd',
        'burnout syndrome', 'insomnia disorder', 'bipolar',
    ])
    cardiac = any(k in disease for k in [
        'coronary', 'heart disease', 'angina', 'arrhythmia', 'atrial fib',
        'heart failure', 'myocardial', 'cardiomyopathy',
    ])
    sleep_disease = any(k in disease for k in [
        'insomnia', 'sleep apn', 'hypersomnia', 'restless leg', 'sleep disorder',
        'sleep disturbance', 'circadian',
    ])

    return {
        'hi_stress': hi_stress, 'mod_stress': mod_stress, 'any_stress': any_stress,
        'poor_sleep': poor_sleep, 'irr_sleep': irr_sleep, 'bad_sleep': bad_sleep,
        'sev_severe': sev_severe, 'sev_moderate': sev_moderate, 'sev_mild': sev_mild,
        'low_act': low_act, 'mod_act': mod_act, 'high_act': high_act,
        'kapha': kapha, 'vata': vata, 'pitta': pitta,
        'bp_critical': bp_critical, 'bp_high': bp_high, 'bp_elevated': bp_elevated,
        'obese': obese, 'overweight': overweight, 'tachycardia': tachycardia,
        'bp_s': bp_s, 'bp_d': bp_d, 'wt': wt, 'pr': pr,
        'metabolic': metabolic, 'hypertension': hypertension,
        'digestive': digestive, 'respiratory': respiratory,
        'joint': joint, 'immune_fatigue': immune_fatigue,
        'mental': mental, 'cardiac': cardiac, 'sleep_disease': sleep_disease,
    }


# ─────────────────────────────────────────────────────────────────────────────
# BUCKET FUNCTION 1 — Herbal Therapy Strategy  (v16 logic, unchanged in v17)
# ─────────────────────────────────────────────────────────────────────────────

def bucket_herbal_strategy(row) -> str:
    """
    OUTPUT 1 — Herbal Therapy Strategy (v16 softened determinism, unchanged in v17)

    HIGH-CONFIDENCE (deterministic):
      Joint disease           → Anti-inflammatory (always)
      Digestive disease       → Digestive (always)
      Respiratory disease     → Immunity (always)
      Confirmed metabolic     → Metabolic (always)
      Cardiac                 → Metabolic (always)

    BORDERLINE (probabilistic):
      High stress + bad sleep → [Stress-Relief 60%, Immunity 40%]
        Rationale: fatigue and stress frequently co-present; an Ayurvedic
        practitioner may choose immune-supportive adaptogens (Ashwagandha,
        Shatavari) which overlap both categories.

      Mod stress + bad sleep  → [Stress-Relief 50%, Digestive 50%]
        Rationale: moderate stress + sleep issues often manifest as gut
        disturbance (Ayurvedic stress-gut axis); Triphala/Haritaki are
        appropriate for both profiles.

      Overweight + mild act.  → [Metabolic 60%, Immunity 40%]
        Rationale: overweight without confirmed metabolic disease may reflect
        immune sluggishness (Kapha accumulation) rather than frank metabolic
        dysfunction.

      Mental disease          → [Stress-Relief 70%, Immunity 30%]
        Rationale: mental health conditions often co-present with immune
        dysregulation; adaptogenic herbs serve both.
    """
    random.seed(_row_seed(row))
    s = _sig(row)

    # ── DETERMINISTIC: unambiguous disease gates ──────────────────────────────
    if s['joint']:
        return 'Anti-inflammatory Herbal Support'

    if s['digestive'] or (s['pitta'] and not s['metabolic'] and not s['joint']):
        return 'Digestive Herbal Support'

    if s['respiratory']:
        return 'Immunity Enhancement Support'

    if s['metabolic'] or s['cardiac']:
        return 'Metabolic Balance Support'

    # ── BORDERLINE: probabilistic overlapping conditions ──────────────────────

    # High stress + confirmed bad sleep → Stress-Relief or Immunity
    if s['hi_stress'] and s['bad_sleep']:
        return random.choices(
            ['Stress-Relief Herbal Support', 'Immunity Enhancement Support'],
            weights=[60, 40]
        )[0]

    # Mental disease without metabolic → Stress-Relief or Immunity
    if s['mental']:
        return random.choices(
            ['Stress-Relief Herbal Support', 'Immunity Enhancement Support'],
            weights=[70, 30]
        )[0]

    # Immune/fatigue without metabolic → Immunity or Stress-Relief
    if s['immune_fatigue']:
        return random.choices(
            ['Immunity Enhancement Support', 'Stress-Relief Herbal Support'],
            weights=[65, 35]
        )[0]

    # Moderate stress + sleep issues → Stress-Relief or Digestive (gut-stress axis)
    if s['mod_stress'] and s['bad_sleep']:
        return random.choices(
            ['Stress-Relief Herbal Support', 'Digestive Herbal Support'],
            weights=[55, 45]
        )[0]

    # Two or more metabolic signals (borderline metabolic profile)
    metabolic_signals = sum([
        s['hypertension'], s['obese'] and s['low_act'], s['kapha'] and s['overweight'],
    ])
    if metabolic_signals >= 2:
        return random.choices(
            ['Metabolic Balance Support', 'Immunity Enhancement Support'],
            weights=[60, 40]
        )[0]

    # Overweight + low activity (mild metabolic risk) → Metabolic or Immunity
    if s['overweight'] and s['low_act']:
        return random.choices(
            ['Metabolic Balance Support', 'Immunity Enhancement Support'],
            weights=[55, 45]
        )[0]

    # ── DETERMINISTIC defaults via Prakriti (distribute residual rows) ────────
    if s['vata']:
        return 'Immunity Enhancement Support'
    if s['low_act'] and not s['kapha']:
        return 'Digestive Herbal Support'
    if s['high_act']:
        return 'Anti-inflammatory Herbal Support'

    return 'Stress-Relief Herbal Support'


# ─────────────────────────────────────────────────────────────────────────────
# BUCKET FUNCTION 2 — Lifestyle Recommendations  (v16 logic, unchanged in v17)
# ─────────────────────────────────────────────────────────────────────────────

def bucket_lifestyle(row) -> str:
    """
    OUTPUT 2 — Lifestyle Recommendations (v16 softened determinism, unchanged in v17)

    HIGH-CONFIDENCE (deterministic):
      Sleep disease           → Sleep Improvement (always)
      Confirmed metabolic     → Weight Management (always)
      Obese + sedentary       → Weight Management (always)
      Cardiac + overweight    → Weight Management (always)

    BORDERLINE (probabilistic):
      Bad sleep + severe symptoms  → [Sleep Improvement 60%, Stress Reduction 40%]
        Rationale: severe symptoms disrupt sleep but high stress is often the
        underlying driver; both lifestyle programmes are clinically valid.

      High stress + bad sleep      → [Stress Reduction 55%, Sleep Improvement 45%]
        Rationale: stress-sleep bidirectional link — addressing either first
        is a legitimate clinical strategy.

      Low activity + no metabolic  → [Active Promotion 60%, Sleep Improvement 40%]
        for patients who also have bad sleep (fatigue-inactivity loop).

      Overweight + moderate act.   → [Active Promotion 60%, Weight Mgmt 40%]
        Rationale: mildly overweight patients with moderate activity don't
        always need the full metabolic programme; active promotion may suffice.

      Moderate stress + bad sleep  → [Stress Reduction 50%, Sleep Improvement 50%]
    """
    random.seed(_row_seed(row))
    s = _sig(row)

    # ── DETERMINISTIC gates ───────────────────────────────────────────────────
    if s['sleep_disease']:
        return 'Sleep Improvement Lifestyle'

    if s['metabolic']:
        return 'Weight Management Lifestyle'

    if s['obese'] and s['low_act']:
        return 'Weight Management Lifestyle'

    if s['cardiac'] or (s['hypertension'] and s['overweight'] and s['sev_severe']):
        return 'Weight Management Lifestyle'

    # ── BORDERLINE: probabilistic cases ──────────────────────────────────────

    # Bad sleep + severe symptoms — stress or sleep could be primary driver
    if s['bad_sleep'] and s['sev_severe']:
        return random.choices(
            ['Sleep Improvement Lifestyle', 'Stress Reduction Lifestyle'],
            weights=[60, 40]
        )[0]

    # High stress + bad sleep — bidirectional; both approaches valid
    if s['hi_stress'] and s['bad_sleep']:
        return random.choices(
            ['Stress Reduction Lifestyle', 'Sleep Improvement Lifestyle'],
            weights=[55, 45]
        )[0]

    # High stress alone (no sleep) + mental disease → Stress Reduction
    if s['hi_stress'] and s['mental']:
        return 'Stress Reduction Lifestyle'

    # High stress + severe symptoms (no sleep flag)
    if s['hi_stress'] and s['sev_severe']:
        return random.choices(
            ['Stress Reduction Lifestyle', 'Sleep Improvement Lifestyle'],
            weights=[65, 35]
        )[0]

    # Low activity without metabolic/stress — inactivity loop with bad sleep?
    if s['low_act'] and not s['hi_stress'] and not s['metabolic']:
        if s['bad_sleep']:
            return random.choices(
                ['Active Lifestyle Promotion', 'Sleep Improvement Lifestyle'],
                weights=[55, 45]
            )[0]
        return 'Active Lifestyle Promotion'

    # Overweight + moderate activity — mild weight risk, Active may suffice
    if s['overweight'] and s['mod_act'] and not s['metabolic']:
        return random.choices(
            ['Active Lifestyle Promotion', 'Weight Management Lifestyle'],
            weights=[60, 40]
        )[0]

    # Moderate stress + bad sleep — roughly equal evidence for both
    if s['mod_stress'] and s['bad_sleep']:
        return random.choices(
            ['Stress Reduction Lifestyle', 'Sleep Improvement Lifestyle'],
            weights=[50, 50]
        )[0]

    # Joint patients — gentle movement therapy
    if s['joint'] and not s['sev_severe']:
        return 'Active Lifestyle Promotion'

    # Respiratory → Active (breathing capacity)
    if s['respiratory']:
        return 'Active Lifestyle Promotion'

    # Immune/fatigue without bad sleep → Active (rehabilitation)
    if s['immune_fatigue'] and not s['bad_sleep']:
        return 'Active Lifestyle Promotion'

    # Poor sleep alone
    if s['poor_sleep']:
        return 'Sleep Improvement Lifestyle'

    # Hypertension + overweight (without severe flag above)
    if s['hypertension'] and s['overweight']:
        return random.choices(
            ['Weight Management Lifestyle', 'Active Lifestyle Promotion'],
            weights=[60, 40]
        )[0]

    return 'Preventive Wellness Lifestyle'


# ─────────────────────────────────────────────────────────────────────────────
# BUCKET FUNCTION 3 — Therapeutic Yoga Module  (v16 logic, unchanged in v17)
# ─────────────────────────────────────────────────────────────────────────────

def bucket_yoga_module(row) -> str:
    """
    OUTPUT 3 — Therapeutic Yoga Module (v16 softened determinism, unchanged in v17)

    HIGH-CONFIDENCE (deterministic):
      Joint disease           → Flexibility & Mobility (always)
      Respiratory disease     → Respiratory Pranayama (always)
      Confirmed metabolic + obese/sedentary/Kapha → Weight Management (always)
      Sleep disease           → Relaxation & Sleep (always)

    BORDERLINE (probabilistic):
      High stress + bad sleep → [Stress Reduction 55%, Relaxation & Sleep 45%]
        Rationale: stress drives the sleep problem OR the sleep problem drives
        stress; both yoga protocols are clinically appropriate starting points.

      Bad sleep + immune fatigue → [Relaxation 60%, Stress Reduction 40%]
        Rationale: fatigue-sleep overlap; restorative vs. calming yoga.

      Overweight + Kapha (no confirmed metabolic) → [Weight Mgmt 60%, Respiratory 40%]
        Rationale: Kapha types have mucus/respiratory tendency alongside weight.

      Metabolic WITHOUT obesity/sedentary → [Weight Mgmt 60%, Relaxation 40%]
        Rationale: controlled diabetics benefit from either active or
        stress-reduction yoga.

      Moderate stress + bad sleep → [Stress Reduction 50%, Relaxation 50%]
    """
    random.seed(_row_seed(row))
    s = _sig(row)

    # ── DETERMINISTIC gates ───────────────────────────────────────────────────
    if s['joint']:
        return 'Flexibility & Mobility Therapy'

    if s['respiratory']:
        return 'Respiratory Pranayama'

    # Metabolic with clear physical profile → Weight Management
    if s['metabolic'] and (s['obese'] or s['low_act'] or s['kapha']):
        return 'Weight Management Yoga'

    if s['obese'] and s['low_act']:
        return 'Weight Management Yoga'

    if s['sleep_disease']:
        return 'Relaxation & Sleep Therapy'

    # ── BORDERLINE: probabilistic cases ──────────────────────────────────────

    # Cardiac → Weight Management (cardiac rehab) or Relaxation (gentle)
    if s['cardiac']:
        return random.choices(
            ['Weight Management Yoga', 'Relaxation & Sleep Therapy'],
            weights=[60, 40]
        )[0]

    # High stress + bad sleep — stress OR sleep as primary driver
    if s['hi_stress'] and s['bad_sleep']:
        return random.choices(
            ['Stress Reduction Yoga', 'Relaxation & Sleep Therapy'],
            weights=[55, 45]
        )[0]

    # Mental disease without metabolic
    if s['mental'] and not s['metabolic']:
        return random.choices(
            ['Stress Reduction Yoga', 'Relaxation & Sleep Therapy'],
            weights=[65, 35]
        )[0]

    # Overweight + Kapha (no confirmed diagnosis) → Weight or Respiratory
    if s['overweight'] and s['kapha'] and not s['metabolic']:
        return random.choices(
            ['Weight Management Yoga', 'Respiratory Pranayama'],
            weights=[60, 40]
        )[0]

    # Metabolic without clear physical obesity — active vs restorative
    if s['metabolic']:
        return random.choices(
            ['Weight Management Yoga', 'Relaxation & Sleep Therapy'],
            weights=[65, 35]
        )[0]

    # Bad sleep + immune fatigue — restorative overlap
    if s['bad_sleep'] and s['immune_fatigue']:
        return random.choices(
            ['Relaxation & Sleep Therapy', 'Stress Reduction Yoga'],
            weights=[60, 40]
        )[0]

    # Moderate stress + bad sleep — roughly equal
    if s['mod_stress'] and s['bad_sleep']:
        return random.choices(
            ['Stress Reduction Yoga', 'Relaxation & Sleep Therapy'],
            weights=[50, 50]
        )[0]

    # Immune/fatigue without metabolic or bad sleep → Relaxation (restorative)
    if s['immune_fatigue'] and not s['metabolic']:
        return 'Relaxation & Sleep Therapy'

    # Poor sleep alone
    if s['poor_sleep']:
        return 'Relaxation & Sleep Therapy'

    # High activity + no metabolic → Flexibility (sports injury prevention)
    if s['high_act'] and not s['metabolic']:
        return 'Flexibility & Mobility Therapy'

    # Overweight + low activity (no Kapha / no metabolic)
    if s['overweight'] and s['low_act']:
        return 'Weight Management Yoga'

    # ── DETERMINISTIC Prakriti-based defaults ─────────────────────────────────
    if s['kapha']:
        return 'Respiratory Pranayama'
    if s['pitta']:
        return 'Relaxation & Sleep Therapy'
    if s['vata']:
        return 'Stress Reduction Yoga'

    return 'Weight Management Yoga'


# ─────────────────────────────────────────────────────────────────────────────
# BUCKET FUNCTION 4 — Follow-up Recommendation  (v16 logic, unchanged in v17)
# ─────────────────────────────────────────────────────────────────────────────

def bucket_followup(row) -> str:
    """
    OUTPUT 4 — Follow-up Recommendation (v16 additive risk score, unchanged in v17)

    The follow-up logic uses the additive risk scoring model from v15, which
    is already realistic and well-calibrated. Only the BORDERLINE SCORE BANDS
    (where the score is within ±0.5 of a threshold) are softened with a
    probabilistic choice between adjacent classes.

    This prevents: "score = 3.01 → always 15 Days" while "score = 2.99 →
    always 1 Month" — a clinical artefact with no real-world meaning.

    HIGH-CONFIDENCE (deterministic):
      risk ≥ 7.0 or critical hard overrides → Immediate Consultation
      risk ≥ 6.0 → Follow-up after 7 Days (clear high risk)
      risk < 1.0 → Regular Wellness Follow-up (genuinely healthy)

    BORDERLINE softening:
      5.0 ≤ risk < 6.0  → [7 Days 70%, 15 Days 30%]
      3.0 ≤ risk < 4.0  → [15 Days 60%, 1 Month 40%]
      1.5 ≤ risk < 2.5  → [1 Month 60%, Regular 40%]
    """
    random.seed(_row_seed(row))
    s = _sig(row)

    # ── Hard overrides: clinical emergencies bypass scoring ───────────────────
    if (s['bp_critical'] and s['sev_severe']) or (s['bp_s'] >= 180) or \
       (s['cardiac'] and s['sev_severe']) or (s['tachycardia'] and s['sev_severe']):
        return 'Immediate Consultation Recommended'

    # ── Additive risk score (unchanged weights from v15) ─────────────────────
    risk = 0.0

    if s['bp_critical']:      risk += 3.0
    elif s['bp_high']:        risk += 2.0
    elif s['bp_elevated']:    risk += 1.0

    if s['sev_severe']:       risk += 2.0
    elif s['sev_moderate']:   risk += 1.0

    if s['hi_stress']:        risk += 1.5
    elif s['mod_stress']:     risk += 0.75

    if s['irr_sleep']:        risk += 1.0
    elif s['poor_sleep']:     risk += 0.5

    if s['cardiac']:          risk += 2.0
    elif s['metabolic'] and s['sev_severe']:
                              risk += 1.75
    elif s['metabolic']:      risk += 1.25
    elif s['hypertension']:   risk += 1.25
    elif s['joint']:          risk += 0.75
    elif s['respiratory']:    risk += 1.0
    elif s['immune_fatigue']: risk += 0.5
    elif s['mental']:         risk += 0.75
    elif s['sleep_disease']:  risk += 0.75

    if s['obese'] and s['low_act']:        risk += 0.75
    elif s['overweight'] and s['low_act']: risk += 0.5

    if s['tachycardia'] and not s['cardiac']: risk += 0.5

    # ── Map score to class with borderline softening ──────────────────────────
    if risk >= 7.0:
        return 'Immediate Consultation Recommended'

    if risk >= 6.0:
        return 'Follow-up after 7 Days'   # high-confidence 7-day band

    if 5.0 <= risk < 6.0:
        # Borderline: high-risk but not severely so — 7 Days or 15 Days
        return random.choices(
            ['Follow-up after 7 Days', 'Follow-up after 15 Days'],
            weights=[70, 30]
        )[0]

    if risk >= 4.0:
        return 'Follow-up after 15 Days'  # high-confidence 15-day band

    if 3.0 <= risk < 4.0:
        # Borderline: moderate risk — 15 Days or 1 Month
        return random.choices(
            ['Follow-up after 15 Days', 'Follow-up after 1 Month'],
            weights=[60, 40]
        )[0]

    if risk >= 2.5:
        return 'Follow-up after 1 Month'  # high-confidence 1-month band

    if 1.5 <= risk < 2.5:
        # Borderline: mild risk — 1 Month or Regular Wellness
        return random.choices(
            ['Follow-up after 1 Month', 'Regular Wellness Follow-up'],
            weights=[60, 40]
        )[0]

    return 'Regular Wellness Follow-up'


# ─────────────────────────────────────────────────────────────────────────────
# apply_output_bucketing — dispatches full rows to row-aware functions
# ─────────────────────────────────────────────────────────────────────────────

def apply_output_bucketing(df: pd.DataFrame) -> pd.DataFrame:
    """
    Step 3 (v16 logic, unchanged in v17): Apply all 4 row-aware bucket functions using normalized input
    feature columns as the primary signal source.

    Must be called AFTER normalize_labels() and BEFORE train/test split.
    Row-level seeded randomization ensures reproducibility across runs.
    """
    df = df.copy()
    df['Herbal Therapy Strategy']   = df.apply(bucket_herbal_strategy, axis=1)
    df['Lifestyle Recommendations'] = df.apply(bucket_lifestyle,        axis=1)
    df['Therapeutic Yoga Module']   = df.apply(bucket_yoga_module,      axis=1)
    df['Follow-up Recommendation']  = df.apply(bucket_followup,         axis=1)
    return df


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 3b — LABEL QUALITY VALIDATION  (Steps 5 + 6)
# ─────────────────────────────────────────────────────────────────────────────

def validate_output_balance(Y: pd.DataFrame) -> bool:
    """
    Print class distributions, Shannon entropy, and imbalance warnings for
    all output columns in Y.

    Returns True if ALL columns are within the healthy 10%–40% per-class range,
    False if any warning was raised.

    Called immediately after apply_output_bucketing() and before train/test
    split. If warnings are raised, the bucket functions need further tuning
    before retraining — do NOT proceed to model training with >40% dominance.
    """
    import math
    print(f"\n{'='*64}")
    print("[VALIDATE] Output Class Balance Report (v15 targets: 10%–40%)")
    print("─"*64)

    all_healthy = True

    for col in Y.columns:
        vc      = Y[col].value_counts(normalize=True).sort_values(ascending=False)
        n_cls   = len(vc)
        entropy = -sum(p * math.log2(p) for p in vc if p > 0)
        max_ent = math.log2(n_cls) if n_cls > 1 else 1.0
        bal_pct = entropy / max_ent * 100

        print(f"\n  ── {col}")
        for cls_name, pct in vc.items():
            bar    = '█' * int(pct * 35)
            marker = ''
            if pct > 0.40:
                marker = '  ⚠ DOMINANT >40% — tighten bucket conditions'
                all_healthy = False
            elif pct < 0.10:
                marker = '  ⚠ SPARSE <10% — loosen bucket conditions'
                all_healthy = False
            print(f"    {cls_name:<36}: {pct*100:5.1f}%  {bar}{marker}")

        bal_icon = '✓' if bal_pct >= 65 else ('△' if bal_pct >= 45 else '✗')
        print(f"    Balance score: {bal_pct:.0f}% of perfect entropy  {bal_icon}")

        if bal_pct < 45:
            print(f"    ⚠ [WARNING] Class imbalance detected — "
                  f"balance score {bal_pct:.0f}% < 45% threshold.")
            all_healthy = False

    print(f"\n{'─'*64}")
    if all_healthy:
        print("  ✓ All outputs within healthy balance range (10%–40% per class).")
        print("    SMOTE will fine-tune remaining minor imbalances during training.")
    else:
        print("  ⚠ [WARNING] Class imbalance detected in one or more outputs.")
        print("    Review bucket functions above. SMOTE provides a safety net but")
        print("    cannot fully compensate for >60% single-class dominance.")
    print(f"{'='*64}\n")
    return all_healthy


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 3c — RULE-BASED RECOMMENDATION ENGINES
# These are NOT ML models — they are deterministic lookup tables that enrich
# the ML predictions at inference time with structured, actionable guidance.
# WHY rule-based? Recommendation details (specific poses, durations, habits)
# are clinically standardized and do not require learning from patient data.
# The ML model decides WHICH category; the engine provides the HOW.
# ─────────────────────────────────────────────────────────────────────────────
# These are NOT ML models — they are deterministic lookup tables that enrich
# the ML predictions at inference time with structured, actionable guidance.
# WHY rule-based? Recommendation details (specific poses, durations, habits)
# are clinically standardized and do not require learning from patient data.
# The ML model decides WHICH category; the engine provides the HOW.
# ─────────────────────────────────────────────────────────────────────────────

# ── A. Lifestyle Recommendation Engine ───────────────────────────────────────
LIFESTYLE_ACTIONS: dict = {
    'Stress Reduction Lifestyle': {
        'focus'          : 'Mental wellness and nervous system regulation',
        'daily_habits'   : [
            'Practice 20 minutes of mindfulness or guided meditation each morning',
            'Limit caffeine intake to 1 cup before noon',
            'Maintain a consistent sleep-wake schedule (same time ±30 min daily)',
            'Take 5-minute breathing breaks every 2 hours during work',
            'Reduce screen exposure 1 hour before bedtime',
        ],
        'dietary_changes': [
            'Include Ashwagandha warm milk (1 tsp) before bed',
            'Avoid highly processed foods and refined sugars',
            'Eat warm, easily digestible meals — favour cooked over raw',
            'Include magnesium-rich foods: spinach, almonds, pumpkin seeds',
        ],
        'wellness_tips'  : [
            'Journal thoughts each night for 5 minutes to offload mental load',
            'Walk barefoot on grass (Earthing) for 10 minutes daily',
            'Maintain regular social connections — isolation amplifies stress',
        ],
        'avoid'          : ['Late-night work', 'High-intensity competitive exercise', 'Irregular meal timing'],
    },

    'Weight Management Lifestyle': {
        'focus'          : 'Metabolic regulation and sustainable body composition',
        'daily_habits'   : [
            'Walk briskly for minimum 30 minutes after the largest meal of the day',
            'Use smaller plates to reduce portion size without calorie counting',
            'Drink 300 ml warm water 20 minutes before each meal',
            'Weigh yourself weekly (not daily) to track trend without anxiety',
            'Sleep 7–8 hours — sleep deprivation raises ghrelin (hunger hormone)',
        ],
        'dietary_changes': [
            'Adopt Ayurvedic principle: breakfast moderate, lunch largest, dinner lightest',
            'Replace refined carbs with millets (ragi, jowar, bajra)',
            'Include bitter gourd (karela) juice 30 ml on empty stomach 3×/week',
            'Limit fried and deep-fat foods; use cold-pressed oils sparingly',
            'Include fenugreek seeds (1 tsp soaked overnight) before breakfast',
        ],
        'wellness_tips'  : [
            'Track food intake in a simple diary for the first 2 weeks',
            'Celebrate non-scale victories: energy, mood, clothing fit',
            'Involve a family member in healthy cooking for accountability',
        ],
        'avoid'          : ['Crash diets', 'Skipping meals', 'Late-night heavy dinners', 'Sugary beverages'],
    },

    'Sleep Improvement Lifestyle': {
        'focus'          : 'Circadian rhythm restoration and deep sleep quality',
        'daily_habits'   : [
            'Go to bed and wake at the same time every day — weekends included',
            'Keep bedroom cool (18–20°C), dark, and quiet',
            'Avoid napping after 3 PM',
            'No caffeine or alcohol within 6 hours of bedtime',
            'Do light stretching or legs-up-the-wall pose for 10 min before bed',
        ],
        'dietary_changes': [
            'Drink warm turmeric milk (Haldi doodh) 30 minutes before sleep',
            'Light dinner before 7:30 PM — avoid heavy proteins at night',
            'Include tart cherry juice or banana for natural melatonin',
            'Avoid spicy food at dinner — increases body temperature',
        ],
        'wellness_tips'  : [
            'Create a 30-minute pre-sleep ritual: dim lights, read, warm bath',
            'Use progressive muscle relaxation if racing thoughts prevent sleep',
            'Blue-light blocking glasses after 8 PM significantly improve sleep onset',
        ],
        'avoid'          : ['Screen time in bed', 'Heavy exercise after 7 PM', 'Stimulating conversations late at night'],
    },

    'Active Lifestyle Promotion': {
        'focus'          : 'Building sustainable physical activity from a sedentary baseline',
        'daily_habits'   : [
            'Start with 15-minute morning walks; increase 5 minutes each week',
            'Use stairs instead of lifts for the first 3 floors',
            'Set a phone reminder to stand and move for 2 minutes every hour',
            'Aim for 7,000–10,000 steps per day as a progressive target',
            'Exercise with a partner or group for accountability and motivation',
        ],
        'dietary_changes': [
            'Increase protein intake to support muscle building: eggs, legumes, paneer',
            'Eat a banana or dates 30 minutes before exercise for natural energy',
            'Stay hydrated: 250 ml water for every 20 minutes of activity',
            'Post-exercise recovery: coconut water + a handful of nuts',
        ],
        'wellness_tips'  : [
            'Track activity with a simple step counter — visibility drives behaviour',
            'Pick activities you enjoy: dancing, cycling, swimming, cricket',
            'Rest 1 day per week to allow muscle repair',
        ],
        'avoid'          : ['Going from zero to intense exercise immediately', 'Skipping warm-up and cool-down', 'Dehydration during activity'],
    },

    'Preventive Wellness Lifestyle': {
        'focus'          : 'Maintaining current health and building long-term resilience',
        'daily_habits'   : [
            'Follow Dinacharya (Ayurvedic daily routine): wake before sunrise, tongue scrape, oil pulling',
            'Practice Abhyanga (self-massage with sesame oil) 2–3 times per week',
            'Maintain regular meal timings — eat at similar times each day',
            'Annual full-body health check-up including blood panel',
            '30 minutes of moderate exercise 5 days per week',
        ],
        'dietary_changes': [
            'Eat seasonal, locally grown produce — aligned with your Prakriti',
            'Include Triphala churna (1/2 tsp with warm water at bedtime) for gut health',
            'Minimize processed and packaged foods',
            'Practice mindful eating — chew each bite 20–30 times',
        ],
        'wellness_tips'  : [
            'Cultivate a gratitude practice: 3 things daily',
            'Maintain social and creative hobbies for mental longevity',
            'Sun exposure (15 min before 10 AM) for natural Vitamin D',
        ],
        'avoid'          : ['Ignoring early warning signs', 'Skipping annual health checks', 'Chronic sleep debt'],
    },
}

# ── B. Yoga Module Engine ─────────────────────────────────────────────────────
YOGA_MODULES: dict = {
    'Stress Reduction Yoga': {
        'focus'      : 'Calming the nervous system and releasing mental tension',
        'duration'   : '30–45 minutes daily',
        'poses'      : [
            'Balasana (Child\'s Pose) — 2 min, grounding and surrender',
            'Viparita Karani (Legs-Up-Wall) — 5 min, parasympathetic activation',
            'Uttanasana (Standing Forward Fold) — 1 min, brain blood flow',
            'Janu Sirsasana (Head-to-Knee Forward Bend) — 1 min each side',
            'Savasana (Corpse Pose) — 10 min, full body surrender',
        ],
        'pranayama'  : [
            'Nadi Shodhana (Alternate Nostril Breathing) — 10 min: balances left/right brain hemispheres',
            'Bhramari (Humming Bee Breath) — 5 min: activates vagus nerve, instant calm',
            '4-7-8 Breathing — 4 min: inhale 4s, hold 7s, exhale 8s; slows heart rate',
        ],
        'meditation' : 'Body Scan Meditation — 10 min before sleep',
        'benefits'   : ['Reduces cortisol 20–30%', 'Improves sleep quality', 'Lowers blood pressure', 'Reduces anxiety and rumination'],
        'precautions': ['Avoid inverted poses if hypertensive (BP > 160)', 'Stop if dizziness occurs during pranayama'],
    },

    'Respiratory Pranayama': {
        'focus'      : 'Strengthening lung capacity and clearing respiratory pathways',
        'duration'   : '25–35 minutes daily',
        'poses'      : [
            'Gomukhasana (Cow-Face Pose) — opens chest and shoulders',
            'Matsyasana (Fish Pose) — expands thoracic cavity',
            'Setu Bandhasana (Bridge Pose) — strengthens diaphragm',
            'Bhujangasana (Cobra Pose) — opens lungs, strengthens back',
            'Trikonasana (Triangle Pose) — lateral chest expansion',
        ],
        'pranayama'  : [
            'Kapalbhati (Skull-Shining Breath) — 5 min: clears airways, expels CO₂',
            'Bhastrika (Bellows Breath) — 3 min: maximum lung capacity exercise',
            'Anulom Vilom (Alternate Nostril) — 10 min: balances respiratory rhythm',
            'Ujjayi (Ocean Breath) — 5 min: warms airways, improves breath control',
        ],
        'meditation' : 'Mindful breathing observation — 5 min',
        'benefits'   : ['Increases vital lung capacity', 'Reduces asthma attacks', 'Improves oxygen saturation', 'Clears mucus and congestion'],
        'precautions': ['Avoid Kapalbhati during acute asthma or fever', 'Practise Bhastrika only with trained guidance initially', 'Avoid retention (Kumbhaka) if hypertensive'],
    },

    'Weight Management Yoga': {
        'focus'      : 'Boosting metabolism and building core strength',
        'duration'   : '45–60 minutes daily',
        'poses'      : [
            'Surya Namaskar (Sun Salutation) — 12 rounds: full-body warm-up + cardio',
            'Virabhadrasana I & II (Warrior I & II) — 1 min each: builds leg and core strength',
            'Navasana (Boat Pose) — 30 sec × 3: intense core activation',
            'Ardha Chandrasana (Half Moon Pose) — balance and hip strengthening',
            'Parivrtta Trikonasana (Revolved Triangle) — abdominal twist, digestive stimulation',
            'Dhanurasana (Bow Pose) — stimulates digestive organs',
        ],
        'pranayama'  : [
            'Kapalbhati — 10 min: stimulates abdominal muscles and digestive fire (Agni)',
            'Bhastrika — 5 min: raises metabolic rate',
            'Surya Bhedana (Right Nostril Breathing) — 5 min: activates sympathetic metabolism',
        ],
        'meditation' : 'Mindful eating visualization — 5 min before main meal',
        'benefits'   : ['Boosts basal metabolic rate', 'Reduces visceral fat', 'Improves insulin sensitivity', 'Strengthens core and postural muscles'],
        'precautions': ['Avoid Navasana if lower back pain is acute', 'Progress Surya Namaskar rounds gradually (start with 4)', 'Stay hydrated throughout session'],
    },

    'Flexibility & Mobility Therapy': {
        'focus'      : 'Joint lubrication, range of motion, and pain relief',
        'duration'   : '30–40 minutes daily',
        'poses'      : [
            'Balasana (Child\'s Pose) — 3 min: lumbar decompression',
            'Supta Kapotasana (Reclined Pigeon) — 2 min each: hip flexor release',
            'Setu Bandhasana (Bridge Pose) — 1 min × 3: strengthens posterior chain',
            'Pavanamuktasana (Wind-Relieving Pose) — releases lower back tension',
            'Trikonasana (Triangle Pose) — lateral spine and hip stretch',
            'Vakrasana (Spinal Twist) — lubricates intervertebral discs',
        ],
        'pranayama'  : [
            'Nadi Shodhana — 8 min: reduces systemic inflammation (parasympathetic)',
            'Bhramari — 5 min: reduces pain perception via vagal tone',
        ],
        'meditation' : 'Body awareness scan focusing on tense areas — 8 min',
        'benefits'   : ['Reduces joint stiffness by 40–50%', 'Improves synovial fluid circulation', 'Reduces arthritis pain', 'Prevents injury and muscle imbalances'],
        'precautions': ['Avoid deep twists in acute disc herniation', 'Use props (blocks, bolsters) generously', 'Never force a joint past pain threshold'],
    },

    'Relaxation & Sleep Therapy': {
        'focus'      : 'Deep nervous system restoration and sleep onset support',
        'duration'   : '30 minutes (ideally 8–9 PM)',
        'poses'      : [
            'Viparita Karani (Legs-Up-Wall) — 10 min: reverses venous pooling, deep calm',
            'Supta Baddha Konasana (Reclined Butterfly) — 5 min: hip release',
            'Paschimottanasana (Seated Forward Fold) — 3 min: calms nervous system',
            'Balasana (Child\'s Pose) — 3 min: grounding, inward focus',
            'Savasana with guided body scan — 10 min: full physical and mental release',
        ],
        'pranayama'  : [
            'Chandra Bhedana (Left Nostril Breathing) — 8 min: activates rest-digest mode',
            '4-7-8 Breathing — 5 min: proven sleep onset technique',
            'Bhramari — 5 min: immediate nervous system deceleration',
        ],
        'meditation' : 'Yoga Nidra (psychic sleep) — 20 min audio-guided',
        'benefits'   : ['Improves sleep onset by 15–20 min', 'Increases deep NREM sleep proportion', 'Reduces nighttime cortisol', 'Addresses insomnia and fatigue'],
        'precautions': ['Do not practice after heavy meals (wait 2 hours)', 'Avoid stimulating backbends close to bedtime', 'Use an eye pillow in Savasana for deeper relaxation'],
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 4 — PREPROCESSOR FACTORY
# OHE on categorical, passthrough on numeric, drop everything else.
# handle_unknown='ignore' prevents crashes on unseen values during inference.
# NEVER StandardScaler — tree models are threshold-based.
# NEVER LabelEncoder on X features — always OHE.
# ─────────────────────────────────────────────────────────────────────────────

def make_preprocessor() -> ColumnTransformer:
    return ColumnTransformer(
        transformers=[
            ('cat', OneHotEncoder(handle_unknown='ignore', sparse_output=False), CATEGORICAL_COLS),
            ('num', 'passthrough', NUMERIC_COLS),
        ],
        remainder='drop',
    )


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 4b — SMOTE HELPER
# Applies SMOTE to already-preprocessed (numeric) feature matrix X_pre and a
# single binary/multiclass label vector y for ONE output column.
#
# IMPORTANT design decisions:
#   • Called AFTER the ColumnTransformer has transformed X_train to a dense
#     numeric array. SMOTE requires numeric input — it cannot operate on raw
#     categorical strings or sparse OHE matrices.
#   • k_neighbors is auto-capped to min_class_size − 1.  Without this cap,
#     SMOTE crashes when a minority class has fewer samples than the default
#     k=5 neighbours. This makes SMOTE robust to very rare classes.
#   • SMOTE is applied only to the training split. The test set is never
#     touched — preserving the real-world class distribution for evaluation.
#   • If SMOTE fails for any reason (e.g. only 1 sample in a class), we fall
#     back to the original unbalanced data and log a warning.
# ─────────────────────────────────────────────────────────────────────────────

def apply_smote(X_pre: np.ndarray, y: np.ndarray, col_name: str,
                le: LabelEncoder) -> tuple:
    """
    Apply SMOTE to a preprocessed feature matrix and a single-output label
    vector. Returns (X_balanced, y_balanced).

    Parameters
    ----------
    X_pre     : np.ndarray — OHE + numeric transformed training features
    y         : np.ndarray — integer-encoded labels for one output column
    col_name  : str        — output column name (used for logging only)
    le        : LabelEncoder — fitted encoder (used to decode class names)

    Returns
    -------
    (X_res, y_res) : balanced arrays ready for classifier .fit()
    """
    class_names   = list(le.classes_)
    counts_before = np.bincount(y)
    total_before  = len(y)

    print(f"\n  [SMOTE] {col_name}")
    print(f"  Class distribution BEFORE SMOTE ({total_before} samples):")
    for cls_idx, cnt in enumerate(counts_before):
        pct = cnt / total_before * 100
        name = class_names[cls_idx] if cls_idx < len(class_names) else str(cls_idx)
        bar  = '█' * int(pct / 2)
        print(f"    {name:<28}: {cnt:>5}  ({pct:5.1f}%)  {bar}")

    if not SMOTE_AVAILABLE:
        print(f"  [SMOTE] Skipped — imbalanced-learn not installed.")
        return X_pre, y

    # Auto-cap k_neighbors to avoid crash when a class has < k+1 samples.
    # SMOTE default k=5 fails if any class has ≤ 5 samples.
    min_class_size = counts_before.min()
    k = max(1, min(Config.SMOTE_MAX_K_NEIGHBORS, int(min_class_size) - 1))

    if k < 1:
        print(f"  [SMOTE] Skipped — smallest class has only {min_class_size} sample(s).")
        return X_pre, y

    try:
        sm = SMOTE(k_neighbors=k, random_state=Config.RANDOM_SEED)
        X_res, y_res = sm.fit_resample(X_pre, y)
    except Exception as e:
        print(f"  [SMOTE] Failed ({e}). Falling back to original data.")
        return X_pre, y

    counts_after = np.bincount(y_res)
    total_after  = len(y_res)

    print(f"  Class distribution AFTER SMOTE ({total_after} samples, +{total_after - total_before}):")
    for cls_idx, cnt in enumerate(counts_after):
        pct = cnt / total_after * 100
        name = class_names[cls_idx] if cls_idx < len(class_names) else str(cls_idx)
        bar  = '█' * int(pct / 2)
        print(f"    {name:<28}: {cnt:>5}  ({pct:5.1f}%)  {bar}")

    return X_res, y_res


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 5 — LOAD & PREPARE DATA
# ─────────────────────────────────────────────────────────────────────────────

def load_and_prepare(filepath: str) -> pd.DataFrame:
    """
    Step 1+2+3: Load → fill nulls → normalize labels → bucket outputs.
    Returns cleaned DataFrame ready for split.
    """
    print(f"\n{'='*60}")
    print(f"[LOAD] Dataset: {filepath}")
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Dataset not found: {filepath}")

    df = pd.read_csv(filepath)
    print(f"[LOAD] Shape: {df.shape[0]} rows × {df.shape[1]} columns")

    # Step 1: Fill nulls
    null_count = df.isnull().sum().sum()
    df = df.fillna('Unknown')
    print(f"[LOAD] Nulls filled: {null_count}")

    # Force numeric columns to float
    for c in NUMERIC_COLS:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0.0).astype(float)

    # Verify all required INPUT columns exist (output columns validated via bucketing)
    missing_x = [c for c in INPUT_FEATURES if c not in df.columns]
    if missing_x:
        raise ValueError(
            f"Missing INPUT columns: {missing_x}\n"
            f"  Ensure your dataset contains all 12 input features."
        )
    # Output source columns: checked inside apply_output_bucketing with fallback logic

    # Step 2: Normalize input labels (BEFORE bucketing)
    df = normalize_labels(df)

    # Step 3: Bucket output columns (BEFORE split — prevents leakage)
    df = apply_output_bucketing(df)
    print(f"[LOAD] Output bucketing applied.")

    return df


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 6 — MODEL FACTORY (centralized classifier construction)
#
# [Architecture Audit — Task 1] v17 originally defined these EXACT same
# hyperparameters in THREE separate places: five unused build_*_pipeline()
# functions (dead code, never called), a duplicate _build_raw_classifier()
# used only by fold-safe CV, and a third copy inlined directly in Step 7's
# training loop. All three were kept in sync by hand, with nothing enforcing
# it — a future hyperparameter edit applied to only one site could silently
# desynchronize the CV-scored model from the deployed model.
#
# ModelFactory.build_classifier() is now the SINGLE source of truth. Every
# hyperparameter value below is copied verbatim from v17 — nothing was
# tuned, added, or removed. Both Section 7 (final per-output training) and
# fold_safe_cv_macro_f1() (Section 6b) call this same factory.
# ─────────────────────────────────────────────────────────────────────────────

class ModelFactory:
    """
    Centralized, single-source-of-truth classifier construction.

    Usage:
        ModelFactory.build_classifier('RF', n_classes)
        ModelFactory.build_classifier('XGB', n_classes)

    Returns a FRESH, UNFITTED estimator with the exact v17 hyperparameters.
    Fit-time specifics that vary by algorithm (e.g. GradientBoosting's
    sample_weight in final training) are NOT part of this factory — they
    remain at each call site, exactly as in v17, since they are training
    METHODOLOGY (out of scope for this architecture refactor), not
    construction hyperparameters.
    """

    @staticmethod
    def build_classifier(algo: str, n_classes: int):
        if algo == 'RF':
            return RandomForestClassifier(
                n_estimators=300,
                max_depth=10,
                min_samples_split=10,
                min_samples_leaf=5,
                max_features='sqrt',
                class_weight='balanced_subsample',
                random_state=Config.RANDOM_SEED,
                n_jobs=-1,
            )
        if algo == 'ET':
            return ExtraTreesClassifier(
                n_estimators=300,
                max_depth=10,
                min_samples_split=10,
                min_samples_leaf=5,
                max_features='sqrt',
                class_weight='balanced_subsample',
                random_state=Config.RANDOM_SEED,
                n_jobs=-1,
            )
        if algo == 'GB':
            return GradientBoostingClassifier(
                n_estimators=200,
                max_depth=4,
                learning_rate=0.1,
                subsample=0.8,
                random_state=Config.RANDOM_SEED,
            )
        if algo == 'XGB':
            if not XGB_AVAILABLE:
                raise RuntimeError("xgboost not installed")
            return XGBClassifier(
                n_estimators=300,
                max_depth=6,
                learning_rate=0.05,
                subsample=0.8,
                colsample_bytree=0.8,
                reg_alpha=1.0,
                reg_lambda=1.0,
                eval_metric='mlogloss',
                objective='multi:softmax' if n_classes > 2 else 'binary:logistic',
                num_class=n_classes if n_classes > 2 else None,
                random_state=Config.RANDOM_SEED,
                n_jobs=-1,
            )
        if algo == 'CB':
            if not CAT_AVAILABLE:
                raise RuntimeError("catboost not installed")
            return CatBoostClassifier(
                iterations=300,
                depth=6,
                learning_rate=0.05,
                l2_leaf_reg=5,
                loss_function='MultiClass' if n_classes > 2 else 'Logloss',
                verbose=0,
                random_seed=Config.RANDOM_SEED,
            )
        raise ValueError(f"Unknown algorithm: {algo}")


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 6b — V17 FOLD-SAFE CROSS-VALIDATION HELPERS
#
# WHY these exist (v17):
#   The old CustomAIFramework called cross_val_score(clf, X_train_pre, y, ...)
#   directly. sklearn's cross_val_score CLONES the estimator per fold — the
#   clone is refit from scratch on RAW, NON-SMOTE fold data, while the actual
#   deployed classifier (models[col][algo]) was trained on SMOTE-balanced
#   data. The CV score therefore measured a materially different model than
#   the one being scored/selected.
#
#   v17 fixes this with a manual fold loop where SMOTE is applied ONLY to
#   each fold's TRAINING partition, never to its validation partition, and
#   the fold classifier uses the SAME hyperparameters as the real, deployed
#   classifier for that algorithm. This makes the CV estimate representative
#   of "this algorithm + SMOTE", matching how the final classifier is
#   actually trained in Step 7.
# ─────────────────────────────────────────────────────────────────────────────

def fold_safe_cv_macro_f1(algo: str, X_train_raw, y_tr_i: np.ndarray,
                           n_classes: int, n_splits: int = Config.CV_N_SPLITS) -> tuple:
    """
    Step 8 (v17): Fold-safe 5-fold cross-validation for ONE (algorithm,
    output) pair.

    Flow (per fold) — matches the required Phase-3 CV data flow exactly:
        raw X_train partition (X_train_raw, a pandas DataFrame)
          → StratifiedKFold split → CV training indices / CV validation indices
          → fit a FRESH ColumnTransformer (make_preprocessor()) ONLY on the
            CV training fold's raw rows
          → transform the CV training fold with that fold-local preprocessor
          → transform the untouched CV validation fold with the SAME
            fold-local preprocessor (fit-free — .transform() only)
          → apply SMOTE ONLY to the transformed CV training fold
          → fit a fresh classifier on the SMOTE-resampled CV training fold
          → evaluate (untouched, never SMOTE'd) on the transformed CV
            validation fold

    [v17 FIX — CV PREPROCESSING LEAKAGE]
    Earlier versions of this routine received X_train_pre — feature data
    already transformed by `shared_pre`, which was itself fit once on the
    ENTIRE X_train (Step 6, outside this function). That means every CV
    fold's "validation" rows had already contributed to fitting the
    OneHotEncoder category vocabulary that transformed them, which is a
    preprocessing leakage: the validation fold is supposed to be unseen by
    everything that touches the training fold, including preprocessing.
    This function now takes the RAW (pre-transform) training partition and
    fits `make_preprocessor()` fresh, per fold, on ONLY that fold's training
    rows — the CV validation rows are never seen by any fitting step.

    Uses imblearn's Pipeline where technically appropriate for the
    SMOTE → classifier stage: an imblearn Pipeline only resamples during
    .fit(); its .predict() step passes data straight to the classifier with
    NO resampling. This makes the CV validation fold structurally protected
    from SMOTE, not just protected by convention. Preprocessing is fit
    separately (see above) since ColumnTransformer.fit_transform on a
    DataFrame is clearer to reason about than nesting it inside the
    imblearn Pipeline as well; the leakage-safety guarantee is identical
    either way because both stages are re-fit per fold on the training
    partition only.

    Falls back to training on the raw (unbalanced) fold if the fold's
    smallest class is too small for SMOTE's k-neighbours requirement —
    mirroring apply_smote()'s existing graceful-degradation behaviour.

    Parameters
    ----------
    X_train_raw : pandas.DataFrame
        The RAW (pre-transform) training partition — same rows/order as
        y_tr_i. Must NOT be the shared_pre-transformed array.
    y_tr_i : np.ndarray
        Encoded labels for this output, aligned row-for-row with X_train_raw.

    Returns
    -------
    (cv_macro_f1_mean, cv_std) — both decimals in [0, 1].
    """
    skf_inner = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=Config.RANDOM_SEED)
    fold_scores = []
    row_index = np.arange(len(y_tr_i))

    for cv_train_idx, cv_val_idx in skf_inner.split(row_index, y_tr_i):
        # ── Raw (pre-transform) fold partitions ──────────────────────────
        cv_train_X_raw = X_train_raw.iloc[cv_train_idx]
        cv_val_X_raw   = X_train_raw.iloc[cv_val_idx]
        cv_train_y     = y_tr_i[cv_train_idx]
        cv_val_y       = y_tr_i[cv_val_idx]

        try:
            # ── Fit preprocessing ONLY on this fold's training rows ──────
            fold_pre = make_preprocessor()
            cv_train_X = fold_pre.fit_transform(cv_train_X_raw)
            # Transform-only — the validation fold never influences fitting.
            cv_val_X = fold_pre.transform(cv_val_X_raw)
        except Exception as e:
            print(f"  [WARN] Fold-local preprocessing failed for {algo}: {e}")
            fold_scores.append(0.0)
            continue

        try:
            fresh_clf = ModelFactory.build_classifier(algo, n_classes)
        except Exception:
            fold_scores.append(0.0)
            continue

        # Cap k_neighbors to the smallest class within THIS fold's training
        # partition only (same safety cap logic as apply_smote(), applied at
        # fold granularity so small folds never crash SMOTE).
        min_class_size = int(np.bincount(cv_train_y).min()) if len(cv_train_y) else 0
        k = max(1, min(Config.SMOTE_MAX_K_NEIGHBORS, min_class_size - 1))

        try:
            if SMOTE_AVAILABLE and k >= 1 and min_class_size > 1:
                fold_pipeline = ImbPipeline([
                    ('smote', SMOTE(k_neighbors=k, random_state=Config.RANDOM_SEED)),
                    ('clf',   fresh_clf),
                ])
                fold_pipeline.fit(cv_train_X, cv_train_y)
                # .predict() on an imblearn Pipeline never resamples — the
                # CV validation fold reaches the classifier completely raw.
                fold_pred = np.asarray(fold_pipeline.predict(cv_val_X)).reshape(-1)
            else:
                # Too few minority samples in this fold to SMOTE safely.
                fresh_clf.fit(cv_train_X, cv_train_y)
                fold_pred = np.asarray(fresh_clf.predict(cv_val_X)).reshape(-1)

            fold_f1 = f1_score(cv_val_y, fold_pred, average='macro', zero_division=0)
        except Exception as e:
            print(f"  [WARN] Fold-safe CV failed for {algo}: {e}")
            fold_f1 = 0.0

        fold_scores.append(float(fold_f1))

    fold_scores_arr = np.array(fold_scores) if fold_scores else np.array([0.0])
    return float(fold_scores_arr.mean()), float(fold_scores_arr.std())


# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
# SECTION 6c — GLOBAL SELECTION WITH CONFIGURABLE TIE-BREAKING (Task 2)
#
# The Global CAF formula, its weights, and its inputs are UNCHANGED from
# v17 (see Section 8 inside train_ayursage()). This function only decides
# WHAT TO DO once every algorithm's global_hybrid_score is known: if the
# top score(s) are separated by more than Config.TIE_BREAK_SCORE_THRESHOLD,
# the highest score wins outright — identical to v17's plain
# max(global_hybrid_scores, key=...) behaviour. If two or more algorithms
# land within that margin of each other, they are disambiguated using
# secondary, non-accuracy criteria (CV stability, overfit gap, runtime,
# model complexity, deployment simplicity) — because a 0.0017 score gap is
# noise, not evidence that one algorithm is meaningfully better.
#
# Setting Config.TIE_BREAK_SCORE_THRESHOLD = 0.0 disables tie-breaking
# entirely and reproduces pure v17 argmax selection exactly.
# ─────────────────────────────────────────────────────────────────────────────

def select_best_overall_model(algorithm_results: dict,
                               threshold: float = Config.TIE_BREAK_SCORE_THRESHOLD) -> tuple:
    """
    Selects best_overall_model from algorithm_results using the (unchanged)
    Global CAF scores, with a configurable tie-breaking policy for
    near-identical top scores.

    Parameters
    ----------
    algorithm_results : dict
        {algo: {..., 'global_hybrid_score': float, 'stability_score': float,
                 'mean_overfit_gap': float, 'runtime_seconds': float,
                 'complexity_rank': int, 'deployment_simplicity_rank': int}}
    threshold : float
        Absolute Global CAF score margin within which algorithms are
        considered tied. threshold=0.0 disables tie-breaking.

    Returns
    -------
    (best_overall_model, global_hybrid_scores, tie_break_decision)
        tie_break_decision is a human-readable string explaining WHY the
        winner won — either "clear winner" (no tie) or a description of
        which secondary criterion(a) broke the tie. Never None, so the
        decision is always auditable in training_results.json/metadata.json.
    """
    global_hybrid_scores = {algo: res['global_hybrid_score']
                             for algo, res in algorithm_results.items()}
    if not global_hybrid_scores:
        raise RuntimeError("[CAF] No algorithms produced results — cannot select best_overall_model.")

    best_score = max(global_hybrid_scores.values())
    contenders = [algo for algo, score in global_hybrid_scores.items()
                  if (best_score - score) <= threshold]

    if len(contenders) <= 1:
        winner = max(global_hybrid_scores, key=global_hybrid_scores.get)
        decision = (f"Clear winner: '{winner}' scored {global_hybrid_scores[winner]:.4f}, "
                    f"more than {threshold:.4f} above every other algorithm — "
                    f"no tie-break needed.")
        return winner, global_hybrid_scores, decision

    # ── Near-tie: apply secondary criteria in priority order ────────────────
    # Each step narrows `contenders` to whichever subset is strictly best on
    # that criterion; ties (rare, exact float equality) fall through to the
    # next criterion. The loop guarantees a single, deterministic winner.
    criteria = [
        ('CV Stability (higher stability_score wins)',
         lambda a: -algorithm_results[a]['stability_score']),
        ('Mean Overfit Gap (lower wins)',
         lambda a: algorithm_results[a]['mean_overfit_gap']),
        ('Training Runtime (lower wins)',
         lambda a: algorithm_results[a].get('runtime_seconds', float('inf'))),
        ('Model Complexity (lower wins)',
         lambda a: algorithm_results[a].get('complexity_rank', 99)),
        ('Deployment Simplicity (lower wins)',
         lambda a: algorithm_results[a].get('deployment_simplicity_rank', 99)),
    ]

    trail = [f"Near-tie detected: {sorted(contenders)} scored within "
             f"{threshold:.4f} of the top score ({best_score:.4f})."]

    remaining = list(contenders)
    decisive_criterion = None
    for label, keyfn in criteria:
        if len(remaining) <= 1:
            break
        best_val = min(keyfn(a) for a in remaining)
        narrowed = [a for a in remaining if keyfn(a) == best_val]
        if len(narrowed) < len(remaining):
            decisive_criterion = label
            trail.append(f"  → {label}: narrowed {sorted(remaining)} to {sorted(narrowed)}.")
        remaining = narrowed

    if len(remaining) > 1:
        # Still fully tied after every criterion — deterministic, not random:
        # fall back to alphabetical order so results are reproducible.
        winner = sorted(remaining)[0]
        trail.append(f"  → Still tied after all criteria — resolved alphabetically: '{winner}'.")
    else:
        winner = remaining[0]

    decision = " ".join(trail) + f" Selected: '{winner}'" + (
        f" (decisive criterion: {decisive_criterion})." if decisive_criterion else "."
    )
    return winner, global_hybrid_scores, decision


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 6d — RESEARCH DOCUMENTATION GENERATOR (Task 5)
#
# Produces a concise, self-contained architecture summary, generated
# automatically from THIS run's actual results (not a static template) —
# suitable for inclusion in an SRS, a conference paper's methodology
# section, or as a viva reference sheet. It describes the SELECTION
# ARCHITECTURE only; it does not claim any accuracy figure as final research
# validation on its own (the full training_results.json remains the
# authoritative metrics record).
# ─────────────────────────────────────────────────────────────────────────────

def generate_architecture_summary(best_overall_model: str,
                                   tie_break_decision: str,
                                   global_hybrid_scores: dict,
                                   algorithm_results: dict) -> str:
    """Builds the Markdown architecture summary described in Task 5."""
    scores_table = "\n".join(
        f"| {algo} | {score:.4f} |"
        for algo, score in sorted(global_hybrid_scores.items(), key=lambda kv: kv[1], reverse=True)
    )
    winner_metrics = algorithm_results.get(best_overall_model, {})

    return f"""# AYUR-SAGE — Model Selection Architecture Summary

*Auto-generated from pipeline version {Config.PIPELINE_VERSION}. This document explains
the model-selection architecture and is suitable for an SRS appendix, a
conference paper's methodology section, or viva reference.*

## 1. Why one unified algorithm is selected

AYUR-SAGE produces four related outputs — Herbal Therapy Strategy, Lifestyle
Recommendations, Therapeutic Yoga Module, and Follow-up Recommendation — for
the same patient. Deploying a *different* algorithm family per output (e.g.
Gradient Boosting for Herbal, CatBoost for Lifestyle) would mean shipping,
maintaining, and monitoring several unrelated model types for one clinical
decision, each with its own dependency footprint, retraining cadence, and
failure mode. A single unified algorithm family — one that has been shown to
generalize well across *all four* clinical decision points, not just one —
is simpler to validate, easier to explain to a regulator or reviewer, and
removes the risk of silently inconsistent behaviour between outputs for the
same patient.

## 2. Why multiple algorithms are still trained during experimentation

Committing to one algorithm without comparison would be an arbitrary design
choice. During training, every available algorithm family
(Random Forest, Extra Trees, Gradient Boosting, and — where the optional
dependency is installed — XGBoost and CatBoost) is trained and evaluated
independently on **all four** outputs. This produces the evidence needed to
justify the deployed choice, and preserves full reproducibility: the
research (non-production) bundle retains every candidate classifier so the
comparison can be re-audited later without retraining.

## 3. How Global CAF determines the winner

Each algorithm's results across the four outputs are aggregated into mean
metrics (train accuracy, test accuracy, Macro F1, Weighted F1, CV Macro F1,
CV standard deviation, overfit gap), then combined into a single **Global
CustomAIFramework (CAF) hybrid score**:

```
stability_score      = max(0, 1 − mean_cv_std)
base_hybrid_score     = 0.40·mean_cv_macro_f1 + 0.25·mean_macro_f1
                       + 0.15·mean_weighted_f1 + 0.10·mean_test_accuracy
                       + 0.10·stability_score
overfit_penalty       = min(mean_overfit_gap, 0.20)
global_hybrid_score   = base_hybrid_score − 0.15·overfit_penalty
```

The algorithm with the highest `global_hybrid_score` is selected as
`best_overall_model` — a single, data-driven decision that accounts for
generalization (test accuracy), minority-class performance (Macro F1),
cross-validated stability, and an explicit overfitting penalty, rather than
optimizing any single metric in isolation.

**This run's Global CAF comparison:**

| Algorithm | Global Hybrid Score |
|---|---|
{scores_table}

**Selected:** `{best_overall_model}` (mean CV Macro F1: {winner_metrics.get('mean_cv_macro_f1', 0):.4f},
mean Macro F1: {winner_metrics.get('mean_macro_f1', 0):.4f}, mean overfit gap:
{winner_metrics.get('mean_overfit_gap', 0):.4f})

## 4. How the tie-break policy works

A raw score difference of a few thousandths (e.g. 0.7568 vs 0.7551) is not
meaningful evidence that one algorithm is truly better — it can reflect
noise in a single train/test split. When the top-scoring algorithms fall
within a configurable margin (`Config.TIE_BREAK_SCORE_THRESHOLD`, currently
{Config.TIE_BREAK_SCORE_THRESHOLD}) of each other, the pipeline treats them as a near-tie and
disambiguates using secondary, non-accuracy criteria in priority order:
**(1)** cross-validation stability, **(2)** mean overfit gap, **(3)**
training runtime, **(4)** model complexity, **(5)** deployment simplicity
(whether the algorithm ships as a core scikit-learn dependency or requires
an additional package). If every criterion remains tied, selection falls
back to a deterministic alphabetical rule so the outcome is always
reproducible. Setting the threshold to 0 disables tie-breaking entirely and
reproduces plain highest-score selection.

**This run's decision:** {tie_break_decision}

## 5. Why only the selected algorithm is deployed

All candidate algorithms are trained for comparison, but only
`best_overall_model`'s four classifiers (one per output, since standard
classifiers are single-target) are included in the production bundle
(`{Config.PRODUCTION_BUNDLE_PATH}`). This keeps the deployed artifact small,
removes unused dependencies from the serving path, and ensures the model
actually running in production is unambiguous — there is exactly one
algorithm family answering every request. The full candidate set remains
available separately in the research bundle
(`{Config.RESEARCH_BUNDLE_PATH}`) for future re-comparison or audit.

## 6. Why Doctor HITL remains essential

Every ML output in AYUR-SAGE — herbal strategy, lifestyle guidance, yoga
module, and follow-up interval — is generated for a *wellness recommendation
system*, not an autonomous diagnostic or prescribing agent. The
`Doctor Prescription & Care Notes` field is deliberately never produced by
the model: it is always returned as `PENDING_DOCTOR_REVIEW` and must be
completed by a licensed doctor in the review UI before any recommendation
reaches a patient. This human-in-the-loop boundary exists because Ayurvedic
therapy recommendations can interact with a patient's actual medical
history, current medications, and comorbidities in ways the model has no
visibility into — the ML system proposes a starting point for clinical
judgement, it does not replace it.

---
*Generated automatically at training time from `algorithm_comparison` and
`tie_break_decision` in the production bundle. See `training_results.json`
and `metadata.json` for full numerical detail.*
"""


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 7 — MAIN TRAINING PIPELINE
# ─────────────────────────────────────────────────────────────────────────────

def train_ayursage(filepath: str = Config.DEFAULT_DATASET) -> dict:
    """
    Full training pipeline. Expects the 10K synthetic dataset.
    Falls back to 446-row original if 10K not available (with accuracy warning).

    Returns the saved bundle dict.
    """
    t0 = time.time()

    # [Production Readiness — Task 3] Runtime profiling accumulators. Every
    # phase below is timed with time.time() brackets around the EXISTING
    # code — no methodology, order, or behaviour is changed; this is purely
    # additive instrumentation, persisted into metadata.json at the end.
    runtime_profile = {
        'dataset_loading'       : 0.0,
        'preprocessing'         : 0.0,
        'smote'                 : 0.0,
        'cross_validation'      : 0.0,
        'training'              : 0.0,
        'evaluation'            : 0.0,
        'bundle_saving'         : 0.0,
        'visualization'         : 0.0,
    }

    # ── Load & prepare ──────────────────────────────────────────────────────
    _t = time.time()
    df = load_and_prepare(filepath)
    runtime_profile['dataset_loading'] += time.time() - _t

    X = df[INPUT_FEATURES].copy()
    Y = df[OUTPUT_TARGETS].copy()

    print(f"\n[INFO] Input features  : {len(INPUT_FEATURES)} "
          f"({len(CATEGORICAL_COLS)} categorical, {len(NUMERIC_COLS)} numeric)")
    print(f"[INFO] Output targets  : {len(OUTPUT_TARGETS)}")
    print(f"\n[INFO] Post-bucketing class counts:")
    for col in OUTPUT_TARGETS:
        vc = Y[col].value_counts()
        classes_str = ' | '.join([f"{k}:{v}" for k, v in vc.items()])
        print(f"  {col[:40]:<40}: {classes_str}")

    # ── Validate class balance BEFORE training ────────────────────────────────
    # validate_output_balance() prints per-class distributions, entropy scores,
    # and flags any class >40% or <10%. This is the earliest possible warning:
    # if dominance is severe here, SMOTE alone cannot fully compensate and the
    # bucket functions should be reviewed before proceeding.
    validate_output_balance(Y)

    # ── Step 4: Stratified train/test split ─────────────────────────────────
    # [PART 8] Stratify on the most balanced output column.
    # This ensures the rare classes in Diet appear proportionally in both
    # train and test sets, preventing accidental over/under-representation
    # that can inflate or deflate reported accuracy metrics.
    try:
        stratify_vec = Y[STRATIFY_ON]
        X_train, X_test, Y_train, Y_test = train_test_split(
            X, Y,
            test_size=0.20,
            random_state=Config.RANDOM_SEED,
            stratify=stratify_vec,
        )
        print(f"\n[SPLIT] Stratified on '{STRATIFY_ON}'")
    except ValueError as e:
        # Fallback: some classes have < 2 samples; disable stratify
        print(f"\n[WARN] Stratification failed ({e}). Using random split.")
        X_train, X_test, Y_train, Y_test = train_test_split(
            X, Y, test_size=0.20, random_state=Config.RANDOM_SEED
        )

    print(f"[SPLIT] Train: {len(X_train)} rows | Test: {len(X_test)} rows")

    # ── Step 5: LabelEncode outputs ──────────────────────────────────────────
    # Fit on FULL Y (before split) for class stability — prevents unknown-class
    # errors if a rare class only appears in one split.
    le_output = {}
    Y_train_enc = np.zeros((len(Y_train), len(OUTPUT_TARGETS)), dtype=int)
    Y_test_enc  = np.zeros((len(Y_test),  len(OUTPUT_TARGETS)), dtype=int)

    print("\n[ENCODE] Label encoding outputs:")
    for i, col in enumerate(OUTPUT_TARGETS):
        le = LabelEncoder()
        le.fit(Y[col])                                # fit on FULL Y
        Y_train_enc[:, i] = le.transform(Y_train[col])
        Y_test_enc[:, i]  = le.transform(Y_test[col])
        le_output[col] = le
        print(f"  {col[:40]:<40}: classes = {list(le.classes_)}")

    # ── Step 7: Train candidate models (independent per-output classifiers) ──
    # Each of the 4 output columns gets its own fitted classifier for every
    # algorithm (RF/ET/GB/XGB/CB). These are FINAL, full-training-set
    # classifiers — one per (algorithm, output) pair, up to 4 × 5 = 20 total.
    #
    # v17 CHANGE: algorithm SELECTION is no longer per-output. All algorithms
    # trained here are candidates; a single algorithm family is later chosen
    # GLOBALLY (best_overall_model, Step 8-10 below) by aggregating each
    # algorithm's performance across all 4 outputs. The 4 classifiers
    # belonging to that ONE winning family are what actually gets used for
    # inference — but note each output still has its OWN single-output
    # classifier instance (e.g. 4 separate XGBClassifier objects if XGB
    # wins), never a single multi-output classifier.

    models = {col: {} for col in OUTPUT_TARGETS}

    # ── SMOTE pre-processing note ─────────────────────────────────────────────
    # SMOTE must be applied to numeric (post-OHE) data, so we:
    #   1. Fit-transform X_train through a fresh preprocessor to get X_pre.
    #   2. Apply SMOTE on (X_pre, y_i) → (X_bal, y_bal) per output.
    #   3. Train each classifier directly on the balanced arrays instead of
    #      using a Pipeline.fit() call that would re-transform internally.
    #
    # Classifiers in models[col][algo] are stored as plain fitted estimators
    # (not Pipelines) because the OHE step has already been applied via the
    # shared preprocessor. The shared preprocessor is stored in the bundle so
    # Flask inference can still transform raw inputs before prediction.
    #
    # WHY a shared preprocessor?
    #   All 4 output columns share the same X_train. We fit ONE preprocessor
    #   on X_train once and reuse its transform() output for all outputs.
    #   This prevents redundant re-fitting and guarantees that every model
    #   sees an identical feature representation.

    print(f"\n{'='*60}")
    print("[SMOTE] Fitting shared preprocessor on X_train...")
    _t = time.time()
    shared_pre = make_preprocessor()
    X_train_pre = shared_pre.fit_transform(X_train)     # shape: (n_train, n_ohe_features)
    X_test_pre  = shared_pre.transform(X_test)          # transform only — no leakage
    runtime_profile['preprocessing'] += time.time() - _t
    print(f"  Preprocessed shape — Train: {X_train_pre.shape}  Test: {X_test_pre.shape}")

    # ── Per-output SMOTE + training ───────────────────────────────────────────
    print(f"\n{'='*60}")
    print("[SMOTE] Applying per-output SMOTE oversampling + training all algos...")
    print("─"*60)

    for i, col in enumerate(OUTPUT_TARGETS):
        y_tr_i = Y_train_enc[:, i]
        n_classes = len(le_output[col].classes_)

        # STEP 1+2: Apply SMOTE independently for this output column
        _t = time.time()
        X_bal, y_bal = apply_smote(X_train_pre, y_tr_i, col, le_output[col])
        runtime_profile['smote'] += time.time() - _t

        print(f"\n  ── Training all algos on balanced data for: {col}")

        # STEP 3: Train each classifier on the SMOTE-balanced arrays.
        # Note: classifiers receive pre-transformed X (numpy arrays), so we
        # store plain fitted estimators — not Pipelines. The shared_pre
        # preprocessor handles transformation at inference time.
        #
        # [Architecture Audit — Task 1] Classifier CONSTRUCTION now comes
        # from ModelFactory.build_classifier() — the single source of truth
        # also used by fold-safe CV (Section 6b). Fit-time methodology is
        # UNCHANGED from v17: GradientBoosting still receives the extra
        # sample_weight computed from the SMOTE-balanced labels (GB has no
        # native class_weight parameter); every other algorithm fits
        # normally. This preserves v17's exact training behaviour while
        # removing the third copy of the classifier hyperparameters.
        for algo in ALL_ALGOS:
            try:
                _t = time.time()
                clf = ModelFactory.build_classifier(algo, n_classes)
                if algo == 'GB':
                    # GB doesn't support class_weight natively, so we pass
                    # sample_weight computed from the SMOTE-balanced y_bal
                    # (not the original y_tr_i). After SMOTE the classes
                    # should be roughly equal, so sample weights will be
                    # near-uniform — but this is a safe defensive practice.
                    sw_bal = compute_sample_weight('balanced', y_bal)
                    clf.fit(X_bal, y_bal, sample_weight=sw_bal)
                else:
                    # class_weight='balanced_subsample' (RF/ET) is kept as a
                    # secondary defence inside the classifier even after
                    # SMOTE, providing double coverage: SMOTE handles global
                    # distribution; balanced_subsample re-weights each
                    # bootstrap draw for any residual imbalance SMOTE misses.
                    clf.fit(X_bal, y_bal)
                runtime_profile['training'] += time.time() - _t
                models[col][algo] = clf
                print(f"    {algo:<3} ✓  (trained on {len(X_bal)} balanced samples)")
            except Exception as e:
                print(f"    {algo:<3} ERROR: {e}")
                traceback.print_exc()

    # ── Step 8: GLOBAL CustomAIFramework — algorithm_results aggregation ─────
    # [v17] REMOVED: per-output algorithm selection (best_model_per_output).
    # Every algorithm is now evaluated across ALL FOUR outputs, then its
    # per-output metrics are aggregated into ONE set of mean metrics for
    # that algorithm family. A single algorithm family is selected globally
    # (best_overall_model) — it is NOT acceptable for Herbal to use GB while
    # Lifestyle uses CB; whichever family wins, wins for all 4 outputs.
    #
    # For each algorithm, for each output:
    #   - train_accuracy, test_accuracy, macro_f1, weighted_f1, overfit_gap
    #     are computed from the FINAL classifier (models[col][algo]), which
    #     was trained on that output's own SMOTE-balanced full training data
    #     (Step 7 above) — per-output SMOTE for final training is unchanged.
    #   - cv_macro_f1, cv_std come from fold_safe_cv_macro_f1() (Section 6b),
    #     where SMOTE is applied only inside each CV training fold and the
    #     CV validation fold is never touched by SMOTE.
    #
    # All values below are kept as DECIMALS in [0, 1]. Percentage formatting
    # (×100) is applied ONLY at print() time for console display.
    print(f"\n{'='*60}")
    print("[CAF] Global CustomAIFramework — Algorithm-Level Evaluation")
    print(f"      Algos under evaluation: {ALL_ALGOS}")
    print("─"*60)

    algorithm_results = {}   # {algo: {per_output: {...}, mean_*: ..., global_hybrid_score: ...}}

    for algo in ALL_ALGOS:
        algo_start_time = time.time()   # Task 2: runtime tie-break criterion
        print(f"\n  ── Algorithm: {algo}")
        print(f"  {'Output':<32} {'TrainAcc':>8} {'TestAcc':>8} {'MacroF1':>8} "
              f"{'WtdF1':>7} {'CV-F1':>7} {'CV-Std':>7} {'Gap':>6}")
        print(f"  {'─'*90}")

        per_output = {}

        for i, col in enumerate(OUTPUT_TARGETS):
            if algo not in models[col]:
                # This algorithm failed to train for this output (Step 7
                # try/except) — skip it for this output only; it will simply
                # be absent from the mean aggregation below.
                print(f"  {col[:32]:<32}  [NOT TRAINED FOR THIS OUTPUT — skipped]")
                continue

            clf     = models[col][algo]
            y_tr_i  = Y_train_enc[:, i]
            n_classes = len(le_output[col].classes_)

            # ── Test-set metrics from the FINAL (SMOTE-trained) classifier ──
            try:
                # [PART 3] Safe flatten — some classifiers return shape (n,1) not (n,)
                tr_pred = np.asarray(clf.predict(X_train_pre)).reshape(-1)
                te_pred = np.asarray(clf.predict(X_test_pre)).reshape(-1)

                train_accuracy = float(accuracy_score(y_tr_i,            tr_pred))
                test_accuracy  = float(accuracy_score(Y_test_enc[:, i],  te_pred))
                macro_f1       = float(f1_score(Y_test_enc[:, i], te_pred,
                                                 average='macro',    zero_division=0))
                weighted_f1    = float(f1_score(Y_test_enc[:, i], te_pred,
                                                 average='weighted', zero_division=0))
                overfit_gap    = abs(train_accuracy - test_accuracy)
            except Exception as e:
                print(f"  [WARN] Prediction failed for {algo} on '{col}': {e}")
                train_accuracy = test_accuracy = macro_f1 = weighted_f1 = 0.0
                overfit_gap = 1.0

            # ── Fold-safe CV Macro F1 (Section 6b) ───────────────────────────
            # SMOTE applied only inside each CV training fold; CV validation
            # fold and the outer test set are never touched by SMOTE.
            # v17 FIX: pass RAW X_train (not X_train_pre) — preprocessing is
            # now fit fresh inside each fold on the fold's training rows
            # only, eliminating CV preprocessing leakage (see docstring).
            _t = time.time()
            try:
                cv_macro_f1, cv_std = fold_safe_cv_macro_f1(
                    algo, X_train, y_tr_i, n_classes, n_splits=Config.CV_N_SPLITS,
                )
            except Exception as e:
                print(f"  [WARN] Fold-safe CV failed for {algo} on '{col}': {e}")
                cv_macro_f1, cv_std = 0.0, 1.0
            runtime_profile['cross_validation'] += time.time() - _t

            per_output[col] = {
                'train_accuracy': train_accuracy,
                'test_accuracy' : test_accuracy,
                'macro_f1'      : macro_f1,
                'weighted_f1'   : weighted_f1,
                'cv_macro_f1'   : cv_macro_f1,
                'cv_std'        : cv_std,
                'overfit_gap'   : overfit_gap,
            }

            print(f"  {col[:32]:<32} {train_accuracy*100:7.2f}% {test_accuracy*100:7.2f}% "
                  f"{macro_f1*100:7.2f}% {weighted_f1*100:6.2f}% {cv_macro_f1*100:6.2f}% "
                  f"{cv_std:7.4f} {overfit_gap*100:5.2f}%")

        # ── Aggregate this algorithm's per-output metrics into means ────────
        if per_output:
            mean_train_accuracy = float(np.mean([v['train_accuracy'] for v in per_output.values()]))
            mean_test_accuracy  = float(np.mean([v['test_accuracy']  for v in per_output.values()]))
            mean_macro_f1       = float(np.mean([v['macro_f1']       for v in per_output.values()]))
            mean_weighted_f1    = float(np.mean([v['weighted_f1']    for v in per_output.values()]))
            mean_cv_macro_f1    = float(np.mean([v['cv_macro_f1']    for v in per_output.values()]))
            mean_cv_std         = float(np.mean([v['cv_std']         for v in per_output.values()]))
            mean_overfit_gap    = float(np.mean([v['overfit_gap']    for v in per_output.values()]))
        else:
            # Algorithm failed to train on ALL 4 outputs — score it out of
            # contention rather than crashing global selection.
            mean_train_accuracy = mean_test_accuracy = mean_macro_f1 = 0.0
            mean_weighted_f1 = mean_cv_macro_f1 = 0.0
            mean_cv_std = 1.0
            mean_overfit_gap = 1.0

        # ── Global CAF hybrid score (approved v17 formula — UNCHANGED) ────────
        # base_hybrid_score =
        #       0.40 * mean_cv_macro_f1
        #     + 0.25 * mean_macro_f1
        #     + 0.15 * mean_weighted_f1
        #     + 0.10 * mean_test_accuracy
        #     + 0.10 * stability_score
        # stability_score  = max(0, 1 - mean_cv_std)
        # overfit_penalty  = min(mean_overfit_gap, 0.20)
        # global_hybrid_score = base_hybrid_score - (0.15 * overfit_penalty)
        # [Task 4] Weights now read from Config — identical numeric values,
        # single named location instead of bare literals in the formula.
        stability_score = max(0.0, 1.0 - mean_cv_std)
        base_hybrid_score = (
            Config.CAF_WEIGHT_CV_MACRO_F1   * mean_cv_macro_f1 +
            Config.CAF_WEIGHT_MACRO_F1      * mean_macro_f1 +
            Config.CAF_WEIGHT_WEIGHTED_F1   * mean_weighted_f1 +
            Config.CAF_WEIGHT_TEST_ACCURACY * mean_test_accuracy +
            Config.CAF_WEIGHT_STABILITY     * stability_score
        )
        overfit_penalty = min(mean_overfit_gap, Config.CAF_OVERFIT_PENALTY_CAP)
        global_hybrid_score = base_hybrid_score - (Config.CAF_OVERFIT_PENALTY_WEIGHT * overfit_penalty)

        algo_runtime_seconds = round(time.time() - algo_start_time, 2)   # Task 2 tie-break input

        algorithm_results[algo] = {
            'per_output'          : per_output,
            'mean_train_accuracy' : mean_train_accuracy,
            'mean_test_accuracy'  : mean_test_accuracy,
            'mean_macro_f1'       : mean_macro_f1,
            'mean_weighted_f1'    : mean_weighted_f1,
            'mean_cv_macro_f1'    : mean_cv_macro_f1,
            'mean_cv_std'         : mean_cv_std,
            'mean_overfit_gap'    : mean_overfit_gap,
            'stability_score'     : stability_score,
            'base_hybrid_score'   : base_hybrid_score,
            'global_hybrid_score' : global_hybrid_score,
            'runtime_seconds'     : algo_runtime_seconds,
            'complexity_rank'     : Config.MODEL_COMPLEXITY_RANK.get(algo, 99),
            'deployment_simplicity_rank': Config.DEPLOYMENT_SIMPLICITY_RANK.get(algo, 99),
        }

        print(f"  {'─'*90}")
        print(f"  MEAN  TrainAcc:{mean_train_accuracy*100:6.2f}%  TestAcc:{mean_test_accuracy*100:6.2f}%  "
              f"MacroF1:{mean_macro_f1*100:6.2f}%  WtdF1:{mean_weighted_f1*100:6.2f}%  "
              f"CV-F1:{mean_cv_macro_f1*100:6.2f}%  CV-Std:{mean_cv_std:.4f}  "
              f"Gap:{mean_overfit_gap*100:5.2f}%")
        print(f"  Global Hybrid Score: {global_hybrid_score:.4f}   (runtime: {algo_runtime_seconds}s)")

    # ── Step 9: Select best_overall_model — NOT hardcoded, purely score-driven
    # [Task 2] Selection now goes through select_best_overall_model(), which
    # reproduces plain argmax when the top score is a clear winner, and only
    # applies secondary tie-break criteria (CV stability, overfit gap,
    # runtime, complexity, deployment simplicity) when two or more
    # algorithms land within Config.TIE_BREAK_SCORE_THRESHOLD of each other.
    # The Global CAF formula/inputs computed above are completely unchanged.
    best_overall_model, global_hybrid_scores, tie_break_decision = \
        select_best_overall_model(algorithm_results, Config.TIE_BREAK_SCORE_THRESHOLD)

    print(f"\n{'='*60}")
    print("SELECTED UNIFIED ALGORITHM")
    print("─"*60)
    print(f"  best_overall_model = '{best_overall_model}'")
    print(f"  (One unified algorithm family used for ALL 4 outputs — no mixed ensemble.)")
    print(f"  WHY: {tie_break_decision}")

    print(f"\n{'='*60}")
    print("[CAF] GLOBAL ALGORITHM COMPARISON")
    print("─"*60)
    print(f"  {'Algorithm':<10} {'GlobalHybridScore':>18}")
    for algo, score in sorted(global_hybrid_scores.items(), key=lambda kv: kv[1], reverse=True):
        marker = '  ← SELECTED' if algo == best_overall_model else ''
        print(f"  {algo:<10} {score:18.4f}{marker}")

    # ── FINAL UNIFIED MODEL EVALUATION ────────────────────────────────────────
    # v17: the mixed best-model-per-output ensemble is REMOVED. Every output
    # is evaluated using the SAME winning algorithm family (best_overall_model).
    print(f"\n{'='*60}")
    print("FINAL UNIFIED MODEL EVALUATION")
    print("─"*60)
    print(f"Selected Unified Algorithm: {best_overall_model}")
    print("─"*60)

    final_test_preds  = np.zeros((len(X_test),  len(OUTPUT_TARGETS)), dtype=int)
    final_train_preds = np.zeros((len(X_train), len(OUTPUT_TARGETS)), dtype=int)

    for i, col in enumerate(OUTPUT_TARGETS):
        # [PART 3] Safe flatten — prevents (n,1) → (n,) broadcast ValueError
        final_test_preds[:, i]  = np.asarray(models[col][best_overall_model].predict(X_test_pre)).reshape(-1)
        final_train_preds[:, i] = np.asarray(models[col][best_overall_model].predict(X_train_pre)).reshape(-1)

    print(f"\n  {'Output':<42} {'Train':>7} {'Test':>7} {'Gap':>7} {'MacroF1':>8} {'WtdF1':>7}")
    print("  " + "─"*76)
    all_tr, all_te, all_mf1, all_wf1 = [], [], [], []
    for i, col in enumerate(OUTPUT_TARGETS):
        ta  = accuracy_score(Y_train_enc[:, i], final_train_preds[:, i]) * 100
        tea = accuracy_score(Y_test_enc[:, i],  final_test_preds[:, i])  * 100
        mf1 = f1_score(Y_test_enc[:, i], final_test_preds[:, i],
                       average='macro',    zero_division=0) * 100
        wf1 = f1_score(Y_test_enc[:, i], final_test_preds[:, i],
                       average='weighted', zero_division=0) * 100
        all_tr.append(ta); all_te.append(tea)
        all_mf1.append(mf1); all_wf1.append(wf1)
        print(f"  [{i+1}] {col[:38]:<38} {ta:6.1f}%  {tea:6.1f}%  {ta-tea:5.1f}%  "
              f"{mf1:7.1f}%  {wf1:6.1f}%")
    print("  " + "─"*76)
    print(f"  {'MEAN':<40} {np.mean(all_tr):6.1f}%  {np.mean(all_te):6.1f}%  "
          f"{np.mean(all_tr)-np.mean(all_te):5.1f}%  {np.mean(all_mf1):7.1f}%  {np.mean(all_wf1):6.1f}%")

    # ── Step 9a: Advanced Evaluation ─────────────────────────────────────────
    # [PART 7] Confusion matrix + classification report per output
    _ensure_output_dirs()

    print(f"\n{'='*60}")
    print("[EVAL] ADVANCED EVALUATION — Classification Reports + Confusion Matrices")
    print("─"*60)

    training_results = {}

    for i, col in enumerate(OUTPUT_TARGETS):
        # v17: winner is the single global best_overall_model — identical
        # across all 4 outputs, no per-output mixing.
        winner      = best_overall_model
        te_pred     = final_test_preds[:, i]
        te_true     = Y_test_enc[:, i]
        class_names = list(le_output[col].classes_)

        # [PART 7] Full classification report
        # FIX: pass explicit labels= to prevent ValueError when some classes
        # are absent from y_pred (sparse test set after SMOTE rebalancing).
        # zero_division=0 suppresses warnings for classes with no predictions.
        _t = time.time()
        try:
            report = classification_report(
                te_true, te_pred,
                labels=list(range(len(class_names))),
                target_names=class_names,
                zero_division=0,
            )
            print(f"\n  [{i+1}] {col} (winner: {winner})")
            print(report)
        except Exception as e:
            print(f"\n  [{i+1}] {col} (winner: {winner})")
            print(f"  [WARN] classification_report failed: {e} — skipping report.")
        runtime_profile['evaluation'] += time.time() - _t

        # [PART 7] Confusion matrix — wrapped in try/except so a single output
        # failure never aborts the full training run or blocks bundle saving.
        cm = None
        try:
            _t = time.time()
            cm = confusion_matrix(te_true, te_pred)
            runtime_profile['evaluation'] += time.time() - _t

            _t = time.time()
            fig, ax = plt.subplots(figsize=(max(5, len(class_names)), max(4, len(class_names))))
            im = ax.imshow(cm, interpolation='nearest', cmap='Blues')
            plt.colorbar(im, ax=ax)
            ax.set_xticks(range(len(class_names)))
            ax.set_yticks(range(len(class_names)))
            ax.set_xticklabels(class_names, rotation=35, ha='right', fontsize=8)
            ax.set_yticklabels(class_names, fontsize=8)
            ax.set_xlabel('Predicted', fontsize=10)
            ax.set_ylabel('Actual',    fontsize=10)
            ax.set_title(f'{col[:40]}\n(winner: {winner})', fontsize=9, pad=10)
            thresh = cm.max() / 2.0
            for r in range(cm.shape[0]):
                for c_idx in range(cm.shape[1]):
                    ax.text(c_idx, r, str(cm[r, c_idx]),
                            ha='center', va='center', fontsize=8,
                            color='white' if cm[r, c_idx] > thresh else 'black')
            plt.tight_layout()
            safe_name = col.replace('/', '_').replace(' ', '_').replace('&', 'and')
            cm_path = f'{Config.RESULTS_DIR}/cm_{i+1}_{safe_name}_{winner}.png'
            plt.savefig(cm_path, dpi=120)
            plt.close(fig)
            runtime_profile['visualization'] += time.time() - _t
            print(f"  Confusion matrix saved: {cm_path}")
        except Exception as e:
            print(f"  [WARN] Confusion matrix failed for '{col}': {e}")

        # ── [PART 9] Feature Importance ──────────────────────────────────────
        # Models are now plain classifiers; use shared_pre for feature names.
        _t = time.time()
        try:
            try:
                ohe_features = shared_pre.named_transformers_['cat'] \
                    .get_feature_names_out(CATEGORICAL_COLS).tolist()
            except AttributeError:
                ohe_features = shared_pre.named_transformers_['cat'] \
                    .get_feature_names(CATEGORICAL_COLS).tolist()
            all_feature_names = ohe_features + NUMERIC_COLS

            clf = models[col][winner]

            # Generic feature-importance extraction: try the common sklearn
            # attribute first, then CatBoost's method-based equivalent. If
            # neither is exposed by this estimator, warn and skip safely —
            # training must never crash because one algorithm lacks
            # feature importances.
            importances = None
            if hasattr(clf, 'feature_importances_'):
                importances = np.asarray(clf.feature_importances_)
            elif hasattr(clf, 'get_feature_importance'):
                importances = np.asarray(clf.get_feature_importance())
            else:
                print(f"  [WARN] '{winner}' does not expose feature_importances_ "
                      f"(or get_feature_importance) — skipping feature importance "
                      f"plot for '{col}'.")

            if importances is not None and len(importances) == len(all_feature_names):
                top_n   = min(Config.FEATURE_IMPORTANCE_TOP_N, len(importances))
                indices  = np.argsort(importances)[::-1][:top_n]
                top_names = [all_feature_names[j] for j in indices]
                top_vals  = importances[indices]

                fig2, ax2 = plt.subplots(figsize=(9, max(4, top_n * 0.4)))
                ax2.barh(range(top_n), top_vals[::-1], color='steelblue', edgecolor='white')
                ax2.set_yticks(range(top_n))
                ax2.set_yticklabels(top_names[::-1], fontsize=7)
                ax2.set_xlabel('Feature Importance', fontsize=9)
                ax2.set_title(f'Top-{top_n} Feature Importances\n{col[:40]} [{winner}]',
                              fontsize=9)
                ax2.xaxis.set_major_formatter(mticker.FormatStrFormatter('%.3f'))
                plt.tight_layout()
                fi_path = f'{Config.FEATURE_IMPORTANCE_DIR}/fi_{i+1}_{safe_name}_{winner}.png'
                plt.savefig(fi_path, dpi=120)
                plt.close(fig2)
                print(f"  Feature importance saved: {fi_path}")
            elif importances is not None:
                print(f"  [WARN] Feature importance shape mismatch for {winner} "
                      f"on '{col}' ({len(importances)} importances vs "
                      f"{len(all_feature_names)} feature names) — skipped safely.")
        except Exception as e:
            print(f"  [WARN] Feature importance failed for {winner} on '{col}': {e} "
                  f"— skipped safely, training continues.")
        runtime_profile['visualization'] += time.time() - _t

        # ── [Production Readiness — Task 2] SHAP Explainability ───────────────
        # Purely explanatory — never affects predictions, training, or model
        # selection. Uses shap.TreeExplainer, appropriate for all 5 supported
        # algorithm families (RF/ET/GB/XGB/CB are all tree ensembles). Any
        # failure (unsupported estimator, shap internals mismatch, etc.) is
        # caught, logged, and skipped — training must never crash because of
        # an explainability add-on.
        _shap_t0 = time.time()
        if SHAP_AVAILABLE:
            try:
                clf = models[col][winner]
                sample_n = min(Config.SHAP_MAX_SAMPLES, X_test_pre.shape[0])
                X_shap_sample = X_test_pre[:sample_n]

                explainer = shap.TreeExplainer(clf)
                shap_values = explainer.shap_values(X_shap_sample)

                # Multi-class tree explainers return a list of per-class
                # arrays (or a 3-D array in newer shap versions) — reduce to
                # a single mean(|SHAP value|) per feature across classes so
                # one summary plot can represent the whole output.
                if isinstance(shap_values, list):
                    mean_abs_shap = np.mean(
                        [np.abs(sv).mean(axis=0) for sv in shap_values], axis=0
                    )
                elif isinstance(shap_values, np.ndarray) and shap_values.ndim == 3:
                    mean_abs_shap = np.abs(shap_values).mean(axis=(0, 2))
                else:
                    mean_abs_shap = np.abs(shap_values).mean(axis=0)

                if len(mean_abs_shap) == len(all_feature_names):
                    top_n_shap = min(Config.FEATURE_IMPORTANCE_TOP_N, len(mean_abs_shap))
                    shap_indices = np.argsort(mean_abs_shap)[::-1][:top_n_shap]
                    shap_names = [all_feature_names[j] for j in shap_indices]
                    shap_vals  = mean_abs_shap[shap_indices]

                    fig3, ax3 = plt.subplots(figsize=(9, max(4, top_n_shap * 0.4)))
                    ax3.barh(range(top_n_shap), shap_vals[::-1], color='indianred', edgecolor='white')
                    ax3.set_yticks(range(top_n_shap))
                    ax3.set_yticklabels(shap_names[::-1], fontsize=7)
                    ax3.set_xlabel('Mean |SHAP value|', fontsize=9)
                    ax3.set_title(f'SHAP Feature Impact — Top-{top_n_shap}\n{col[:40]} [{winner}]',
                                  fontsize=9)
                    plt.tight_layout()
                    shap_path = f'{Config.SHAP_DIR}/shap_{i+1}_{safe_name}_{winner}.png'
                    plt.savefig(shap_path, dpi=120)
                    plt.close(fig3)
                    print(f"  SHAP explanation saved: {shap_path}")
                else:
                    print(f"  [WARN] SHAP value shape mismatch for {winner} on '{col}' "
                          f"— skipped safely.")
            except Exception as e:
                print(f"  [WARN] SHAP explanation failed for {winner} on '{col}': {e} "
                      f"— skipped safely, training continues.")
        else:
            print(f"  [INFO] SHAP not available — explanation skipped for '{col}'.")
        runtime_profile['visualization'] += time.time() - _shap_t0

        # ── Per-output results dict (for JSON) ────────────────────────────────
        per_class_f1 = f1_score(te_true, te_pred, average=None, zero_division=0).tolist()
        training_results[col] = {
            'winner_model'    : winner,   # == best_overall_model for every output (v17)
            'train_accuracy'  : round(float(accuracy_score(
                                    Y_train_enc[:, i], final_train_preds[:, i]) * 100), 2),
            'test_accuracy'   : round(float(accuracy_score(te_true, te_pred) * 100), 2),
            'macro_f1'        : round(float(f1_score(
                                    te_true, te_pred, average='macro', zero_division=0) * 100), 2),
            'weighted_f1'     : round(float(f1_score(
                                    te_true, te_pred, average='weighted', zero_division=0) * 100), 2),
            'classes'         : class_names,
            'per_class_f1'    : {class_names[k]: round(per_class_f1[k] * 100, 2)
                                 for k in range(len(class_names))},
            'confusion_matrix': cm.tolist() if cm is not None else [],
            # cv_scores: this output's CV Macro F1 for EVERY evaluated algorithm
            # (not just the winner) — sourced from algorithm_results (Step 8),
            # preserved for downstream inspection of the global comparison.
            'cv_scores'       : {algo: round(
                                    algorithm_results[algo]['per_output']
                                        .get(col, {}).get('cv_macro_f1', 0.0) * 100, 2)
                                 for algo in ALL_ALGOS},
        }

    # ── [PART 7] Save training_results.json ──────────────────────────────────
    elapsed = round(time.time() - t0, 1)

    def _to_native(obj):
        """
        Recursively converts numpy scalar/array types to standard Python
        float/int/str/list types so json.dump() never chokes on numpy
        objects (np.float64, np.int64, np.ndarray, np.str_, etc.). Applied
        as a final safety pass over the whole payload before serialization.
        """
        if isinstance(obj, dict):
            return {str(k): _to_native(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [_to_native(v) for v in obj]
        if isinstance(obj, np.ndarray):
            return _to_native(obj.tolist())
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, np.bool_):
            return bool(obj)
        if isinstance(obj, np.str_):
            return str(obj)
        return obj

    # ── global_algorithm_comparison: ONE aggregated record per algorithm ──────
    # (mean metrics across all 4 outputs + the global hybrid score that
    # decided best_overall_model). Percentage scale for readability, decimal
    # internals were used for the actual selection math (Step 8/9 above).
    global_algorithm_comparison = {
        algo: {
            'mean_train_accuracy' : round(res['mean_train_accuracy'] * 100, 2),
            'mean_test_accuracy'  : round(res['mean_test_accuracy']  * 100, 2),
            'mean_macro_f1'       : round(res['mean_macro_f1']       * 100, 2),
            'mean_weighted_f1'    : round(res['mean_weighted_f1']    * 100, 2),
            'mean_cv_macro_f1'    : round(res['mean_cv_macro_f1']    * 100, 2),
            'mean_cv_std'         : round(res['mean_cv_std'], 4),
            'mean_overfit_gap'    : round(res['mean_overfit_gap']    * 100, 2),
            'global_hybrid_score' : round(res['global_hybrid_score'], 4),
        }
        for algo, res in algorithm_results.items()
    }

    # ── selected_model_per_output_results: PER-OUTPUT PERFORMANCE of the ──────
    # SAME globally selected algorithm (best_overall_model) only. This is NOT
    # a per-output winner table — 'winner_model' is included purely so it's
    # visually verifiable that every entry names the identical algorithm.
    selected_model_per_output_results = {
        col: {
            'winner_model'    : res['winner_model'],   # == best_overall_model, every row
            'train_accuracy'  : res['train_accuracy'],
            'test_accuracy'   : res['test_accuracy'],
            'macro_f1'        : res['macro_f1'],
            'weighted_f1'     : res['weighted_f1'],
            'classes'         : res['classes'],
            'per_class_f1'    : res['per_class_f1'],
            'confusion_matrix': res['confusion_matrix'],
        }
        for col, res in training_results.items()
    }
    assert len(set(r['winner_model'] for r in selected_model_per_output_results.values())) <= 1, \
        "[BUG] selected_model_per_output_results contains more than one distinct algorithm winner!"

    # ── overall_selected_model_metrics: mean of the SAME winning algorithm's ──
    # per-output metrics (i.e. the headline numbers for best_overall_model).
    overfit_gaps = [abs(t - e) for t, e in zip(all_tr, all_te)]
    overall_selected_model_metrics = {
        'mean_train_accuracy' : round(float(np.mean(all_tr)), 2),
        'mean_test_accuracy'  : round(float(np.mean(all_te)), 2),
        'mean_macro_f1'       : round(float(np.mean(all_mf1)), 2),
        'mean_weighted_f1'    : round(float(np.mean(all_wf1)), 2),
        'mean_overfit_gap'    : round(float(np.mean(overfit_gaps)), 2),
    }

    summary_payload = {
        'pipeline_version'                   : Config.PIPELINE_VERSION,
        'selected_unified_algorithm'         : best_overall_model,
        'global_algorithm_comparison'        : global_algorithm_comparison,
        'selected_model_per_output_results'  : selected_model_per_output_results,
        'overall_selected_model_metrics'     : overall_selected_model_metrics,
    }
    summary_payload = _to_native(summary_payload)   # final numpy-safety pass

    json_path = Config.TRAINING_RESULTS_PATH
    try:
        with open(json_path, 'w', encoding='utf-8') as jf:
            json.dump(summary_payload, jf, indent=2, ensure_ascii=False)
        print(f"\n  Training results JSON saved: {json_path}")
    except Exception as e:
        print(f"\n  [WARN] Could not save training_results.json: {e}")
    print(f"  Confusion matrices  : {Config.RESULTS_DIR}/cm_*_{best_overall_model}.png")
    print(f"  Feature importances : {Config.FEATURE_IMPORTANCE_DIR}/fi_*_{best_overall_model}.png")

    # ── [PART 10] Save bundles: PRODUCTION (lean) + RESEARCH (full) ───────────
    # [Architecture Audit — Task 3] v17 originally saved ONE bundle containing
    # every trained (algorithm, output) classifier — up to 20 fitted models —
    # even though inference only ever uses the 4 belonging to
    # best_overall_model. That's fine for research reproducibility, but
    # wasteful and unnecessary for a production deployment artifact.
    #
    # We now save TWO bundles:
    #   • PRODUCTION bundle (Config.PRODUCTION_BUNDLE_PATH, default
    #     'ayursage_model.pkl'): models[col] contains ONLY
    #     {best_overall_model: <fitted classifier>} for each of the 4
    #     outputs — exactly 4 classifier objects total, not up to 20. This
    #     is what predict_single()/Flask should load for serving.
    #   • RESEARCH bundle (Config.RESEARCH_BUNDLE_PATH, default
    #     'ayursage_model_research.pkl'): unchanged from v17 — every
    #     candidate classifier for every (algorithm, output) pair, for
    #     reproducibility / re-auditing the Global CAF comparison later.
    #
    # predict_single()'s access pattern — bundle['models'][col][winner] — is
    # UNCHANGED and works identically against either bundle, since `winner`
    # is always a valid key in models[col] in both cases.
    production_models = {
        col: {best_overall_model: models[col][best_overall_model]}
        for col in OUTPUT_TARGETS
        if best_overall_model in models[col]
    }

    bundle_common = {
        'pipeline_version'     : Config.PIPELINE_VERSION,
        'shared_pre'           : shared_pre,
        'smote_applied'        : SMOTE_AVAILABLE,
        'best_overall_model'   : best_overall_model,     # v17: single global winner, not per-output
        'tie_break_decision'   : tie_break_decision,      # Task 2: WHY this algorithm won
        'algorithm_comparison' : algorithm_results,       # aggregated metrics only — no model objects
        'le_output'            : le_output,
        'input_features'       : INPUT_FEATURES,
        'output_targets'       : OUTPUT_TARGETS,
        'categorical_cols'     : CATEGORICAL_COLS,
        'numeric_cols'         : NUMERIC_COLS,
        'lifestyle_engine'     : LIFESTYLE_ACTIONS,
        'yoga_engine'          : YOGA_MODULES,
        'training_dataset'     : filepath,
        'train_rows'           : len(X_train),
        'test_rows'            : len(X_test),
        'mean_test_accuracy'   : float(np.mean(all_te)),
        'mean_macro_f1'        : float(np.mean(all_mf1)),
        'mean_weighted_f1'     : float(np.mean(all_wf1)),
        'training_results'     : training_results,
    }

    production_bundle = {'models': production_models, **bundle_common}
    research_bundle   = {'models': models,             **bundle_common}

    _ensure_output_dirs()
    _t = time.time()
    log_stage(f"Saving PRODUCTION bundle ({len(OUTPUT_TARGETS)} classifiers, "
              f"algorithm='{best_overall_model}') → {Config.PRODUCTION_BUNDLE_PATH}")
    try:
        joblib.dump(production_bundle, Config.PRODUCTION_BUNDLE_PATH)
        print(f"[INFO] Production bundle saved successfully.")
    except Exception as e:
        print(f"[ERROR] Production bundle saving failed: {e}")
        traceback.print_exc()
        raise   # re-raise so caller knows the bundle was not saved

    research_candidate_count = sum(len(v) for v in models.values())
    log_stage(f"Saving RESEARCH bundle ({research_candidate_count} candidate classifiers) "
              f"→ {Config.RESEARCH_BUNDLE_PATH}")
    try:
        joblib.dump(research_bundle, Config.RESEARCH_BUNDLE_PATH)
        print(f"[INFO] Research bundle saved successfully.")
    except Exception as e:
        print(f"[WARN] Research bundle saving failed (production bundle is unaffected): {e}")
    runtime_profile['bundle_saving'] += time.time() - _t

    output_path = Config.PRODUCTION_BUNDLE_PATH   # kept for the summary print below

    total_candidates = len(OUTPUT_TARGETS) * len(ALL_ALGOS)
    print(f"\n{'='*60}")
    print("BUNDLE SUMMARY")
    print("─"*60)
    print(f"  Production bundle file   : {Config.PRODUCTION_BUNDLE_PATH}")
    print(f"  Research bundle file     : {Config.RESEARCH_BUNDLE_PATH}")
    print(f"  Algos evaluated          : {ALL_ALGOS}")
    print(f"  Fitted classifiers (research): {research_candidate_count} (up to {len(OUTPUT_TARGETS)} outputs × {len(ALL_ALGOS)} algos)")
    print(f"  Fitted classifiers (production): {len(production_models)} (1 per output — '{best_overall_model}' only)")
    print(f"  Selected unified algo    : {best_overall_model}  (used for all {len(OUTPUT_TARGETS)} outputs)")
    print(f"  Tie-break decision       : {tie_break_decision}")
    print(f"  LabelEncoders            : {len(le_output)} (one per output column)")
    print(f"  Input features           : {len(INPUT_FEATURES)}")
    print(f"  Mean Test Acc            : {np.mean(all_te):.1f}%")
    print(f"  Mean Macro F1            : {np.mean(all_mf1):.1f}%")
    print(f"  Mean Train/Test Gap      : {np.mean(all_tr)-np.mean(all_te):.1f}%")
    print(f"  Training time            : {elapsed}s")
    print(f"{'='*60}")

    # ── [Task 6] Experiment tracking: metadata.json ───────────────────────────
    training_runtime_seconds = round(time.time() - t0, 2)

    # [Task 3] Runtime profile — every phase timed via brackets placed around
    # the EXISTING code earlier in this function; values are rounded here
    # only for readability, never altering the underlying measurement.
    runtime_profile_rounded = {phase: round(seconds, 3)
                                for phase, seconds in runtime_profile.items()}
    runtime_profile_rounded['total_measured'] = round(sum(runtime_profile.values()), 3)
    runtime_profile_rounded['total_wall_clock'] = training_runtime_seconds

    metadata_payload = {
        'pipeline_version'      : Config.PIPELINE_VERSION,
        'dataset'                : filepath,
        'training_timestamp'    : datetime.now(timezone.utc).isoformat(timespec='seconds') + 'Z',
        'selected_algorithm'    : best_overall_model,
        'global_caf_score'      : round(global_hybrid_scores[best_overall_model], 4),
        'global_caf_scores_all' : {a: round(s, 4) for a, s in global_hybrid_scores.items()},
        'tie_break_decision'    : tie_break_decision,
        'tie_break_threshold'   : Config.TIE_BREAK_SCORE_THRESHOLD,
        'training_runtime_seconds': training_runtime_seconds,
        'runtime_profile_seconds' : runtime_profile_rounded,
        'random_seed'            : Config.RANDOM_SEED,
        'environment'             : {
            # Hardware-independent only — no CPU model, no host identifiers.
            'python_version'   : platform.python_version(),
            'sklearn_version'  : sklearn.__version__,
            'xgboost_available': XGB_AVAILABLE,
            'catboost_available': CAT_AVAILABLE,
            'smote_available'  : SMOTE_AVAILABLE,
            'shap_available'   : SHAP_AVAILABLE,
            'os_family'        : platform.system(),   # e.g. 'Linux' — not host-specific
        },
    }
    try:
        with open(Config.METADATA_PATH, 'w', encoding='utf-8') as mf:
            json.dump(metadata_payload, mf, indent=2, ensure_ascii=False)
        print(f"  Metadata saved: {Config.METADATA_PATH}")
    except Exception as e:
        print(f"  [WARN] Could not save metadata.json: {e}")

    # ── [Task 5] Research documentation: architecture_summary.md ──────────────
    try:
        summary_md = generate_architecture_summary(
            best_overall_model, tie_break_decision, global_hybrid_scores, algorithm_results
        )
        with open(Config.RESEARCH_SUMMARY_PATH, 'w', encoding='utf-8') as sf:
            sf.write(summary_md)
        print(f"  Architecture summary saved: {Config.RESEARCH_SUMMARY_PATH}")
    except Exception as e:
        print(f"  [WARN] Could not save architecture_summary.md: {e}")

    return production_bundle


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 8 — FLASK INFERENCE HELPER  (v17)
# Returns a structured JSON response with:
#   • ML classification label per output
#   • Enriched Lifestyle actions from LIFESTYLE_ACTIONS engine
#   • Enriched Yoga module details from YOGA_MODULES engine
#   • Follow-up recommendation as a plain string
#   • AI-generated dynamic clinical reasoning per output (Section 8b engine)
#   • Placeholder slot for Doctor Prescription (HITL — filled in Flask UI)
#
# v17 CHANGE: uses bundle['best_overall_model'] — ONE algorithm family for
# ALL FOUR outputs — instead of the removed per-output best_model_per_output.
# Each output still has its own single-output classifier instance; this is
# still 4 separate .predict() calls, not one multi-output model.
# ─────────────────────────────────────────────────────────────────────────────

def predict_single(bundle: dict, input_data: dict) -> dict:
    """
    Runs inference for a single patient and returns a structured prediction.

    Parameters
    ----------
    bundle     : loaded joblib bundle from ayursage_model.pkl
    input_data : dict with 12 input feature keys

    Returns
    -------
    dict with keys:
        'Herbal Therapy Strategy'       : dict  (ML label + AI reasoning)
        'Lifestyle Recommendations'     : dict  (category + actions + AI reasoning)
        'Therapeutic Yoga Module'       : dict  (category + poses + AI reasoning)
        'Follow-up Recommendation'      : dict  (ML label + AI reasoning)
        'Doctor Prescription & Care Notes' : str  (HITL placeholder — NOT ML)

    Flask app.py receives this dict and renders each section in the UI.
    The doctor then fills in 'Doctor Prescription & Care Notes' manually.
    """
    # ── Step 1: Build input DataFrame ────────────────────────────────────────
    row   = {f: input_data.get(f, 'Unknown') for f in bundle['input_features']}
    X_new = pd.DataFrame([row])

    for c in bundle['numeric_cols']:
        X_new[c] = pd.to_numeric(X_new[c], errors='coerce').fillna(0.0)

    # ── Step 2: Preprocess ───────────────────────────────────────────────────
    X_pre = bundle['shared_pre'].transform(X_new)

    # ── Step 3: ML prediction for each of the 4 outputs ─────────────────────
    # v17: winner is the single global best_overall_model, identical for
    # every output — the mixed per-output ensemble is removed. Each output
    # still uses its OWN single-output classifier instance of that algorithm.
    #
    # [Production Readiness — Task 1] Confidence scores are read from
    # predict_proba() SEPARATELY from the prediction itself. The predicted
    # label always comes from .predict() below — predict_proba() is never
    # used to derive or override the label, so predictions are byte-for-byte
    # identical to pre-Task-1 behaviour whether or not confidence is
    # available for a given algorithm.
    winner = bundle['best_overall_model']
    raw_labels = {}
    confidence_info = {}
    for i, col in enumerate(bundle['output_targets']):
        clf = bundle['models'][col][winner]
        pred_int = int(np.asarray(clf.predict(X_pre)).reshape(-1)[0])
        raw_labels[col] = bundle['le_output'][col].inverse_transform([pred_int])[0]

        # Confidence / class probabilities — additive only, skipped
        # gracefully (never crashes) if the selected algorithm doesn't
        # expose predict_proba().
        if hasattr(clf, 'predict_proba'):
            try:
                proba_row = np.asarray(clf.predict_proba(X_pre)).reshape(-1)
                class_names = bundle['le_output'][col].classes_
                confidence_info[col] = {
                    'confidence_score'   : round(float(proba_row[pred_int]), 4),
                    'class_probabilities': {
                        str(class_names[j]): round(float(proba_row[j]), 4)
                        for j in range(len(class_names))
                    },
                }
            except Exception:
                confidence_info[col] = None   # skip gracefully, never crash inference
        else:
            confidence_info[col] = None

    # ── Step 4: Enrich predictions with rule-based engines ───────────────────
    lifestyle_cat  = raw_labels.get('Lifestyle Recommendations', 'Preventive Wellness Lifestyle')
    yoga_cat       = raw_labels.get('Therapeutic Yoga Module',   'Stress Reduction Yoga')
    herbal_cat     = raw_labels.get('Herbal Therapy Strategy',   'Metabolic Balance Support')
    followup_cat   = raw_labels.get('Follow-up Recommendation',  'Regular Wellness Follow-up')

    lifestyle_detail = bundle.get('lifestyle_engine', LIFESTYLE_ACTIONS).get(
        lifestyle_cat,
        {'category': lifestyle_cat, 'note': 'Details not available — consult doctor'}
    )
    yoga_detail = bundle.get('yoga_engine', YOGA_MODULES).get(
        yoga_cat,
        {'category': yoga_cat, 'note': 'Details not available — consult doctor'}
    )

    # ── Step 5: Generate dynamic AI clinical reasoning ────────────────────────
    # The reasoning engine (Section 8b) reads patient features and the predicted
    # class and composes a natural-language explanation. No ML is involved —
    # this is a deterministic linguistic generation layer. Predictions are
    # identical whether or not reasoning is generated.
    reasoning = generate_clinical_reasoning(input_data, raw_labels)

    # ── Step 6: Build structured response ────────────────────────────────────
    result = {
        'Herbal Therapy Strategy': {
            'category'  : herbal_cat,
            'reasoning' : reasoning['herbal'],
            'confidence': confidence_info.get('Herbal Therapy Strategy'),
        },

        'Lifestyle Recommendations': {
            'category'       : lifestyle_cat,
            'focus'          : lifestyle_detail.get('focus', ''),
            'actions'        : lifestyle_detail.get('daily_habits', []),
            'dietary_changes': lifestyle_detail.get('dietary_changes', []),
            'wellness_tips'  : lifestyle_detail.get('wellness_tips', []),
            'avoid'          : lifestyle_detail.get('avoid', []),
            'reasoning'      : reasoning['lifestyle'],
            'confidence'     : confidence_info.get('Lifestyle Recommendations'),
        },

        'Therapeutic Yoga Module': {
            'category'   : yoga_cat,
            'focus'      : yoga_detail.get('focus', ''),
            'duration'   : yoga_detail.get('duration', ''),
            'poses'      : yoga_detail.get('poses', []),
            'pranayama'  : yoga_detail.get('pranayama', []),
            'meditation' : yoga_detail.get('meditation', ''),
            'benefits'   : yoga_detail.get('benefits', []),
            'precautions': yoga_detail.get('precautions', []),
            'reasoning'  : reasoning['yoga'],
            'confidence' : confidence_info.get('Therapeutic Yoga Module'),
        },

        'Follow-up Recommendation': {
            'category' : followup_cat,
            'reasoning': reasoning['followup'],
            'confidence': confidence_info.get('Follow-up Recommendation'),
        },

        # HITL slot — never ML-generated; filled by licensed doctor in Flask UI
        'Doctor Prescription & Care Notes': 'PENDING_DOCTOR_REVIEW',
    }

    return result


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 8b — DYNAMIC CLINICAL REASONING ENGINE  (v16 logic, unchanged in v17)
#
# PURPOSE:
#   Generates human-like, AI-style natural language explanations for each
#   predicted output class. These are post-prediction linguistic annotations —
#   they do NOT affect ML predictions, accuracy, Macro F1, or any metric.
#
# DESIGN PHILOSOPHY:
#   Three-part sentence structure: INTRO → FACTORS → CONCLUSION
#   • INTRO    : varied clinical framing phrases (patient/assessment focused)
#   • FACTORS  : dynamically extracted from actual patient input values
#   • CONCLUSION: class-specific closing statement with varied phrasing
#
#   Factor extraction reads the raw input_data dict directly — the same 12
#   features the ML model uses. This ensures the reasoning is grounded in
#   real patient data, not generic templates.
#
# VARIATION MECHANISM:
#   • Each phrase pool (intros, connectors, factor phrases) contains 4–7 options.
#   • A deterministic per-patient seed is computed from the patient's feature
#     values, ensuring the same patient always gets the same explanation (stable
#     for doctor review) while different patients see different phrasing.
#   • random.choice() selects from the pools using this seed — no randomness
#     is exposed to the user; outputs feel naturally varied, not random.
#
# OFFLINE + LIGHTWEIGHT:
#   Pure Python string operations. No external libraries, no internet calls,
#   no transformers. Adds < 2ms to inference time.
# ─────────────────────────────────────────────────────────────────────────────

def _patient_seed(input_data: dict) -> int:
    """
    Derive a stable per-patient integer seed for controlled language variation.
    Same patient inputs → same seed → same explanation phrasing (reproducible).
    Different patients → different seeds → naturally varied explanations.
    Uses djb2 hash on concatenated feature string (process-stable, no PYTHONHASHSEED).
    """
    seed_str = ''.join([
        str(input_data.get('Disease',                  '')),
        str(input_data.get('Stress Levels',            '')),
        str(input_data.get('Sleep Patterns',           '')),
        str(input_data.get('Constitution/Prakriti',    '')),
        str(input_data.get('Nadi Reading',             '')),
        str(input_data.get('BP Systolic',              '')),
        str(input_data.get('Weight (kg)',              '')),
        str(input_data.get('Physical Activity Levels', '')),
    ])
    h = 5381
    for c in seed_str:
        h = ((h << 5) + h) + ord(c)
    return h & 0x7FFFFFFF


def _extract_wellness_factors(input_data: dict) -> dict:
    """
    Extract human-readable contributing wellness factors from patient features.

    Returns a dict of factor lists keyed by clinical domain:
      'metabolic'      — BP, weight, diabetes, activity
      'stress_sleep'   — stress levels, sleep patterns
      'constitution'   — Prakriti and Nadi reading
      'severity'       — symptom severity
      'joint'          — joint/inflammatory indicators from disease name
      'immune'         — fatigue/immunity indicators
      'digestive'      — gut/digestive indicators
      'respiratory'    — respiratory indicators

    Each list contains natural-language phrases ready for sentence insertion.
    These are dynamically composed from actual input values — not pre-written
    for specific patients.
    """
    d = input_data
    disease  = str(d.get('Disease',                  '')).lower()
    stress   = str(d.get('Stress Levels',            '')).lower()
    sleep_p  = str(d.get('Sleep Patterns',           '')).lower()
    activity = str(d.get('Physical Activity Levels', '')).lower()
    prakriti = str(d.get('Constitution/Prakriti',    '')).lower()
    nadi     = str(d.get('Nadi Reading',             '')).lower()
    severity = str(d.get('Symptom Severity',         '')).lower()
    age      = str(d.get('Age Group',                '')).lower()

    try: bp_s = float(d.get('BP Systolic',  120))
    except: bp_s = 120.0
    try: bp_d = float(d.get('BP Diastolic',  80))
    except: bp_d = 80.0
    try: wt   = float(d.get('Weight (kg)',   70))
    except: wt = 70.0
    try: pr   = float(d.get('Pulse Rate',    75))
    except: pr = 75.0

    factors = {
        'metabolic': [], 'stress_sleep': [], 'constitution': [],
        'severity': [], 'joint': [], 'immune': [],
        'digestive': [], 'respiratory': [],
    }

    # ── Metabolic / cardiovascular factors ───────────────────────────────────
    if bp_s >= 160 or bp_d >= 100:
        factors['metabolic'].append('critically elevated blood pressure')
    elif bp_s >= 140 or bp_d >= 90:
        factors['metabolic'].append('elevated blood pressure (Stage 1 hypertension)')
    elif bp_s >= 130 or bp_d >= 85:
        factors['metabolic'].append('mildly elevated blood pressure')

    if wt >= 95:
        factors['metabolic'].append('significant weight excess (obesity range)')
    elif wt >= 80:
        factors['metabolic'].append('above-optimal body weight')

    if 'low' in activity:
        factors['metabolic'].append('a sedentary physical activity pattern')
    elif 'moderate' in activity:
        factors['metabolic'].append('a moderately active lifestyle')

    if pr >= 100:
        factors['metabolic'].append('elevated resting pulse rate')

    # Add disease-specific metabolic phrases
    for kw, phrase in [
        ('diabetes', 'insulin regulation concerns'),
        ('obesity',  'weight management challenges'),
        ('hypothyroid', 'thyroid function imbalance'),
        ('hyperlipid', 'lipid profile irregularities'),
        ('hypertension', 'persistent hypertensive tendency'),
        ('pcod', 'hormonal metabolic imbalance'),
        ('pcos', 'hormonal metabolic imbalance'),
    ]:
        if kw in disease:
            factors['metabolic'].append(phrase)
            break

    # ── Stress / sleep factors ────────────────────────────────────────────────
    if 'high stress' in stress:
        factors['stress_sleep'].append('high psychological stress burden')
    elif 'moderate stress' in stress:
        factors['stress_sleep'].append('moderate stress accumulation')

    if 'poor sleep' in sleep_p:
        factors['stress_sleep'].append('persistently poor sleep quality')
    elif 'irregular sleep' in sleep_p:
        factors['stress_sleep'].append('irregular and disrupted sleep patterns')

    for kw, phrase in [
        ('anxiety',    'anxiety-related nervous system activation'),
        ('depression', 'depressive mood burden'),
        ('insomnia',   'clinical insomnia presentation'),
        ('burnout',    'burnout and exhaustion indicators'),
        ('ptsd',       'trauma-related stress responses'),
    ]:
        if kw in disease:
            factors['stress_sleep'].append(phrase)
            break

    # ── Constitutional / Prakriti factors ────────────────────────────────────
    if 'kapha' in prakriti:
        factors['constitution'].append('Kapha-dominant constitution (tendency toward sluggish metabolism)')
    elif 'vata' in prakriti:
        factors['constitution'].append('Vata-dominant constitution (tendency toward nervous depletion)')
    elif 'pitta' in prakriti:
        factors['constitution'].append('Pitta-dominant constitution (tendency toward inflammatory excess)')

    if 'kapha' in nadi and 'kapha' not in prakriti:
        factors['constitution'].append('Kapha Nadi reading indicating current metabolic sluggishness')
    elif 'vata' in nadi and 'vata' not in prakriti:
        factors['constitution'].append('Vata Nadi reading indicating current nervous instability')
    elif 'pitta' in nadi and 'pitta' not in prakriti:
        factors['constitution'].append('Pitta Nadi reading indicating current inflammatory tendency')

    if age in ('41-60', '61+', '61-80'):
        factors['constitution'].append(f'age-related wellness considerations ({age} age group)')

    # ── Severity ─────────────────────────────────────────────────────────────
    if 'severe' in severity or 'high' in severity:
        factors['severity'].append('severe symptom presentation requiring active management')
    elif 'moderate' in severity:
        factors['severity'].append('moderate symptom burden requiring systematic care')
    elif 'mild' in severity:
        factors['severity'].append('mild symptom profile with preventive potential')

    # ── Joint / inflammatory factors ─────────────────────────────────────────
    for kw, phrase in [
        ('arthritis',    'arthritic inflammation and joint degeneration'),
        ('rheumatoid',   'rheumatoid autoimmune joint involvement'),
        ('osteoarthritis', 'degenerative joint wear patterns'),
        ('gout',         'uric acid crystal deposition in joints'),
        ('spondylitis',  'spinal inflammatory changes'),
        ('back pain',    'chronic back pain and postural strain'),
        ('fibromyalgia', 'widespread musculoskeletal pain sensitization'),
        ('joint pain',   'persistent joint pain and reduced mobility'),
        ('sciatica',     'sciatic nerve compression and radiating pain'),
    ]:
        if kw in disease:
            factors['joint'].append(phrase)
            break

    # ── Immune / fatigue factors ──────────────────────────────────────────────
    for kw, phrase in [
        ('chronic fatigue', 'chronic fatigue syndrome indicators'),
        ('anaemi',    'haematological deficiency (anaemia)'),
        ('anemia',    'haematological deficiency (anaemia)'),
        ('low immunity', 'compromised immune defence capacity'),
        ('recurrent infection', 'recurrent infectious susceptibility'),
        ('weakness',  'generalised weakness and low vitality'),
        ('autoimmune', 'autoimmune dysregulation'),
    ]:
        if kw in disease:
            factors['immune'].append(phrase)
            break

    # ── Digestive factors ─────────────────────────────────────────────────────
    for kw, phrase in [
        ('ibs',           'irritable bowel syndrome disruption'),
        ('gastritis',     'gastric mucosal inflammation'),
        ('gerd',          'gastroesophageal reflux disorder'),
        ('acid reflux',   'chronic acid reflux imbalance'),
        ('constipation',  'bowel motility impairment'),
        ('fatty liver',   'hepatic lipid accumulation'),
        ('indigestion',   'chronic indigestion and digestive weakness'),
        ('colitis',       'colonic inflammatory patterns'),
        ('bloating',      'persistent abdominal bloating and gas accumulation'),
        ('dyspepsia',     'functional dyspepsia and epigastric discomfort'),
    ]:
        if kw in disease:
            factors['digestive'].append(phrase)
            break

    # ── Respiratory factors ───────────────────────────────────────────────────
    for kw, phrase in [
        ('asthma',   'bronchial hypersensitivity (asthma)'),
        ('copd',     'chronic obstructive pulmonary impairment'),
        ('bronchitis', 'bronchial inflammatory changes'),
        ('sinusitis', 'chronic sinus congestion and inflammation'),
        ('pneumonia', 'pulmonary infectious burden'),
        ('sleep apn', 'sleep apnoea-related respiratory interruption'),
    ]:
        if kw in disease:
            factors['respiratory'].append(phrase)
            break

    return factors


# ── Language phrase pools ─────────────────────────────────────────────────────
# Each pool has 5–7 options. Selection is seeded per-patient so the same
# patient always sees the same phrasing, but different patients see variety.

_INTROS = [
    "The patient's wellness profile reflects",
    "Clinical wellness indicators highlight",
    "The assessment of this patient's health profile reveals",
    "Observed wellness patterns in this patient indicate",
    "The patient's holistic health presentation suggests",
    "Integrated clinical indicators point toward",
    "The patient's Ayurvedic wellness assessment identifies",
]

_CONNECTORS = [
    "combined with",
    "alongside",
    "in conjunction with",
    "compounded by",
    "associated with",
    "further supported by",
    "co-occurring with",
]

_STRENGTHENERS = [
    "The recommendation is further strengthened by",
    "Primary contributing wellness indicators include",
    "The assessment is primarily anchored in",
    "Key driving factors for this recommendation include",
    "This clinical direction is reinforced by",
]

_HERBAL_CONCLUSIONS = {
    'Metabolic Balance Support'        : [
        "supporting a metabolism-focused Ayurvedic herbal strategy.",
        "indicating the priority of metabolic regulation through targeted herbal support.",
        "aligning with a Kapha-pacifying, metabolism-balancing herbal protocol.",
        "suggesting a herbal strategy centred on blood sugar, weight, and metabolic stability.",
    ],
    'Stress-Relief Herbal Support'     : [
        "indicating the need for nervine and adaptogenic herbal support.",
        "supporting a stress-relief and nervous system restoration herbal strategy.",
        "suggesting Vata-calming, adaptogenic herbal care as the primary approach.",
        "aligning with a herbal protocol focused on psychological resilience and sleep restoration.",
    ],
    'Digestive Herbal Support'         : [
        "suggesting a digestive wellness-oriented Ayurvedic herbal protocol.",
        "indicating the priority of gut flora restoration and digestive fire (Agni) correction.",
        "supporting herbal care focused on gastric integrity and bowel regularity.",
        "aligning with a Pitta-pacifying, digestive herbal management plan.",
    ],
    'Immunity Enhancement Support'     : [
        "supporting an immunity-enhancement and vitality restoration herbal strategy.",
        "indicating the need for Rasayana (rejuvenating) Ayurvedic herbal intervention.",
        "suggesting immune-modulating and energy-restoring herbal support as the focus.",
        "aligning with an herbal protocol prioritising Ojas (vital essence) replenishment.",
    ],
    'Anti-inflammatory Herbal Support' : [
        "indicating the priority of anti-inflammatory and joint-protective herbal management.",
        "supporting a Vata-Pitta-pacifying, anti-inflammatory herbal strategy.",
        "suggesting targeted herbal support for musculoskeletal inflammation and pain relief.",
        "aligning with an herbal protocol centred on reducing systemic inflammatory burden.",
    ],
}

_LIFESTYLE_CONCLUSIONS = {
    'Stress Reduction Lifestyle'    : [
        "indicating a stress-reduction and nervous system rehabilitation lifestyle approach.",
        "supporting a lifestyle framework centred on psychological restoration and calm.",
        "aligning with a Vata-balancing, stress-reduction daily wellness protocol.",
        "suggesting prioritisation of mental health, sleep hygiene, and nervous system recovery.",
    ],
    'Weight Management Lifestyle'   : [
        "supporting a structured weight and metabolic management lifestyle programme.",
        "indicating the priority of sustainable dietary modification and metabolic rebalancing.",
        "aligning with a Kapha-reducing, weight management-oriented lifestyle protocol.",
        "suggesting an integrated lifestyle approach to metabolic stabilisation and weight care.",
    ],
    'Sleep Improvement Lifestyle'   : [
        "indicating the priority of circadian rhythm restoration and sleep quality improvement.",
        "supporting a lifestyle framework focused on sleep hygiene and nervous system restoration.",
        "suggesting a structured approach to normalising sleep architecture and evening routines.",
        "aligning with a Vata-calming, sleep-restorative daily wellness practice.",
    ],
    'Active Lifestyle Promotion'    : [
        "supporting a gradual, progressive physical activity promotion lifestyle strategy.",
        "indicating the priority of overcoming sedentary patterns through structured movement.",
        "aligning with an active wellness framework to improve metabolic and cardiovascular health.",
        "suggesting a supervised physical rehabilitation and active living lifestyle protocol.",
    ],
    'Preventive Wellness Lifestyle' : [
        "supporting a preventive wellness maintenance lifestyle approach.",
        "indicating a stable health baseline amenable to proactive Ayurvedic wellness care.",
        "aligning with a Dinacharya-based preventive wellness and longevity lifestyle protocol.",
        "suggesting a health optimisation and disease prevention lifestyle strategy.",
    ],
}

_YOGA_CONCLUSIONS = {
    'Stress Reduction Yoga'       : [
        "supporting a calming, Vata-pacifying yoga and meditation therapeutic programme.",
        "indicating the priority of nervous system deactivation through restorative yoga practice.",
        "aligning with a yoga protocol focused on cortisol reduction and parasympathetic activation.",
        "suggesting therapeutic yoga centred on mind-body stress regulation and emotional balance.",
    ],
    'Respiratory Pranayama'       : [
        "supporting a pranayama and respiratory capacity restoration therapeutic protocol.",
        "indicating the priority of airway management and lung function improvement through yoga.",
        "aligning with a Kapha-clearing, respiratory pranayama therapeutic programme.",
        "suggesting structured breathing therapy to restore pulmonary function and oxygen capacity.",
    ],
    'Weight Management Yoga'      : [
        "supporting an active, metabolic-stimulating yoga therapeutic programme.",
        "indicating the priority of Agni (metabolic fire) activation through dynamic yoga practice.",
        "aligning with a Kapha-reducing, calorie-expenditure yoga therapeutic protocol.",
        "suggesting a structured yoga programme to improve insulin sensitivity and body composition.",
    ],
    'Flexibility & Mobility Therapy' : [
        "supporting a joint-specific flexibility and mobility restoration yoga therapy.",
        "indicating the priority of synovial fluid circulation and joint lubrication through yoga.",
        "aligning with a Vata-pacifying, joint-protective therapeutic yoga and mobility protocol.",
        "suggesting targeted yoga therapy for pain reduction, range of motion, and postural correction.",
    ],
    'Relaxation & Sleep Therapy'  : [
        "supporting a Yoga Nidra-based deep relaxation and sleep restoration therapeutic protocol.",
        "indicating the priority of nervous system deceleration through restorative yoga practice.",
        "aligning with a parasympathetic-activation yoga protocol for sleep and recovery.",
        "suggesting a therapeutic yoga programme centred on deep rest, restoration, and sleep quality.",
    ],
}

_FOLLOWUP_CONCLUSIONS = {
    'Immediate Consultation Recommended' : [
        "indicating an urgent need for immediate medical evaluation and clinical intervention.",
        "suggesting that the patient's risk profile requires same-day physician assessment.",
        "supporting escalation to immediate clinical care given the severity of risk indicators.",
        "indicating that the current health parameters necessitate immediate professional review.",
    ],
    'Follow-up after 7 Days'            : [
        "supporting a close 7-day follow-up to monitor treatment response and risk stabilisation.",
        "indicating the need for near-term clinical review within one week.",
        "suggesting active monitoring with a structured 7-day reassessment appointment.",
        "supporting weekly follow-up to track high-risk clinical indicators.",
    ],
    'Follow-up after 15 Days'           : [
        "indicating a 15-day follow-up to assess treatment adherence and clinical progress.",
        "supporting a fortnightly review to monitor moderate-risk health indicators.",
        "suggesting biweekly reassessment to evaluate therapeutic response.",
        "aligning with a 15-day clinical monitoring plan for moderate health risk management.",
    ],
    'Follow-up after 1 Month'           : [
        "supporting a 1-month routine follow-up to evaluate wellness progress.",
        "indicating a monthly review for stable moderate-risk clinical monitoring.",
        "suggesting a 30-day reassessment for mild-to-moderate health management.",
        "aligning with a monthly wellness review plan for ongoing care optimisation.",
    ],
    'Regular Wellness Follow-up'        : [
        "supporting a standard preventive wellness check-up schedule.",
        "indicating a stable health profile appropriate for routine periodic review.",
        "aligning with a preventive health monitoring protocol for low-risk wellness management.",
        "suggesting standard annual or biannual wellness assessments for health optimisation.",
    ],
}


def generate_clinical_reasoning(input_data: dict, raw_labels: dict) -> dict:
    """
    Generate dynamic AI-style clinical reasoning for all 4 predicted outputs.

    Parameters
    ----------
    input_data  : dict of 12 patient input features (same keys as ML model)
    raw_labels  : dict of {output_column: predicted_class_string}

    Returns
    -------
    dict with keys: 'herbal', 'lifestyle', 'yoga', 'followup'
    Each value is a multi-sentence natural language reasoning string.

    HOW VARIATION IS ACHIEVED:
    1. Factor extraction: reads actual patient values to build a list of
       specific clinical findings (e.g. "elevated BP 135/88 mmHg", "Kapha
       dominance"). Different patients have different factors.
    2. Phrase selection: intro, connector, and conclusion are drawn from
       pools of 5–7 options using a per-patient deterministic seed. Same
       patient → same phrasing. Different patients → naturally varied output.
    3. Sentence construction: factors are joined with varied connectors,
       producing sentences that read as clinically reasoned narratives.

    NO ML IS INVOLVED. Predictions are unaffected by this function.
    Calling or not calling this function does not change any metric.
    """
    seed = _patient_seed(input_data)
    random.seed(seed)

    factors = _extract_wellness_factors(input_data)
    herbal_class   = raw_labels.get('Herbal Therapy Strategy',   'Metabolic Balance Support')
    lifestyle_class= raw_labels.get('Lifestyle Recommendations', 'Preventive Wellness Lifestyle')
    yoga_class     = raw_labels.get('Therapeutic Yoga Module',   'Stress Reduction Yoga')
    followup_class = raw_labels.get('Follow-up Recommendation',  'Regular Wellness Follow-up')

    def _join_factors(factor_lists: list, max_factors: int = 3) -> list:
        """
        Pull from multiple factor category lists, deduplicate, and cap at max.
        Returns a flat list of factor phrases in a naturally varied order.
        """
        combined = []
        for lst in factor_lists:
            combined.extend(lst)
        combined = list(dict.fromkeys(combined))   # preserve order, deduplicate
        if len(combined) > max_factors:
            # Deterministically select a varied subset — not always first N
            step = max(1, len(combined) // max_factors)
            combined = [combined[i] for i in range(0, len(combined), step)][:max_factors]
        return combined

    def _build_sentence(intro: str, factor_list: list, conclusion: str,
                         strengthener: str = '', strengthener_factors: list = None) -> str:
        """
        Construct a 1–2 sentence reasoning string.

        Sentence 1: INTRO + up to 3 factors joined by connectors + CONCLUSION
        Sentence 2 (optional): STRENGTHENER + additional context factors

        Example output:
          "The patient's wellness profile reflects Kapha dominance, elevated
          blood pressure, and a sedentary physical activity pattern, supporting
          a metabolism-focused Ayurvedic herbal strategy. The recommendation
          is further strengthened by significant weight excess and moderate
          symptom burden."
        """
        if not factor_list:
            return f"{intro} a complex multi-domain wellness presentation, {conclusion}"

        connector = random.choice(_CONNECTORS)

        if len(factor_list) == 1:
            main = f"{intro} {factor_list[0]}, {conclusion}"
        elif len(factor_list) == 2:
            main = f"{intro} {factor_list[0]} {connector} {factor_list[1]}, {conclusion}"
        else:
            # Oxford-style: factor1, factor2, connector factor3 — avoids repetitive "and"
            main = (f"{intro} {factor_list[0]}, {factor_list[1]}, "
                    f"{connector} {factor_list[2]}, {conclusion}")

        # Optional second sentence for additional context
        if strengthener and strengthener_factors:
            extra = f" {strengthener} {' and '.join(strengthener_factors[:2])}."
            return main + extra

        return main

    # ── HERBAL REASONING ──────────────────────────────────────────────────────
    # Select factors most relevant to the predicted herbal class
    herbal_factor_priority = {
        'Metabolic Balance Support'        : ['metabolic', 'constitution', 'severity'],
        'Stress-Relief Herbal Support'     : ['stress_sleep', 'constitution', 'severity'],
        'Digestive Herbal Support'         : ['digestive', 'constitution', 'severity'],
        'Immunity Enhancement Support'     : ['immune', 'constitution', 'stress_sleep'],
        'Anti-inflammatory Herbal Support' : ['joint', 'severity', 'constitution'],
    }
    h_priority = herbal_factor_priority.get(herbal_class, ['metabolic', 'constitution', 'severity'])
    h_factors  = _join_factors([factors[k] for k in h_priority], max_factors=3)
    h_extra    = _join_factors([factors[k] for k in ['severity', 'stress_sleep']
                                 if k not in h_priority], max_factors=2)
    herbal_reasoning = _build_sentence(
        intro       = random.choice(_INTROS),
        factor_list = h_factors,
        conclusion  = random.choice(_HERBAL_CONCLUSIONS.get(herbal_class, ['requiring targeted herbal care.'])),
        strengthener         = random.choice(_STRENGTHENERS) if h_extra else '',
        strengthener_factors = h_extra,
    )

    # ── LIFESTYLE REASONING ───────────────────────────────────────────────────
    lifestyle_factor_priority = {
        'Stress Reduction Lifestyle'    : ['stress_sleep', 'constitution', 'severity'],
        'Weight Management Lifestyle'   : ['metabolic', 'constitution', 'severity'],
        'Sleep Improvement Lifestyle'   : ['stress_sleep', 'constitution', 'metabolic'],
        'Active Lifestyle Promotion'    : ['metabolic', 'joint', 'constitution'],
        'Preventive Wellness Lifestyle' : ['constitution', 'severity', 'metabolic'],
    }
    l_priority = lifestyle_factor_priority.get(lifestyle_class, ['metabolic', 'constitution', 'severity'])
    l_factors  = _join_factors([factors[k] for k in l_priority], max_factors=3)
    l_extra    = _join_factors([factors['immune'], factors['digestive']], max_factors=1)
    lifestyle_reasoning = _build_sentence(
        intro       = random.choice(_INTROS),
        factor_list = l_factors,
        conclusion  = random.choice(_LIFESTYLE_CONCLUSIONS.get(lifestyle_class, ['requiring lifestyle modification.'])),
        strengthener         = random.choice(_STRENGTHENERS) if l_extra else '',
        strengthener_factors = l_extra,
    )

    # ── YOGA REASONING ────────────────────────────────────────────────────────
    yoga_factor_priority = {
        'Stress Reduction Yoga'          : ['stress_sleep', 'constitution', 'severity'],
        'Respiratory Pranayama'          : ['respiratory', 'constitution', 'metabolic'],
        'Weight Management Yoga'         : ['metabolic', 'constitution', 'severity'],
        'Flexibility & Mobility Therapy' : ['joint', 'severity', 'constitution'],
        'Relaxation & Sleep Therapy'     : ['stress_sleep', 'immune', 'constitution'],
    }
    y_priority = yoga_factor_priority.get(yoga_class, ['metabolic', 'constitution', 'severity'])
    y_factors  = _join_factors([factors[k] for k in y_priority], max_factors=3)
    yoga_reasoning = _build_sentence(
        intro       = random.choice(_INTROS),
        factor_list = y_factors,
        conclusion  = random.choice(_YOGA_CONCLUSIONS.get(yoga_class, ['requiring yoga therapeutic support.'])),
    )

    # ── FOLLOW-UP REASONING ───────────────────────────────────────────────────
    # Follow-up reasoning emphasises the risk-tier signals: BP + severity + disease
    f_factors  = _join_factors([factors['metabolic'], factors['severity'], factors['stress_sleep']], max_factors=3)
    followup_reasoning = _build_sentence(
        intro       = random.choice(_INTROS),
        factor_list = f_factors,
        conclusion  = random.choice(_FOLLOWUP_CONCLUSIONS.get(followup_class, ['requiring clinical follow-up.'])),
    )

    return {
        'herbal'   : herbal_reasoning,
        'lifestyle': lifestyle_reasoning,
        'yoga'     : yoga_reasoning,
        'followup' : followup_reasoning,
    }


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 9 — DEMO / SMOKE TEST  (v17)
# ─────────────────────────────────────────────────────────────────────────────

def run_demo_prediction(bundle: dict) -> dict:
    """
    Runs a smoke-test prediction with a sample Kapha-dominant patient.
    Validates all 4 ML outputs + recommendation engine enrichment + AI reasoning.
    'Doctor Prescription & Care Notes' is correctly shown as HITL placeholder.
    """
    print(f"\n{'='*64}")
    print("DEMO — Sample Nadi Pariksha Patient Prediction (v17)")
    print("─"*64)

    sample = {
        'Disease'                 : 'Diabetes Mellitus Type 2',
        'Symptom Severity'        : 'Moderate',
        'Nadi Reading'            : 'Kapha',
        'Constitution/Prakriti'   : 'Kapha',
        'Stress Levels'           : 'Moderate Stress',
        'Sleep Patterns'          : 'Regular Sleep',
        'Age Group'               : '41-60',
        'Physical Activity Levels': 'Low',
        'BP Systolic'             : 135.0,
        'BP Diastolic'            : 88.0,
        'Pulse Rate'              : 76.0,
        'Weight (kg)'             : 92.0,
    }

    print("Patient inputs (post-nadiMapper):")
    for k, v in sample.items():
        print(f"  {k:<35}: {v}")

    result = predict_single(bundle, sample)

    print(f"\n{'─'*64}")
    print("AI PREDICTION RESULTS (4 ML outputs + dynamic reasoning):")
    print(f"{'─'*64}")

    # ── Output 1: Herbal Therapy Strategy ────────────────────────────────────
    herb = result['Herbal Therapy Strategy']
    print(f"\n  [1] Herbal Therapy Strategy")
    print(f"      → {herb['category']}")
    print(f"\n      AI Clinical Reasoning:")
    # Word-wrap the reasoning at 60 chars for clean console display
    words = herb['reasoning'].split()
    line, lines = [], []
    for w in words:
        if sum(len(x)+1 for x in line) + len(w) > 58:
            lines.append(' '.join(line))
            line = [w]
        else:
            line.append(w)
    if line: lines.append(' '.join(line))
    for l in lines:
        print(f"        {l}")

    # ── Output 2: Lifestyle Recommendations ─────────────────────────────────
    life = result['Lifestyle Recommendations']
    print(f"\n  [2] Lifestyle Recommendations")
    print(f"      → {life['category']}")
    print(f"      Focus    : {life['focus']}")
    print(f"      Top habits:")
    for h in life['actions'][:3]:
        print(f"        • {h}")
    print(f"\n      AI Clinical Reasoning:")
    for l in life['reasoning'].split('. '):
        if l.strip():
            print(f"        {l.strip()}{'.' if not l.strip().endswith('.') else ''}")

    # ── Output 3: Therapeutic Yoga Module ────────────────────────────────────
    yoga = result['Therapeutic Yoga Module']
    print(f"\n  [3] Therapeutic Yoga Module")
    print(f"      → {yoga['category']}")
    print(f"      Duration  : {yoga['duration']}")
    print(f"      Key poses :")
    for p in yoga['poses'][:3]:
        print(f"        • {p}")
    print(f"      Benefits  : {', '.join(yoga['benefits'][:2])}")
    print(f"\n      AI Clinical Reasoning:")
    for l in yoga['reasoning'].split('. '):
        if l.strip():
            print(f"        {l.strip()}{'.' if not l.strip().endswith('.') else ''}")

    # ── Output 4: Follow-up Recommendation ───────────────────────────────────
    followup = result['Follow-up Recommendation']
    print(f"\n  [4] Follow-up Recommendation")
    print(f"      → {followup['category']}")
    print(f"\n      AI Clinical Reasoning:")
    for l in followup['reasoning'].split('. '):
        if l.strip():
            print(f"        {l.strip()}{'.' if not l.strip().endswith('.') else ''}")

    # ── HITL slot ─────────────────────────────────────────────────────────────
    print(f"\n  [HITL] Doctor Prescription & Care Notes")
    print(f"      → {result['Doctor Prescription & Care Notes']}")
    print(f"      ⚠  This field is NOT generated by ML or the reasoning engine.")
    print(f"         A licensed doctor must fill this in the Flask review UI.")

    print(f"\n{'─'*64}")
    print("⚠  HITL NOTE: All ML outputs above are PENDING_DOCTOR_REVIEW.")
    print("   The doctor must verify, edit if needed, fill in the prescription,")
    print("   and approve before any output is shown to the patient.")
    print(f"{'='*64}")

    return result


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    # Accept dataset path as CLI argument; default to 10K synthetic dataset
    dataset = sys.argv[1] if len(sys.argv) > 1 else Config.DEFAULT_DATASET

    if not os.path.exists(dataset):
        fallback = 'AyurSage_Dataset_v3_clean.csv'
        if os.path.exists(fallback):
            print(f"\n⚠  WARNING: {dataset} not found.")
            print(f"   Using fallback: {fallback}")
            print(f"   ACCURACY CEILING on 446 rows is ~65%. Use 10K dataset for 83–90%.")
            dataset = fallback
        else:
            print(f"\nERROR: No dataset found. Place either:")
            print(f"  - AyurSage_10k_Synthetic.csv  (recommended, 10 000 rows)")
            print(f"  - AyurSage_Dataset_v3_clean.csv (446-row original)")
            print(f"in the current directory and re-run.")
            sys.exit(1)

    bundle = train_ayursage(dataset)
    run_demo_prediction(bundle)
