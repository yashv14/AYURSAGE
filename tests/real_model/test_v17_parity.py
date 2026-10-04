"""Opt-in real-model checks, separate from mocked backend workflow evidence."""
import os
import pytest


@pytest.mark.real_model
def test_real_v17_candidate_parity():
    if os.environ.get("RUN_V17_REAL_MODEL_TESTS") != "1":
        pytest.skip("Opt-in trusted local artifact and reviewed audit environment required")
    from scripts.audit_v17 import audit
    audit()
