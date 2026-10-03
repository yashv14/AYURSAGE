from datetime import timedelta

import base64
import json
import pytest
from sqlalchemy import select

from backend.app.database import db, utcnow
from backend.app.models import DoctorProfile, RefreshSession, Role, User


@pytest.fixture(autouse=True)
def schema(app):
    with app.app_context():
        db.create_all()
        db.session.add_all([Role(code=code) for code in ("PATIENT", "DOCTOR", "ADMIN")])
        db.session.commit()
    yield
    with app.app_context():
        db.session.remove()
        with db.engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        db.drop_all()


def register(client, email):
    return client.post("/api/v1/auth/register", json={"email": email, "password": "long-synthetic-password", "acceptedTermsVersion": "test-v1"})


def login(client, email, password="long-synthetic-password"):
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    return response, {"Authorization": f"Bearer {response.json['data']['accessToken']}"}


def make_user(app, email, role, password="long-synthetic-password", verified=False):
    from backend.app.auth import hash_password
    with app.app_context():
        role_row = db.session.scalar(select(Role).where(Role.code == role))
        user = User(normalized_email=email, password_hash=hash_password(password), role=role_row)
        db.session.add(user); db.session.flush()
        if verified:
            db.session.add(DoctorProfile(user_id=user.id, verified_at=utcnow(), verified_by_id=user.id,
                                         verification_provenance={"synthetic": True}))
        db.session.commit()
        return user.id


def test_public_registration_is_patient_only_and_password_is_hashed(app):
    client = app.test_client()
    denied = client.post("/api/v1/auth/register", json={"email": "x@example.test", "password": "long-synthetic-password",
                                                        "acceptedTermsVersion": "v1", "role": "ADMIN"})
    assert denied.status_code == 403
    response = register(client, " Patient@Example.Test ")
    assert response.status_code == 201 and response.json["data"]["user"]["role"] == "PATIENT"
    with app.app_context():
        user = db.session.scalar(select(User).where(User.normalized_email == "patient@example.test"))
        assert user.password_hash != "long-synthetic-password"
        assert user.password_hash.startswith("scrypt:")


def test_cross_patient_and_unassigned_doctor_cannot_read_consultation(app):
    client = app.test_client()
    register(client, "one@example.test"); register(client, "two@example.test")
    _, one = login(client, "one@example.test")
    created = client.post("/api/v1/consultations", json={}, headers=one)
    consultation_id = created.json["data"]["consultation"]["id"]
    _, two = login(client, "two@example.test")
    assert client.get(f"/api/v1/consultations/{consultation_id}", headers=two).status_code == 404
    make_user(app, "doctor@example.test", "DOCTOR", verified=True)
    _, doctor = login(client, "doctor@example.test")
    assert client.get(f"/api/v1/consultations/{consultation_id}", headers=doctor).status_code == 404


def test_inputs_are_new_revisions_and_stale_updates_conflict(app):
    client = app.test_client(); register(client, "patient@example.test"); _, headers = login(client, "patient@example.test")
    created = client.post("/api/v1/consultations", json={}, headers=headers).json["data"]["consultation"]
    url = f"/api/v1/consultations/{created['id']}/inputs"
    payload = {"expectedRowVersion": created["rowVersion"], "schemaVersion": "opaque-test-v1",
               "clinicalInput": {"synthetic": "value"}, "provenance": {"source": "synthetic-test"}}
    first = client.put(url, json=payload, headers=headers)
    assert first.status_code == 201 and first.json["data"]["inputRevision"]["revision"] == 1
    assert client.put(url, json=payload, headers=headers).status_code == 409
    payload["expectedRowVersion"] = first.json["data"]["consultation"]["rowVersion"]
    second = client.put(url, json=payload, headers=headers)
    assert second.status_code == 201 and second.json["data"]["inputRevision"]["revision"] == 2


def test_access_token_expiry_and_inactive_account_are_enforced(app):
    client = app.test_client(); register(client, "patient@example.test"); response, headers = login(client, "patient@example.test")
    from backend.app.auth import encode_claims
    raw_payload = response.json["data"]["accessToken"].split(".")[1]
    claims = json.loads(base64.urlsafe_b64decode(raw_payload + "=" * (-len(raw_payload) % 4)))
    claims["exp"] = int((utcnow() - timedelta(seconds=1)).timestamp())
    with app.app_context():
        expired = encode_claims(claims)
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired}"}).status_code == 401
    with app.app_context():
        user = db.session.scalar(select(User).where(User.normalized_email == "patient@example.test")); user.active = False; db.session.commit()
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401


def test_refresh_rotation_logout_and_reuse_revoke_chain(app):
    client = app.test_client(); register(client, "patient@example.test"); login(client, "patient@example.test")
    csrf = client.get_cookie("csrf_token", path="/api/v1/auth").value
    proof = {"Origin": "http://localhost:5173", "X-CSRF-Token": csrf}
    old_refresh = client.get_cookie("refresh_token", path="/api/v1/auth").value
    rotated = client.post("/api/v1/auth/refresh", headers=proof)
    assert rotated.status_code == 200
    new_refresh = client.get_cookie("refresh_token", path="/api/v1/auth").value
    client.set_cookie("refresh_token", old_refresh, path="/api/v1/auth")
    client.set_cookie("csrf_token", "reuse-proof", path="/api/v1/auth")
    reused = client.post("/api/v1/auth/refresh", headers={"Origin": "http://localhost:5173", "X-CSRF-Token": "reuse-proof"})
    assert reused.status_code == 401 and reused.json["error"]["code"] == "REFRESH_REUSE"
    client.set_cookie("refresh_token", new_refresh, path="/api/v1/auth")
    assert client.post("/api/v1/auth/refresh", headers={"Origin": "http://localhost:5173", "X-CSRF-Token": "reuse-proof"}).status_code == 401
    with app.app_context():
        assert all(row.revoked_at is not None for row in db.session.scalars(select(RefreshSession)).all())


def test_refresh_requires_origin_and_csrf_and_logout_revokes(app):
    client = app.test_client(); register(client, "patient@example.test"); login(client, "patient@example.test")
    assert client.post("/api/v1/auth/refresh").status_code == 403
    csrf = client.get_cookie("csrf_token", path="/api/v1/auth").value
    assert client.post("/api/v1/auth/logout", headers={"Origin": "http://localhost:5173", "X-CSRF-Token": csrf}).status_code == 204
    with app.app_context():
        assert db.session.scalar(select(RefreshSession)).revoked_at is not None
