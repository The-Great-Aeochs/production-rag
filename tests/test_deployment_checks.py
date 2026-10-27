import httpx
import pytest

from scripts.check_deployment import base_url, check_deployment


def deployed_response(request):
    path = request.url.path
    if request.url.host == "site.test":
        if path == "/api/metrics":
            return httpx.Response(404)
        if path == "/api/workspaces":
            return httpx.Response(403 if request.method == "POST" else 401)
        return httpx.Response(200, headers={"content-type": "text/html"}, text="<main>Site</main>")
    if path == "/health/live":
        return httpx.Response(200, json={"status": "alive"})
    if path == "/health/ready":
        return httpx.Response(200, json={"status": "ready"})
    return httpx.Response(401)


def test_release_checks_cover_gateway_and_backend_boundaries():
    def response(request):
        if request.url.host == "site.test" and request.url.path == "/workspace":
            pytest.fail("Configured workspaces redirect; full checks must use the sign-in page")
        return deployed_response(request)

    with httpx.Client(transport=httpx.MockTransport(response)) as client:
        checks = check_deployment(client, "https://site.test", "https://api.test")
    assert len(checks) == 14
    assert all(check.passed for check in checks)


@pytest.mark.parametrize(
    "status,body",
    [(503, {"status": "unavailable"}), (200, {"status": "unavailable"}), (200, [])],
)
def test_readiness_requires_both_success_status_and_ready_body(status, body):
    def response(request):
        if request.url.path == "/health/ready":
            return httpx.Response(status, json=body)
        return deployed_response(request)

    with httpx.Client(transport=httpx.MockTransport(response)) as client:
        checks = check_deployment(client, "https://site.test", "https://api.test")
    assert not next(check for check in checks if "readiness" in check.name).passed


def test_redirect_to_login_is_not_a_successful_api_check():
    def response(request):
        if request.url.host == "other.test":
            pytest.fail("Deployment checker must not follow redirects")
        return httpx.Response(302, headers={"location": "https://other.test/login"})

    with httpx.Client(transport=httpx.MockTransport(response)) as client:
        checks = check_deployment(client, "https://site.test", "https://api.test")
    assert not any(check.passed for check in checks)


@pytest.mark.parametrize(
    "url",
    [
        "https://user:secret@api.test",
        "https://api.test?token=secret",
        "https://api.test#secret",
        "http://api.test",
        "file:///etc/passwd",
        "api.test",
    ],
)
def test_destinations_reject_credentials_and_insecure_remote_urls(url):
    with pytest.raises(ValueError):
        base_url(url)


def test_transport_errors_do_not_print_url_or_upstream_secrets():
    def response(request):
        raise httpx.ConnectError("secret diagnostic", request=request)

    with httpx.Client(transport=httpx.MockTransport(response)) as client:
        checks = check_deployment(client, "https://site.test")
    assert all(not check.passed and check.detail == "ConnectError" for check in checks)


def test_unconfigured_login_fails_full_checks_but_not_showcase_mode():
    def response(request):
        if request.url.path == "/api/workspaces" and request.method == "GET":
            return httpx.Response(503)
        return deployed_response(request)

    with httpx.Client(transport=httpx.MockTransport(response)) as client:
        showcase = check_deployment(client, "https://site.test")
        full = check_deployment(client, "https://site.test", "https://api.test")
    assert all(check.passed for check in showcase)
    assert not full[-1].passed
