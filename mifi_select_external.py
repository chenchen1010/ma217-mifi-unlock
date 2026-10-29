"""Select the observed USIM slot using this firmware's original Web UI action.

Default is read-only. --apply performs exactly one SIM selection POST after
checking firmware and slot identity, and saves the prior configuration.
--probe-inserted-card permits a one-shot selection when the human has inserted
the card but inactive-slot presence is still zero. The stock UI also permits
this selection. Read back and restore automatic selection if detection fails.
"""
import argparse
import http.client
import json
from pathlib import Path
import time
from urllib.parse import urlencode

from mifi_probe import MiFi, redact


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-ip", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--probe-inserted-card", action="store_true")
    parser.add_argument("--restore-auto", action="store_true")
    parser.add_argument("--stock-ui-reselect", action="store_true", help="Send the same stock-UI selection once despite a reported ban; does not alter the ban flag")
    args = parser.parse_args()
    client = MiFi(args.source_ip)
    client.login()
    firmware = client.read("firmware_info")
    before = client.read("mss_support_info")
    if firmware.get("version_num") != "LBF1ANT_N10_WH_2ESIM_V001" or firmware.get("hardware_version") != "LBF1A_N10":
        raise SystemExit("Unverified firmware or hardware; no settings changed.")
    external = [s for s in before.get("sim_list", []) if s.get("sim_id") == "2" and s.get("sim_name") == "USIM"]
    if len(external) != 1:
        raise SystemExit("Expected external USIM slot not found; no settings changed.")
    has_card_identity = bool(external[0].get("sim_iccid")) and bool(external[0].get("sim_imsi"))
    if not args.restore_auto and external[0].get("sim_present") != "1" and not has_card_identity and not args.probe_inserted_card:
        raise SystemExit("External USIM is not reported present; no settings changed.")
    if not args.restore_auto and external[0].get("sim_banned") != "0" and not args.stock_ui_reselect:
        raise SystemExit("External USIM is reported restricted; no settings changed.")
    payload = {"switch_mode": "0"} if args.restore_auto else {"sole_sim_id": "2", "switch_mode": "1"}
    evidence = {"firmware": firmware, "before": before, "proposed": payload, "applied": False}
    root = Path(__file__).parent / "artifacts"
    root.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    output = root / f"sim-selection-{stamp}.json"
    output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"before": redact(before), "proposed": payload, "apply": args.apply}, ensure_ascii=False), flush=True)
    if not args.apply:
        return
    path = "/xml_action.cgi?" + urlencode({"method": "post", "module": "duster",
                "file": "json_mss_support_set" + str(int(time.time()) * 1000)})
    conn = http.client.HTTPConnection("192.168.1.1", timeout=45, source_address=(args.source_ip, 0))
    evidence["attempted"] = True
    output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        conn.request("POST", path, body=json.dumps(payload), headers={
            "Authorization": client.auth_header("POST"),
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Connection": "close"})
        response = conn.getresponse()
        body = response.read(100_000).decode("utf-8", "replace")
        evidence.update({"http_status": response.status, "response": body})
        first, last = body.find("{"), body.rfind("}")
        data = json.loads(body[first:last+1]) if first >= 0 and last >= first else {}
        evidence["applied"] = response.status == 200 and data.get("result") == "success"
        print(json.dumps({"http_status": response.status, "response": redact(data),
                          "accepted_not_yet_verified": evidence["applied"]}, ensure_ascii=False))
    except Exception as exc:
        evidence["error"] = str(exc)
        print("Request outcome uncertain; read back before retrying.")
    finally:
        conn.close()
        output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
