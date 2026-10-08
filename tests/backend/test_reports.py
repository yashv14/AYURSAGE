"""Synthetic approved projections, private local storage, no inference/clinical bypass."""
from copy import deepcopy
from datetime import timedelta
from io import BytesIO

import pytest
from pypdf import PdfReader
from sqlalchemy import event, select, update
from sqlalchemy.exc import OperationalError

from backend.app.database import db, utcnow
from backend.app.models import Approval, Report, FileMetadata, AuditLog, User, DoctorProfile, Prescription, PredictionOutput
from backend.app.inference import TARGETS
from backend.app.report_pdf import render_pdf, RenderError
from backend.app.storage import LocalReportStorage, StorageError
from tests.report_support import approved_case, generate
from tests.review_support import seed_case, save, approval_payload, approve


@pytest.fixture(autouse=True)
def schema(app, tmp_path):
    app.extensions["report_storage"] = LocalReportStorage(tmp_path / "private")
    with app.app_context():
        db.create_all()
    yield
    with app.app_context():
        db.session.remove()
        with db.engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        db.drop_all()


@pytest.fixture
def case(app, monkeypatch):
    return approved_case(app, monkeypatch,
        careNotes="Synthetic notes <script>alert('test')</script> & café — Ελληνικά — Кириллица.",
        prescription="Synthetic prescription text; no medication or clinical claim.")


def pdf_text(data):
    return "\n".join(page.extract_text() for page in PdfReader(BytesIO(data)).pages)


def test_exact_approved_projection_and_private_download(case):
    response = generate(case)
    assert response.status_code == 201
    report = response.json["data"]["report"]
    assert report["status"] == "READY" and report["fileChecksum"]
    assert "objectKey" not in report and "url" not in report
    path = f'/api/v1/reports/{report["id"]}'
    download = case["client"].get(path + "/download", headers=case["headers"]["patient"])
    assert download.status_code == 200
    assert download.headers["Content-Type"] == "application/pdf"
    assert download.headers["Cache-Control"] == "no-store"
    assert download.headers["X-Content-Type-Options"] == "nosniff"
    assert "attachment;" in download.headers["Content-Disposition"]
    text = pdf_text(download.data)
    assert case["approval"]["approvedContent"]["careNotes"] in text
    assert case["approval"]["approvedContent"]["prescription"] in text
    assert "SYNTHETIC TEST DATA" in text
    assert case["approval"]["id"] in text and report["id"] in text
    for value in case["approval"]["approvedContent"]["recommendations"].values():
        for field in ("category", "reasoning", "focus", "duration", "meditation"):
            if field in value:
                assert value[field] in text
    assert "confidence" not in text and "sourceChecksum" not in text and "synthetic original input" not in text
    assert case["client"].get(path, headers=case["headers"]["doctor"]).status_code == 200
    with case["app"].app_context():
        events = db.session.scalars(select(AuditLog).where(AuditLog.resource_id == report["id"])).all()
        assert {row.event for row in events} >= {"REPORT_GENERATING", "REPORT_READY", "REPORT_DOWNLOADED"}
        assert all("careNotes" not in row.safe_metadata for row in events)
        assert not case["app"].extensions["inference"].available


def test_duplicate_identity_and_immutable_metadata(case):
    first, second = generate(case), generate(case, "doctor")
    assert (first.status_code, second.status_code) == (201, 200)
    assert first.json["data"] == second.json["data"]
    with case["app"].app_context():
        assert len(db.session.scalars(select(Report)).all()) == 1
        assert len(db.session.scalars(select(FileMetadata)).all()) == 1
        report = db.session.scalar(select(Report))
        report.status = "FAILED"
        with pytest.raises(ValueError, match="immutable"):
            db.session.commit()
        db.session.rollback()
        report = db.session.scalar(select(Report))
        report.file.checksum = "0" * 64
        with pytest.raises(ValueError, match="metadata"):
            db.session.commit()
        db.session.rollback()


