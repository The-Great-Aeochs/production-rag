"""Check deployed HTTP boundaries without credentials or model generation."""

import argparse
from dataclasses import asdict, dataclass
from urllib.parse import urlsplit

import httpx


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str


def base_url(value: str) -> str:
    """Accept explicit HTTPS destinations; permit HTTP only for local checks."""
    parsed = urlsplit(value)
    if (
        not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or not (
            parsed.scheme == "https"
            or (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"})
        )
    ):
        raise ValueError("Use an HTTPS URL without credentials, a query, or a fragment")
    return value.rstrip("/") + "/"


def check_deployment(
    client: httpx.Client, site_url: str, api_url: str | None = None
) -> list[Check]:
    site = base_url(site_url)
    api = base_url(api_url) if api_url else None
    checks = []

    def probe(name, method, url, status, *, expected_json=None, html=False, **kwargs):
        try:
            # Redirects are failures: do not follow a login page or another host
            # and accidentally report that destination as a healthy API.
            response = client.request(method, url, follow_redirects=False, **kwargs)
            passed = response.status_code == status
            detail = f"HTTP {response.status_code}; expected {status}"
            if passed and html:
                passed = "text/html" in response.headers.get("content-type", "")
                if not passed:
                    detail = "Expected an HTML page"
            if passed and expected_json:
                try:
                    data = response.json()
                    passed = isinstance(data, dict) and all(
                        data.get(key) == value for key, value in expected_json.items()
                    )
                except ValueError:
                    passed = False
                if not passed:
                    detail = "Unexpected health response"
            checks.append(Check(name, passed, detail))
        except httpx.HTTPError as exc:
            # HTTP exception strings can contain URLs and upstream diagnostics.
            checks.append(Check(name, False, type(exc).__name__))

    # A configured /workspace correctly redirects anonymous visitors to sign-in.
    # Check that landing page directly in full mode instead of treating the
    # workspace's expected authentication redirect as an outage.
    login_page = ("sign-in", "Sign-in") if api else ("workspace", "Workspace")
    for path, name in [("", "Homepage"), ("docs", "Documentation"), login_page]:
        probe(name, "GET", site + path, 200, html=True)
    probe("Platform routes excluded from website gateway", "GET", site + "api/metrics", 404)
    probe(
        "Cross-origin workspace mutation rejected",
        "POST",
        site + "api/workspaces",
        403,
        headers={"Origin": "https://deployment-check.invalid"},
        json={},
    )
    if api:
        probe("API liveness", "GET", api + "health/live", 200, expected_json={"status": "alive"})
        probe(
            "API dependency and model readiness",
            "GET",
            api + "health/ready",
            200,
            expected_json={"status": "ready"},
        )
        for path, method in [
            ("metrics", "GET"),
            ("workspaces", "GET"),
            ("query", "POST"),
            ("session", "POST"),
            ("ingest", "POST"),
        ]:
            probe(f"Anonymous {path} access rejected", method, api + path, 401)
        probe(
            "Backend login configured and invalid JWT rejected",
            "GET",
            api + "workspaces",
            401,
            headers={"Authorization": "Bearer invalid-deployment-check-token"},
        )
        probe("Website login gateway configured", "GET", site + "api/workspaces", 401)
    return checks


def main() -> int:
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-url", required=True)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--api-url")
    target.add_argument("--showcase-only", action="store_true")
    parser.add_argument("--json", action="store_true", help="Print a machine-readable report")
    args = parser.parse_args()
    try:
        site = base_url(args.site_url)
        api = base_url(args.api_url) if args.api_url else None
    except ValueError as exc:
        parser.error(str(exc))
    with httpx.Client(timeout=httpx.Timeout(15, connect=5), trust_env=False) as client:
        checks = check_deployment(client, site, api)
    if args.json:
        print(json.dumps([asdict(check) for check in checks], indent=2))
    else:
        for check in checks:
            print(f"{'PASS' if check.passed else 'FAIL'} {check.name}: {check.detail}")
        print(
            "Real sign-in, role checks, source ingestion, and answer quality require separate tests."
        )
    return 0 if all(check.passed for check in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
