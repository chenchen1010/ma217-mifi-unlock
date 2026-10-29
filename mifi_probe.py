"""Read selected MA217 Web UI endpoints using the device's observed login flow.

No firmware, SIM, APN, reboot, reset or other configuration writes are exposed.
HTTP is bound to the WiFi address to avoid the identically addressed LAN router.
"""
import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import secrets
import time
from urllib.parse import urlencode

READ_ENDPOINTS = (
    "login_info", "firmware_info", "homepage_info", "status_info", "wan_info",
    "mss_status", "mss_support_info", "wan_apn_profile_info",
    "wan_pdp_context_info", "engineering_info", "device_management_info", "custom_fw_info", "wlan_info",
)


def md5(value):
    return hashlib.md5(value.encode()).hexdigest()


def redact(value, key=""):
    if isinstance(value, dict):
        return {k: redact(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, key) for v in value]
    if re.search(r"imei|imsi|iccid|mac|serial|password|passwd|paswd|token|secret|^sn$|^usr[24]", key, re.I):
        return "[redacted]" if value else value
    if isinstance(value, str):
        value = re.sub(r"\b\d{14,22}\b", "[redacted-id]", value)
        value = re.sub(r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}", "[redacted-mac]", value)
    return value


class MiFi:
    def __init__(self, source_ip):
        self.source_ip = source_ip
        self.username = os.environ.get("MIFI_USERNAME", "admin")
        self.password = os.environ.get("MIFI_PASSWORD", "admin")
        self.nc = 1

    def request(self, path, headers=None):
        conn = http.client.HTTPConnection("192.168.1.1", timeout=12,
                                          source_address=(self.source_ip, 0))
        try:
            conn.request("GET", path, headers={"Connection": "close", **(headers or {})})
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read(2_000_000).decode("utf-8", "replace")
        finally:
            conn.close()

    def digest(self, uri, cnonce, nc, method="GET"):
        ha1 = md5(f"{self.username}:{self.realm}:{self.password}")
        ha2 = md5(f"{method}:{uri}")
        return md5(f"{ha1}:{self.nonce}:{nc}:{cnonce}:{self.qop}:{ha2}")

    def auth_header(self, method="GET"):
        cnonce = secrets.token_hex(8)
        nc = f"{self.nc:08X}"
        self.nc += 1
        uri = "/cgi/xml_action.cgi"
        response = self.digest(uri, cnonce, nc, method)
        return (f'Digest username="{self.username}", realm="{self.realm}", '
                f'nonce="{self.nonce}", uri="{uri}", response="{response}", '
                f'qop={self.qop}, nc={nc}, cnonce="{cnonce}"')

    def login(self):
        status, headers, _ = self.request("/login.cgi")
        challenge = next((v for k, v in headers.items() if k.lower() == "www-authenticate"), "")
        parts = dict(re.findall(r'(\w+)="([^"]*)"', challenge))
        self.realm, self.nonce, self.qop = (parts[k] for k in ("realm", "nonce", "qop"))
        cnonce = secrets.token_hex(8)
        query = urlencode({"Action": "Digest", "username": self.username,
                           "realm": self.realm, "nonce": self.nonce,
                           "response": self.digest("/cgi/protected.cgi", cnonce, "00000001"),
                           "qop": self.qop, "cnonce": cnonce, "temp": "marvell"})
        status, _, body = self.request("/login.cgi?" + query, {"Authorization": self.auth_header()})
        if status != 200 or "200 OK" not in body:
            raise RuntimeError(f"Login was not accepted: HTTP {status}; response {body[:100]!r}")

    def read(self, name):
        if name not in READ_ENDPOINTS:
            raise ValueError("Endpoint is not in the verified read-only allowlist")
        path = "/xml_action.cgi?" + urlencode({"method": "get", "module": "duster",
                "file": "json_" + name + str(int(time.time()) * 1000)})
        status, _, body = self.request(path, {"Authorization": self.auth_header()})
        first, last = body.find("{"), body.rfind("}")
        if status != 200 or first < 0 or last < first:
            raise RuntimeError(f"{name}: HTTP {status}; no JSON object")
        data = json.loads(body[first:last+1])
        if "UNAUTHORIZED" in body or "KICKOFF" in body:
            raise RuntimeError(f"{name}: authentication rejected")
        return data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-ip", required=True)
    parser.add_argument("--only", nargs="+", choices=READ_ENDPOINTS, default=READ_ENDPOINTS)
    args = parser.parse_args()
    client = MiFi(args.source_ip)
    client.login()
    results = {"captured_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "source_ip": args.source_ip, "read_only": True, "responses": {}}
    for name in args.only:
        try:
            results["responses"][name] = client.read(name)
        except Exception as exc:
            results["responses"][name] = {"error": str(exc)}
        print(json.dumps({name: redact(results["responses"][name])}, ensure_ascii=False))
    target = Path(__file__).parent / "artifacts" / ("device-readback-" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + ".json")
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"saved_local": str(target), "note": "Raw identifiers remain local; console output is redacted."}, ensure_ascii=False))


if __name__ == "__main__":
    main()