def test_report_never_reads_changed_draft_or_raw_records(case, app):
    with app.app_context():
        # Simulate restricted out-of-band corruption, never a supported mutation.
        approval = db.session.get(Approval, case["approval"]["id"])
        db.session.execute(update(Prescription).where(Prescription.doctor_review_id == approval.doctor_review_id)
                           .values(care_notes="RESTRICTED MUTABLE DRAFT CONTENT"))
        db.session.execute(update(PredictionOutput).where(PredictionOutput.prediction_run_id == case["run_id"])
                           .values(raw_result={"category": "RESTRICTED RAW CONTENT", "confidence": 0.999}))
        db.session.commit()
    report = generate(case).json["data"]["report"]
    response = case["client"].get(f'/api/v1/reports/{report["id"]}/download', headers=case["headers"]["patient"])
    assert response.status_code == 200
    text = pdf_text(response.data)
    assert case["approval"]["approvedContent"]["careNotes"] in text
    assert "RESTRICTED" not in text


@pytest.mark.parametrize("actor,status", [("other_patient", 404), ("other_doctor", 404), ("admin", 403)])
def test_every_report_operation_authorizes(case, actor, status):
    report = generate(case).json["data"]["report"]
    assert generate(case, actor).status_code == status
    for suffix in ("", "/download"):
        response = case["client"].get(f'/api/v1/reports/{report["id"]}' + suffix, headers=case["headers"][actor])
        assert response.status_code == status
        assert response.headers["Cache-Control"] == "no-store"


def test_inactive_unverified_and_unapproved_rejected(case, app):
    report = generate(case).json["data"]["report"]
    with app.app_context():
        doctor = db.session.get(User, case["ids"]["doctor"])
        doctor.active = False
        db.session.commit()
    assert case["client"].get(f'/api/v1/reports/{report["id"]}/download', headers=case["headers"]["doctor"]).status_code == 401
    unapproved = seed_case(app)
    unapproved["report_payload"] = case["report_payload"]
    assert generate(unapproved).status_code == 404
    draft = save(unapproved)
    assert approve(unapproved, approval_payload(draft)).status_code == 503
    assert case["client"].get("/api/v1/reports/missing/download", headers=case["headers"]["patient"]).status_code == 404


def test_doctor_verification_revocation_and_unknown_versions(case, app):
    report = generate(case).json["data"]["report"]
    with app.app_context():
        profile = db.session.scalar(select(DoctorProfile).where(DoctorProfile.user_id == case["ids"]["doctor"]))
        profile.verified_at = profile.verified_by_id = None
        db.session.commit()
    assert generate(case, "doctor").status_code == 403
    for suffix in ("", "/download"):
        assert case["client"].get(f'/api/v1/reports/{report["id"]}' + suffix, headers=case["headers"]["doctor"]).status_code == 403
    response = case["client"].post(case["url"] + "/reports", headers=case["headers"]["patient"],
                                  json={**case["report_payload"], "reportVersion": "unapproved-template"})
    assert response.status_code == 422


def test_tampered_snapshot_rejected_on_all_operations(case, app):
    report = generate(case).json["data"]["report"]
    with app.app_context():
        db.session.execute(update(Approval).where(Approval.id == case["approval"]["id"]).values(snapshot={"tampered": True}))
        db.session.commit()
    assert generate(case).status_code == 503
    for suffix in ("", "/download"):
        assert case["client"].get(f'/api/v1/reports/{report["id"]}' + suffix, headers=case["headers"]["patient"]).status_code == 503


@pytest.mark.parametrize("missing", [False, True])
def test_file_integrity_and_missing_reject_ready(case, app, missing):
    report = generate(case).json["data"]["report"]
    with app.app_context():
        key = db.session.get(Report, report["id"]).object_key
    path = app.extensions["report_storage"].root / key
    if missing:
        path.unlink()
    else:
        path.write_bytes(b"%PDF-tampered")
    for suffix in ("", "/download"):
        assert case["client"].get(f'/api/v1/reports/{report["id"]}' + suffix, headers=case["headers"]["patient"]).status_code == 503
    assert generate(case).status_code == 503  # READY identity never overwritten.


