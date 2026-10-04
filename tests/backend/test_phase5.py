"""Synthetic mocked workflow tests; these do not prove real-model parity."""
import pytest
from sqlalchemy import event, select

from backend.app.database import db
from backend.app.inference import (artifact_bytes, DisabledInference, InferenceUnavailable,
    INPUTS, TARGETS, MODEL_SHA256, PIPELINE_VERSION, SOURCE_SHA256, ADAPTER_VERSION, validate_input)
from backend.app.models import (ClinicalInput, Consultation, ModelVersion, PredictionRun,
                               PredictionOutput, EnrichmentResult)
from scripts.extract_v17 import adapter_text, verify_adapter
from tests.backend.test_phase4 import schema, register, login, make_user


class SyntheticInference:
    available = True
    calls = 0
    failure = False

    def validate(self, value, schema_version, provenance):
        if schema_version != "synthetic-v1" or value != {"synthetic": True}:
            raise ValueError("synthetic validation failure")

    def predict(self, value):
        self.calls += 1
        if self.failure:
            raise RuntimeError("private patient payload and filesystem path")
        return {**{target: {"category": "synthetic-category", "reasoning": "synthetic-reasoning",
                    "confidence": None} for target in TARGETS},
                "Doctor Prescription & Care Notes": "PENDING_DOCTOR_REVIEW"}


@pytest.fixture
def case(app):
    client = app.test_client()
    register(client, "patient@example.test")
    _, owner = login(client, "patient@example.test")
    created = client.post("/api/v1/consultations", json={}, headers=owner).json["data"]["consultation"]
    url = f"/api/v1/consultations/{created['id']}"
    changed = client.put(url + "/inputs", headers=owner, json={"expectedRowVersion": created["rowVersion"],
        "schemaVersion": "synthetic-v1", "clinicalInput": {"synthetic": True}, "provenance": {"synthetic": True}})
    item = changed.json["data"]["consultation"]
    return client, owner, url, {"expectedRowVersion": item["rowVersion"], "inputRevision": 1}


def enable_synthetic(app):
    service = SyntheticInference()
    app.extensions["inference"] = service
    with app.app_context():
        db.session.add(ModelVersion(version=PIPELINE_VERSION, checksum=MODEL_SHA256, object_key="synthetic-only",
            evidence={"adapterVersion": ADAPTER_VERSION, "sourceChecksum": SOURCE_SHA256}, runtime_reference="synthetic-test", enabled=True))
        db.session.commit()
    return service


def headers(owner, key="synthetic-submit-1"):
    return {**owner, "Idempotency-Key": key}


def test_artifact_hash_precedes_any_deserialization(tmp_path):
    path = tmp_path / "untrusted.pkl"
    path.write_bytes(b"not executable synthetic artifact")
    with pytest.raises(InferenceUnavailable, match="MODEL_CHECKSUM_MISMATCH"):
        artifact_bytes(path)
    assert DisabledInference(path).blockers[0] == "MODEL_CHECKSUM_MISMATCH"
    assert DisabledInference(tmp_path / "missing.pkl").blockers[0] == "MODEL_MISSING"


def test_extraction_is_reproducible_and_training_free():
    assert verify_adapter()
    import ast
    tree = ast.parse(adapter_text())
    functions = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    assert functions == {"predict_single", "_patient_seed", "_extract_wellness_factors", "generate_clinical_reasoning"}


@pytest.mark.parametrize("invalid", [None, {}, {"extra": 1}, True])
def test_invalid_input_structure(invalid):
    with pytest.raises(ValueError):
        validate_input(invalid, {})


@pytest.mark.parametrize("number", [None, "120", True, float("nan"), float("inf"), float("-inf"), 10**1000])
def test_numeric_fallbacks_rejected(number):
    value = {**dict.fromkeys(INPUTS[:8], "synthetic"), **dict.fromkeys(INPUTS[8:], 120.0)}
    value[INPUTS[8]] = number
    with pytest.raises(ValueError):
        validate_input(value, dict.fromkeys(INPUTS[:8], ["synthetic"]))


