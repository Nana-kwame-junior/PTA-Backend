from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_read_root():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["message"] == "Welcome to Parent And Teacher Association Saas"


def test_read_item():
    response = client.get("/api/v1/items/1")
    assert response.status_code == 200
    assert response.json()["id"] == 1


def test_dashboard_origin_passes_login_preflight():
    response = client.options(
        "/api/v1/auth/web/login",
        headers={
            "Origin": "https://pta-frontend-dashboard-gules.vercel.app",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == (
        "https://pta-frontend-dashboard-gules.vercel.app"
    )
