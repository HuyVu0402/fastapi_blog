import pytest

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("path", ["/health", "/login", "/api/posts/999999", "/static/css/main.css"])
async def test_security_headers(client, path):
    response = await client.get(path)
    assert response.headers["x-frame-options"] == "SAMEORIGIN"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "strict-transport-security" not in response.headers


async def test_reset_page_keeps_stricter_policy(client):
    response = await client.get("https://blog.example.com/reset-password")
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["strict-transport-security"] == "max-age=63072000; includeSubDomains"


@pytest.mark.parametrize("url", ["http://blog.example.com/health", "https://localhost/health", "https://127.0.0.1/health", "https://[::1]/health"])
async def test_hsts_excludes_http_and_localhost(client, url):
    response = await client.get(url)
    assert response.status_code == 200
    assert "strict-transport-security" not in response.headers


async def test_untrusted_forwarded_header_does_not_enable_hsts(client):
    response = await client.get("/health", headers={"X-Forwarded-Proto": "https"})
    assert "strict-transport-security" not in response.headers
