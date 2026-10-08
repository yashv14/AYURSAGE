"""Disposable MySQL report claims/fencing; synthetic approved data and local IO."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event

import pytest
from sqlalchemy import select, update, event
from sqlalchemy.exc import OperationalError

from backend.app.database import db, utcnow
from backend.app.models import Report, FileMetadata, User
from backend.app.storage import LocalReportStorage
from tests.report_support import approved_case, generate

pytestmark = pytest.mark.mysql


@pytest.fixture
def case(mysql_app, monkeypatch, tmp_path):
    mysql_app.extensions["report_storage"] = LocalReportStorage(tmp_path / "private")
    return approved_case(mysql_app, monkeypatch)


def threaded_generate(case):
    with case["app"].test_client() as client:
        return client.post(case["url"] + "/reports", json=case["report_payload"], headers=case["headers"]["patient"])


def test_mysql_duplicate_generation_claim_and_no_io_transaction(case, monkeypatch):
    entered, release = Event(), Event()
    storage = case["app"].extensions["report_storage"]
    original = storage.put
    def blocked_put(key, data):
        assert not db.session().in_transaction()
        entered.set()
        assert release.wait(15)
        original(key, data)
    monkeypatch.setattr(storage, "put", blocked_put)
    with ThreadPoolExecutor(max_workers=2) as workers:
        first = workers.submit(threaded_generate, case)
        try:
            assert entered.wait(10)
            second = workers.submit(threaded_generate, case).result(timeout=10)
            assert second.status_code == 409
        finally:
            release.set()
        ready = first.result(timeout=15)
    assert ready.status_code == 201
    assert generate(case).json["data"] == ready.json["data"]
    with case["app"].app_context():
        rows = db.session.scalars(select(Report).where(Report.approval_id == case["approval"]["id"])).all()
        assert len(rows) == 1 and rows[0].status == "READY"
        assert db.session.scalar(select(FileMetadata).where(FileMetadata.id == rows[0].file_id)) is not None


def test_mysql_expired_lease_reclaim_fences_old_worker(case, monkeypatch):
    entered, release = Event(), Event()
    storage = case["app"].extensions["report_storage"]
    original = storage.put
    first_call = True
    def blocked_once(key, data):
        nonlocal first_call
        if first_call:
            first_call = False
            entered.set()
            assert release.wait(15)
        original(key, data)
    monkeypatch.setattr(storage, "put", blocked_once)
    with ThreadPoolExecutor(max_workers=2) as workers:
        first = workers.submit(threaded_generate, case)
        try:
            assert entered.wait(10)
            with case["app"].app_context():
                row = db.session.scalar(select(Report).where(Report.approval_id == case["approval"]["id"]))
                row.lease_expires_at = utcnow() - timedelta(seconds=1)
                db.session.commit()
            second = workers.submit(threaded_generate, case).result(timeout=10)
            assert second.status_code == 200 and second.json["data"]["report"]["status"] == "READY"
        finally:
            release.set()
        assert first.result(timeout=15).status_code == 409
    assert len(list((storage.root / "reports").glob("*.pdf"))) == 1


def test_mysql_rechecks_account_after_upload(case, monkeypatch):
    storage = case["app"].extensions["report_storage"]
    original = storage.put
    def revoke_during_upload(key, data):
        assert not db.session().in_transaction()
        with db.engine.begin() as connection:
            connection.execute(update(User).where(User.id == case["ids"]["patient"]).values(active=False))
        original(key, data)
    monkeypatch.setattr(storage, "put", revoke_during_upload)
    assert generate(case).status_code == 401
    with case["app"].app_context():
        row = db.session.scalar(select(Report).where(Report.approval_id == case["approval"]["id"]))
        assert row.status == "GENERATING" and row.file_id is None


def test_mysql_metadata_failure_preserves_private_object_for_recovery(case):
    with case["app"].app_context():
        engine = db.engine
    def fail(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO file_metadata"):
            raise OperationalError("synthetic", {}, Exception("synthetic"))
    event.listen(engine, "before_cursor_execute", fail)
    try:
        assert generate(case).status_code == 503
    finally:
        event.remove(engine, "before_cursor_execute", fail)
    with case["app"].app_context():
        row = db.session.scalar(select(Report).where(Report.approval_id == case["approval"]["id"]))
        assert row.status == "GENERATING" and row.file_id is None
        assert (case["app"].extensions["report_storage"].root / row.object_key).exists()
        row.lease_expires_at = utcnow() - timedelta(seconds=1)
        db.session.commit()
    assert generate(case).status_code == 200