def test_storage_failure_and_authorized_retry(case, app, monkeypatch):
    storage = app.extensions["report_storage"]
    original = storage.put
    def unavailable(*args):
        raise StorageError("secret/path must not be exposed")
    monkeypatch.setattr(storage, "put", unavailable)
    response = generate(case)
    assert response.status_code == 503 and "secret/path" not in response.get_data(as_text=True)
    with app.app_context():
        report = db.session.scalar(select(Report))
        report_id = report.id
        assert report.status == "FAILED" and report.file_id is None
    monkeypatch.setattr(storage, "put", original)
    retry = generate(case)
    assert retry.status_code == 200 and retry.json["data"]["report"]["id"] == report_id
    assert retry.json["data"]["report"]["retryCount"] == 1


def test_database_failure_after_upload_reconciles_without_duplicate(case, app):
    with app.app_context():
        engine = db.engine
    def fail_metadata(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO file_metadata"):
            raise OperationalError("synthetic DB failure", {}, Exception("synthetic"))
    event.listen(engine, "before_cursor_execute", fail_metadata)
    try:
        assert generate(case).status_code == 503
    finally:
        event.remove(engine, "before_cursor_execute", fail_metadata)
    with app.app_context():
        report = db.session.scalar(select(Report))
        key, report_id = report.object_key, report.id
        assert report.status == "GENERATING" and report.file_id is None
        assert (app.extensions["report_storage"].root / key).is_file()
        assert not db.session.scalars(select(FileMetadata)).all()
    assert generate(case).status_code == 409
    with app.app_context():
        db.session.execute(update(Report).where(Report.id == report_id).values(lease_expires_at=utcnow() - timedelta(seconds=1)))
        db.session.commit()
    retry = generate(case)
    assert retry.status_code == 200 and retry.json["data"]["report"]["id"] == report_id
    assert len(list((app.extensions["report_storage"].root / "reports").glob("*.pdf"))) == 1


def test_no_public_paths_or_path_selection(case, app, tmp_path):
    report = generate(case).json["data"]["report"]
    with app.app_context():
        key = db.session.get(Report, report["id"]).object_key
    for path in ("/" + key, "/static/" + key, "/api/v1/reports/..%2f..%2f.env/download"):
        assert case["client"].get(path, headers=case["headers"]["patient"]).status_code == 404
    response = case["client"].post(case["url"] + "/reports", headers=case["headers"]["patient"],
                                  json={**case["report_payload"], "path": "../../.env"})
    assert response.status_code == 422
    storage = app.extensions["report_storage"]
    for invalid in ("../.env", "/etc/passwd", "reports/../secret", "reports/patient-name.pdf"):
        with pytest.raises(StorageError):
            storage.read(invalid)
        with pytest.raises(StorageError):
            storage.put(invalid, b"test")
    target = tmp_path / "secret"
    target.write_text("secret")
    linked = storage.root / "reports" / ("a" * 32 + ".pdf")
    linked.symlink_to(target)
    with pytest.raises(StorageError):
        storage.read("reports/" + linked.name)


def test_long_unicode_literal_text_and_exact_projection(case):
    view = deepcopy(case["approval"])
    view["approvedContent"]["recommendations"][TARGETS[0]] = {"text": "Synthetic edited <b>literal</b> & café Ω Ж"}
    view["approvedContent"]["careNotes"] = ("Synthetic line with escaped <tag> & Unicode café Ω Ж.\n" * 140).strip()
    first = render_pdf(view, "00000000-0000-0000-0000-000000000000", synthetic=True)
    second = render_pdf(view, "00000000-0000-0000-0000-000000000000", synthetic=True)
    assert first == second
    reader = PdfReader(BytesIO(first))
    assert len(reader.pages) > 1
    text = pdf_text(first)
    assert "Synthetic edited <b>literal</b> & café Ω Ж" in text
    assert text.count("Synthetic line with escaped <tag> & Unicode café Ω Ж.") == 140
    assert all("SYNTHETIC TEST DATA" in page.extract_text() for page in reader.pages)
    view["approvedContent"]["recommendations"][TARGETS[0]]["reason"] = "RESTRICTED"
    with pytest.raises(RenderError):
        render_pdf(view, "test", synthetic=True)
    view["approvedContent"]["recommendations"][TARGETS[0]] = {"text": "देवनागरी"}
    with pytest.raises(RenderError):
        render_pdf(view, "test", synthetic=True)
