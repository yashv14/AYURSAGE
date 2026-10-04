"""Frozen artifact boundary. No fitting, dependency installation, or clinical defaults."""
from hashlib import sha256
from io import BytesIO
import math
from pathlib import Path

MODEL_SHA256 = "e0b60420eaf618e165822af5f69f8c437794c06ae0ca885e5d68df8e6a9a7c98"
PIPELINE_VERSION = "AyurSage_v17"
SOURCE_SHA256 = "afc2fb4b771467e3a47045b1c3b76f9dc898716078fc47d8f930bfb5093088d3"
ADAPTER_VERSION = "v17-inference-1"
INPUTS = ["Disease", "Symptom Severity", "Nadi Reading", "Constitution/Prakriti",
          "Stress Levels", "Sleep Patterns", "Age Group", "Physical Activity Levels",
          "BP Systolic", "BP Diastolic", "Pulse Rate", "Weight (kg)"]
TARGETS = ["Herbal Therapy Strategy", "Lifestyle Recommendations",
           "Therapeutic Yoga Module", "Follow-up Recommendation"]
EVIDENCE_BLOCKERS = ("TRAINING_RUNTIME_EVIDENCE_MISSING", "AUTHORIZED_REFERENCES_MISSING",
                     "CLINICAL_INPUT_CONTRACT_UNAPPROVED", "COLLECTION_POLICY_UNAPPROVED",
                     "REQUIRED_ENRICHMENT_POLICY_UNAPPROVED", "RETRY_POLICY_UNAPPROVED")


def require(condition):
    if not condition:
        raise ValueError("Invalid bundle")


class InferenceUnavailable(Exception):
    """Only stable operational codes may cross this boundary."""


def artifact_bytes(path):
    try:
        data = Path(path).read_bytes()
    except OSError:
        raise InferenceUnavailable("MODEL_MISSING") from None
    if sha256(data).hexdigest() != MODEL_SHA256:
        raise InferenceUnavailable("MODEL_CHECKSUM_MISMATCH")
    return data


def validate_bundle(bundle):
    """Check original bundle structure and fitted objects without fitting anything."""
    from sklearn.utils.validation import check_is_fitted
    from sklearn.compose import ColumnTransformer
    from sklearn.preprocessing import LabelEncoder, OneHotEncoder
    from .v17_callable import LIFESTYLE_ACTIONS, YOGA_MODULES
    families = {"RF": ("sklearn.ensemble._forest", "RandomForestClassifier"),
                "ET": ("sklearn.ensemble._forest", "ExtraTreesClassifier"),
                "GB": ("sklearn.ensemble._gb", "GradientBoostingClassifier"),
                "XGB": ("xgboost.sklearn", "XGBClassifier"),
                "CB": ("catboost.core", "CatBoostClassifier")}
    try:
        require(type(bundle) is dict and bundle["pipeline_version"] == PIPELINE_VERSION)
        require(bundle["input_features"] == INPUTS and bundle["output_targets"] == TARGETS)
        require(bundle["categorical_cols"] == INPUTS[:8] and bundle["numeric_cols"] == INPUTS[8:])
        winner = bundle["best_overall_model"]
        require(winner in families and set(bundle["models"]) == set(TARGETS))
        require(set(bundle["le_output"]) == set(TARGETS))
        pre = bundle["shared_pre"]
        require(isinstance(pre, ColumnTransformer))
        check_is_fitted(pre)
        require(list(pre.feature_names_in_) == INPUTS)
        require([name for name, _, _ in pre.transformers_] == ["cat", "num"])
        require(list(pre.transformers_[0][2]) == INPUTS[:8])
        require(list(pre.transformers_[1][2]) == INPUTS[8:])
        require(pre.remainder == "drop")
        cat = pre.named_transformers_["cat"]
        require(isinstance(cat, OneHotEncoder))
        check_is_fitted(cat)
        require(len(cat.categories_) == 8)
        require(cat.handle_unknown == "ignore" and cat.sparse_output is False)
        require(bundle["lifestyle_engine"] == LIFESTYLE_ACTIONS)
        require(bundle["yoga_engine"] == YOGA_MODULES)
        for target in TARGETS:
            require(set(bundle["models"][target]) == {winner})
            clf = bundle["models"][target][winner]
            require((type(clf).__module__, type(clf).__name__) == families[winner])
            check_is_fitted(clf)
            require(clf.n_features_in_ == len(pre.get_feature_names_out()))
            encoder = bundle["le_output"][target]
            require(isinstance(encoder, LabelEncoder))
            check_is_fitted(encoder)
            require(list(clf.classes_) == list(range(len(encoder.classes_))))
        require(set(bundle["le_output"][TARGETS[1]].classes_) <= set(LIFESTYLE_ACTIONS))
        require(set(bundle["le_output"][TARGETS[2]].classes_) <= set(YOGA_MODULES))
    except Exception:
        raise InferenceUnavailable("MODEL_BUNDLE_INVALID") from None
    return bundle


def load_verified_bundle(path):
    data = artifact_bytes(path)  # Verify the same bytes we deserialize; no path reopen race.
    try:
        import joblib
        import warnings
        from sklearn.exceptions import InconsistentVersionWarning
        with warnings.catch_warnings():
            warnings.simplefilter("error", InconsistentVersionWarning)
            bundle = joblib.load(BytesIO(data))
    except Exception:
        raise InferenceUnavailable("MODEL_RUNTIME_INCOMPATIBLE") from None
    return validate_bundle(bundle)


def validate_input(value, categories):
    """Mechanical validation only; vocabularies must come from reviewed evidence.

    Fitted categories can be used for audit candidates, not clinic authorization.
    No numerical range or unit is inferred from the source's reasoning thresholds.
    """
    if type(value) is not dict or set(value) != set(INPUTS):
        raise ValueError("Exact required input fields must be supplied")
    for name in INPUTS[:8]:
        if type(value[name]) is not str or value[name] not in categories[name]:
            raise ValueError("Unsupported input category")
    for name in INPUTS[8:]:
        number = value[name]
        if type(number) not in (int, float):
            raise ValueError("Finite numeric input required")
        try:
            finite = math.isfinite(number)
        except (OverflowError, ValueError):
            finite = False
        if not finite:
            raise ValueError("Finite numeric input required")
    return dict(value)


class DisabledInference:
    """Worker-local readiness evidence; never deserializes while gates are missing."""
    available = False

    def __init__(self, path):
        try:
            artifact_bytes(path)
            self.blockers = list(EVIDENCE_BLOCKERS)
        except InferenceUnavailable as error:
            self.blockers = [str(error), *EVIDENCE_BLOCKERS]

    def predict(self, value):
        raise InferenceUnavailable("ML_EVIDENCE_INCOMPLETE")
