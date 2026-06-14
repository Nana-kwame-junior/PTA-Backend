#!/usr/bin/env python3
"""Quick smoke tests for PTA Backend API."""

import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("SMOKE_BASE_URL", "http://127.0.0.1:8000/api/v1").rstrip("/")
ROOT = BASE.replace("/api/v1", "")
ADMIN_EMAIL = os.environ.get("SMOKE_ADMIN_EMAIL", "admin@pta.com")
ADMIN_PASSWORD = os.environ.get("SMOKE_ADMIN_PASSWORD", "admin123")


def request(method: str, path: str, body: dict | None = None, token: str | None = None):
    url = f"{BASE}{path}"
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"raw": raw}
        return e.code, payload


def ok(label: str, status: int, expected=(200,)):
    passed = status in expected
    mark = "PASS" if passed else "FAIL"
    print(f"[{mark}] {label} -> HTTP {status}")
    return passed


def main():
    print(f"Smoke testing {BASE}\n")
    failures = 0

    req = urllib.request.Request(f"{ROOT}/")
    with urllib.request.urlopen(req, timeout=10) as resp:
        failures += 0 if ok("GET /", resp.status) else 1

    status, data = request("GET", "/payments/online/config")
    if ok("GET /payments/online/config", status):
        cfg = data.get("data", {})
        pk = cfg.get("public_key") or ""
        print(f"       public_key={pk[:24]}... configured={cfg.get('configured')}")
    else:
        failures += 1
        print(f"       {data}")

    status, data = request("GET", "/dues/current")
    if ok("GET /dues/current (public)", status):
        print(f"       has_dues={data.get('data') is not None}")
    else:
        failures += 1
        print(f"       {data}")

    status, _ = request("GET", "/meetings")
    failures += 0 if ok("GET /meetings", status) else 1

    status, _ = request("GET", "/meetings/upcoming")
    failures += 0 if ok("GET /meetings/upcoming", status) else 1

    status, data = request("POST", "/auth/web/login", {"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    token = None
    refresh = None
    if not ok("POST /auth/web/login", status):
        failures += 1
        print(f"       {data}")
    else:
        token = data["data"]["access_token"]
        refresh = data["data"]["refresh_token"]
        print(f"       role={data['data']['user']['role']}")

    if token:
        status, _ = request("GET", "/students?limit=1", token=token)
        failures += 0 if ok("GET /students (admin)", status) else 1

        status, pay_data = request("GET", "/payments/online?limit=1", token=token)
        if ok("GET /payments/online (admin)", status):
            payments = pay_data.get("data", {}).get("payments", [])
            if payments and not isinstance(payments[0], dict):
                print("       FAIL: payments not serialized as JSON")
                failures += 1
            elif payments:
                print("       payments serialized OK")
        else:
            failures += 1

    if refresh:
        status, _ = request("POST", "/auth/refresh", {"refresh_token": refresh})
        failures += 0 if ok("POST /auth/refresh", status) else 1

    print(f"\nDone — {failures} failure(s)")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
