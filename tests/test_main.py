from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import health, home, serve_frontend


def test_unbuilt_gui_does_not_block_other_routes(tmp_path):
    app = FastAPI()

    @app.get("/health")
    def health():
        return {"status": "ok"}

    app.add_api_route("/", home)
    serve_frontend(app, tmp_path)
    with TestClient(app) as client:
        assert (
            client.get("/", follow_redirects=False).headers["location"] == "/dashboard/"
        )
        assert client.get("/dashboard/").status_code == 503
        assert (
            "app/dashboard" in client.get("/dashboard/projects/demo").json()["detail"]
        )
        for path in ("/app", "/app/", "/app/projects/demo"):
            assert client.get(path, headers={"Accept": "text/html"}).status_code == 404
        assert client.get("/health").status_code == 200
        assert client.get("/openapi.json").status_code == 200
        assert client.get("/docs").status_code == 200


def test_frontend_fallback_and_assets_are_confined_to_build(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>GUI</html>")
    (dist / "assets").mkdir()
    (dist / "assets" / "app.js").write_text("console.log('GUI')")
    (tmp_path / "secret.txt").write_text("synthetic-secret")
    app = FastAPI()

    @app.get("/api/v1/test")
    def api():
        return {"api": True}

    app.add_api_route("/", home)
    serve_frontend(app, dist)
    with TestClient(app) as client:
        assert (
            client.get("/", follow_redirects=False).headers["location"] == "/dashboard/"
        )
        assert client.get("/dashboard/").text == "<html>GUI</html>"
        for path in ("/app", "/app/", "/app/projects/demo"):
            assert client.get(path, headers={"Accept": "text/html"}).status_code == 404
        assert (
            client.get("/dashboard/projects/demo", headers={"Accept": "text/html"}).text
            == "<html>GUI</html>"
        )
        assert client.get("/dashboard/assets/app.js").status_code == 200
        assert (
            client.get(
                "/dashboard/missing.css", headers={"Accept": "text/html"}
            ).status_code
            == 404
        )
        assert (
            client.get(
                "/dashboard/assets/missing.js", headers={"Accept": "text/html"}
            ).status_code
            == 404
        )
        assert client.get("/dashboard/projects/demo").status_code == 404
        assert (
            client.get(
                "/dashboard/%2e%2e/secret.txt", headers={"Accept": "text/html"}
            ).status_code
            == 404
        )
        assert client.post("/dashboard/projects/demo").status_code == 404
        assert (
            client.get("/api/v1/missing", headers={"Accept": "text/html"}).status_code
            == 404
        )
        assert client.get("/api/v1/test").json() == {"api": True}
        assert client.get("/docs").status_code == 200
        assert client.get("/openapi.json").status_code == 200


def test_health_returns_503_when_dispatcher_unavailable(monkeypatch):
    from app.assessments.worker import dispatcher

    monkeypatch.setattr(dispatcher, "_executor", None)
    app = FastAPI()
    app.add_api_route("/health", health)
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["detail"] == "assessment dispatcher unavailable"
