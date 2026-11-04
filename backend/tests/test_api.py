from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_health():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["X-Request-ID"]

def test_error_contract():
    response = client.get("/api/v1/missing")
    assert response.status_code == 404
    assert response.json()["requestId"] == response.headers["X-Request-ID"]
    assert "message" in response.json()
