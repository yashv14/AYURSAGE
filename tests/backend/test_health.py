from backend.app import create_app


def test_liveness_endpoint_reports_process_is_running():
    client = create_app().test_client()

    response = client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_unknown_readiness_endpoint_is_not_claimed():
    client = create_app().test_client()

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 404