def test_mechanical_input_validation_never_normalizes():
    value = {**dict.fromkeys(INPUTS[:8], "synthetic"), **dict.fromkeys(INPUTS[8:], 120.0)}
    categories = dict.fromkeys(INPUTS[:8], ["synthetic"])
    assert validate_input(value, categories) == value
    value[INPUTS[0]] = "unsupported"
    with pytest.raises(ValueError):
        validate_input(value, categories)


def test_disabled_submission_leaves_draft_unchanged(app, case):
    client, owner, url, payload = case
    response = client.post(url + "/submit", headers=headers(owner), json=payload)
    assert response.status_code == 503 and response.json["error"]["code"] == "ML_UNAVAILABLE"
    assert "requestId" in response.json
    with app.app_context():
        assert db.session.scalar(select(Consultation)).state == "DRAFT"
        assert db.session.scalar(select(ClinicalInput)).submitted_at is None
        assert db.session.scalar(select(PredictionRun)) is None


def test_mocked_success_is_atomic_and_patient_cannot_read_pending(app, case):
    client, owner, url, payload = case
    service = enable_synthetic(app)
    response = client.post(url + "/submit", headers=headers(owner), json=payload)
    assert response.status_code == 200
    assert response.json["data"]["consultation"]["state"] == "PENDING_DOCTOR_REVIEW"
    assert service.calls == 1
    assert client.get(url + "/predictions", headers=owner).status_code == 403
    duplicate = client.post(url + "/submit", headers=headers(owner), json=payload)
    assert duplicate.status_code == 200 and service.calls == 1
    assert duplicate.json["data"]["processingStatus"]["id"] == response.json["data"]["processingStatus"]["id"]
    assert client.post(url + "/submit", headers=headers(owner), json={**payload, "expectedRowVersion": 999}).status_code == 409
    assert client.post(url + "/submit", headers=headers(owner, "new-key"), json=payload).status_code == 409
    with app.app_context():
        outputs = db.session.scalars(select(PredictionOutput)).all()
        assert {output.target_code for output in outputs} == set(TARGETS)
        assert all(output.raw_result == {"category": "synthetic-category", "confidence": None} for output in outputs)
        assert "reasoning" not in outputs[0].raw_result
        enrichment = db.session.scalar(select(EnrichmentResult))
        assert set(enrichment.result) == set(TARGETS) and enrichment.status == "SUCCEEDED"
        assert db.session.scalar(select(ClinicalInput)).submitted_at is not None


def test_failure_is_explicit_without_partial_outputs_and_duplicate_does_not_retry(app, case):
    client, owner, url, payload = case
    service = enable_synthetic(app); service.failure = True
    response = client.post(url + "/submit", headers=headers(owner), json=payload)
    assert response.status_code == 200 and response.json["data"]["processingStatus"]["status"] == "FAILED"
    assert "private" not in response.text and "path" not in response.text
    assert client.post(url + "/submit", headers=headers(owner), json=payload).status_code == 200
    assert service.calls == 1
    with app.app_context():
        assert db.session.scalar(select(Consultation)).state == "SUBMITTED"
        assert db.session.scalar(select(PredictionOutput)) is None
        assert db.session.scalar(select(EnrichmentResult)) is None


def test_output_persistence_failure_rolls_back_entire_submission(app, case):
    client, owner, url, payload = case
    enable_synthetic(app)
    def fail(mapper, connection, target):
        raise RuntimeError("synthetic storage failure")
    event.listen(PredictionOutput, "before_insert", fail)
    try:
        assert client.post(url + "/submit", headers=headers(owner), json=payload).status_code == 500
    finally:
        event.remove(PredictionOutput, "before_insert", fail)
    with app.app_context():
        assert db.session.scalar(select(PredictionRun)) is None
        assert db.session.scalar(select(PredictionOutput)) is None
        assert db.session.scalar(select(EnrichmentResult)) is None
        assert db.session.scalar(select(ClinicalInput)).submitted_at is None
        assert db.session.scalar(select(Consultation)).state == "DRAFT"


