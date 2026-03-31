def test_health_check(client):
    """Health endpoint returns 200 with correct service name."""
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "pdf-forge"
