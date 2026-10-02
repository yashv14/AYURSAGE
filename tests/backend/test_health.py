from backend.app import create_app


def test_liveness_endpoint_reports_process_is_running(app):
    client = app.test_client()

    response = client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_unmigrated_database_is_not_ready(app):
    client = app.test_client()

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json["data"]["ml"] == "unavailable"
    assert response.json["requestId"] == response.headers["X-Request-ID"]
