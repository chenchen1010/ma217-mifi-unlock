"""Verify Internet access using only the selected Windows WLAN interface.

DNS and HTTPS sockets set IP_UNICAST_IF and bind the WLAN IPv4 address.
No proxy settings or OS default routes are used or modified.
Reference: https://learn.microsoft.com/en-us/windows/win32/winsock/ipproto-ip-socket-options
"""
import argparse
import hashlib
import http.client
import json
from pathlib import Path
import secrets
import socket
import ssl
import struct
import time

from mifi_probe import MiFi

IP_UNICAST_IF = getattr(socket, "IP_UNICAST_IF", 31)


def bound_socket(source_ip, interface_index, kind=socket.SOCK_STREAM):
    sock = socket.socket(socket.AF_INET, kind)
    sock.settimeout(12)
    sock.setsockopt(socket.IPPROTO_IP, IP_UNICAST_IF, struct.pack("!I", interface_index))
    actual = sock.getsockopt(socket.IPPROTO_IP, IP_UNICAST_IF)
    if actual != interface_index:
        sock.close()
        raise RuntimeError(f"Interface selection mismatch: {actual}")
    sock.bind((source_ip, 0))
    return sock


def skip_name(data, pos):
    while data[pos]:
        if data[pos] & 0xC0 == 0xC0:
            return pos + 2
        pos += 1 + data[pos]
    return pos + 1


def resolve_a(domain, source_ip, interface_index, dns_server="192.168.1.1"):
    ident = secrets.randbelow(65536)
    query = struct.pack("!6H", ident, 0x0100, 1, 0, 0, 0)
    query += b"".join(bytes([len(label)]) + label.encode("ascii") for label in domain.split("."))
    query += b"\x00" + struct.pack("!HH", 1, 1)
    with bound_socket(source_ip, interface_index, socket.SOCK_DGRAM) as sock:
        sock.connect((dns_server, 53))
        sock.send(query)
        data = sock.recv(4096)
    reply_id, flags, qd, an, ns, ar = struct.unpack("!6H", data[:12])
    if reply_id != ident or not flags & 0x8000 or flags & 0x000F or flags & 0x0200:
        raise RuntimeError("Invalid or truncated DNS response")
    pos = 12
    for _ in range(qd):
        pos = skip_name(data, pos) + 4
    addresses = []
    for _ in range(an):
        pos = skip_name(data, pos)
        typ, cls, ttl, length = struct.unpack("!HHIH", data[pos:pos+10])
        pos += 10
        if typ == 1 and cls == 1 and length == 4:
            addresses.append(socket.inet_ntoa(data[pos:pos+4]))
        pos += length
    if not addresses:
        raise RuntimeError("No IPv4 answer from MiFi DNS")
    return addresses


def fetch(domain, source_ip, interface_index, dns_server="192.168.1.1"):
    addresses = resolve_a(domain, source_ip, interface_index, dns_server)
    context = ssl.create_default_context()
    with bound_socket(source_ip, interface_index) as raw:
        raw.connect((addresses[0], 443))
        with context.wrap_socket(raw, server_hostname=domain) as tls:
            local_ip = tls.getsockname()[0]
            request = f"GET / HTTP/1.1\r\nHost: {domain}\r\nUser-Agent: MiFi-Connectivity-Check/1.0\r\nConnection: close\r\n\r\n"
            tls.sendall(request.encode("ascii"))
            response = http.client.HTTPResponse(tls)
            response.begin()
            body = response.read(65536)
            return {"domain": domain, "resolved_ipv4": addresses, "peer_ipv4": tls.getpeername()[0],
                    "local_ipv4": local_ip, "outbound_interface": interface_index,
                    "certificate_validated": True, "http_status": response.status,
                    "body_bytes_sampled": len(body), "body_sha256": hashlib.sha256(body).hexdigest(),
                    "success": response.status == 200 and len(body) > 0}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-ip", required=True)
    parser.add_argument("--interface-index", type=int, required=True)
    parser.add_argument("--dns-server", default="192.168.1.1")
    args = parser.parse_args()
    client = MiFi(args.source_ip)
    client.login()
    sim = client.read("mss_support_info")
    home = client.read("homepage_info")
    before = client.read("status_info")
    external = next(s for s in sim["sim_list"] if s["sim_name"] == "USIM")
    same_card = bool(external.get("sim_iccid")) and external["sim_iccid"] == home.get("iccid")
    report = {"captured_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "source_ip": args.source_ip, "interface_index": args.interface_index, "dns_server": args.dns_server,
              "current_sim_id": sim["current_sim_id"], "switch_mode": sim["switch_mode"],
              "active_iccid_matches_external": same_card, "operator": home["network_name"],
              "wan_ip_assigned": bool(home.get("wan_ip")), "checks": []}
    if sim["current_sim_id"] != "2" or not same_card or home["network_name"] != "CHN TELECOM":
        raise SystemExit("Active external Telecom SIM identity not established; no Internet probe performed.")
    for domain in ("www.baidu.com", "www.qq.com"):
        try:
            check = fetch(domain, args.source_ip, args.interface_index, args.dns_server)
        except Exception as exc:
            check = {"domain": domain, "success": False, "error": str(exc)}
        report["checks"].append(check)
        print(json.dumps(check, ensure_ascii=False), flush=True)
    time.sleep(3)
    after = client.read("status_info")
    report["device_tx_delta_bytes"] = int(after["tx_byte_all"]) - int(before["tx_byte_all"])
    report["device_rx_delta_bytes"] = int(after["rx_byte_all"]) - int(before["rx_byte_all"])
    report["verified"] = all(c["success"] for c in report["checks"]) and report["device_rx_delta_bytes"] > 0
    target = Path(__file__).parent / "artifacts" / ("internet-verification-" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + ".json")
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False), flush=True)
    print(str(target))
    if not report['verified']:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
