import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

base_url = os.environ.get("SMOKE_BASE_URL", "http://localhost:18000")
email = f"smoke-{os.getpid()}{sys.argv[1] if len(sys.argv) > 1 else ''}@example.com"
password = "CorrectHorse-9x!LongEnough"


def post(
    path: str,
    payload: dict,
    token: str | None = None,
    form: bool = False,
) -> tuple[int, dict]:
    content_type = "application/x-www-form-urlencoded" if form else "application/json"
    encoded = (
        urllib.parse.urlencode(payload).encode("utf-8")
        if form
        else json.dumps(payload).encode("utf-8")
    )
    request = urllib.request.Request(
        f"{base_url}{path}",
        data=encoded,
        headers={"Content-Type": content_type}
        | ({"Authorization": f"Bearer {token}"} if token else {}),
        method="POST",
    )
    try:
        with urllib.request.urlopen(request) as response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as error:
        return error.code, {}


def get(path: str, token: str) -> int:
    request = urllib.request.Request(
        f"{base_url}{path}", headers={"Authorization": f"Bearer {token}"}
    )
    with urllib.request.urlopen(request) as response:
        return response.status


status, register_body = post(
    "/auth/register", {"email": email, "password": password, "name": "Smoke"}
)
print(f"register:{status}")
assert status == 201, register_body

status, login_body = post("/auth/login", {"username": email, "password": password}, form=True)
print("login:200")
assert status == 200, login_body

status = get("/auth/me", login_body["access_token"])
print(f"me:{status}")
assert status == 200

status, rotated = post("/auth/refresh", {"refresh_token": login_body["refresh_token"]})
print(f"refresh:{status}")
assert status == 200

status, _ = post("/auth/refresh", {"refresh_token": login_body["refresh_token"]})
print(f"replayed-refresh:{status}")
assert status == 401, f"replay must be rejected, got {status}"

status, _ = post("/auth/logout", {"refresh_token": rotated["refresh_token"]})
print(f"logout:{status}")
assert status == 204 or status == 200, status

status, _ = post("/auth/refresh", {"refresh_token": rotated["refresh_token"]})
print(f"post-logout-refresh:{status}")
assert status == 401, f"revoked token must be rejected, got {status}"

print("SMOKE-OK")
