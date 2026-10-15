"""Hardening of the public API: rate limit, read-only mode, CORS, payload size."""


def _post(client, subject="Card reader outage", **kw):
    return client.post("/tickets", json={"subject": subject}, **kw)


def test_write_rate_limit_returns_429(client, monkeypatch):
    monkeypatch.setenv("ESCALATE_WRITE_RATE_LIMIT", "3")
    codes = [_post(client).status_code for _ in range(4)]
    assert codes == [201, 201, 201, 429]
    r = _post(client)
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) >= 1


def test_resolve_is_rate_limited_too(client, monkeypatch):
    monkeypatch.setenv("ESCALATE_WRITE_RATE_LIMIT", "2")
    tid = _post(client).json()["id"]
    assert client.post(f"/tickets/{tid}/resolve").status_code == 200
    assert client.post(f"/tickets/{tid}/resolve").status_code == 429


def test_reads_are_not_rate_limited(client, monkeypatch):
    monkeypatch.setenv("ESCALATE_WRITE_RATE_LIMIT", "1")
    assert all(client.get("/metrics").status_code == 200 for _ in range(5))


def test_rate_limit_is_per_client_ip_behind_proxy(client, monkeypatch):
    monkeypatch.setenv("ESCALATE_WRITE_RATE_LIMIT", "1")
    monkeypatch.setenv("ESCALATE_TRUST_PROXY", "true")
    a = {"X-Forwarded-For": "198.51.100.1"}
    b = {"X-Forwarded-For": "198.51.100.2"}
    assert _post(client, headers=a).status_code == 201
    assert _post(client, headers=a).status_code == 429
    assert _post(client, headers=b).status_code == 201


def test_spoofed_forwarded_for_prefix_does_not_reset_limit(client, monkeypatch):
    # The proxy appends the real client IP last; a client-supplied first entry
    # must not create a fresh bucket.
    monkeypatch.setenv("ESCALATE_WRITE_RATE_LIMIT", "1")
    monkeypatch.setenv("ESCALATE_TRUST_PROXY", "true")
    assert _post(client, headers={"X-Forwarded-For": "1.1.1.1, 198.51.100.1"}).status_code == 201
    assert _post(client, headers={"X-Forwarded-For": "2.2.2.2, 198.51.100.1"}).status_code == 429


def test_read_only_mode_blocks_writes_but_not_reads(client, monkeypatch):
    tid = _post(client).json()["id"]
    monkeypatch.setenv("ESCALATE_READ_ONLY", "true")
    assert _post(client).status_code == 403
    assert client.post(f"/tickets/{tid}/resolve").status_code == 403
    assert client.get("/tickets").status_code == 200
    assert client.get("/health").json() == {"status": "ok", "read_only": True}


def test_health_reports_writable_by_default(client):
    assert client.get("/health").json() == {"status": "ok", "read_only": False}


def test_cors_allows_only_configured_origins(client):
    ok = client.get("/health", headers={"Origin": "http://localhost:5173"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    evil = client.get("/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in evil.headers


def test_oversized_body_rejected(client):
    r = client.post("/tickets", json={"subject": "x", "body": "a" * 5001})
    assert r.status_code == 422
