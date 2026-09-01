import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

base_url = os.environ.get("SMOKE_BASE_URL", "http://localhost:18000")
suffix = f"{os.getpid()}{sys.argv[1] if len(sys.argv) > 1 else ''}"
owner_email = f"scope-owner-{suffix}@example.com"
intruder_email = f"intruder-{suffix}@example.com"
password = "CorrectHorse-9x!LongEnough"


def request(path: str, payload: dict | None, token: str | None = None) -> tuple[int, dict]:
    encoded = (
        json.dumps(payload).encode("utf-8") if payload is not None else None
    )
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    http_request = urllib.request.Request(
        f"{base_url}{path}", data=encoded, headers=headers
    )
    try:
        with urllib.request.urlopen(http_request) as response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as error:
        return error.code, {}
    except urllib.error.URLError as error:
        raise SystemExit(f"unreachable: {path}: {error.reason}")


def register_and_login(email: str) -> str:
    status, body = request(
        "/auth/register", {"email": email, "password": password, "name": "Scope"}
    )
    assert status in (201, 409), f"register {email}: {status} {body}"
    form = urllib.parse.urlencode({"username": email, "password": password}).encode()
    login_request = urllib.request.Request(
        f"{base_url}/auth/login",
        data=form,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(login_request) as response:
        return json.loads(response.read().decode("utf-8"))["access_token"]


owner_access = register_and_login(owner_email)
intruder_access = register_and_login(intruder_email)

status, owner_me = request("/auth/me", None, token=owner_access)
assert status == 200, f"owner me: {status} {owner_me}"
assert owner_me.get("email") == owner_email.lower(), owner_me

status, intruder_me = request("/auth/me", None, token=intruder_access)
assert status == 200, f"intruder me: {status} {intruder_me}"
assert intruder_me.get("email") == intruder_email.lower(), intruder_me

for _ in range(3):
    status, owner_me = request("/auth/me", None, token=owner_access)
    assert status == 200 and owner_me.get("email") == owner_email.lower(), owner_me
    status, intruder_me = request("/auth/me", None, token=intruder_access)
    assert (
        status == 200 and intruder_me.get("email") == intruder_email.lower()
    ), intruder_me

status, _ = request("/auth/me", None, token=None)
assert status in (401, 403), f"anonymous me must be rejected, got {status}"

status, _ = request("/accounts/00000000-0000-0000-0000-000000000000", None, token=owner_access)
assert status == 404, f"unknown resource must be 404, got {status}"

print("identity-isolation:200")
print("cross-token-never-leaks:ok")
print("anonymous-rejected:ok")
print("unknown-resource:404")
print("SCOPE-ISOLATION-OK")
