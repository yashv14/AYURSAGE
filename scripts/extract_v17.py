"""Reproduce the inference-only extraction without importing training source."""
import ast
import copy
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_SHA256 = "afc2fb4b771467e3a47045b1c3b76f9dc898716078fc47d8f930bfb5093088d3"
NAMES = {
    "CATEGORICAL_COLS", "NUMERIC_COLS", "INPUT_FEATURES", "OUTPUT_TARGETS",
    "LIFESTYLE_ACTIONS", "YOGA_MODULES", "predict_single", "_patient_seed",
    "_extract_wellness_factors", "generate_clinical_reasoning", "_INTROS",
    "_CONNECTORS", "_STRENGTHENERS", "_HERBAL_CONCLUSIONS",
    "_LIFESTYLE_CONCLUSIONS", "_YOGA_CONCLUSIONS", "_FOLLOWUP_CONCLUSIONS",
}


def selected_tree():
    source = ROOT / "ml/source/AyurSage_Training_v17.py"
    data = source.read_bytes()
    if hashlib.sha256(data).hexdigest() != SOURCE_SHA256:
        raise ValueError("Reference source checksum mismatch")
    selected, found = [], set()
    for node in ast.parse(data).body:
        if isinstance(node, ast.FunctionDef):
            name = node.name
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
        else:
            continue
        if name in NAMES:
            selected.append(node)
            found.add(name)
    if found != NAMES:
        raise ValueError("Incomplete inference source")
    return ast.Module(body=selected, type_ignores=[])


def adapter_text():
    tree = copy.deepcopy(selected_tree())
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "generate_clinical_reasoning":
            for index, statement in enumerate(node.body):
                if ast.unparse(statement) == "random.seed(seed)":
                    # Same seed and same CPython Random algorithm; invocation-local state.
                    node.body[index] = ast.parse("random = Random(seed)").body[0]
                    break
            else:
                raise ValueError("Expected original seed operation absent")
    ast.fix_missing_locations(tree)
    return ('"""Generated frozen inference extraction. See scripts/extract_v17.py.\n'
            'Original source SHA-256: ' + SOURCE_SHA256 + '\n"""\n'
            'from random import Random\nimport pandas as pd\nimport numpy as np\n\n'
            + ast.unparse(tree) + '\n')


def verify_adapter():
    """Compare syntax exactly, independent of patch-version quote formatting."""
    actual = (ROOT / "backend/app/v17_callable.py").read_text(encoding="utf-8")
    return ast.dump(ast.parse(actual), include_attributes=False) == ast.dump(
        ast.parse(adapter_text()), include_attributes=False)


if __name__ == "__main__":
    (ROOT / "backend/app/v17_callable.py").write_text(adapter_text(), encoding="utf-8")
