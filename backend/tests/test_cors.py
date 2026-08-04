from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def _preflight(origin: str):
    with TestClient(app) as client:
        return client.options(
            "/statistics",
            headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
        )


def test_windows_webview2_origin_is_allowed():
    """Regression test for a real bug: the installed Windows desktop app
    couldn't reach its own healthy, correctly-running backend, because
    every request was silently blocked by CORS. The actual origin
    WebView2 uses turned out to be http://tauri.localhost -- confirmed
    directly from the browser's own console error -- not
    https://tauri.localhost as first assumed/documented, and not
    tauri://localhost (the macOS/Linux scheme). Getting this scheme
    wrong is exactly why this needs to be a regex match covering both
    schemes, not a single hardcoded guess."""
    resp = _preflight("http://tauri.localhost")
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "http://tauri.localhost"


def test_macos_linux_tauri_origin_still_allowed():
    resp = _preflight("tauri://localhost")
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "tauri://localhost"


def test_https_tauri_localhost_also_allowed():
    """In case a future Tauri/WebView2 version ever does use https --
    covered by the regex either way, so this shouldn't need another
    emergency fix if that assumption ever changes again."""
    resp = _preflight("https://tauri.localhost")
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "https://tauri.localhost"


def test_dev_server_origins_still_allowed():
    for origin in ("http://localhost:1420", "http://localhost:5173"):
        resp = _preflight(origin)
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") == origin


def test_arbitrary_untrusted_origin_is_still_rejected():
    """The whole point of CORS in the first place -- confirms the fix
    didn't accidentally widen this into an open policy. A malicious
    website loaded in a normal browser tab must still be unable to reach
    this locally-running backend via JavaScript."""
    resp = _preflight("http://evil-site.example.com")
    assert resp.headers.get("access-control-allow-origin") is None
