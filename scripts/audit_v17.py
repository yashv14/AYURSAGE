"""Opt-in real-artifact candidate parity audit. Never imports the training module.

No patient data or clinical reports are written. stdout contains only audit evidence.
Run in a dedicated environment with locally supplied, reviewed dependencies.
"""
import ast
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from importlib.metadata import version
import json
import platform
import random
from time import perf_counter

from scripts.extract_v17 import ROOT, selected_tree, adapter_text, SOURCE_SHA256
from backend.app.inference import (load_verified_bundle, validate_bundle, validate_input,
                                  INPUTS, TARGETS, MODEL_SHA256, InferenceUnavailable)


def audit():
    # All original import-time statements, training and demo execution are excluded.
    import numpy as np
    import pandas as pd
    from backend.app.v17_callable import predict_single
    require_text = (ROOT / "backend/app/v17_callable.py").read_text(encoding="utf-8")
    assert require_text == adapter_text()
    namespace = {"pd": pd, "np": np, "random": random}
    exec(compile(selected_tree(), "<isolated-original-inference>", "exec"), namespace)
    source_tree = ast.parse((ROOT / "ml/source/AyurSage_Training_v17.py").read_bytes())
    demo = next(node for node in source_tree.body if isinstance(node, ast.FunctionDef) and node.name == "run_demo_prediction")
    sample = ast.literal_eval(next(node.value for node in demo.body if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "sample"))
    bundle = load_verified_bundle(ROOT / "ml/artifacts/ayursage_model.pkl")
    categories = dict(zip(INPUTS[:8], bundle["shared_pre"].named_transformers_["cat"].categories_))
    # Demo + numeric variants remain unapproved synthetic candidates, not clinical boundaries.
    unsupported_demo = [key for key in INPUTS[:8] if sample[key] not in categories[key]]
    # Record the source demo mismatch explicitly, rather than normalizing API input.
    demo_parity = predict_single(bundle, sample) == namespace["predict_single"](bundle, sample)
    sample = {**sample, "Disease": "Diabetes Mellitus (Type 2)"}
    candidates = [sample, {**sample, "BP Systolic": 120.0, "Weight (kg)": 70.0},
                  {**sample, "BP Systolic": 145.0, "Weight (kg)": 100.0}]
    expected, timings = [], []
    for candidate in candidates:
        validate_input(candidate, categories)
        output = namespace["predict_single"](bundle, candidate)
        started = perf_counter()
        actual = predict_single(bundle, candidate)
        timings.append(perf_counter() - started)
        assert actual == output
        expected.append(output)
    state = random.getstate()
    tasks = [index % len(candidates) for index in range(60)]
    with ThreadPoolExecutor(max_workers=8) as executor:
        actual = list(executor.map(lambda i: predict_single(bundle, candidates[i]), tasks))
    assert random.getstate() == state
    assert actual == [expected[i] for i in tasks]
    # Mutations of metadata and engines must fail validation; never alter fitted objects.
    mutations = {"pipeline_version": "invalid", "input_features": list(reversed(INPUTS)),
                 "output_targets": TARGETS[:3], "best_overall_model": "invalid",
                 "models": {}, "shared_pre": None, "le_output": {}, "lifestyle_engine": {}, "yoga_engine": {}}
    for key, value in mutations.items():
        invalid = dict(bundle, **{key: value})
        try:
            validate_bundle(invalid)
        except InferenceUnavailable:
            pass
        else:
            raise AssertionError("Invalid bundle accepted")
    print(json.dumps({"modelChecksum": MODEL_SHA256, "sourceChecksum": SOURCE_SHA256,
        "pipelineVersion": bundle["pipeline_version"], "algorithm": bundle["best_overall_model"],
        "pythonTested": platform.python_version(), "packagesTested": {name: version(name) for name in
            ["numpy", "pandas", "scipy", "scikit-learn", "joblib", "xgboost"]},
        "trainingEnvironment": "NOT SUPPLIED", "referenceApproval": "UNAPPROVED CANDIDATES",
        "candidateCount": len(candidates), "exactCompleteOutputParity": True,
        "originalDemoParity": demo_parity, "originalDemoUnsupportedFields": unsupported_demo,
        "concurrentCalls": len(tasks), "concurrentWorkers": 8, "globalRandomUnchanged": True,
        "negativeBundleCases": len(mutations), "sequentialSeconds": timings}, indent=2))


if __name__ == "__main__":
    audit()