def test_stale_revision_and_cross_patient_are_rejected_before_inference(app, case):
    client, owner, url, payload = case
    service = enable_synthetic(app)
    assert client.post(url + "/submit", headers=headers(owner), json={**payload, "inputRevision": 2}).status_code == 409
    assert client.post(url + "/submit", headers=headers(owner), json={**payload, "expectedRowVersion": 1}).status_code == 409
    register(client, "other@example.test"); _, other = login(client, "other@example.test")
    assert client.post(url + "/submit", headers=headers(other), json=payload).status_code == 404
    assert service.calls == 0


def test_only_assigned_active_doctor_can_read_complete_pending_result(app, case):
    client, owner, url, payload = case
    enable_synthetic(app)
    doctor_id = make_user(app, "doctor@example.test", "DOCTOR", verified=True)
    with app.app_context():
        item = db.session.scalar(select(Consultation)); item.assigned_doctor_id = doctor_id; db.session.commit()
        payload["expectedRowVersion"] = item.row_version
    _, doctor = login(client, "doctor@example.test")
    assert client.post(url + "/submit", headers=headers(doctor), json=payload).status_code == 403
    assert client.post(url + "/submit", headers=headers(owner), json=payload).status_code == 200
    read = client.get(url + "/predictions", headers=doctor)
    assert read.status_code == 200 and set(read.json["data"]["originalOutputs"]) == set(TARGETS)
    assert client.post(url + "/prediction-runs", headers=doctor, json={}).status_code == 503
    make_user(app, "unassigned@example.test", "DOCTOR", verified=True)
    _, unassigned = login(client, "unassigned@example.test")
    assert client.get(url + "/predictions", headers=unassigned).status_code == 404
    assert client.post(url + "/prediction-runs", headers=unassigned, json={}).status_code == 404


def test_incomplete_result_cannot_be_successful(app, case):
    client, owner, url, payload = case
    service = enable_synthetic(app)
    service.predict = lambda value: {TARGETS[0]: {"category": "synthetic"}}
    response = client.post(url + "/submit", headers=headers(owner), json=payload)
    assert response.json["data"]["processingStatus"]["status"] == "FAILED"
    with app.app_context():
        assert db.session.scalar(select(PredictionOutput)) is None


def test_model_provenance_and_enrichment_remain_immutable(app, case):
    client, owner, url, payload = case
    enable_synthetic(app)
    assert client.post(url + "/submit", headers=headers(owner), json=payload).status_code == 200
    with app.app_context():
        model = db.session.scalar(select(ModelVersion)); model.evidence = {"changed": True}
        with pytest.raises(ValueError, match="provenance"):
            db.session.commit()
        db.session.rollback()
        enrichment = db.session.scalar(select(EnrichmentResult)); enrichment.result = {"changed": True}
        with pytest.raises(ValueError, match="enrichment"):
            db.session.commit()
        db.session.rollback()


def test_concurrent_aggregate_change_prevents_inference_and_rolls_back_attempt(app, case):
    from sqlalchemy import update
    from sqlalchemy.orm import Session
    client, owner, url, payload = case
    service = enable_synthetic(app)
    original_validation = service.validate
    def competing_change(value, schema_version, provenance):
        original_validation(value, schema_version, provenance)
        with Session(db.engine) as competing:
            competing.execute(update(Consultation).values(row_version=Consultation.row_version + 1))
            competing.commit()
    service.validate = competing_change
    response = client.post(url + "/submit", headers=headers(owner), json=payload)
    assert response.status_code == 409 and service.calls == 0
    with app.app_context():
        assert db.session.scalar(select(PredictionRun)) is None
        assert db.session.scalar(select(PredictionOutput)) is None
        assert db.session.scalar(select(ClinicalInput)).submitted_at is None
        assert db.session.scalar(select(Consultation)).state == "DRAFT"
