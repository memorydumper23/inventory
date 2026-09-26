#!/usr/bin/env python3
import os
import sys
import json
import argparse
from typing import Any, Dict, List
from urllib.parse import quote

import requests
from dotenv import load_dotenv


def load_env() -> Dict[str, str]:
    load_dotenv()
    cfg = {
        "GLPI_BASE_URL": os.getenv("GLPI_BASE_URL", "").rstrip("/"),
        "GLPI_LEGACY_API_URL": os.getenv("GLPI_LEGACY_API_URL", "").strip(),
        "GLPI_API_USERNAME": os.getenv("GLPI_API_USERNAME", "").strip(),
        "GLPI_API_PASSWORD": os.getenv("GLPI_API_PASSWORD", "").strip(),
        "GLPI_LEGACY_APP_TOKEN": os.getenv("GLPI_LEGACY_APP_TOKEN", "").strip(),
        "GLPI_ITEMTYPE": os.getenv("GLPI_ITEMTYPE", r"Glpi\CustomAsset\NmapAsset").strip(),
        "FIELD_TCP_KEY": os.getenv("FIELD_TCP_KEY", "tcp_ports").strip(),
        "FIELD_UDP_KEY": os.getenv("FIELD_UDP_KEY", "udp_ports").strip(),
        "FIELD_SERVICES_KEY": os.getenv("FIELD_SERVICES_KEY", "services").strip(),
        "STATE_FILE": os.getenv("STATE_FILE", "glpi_nmap_state_legacy.json").strip(),
        "GLPI_HTTP_TIMEOUT": os.getenv("GLPI_HTTP_TIMEOUT", "30").strip(),
    }

    if not cfg["GLPI_LEGACY_API_URL"] and cfg["GLPI_BASE_URL"]:
        cfg["GLPI_LEGACY_API_URL"] = f"{cfg['GLPI_BASE_URL']}/apirest.php"

    # A relative state file path is relative to this script's directory
    if not os.path.isabs(cfg["STATE_FILE"]):
        cfg["STATE_FILE"] = os.path.join(os.path.dirname(os.path.abspath(__file__)), cfg["STATE_FILE"])

    return cfg


def check_required_env(cfg: Dict[str, str]) -> None:
    required = ("GLPI_LEGACY_API_URL", "GLPI_API_USERNAME", "GLPI_API_PASSWORD")
    missing = [k for k in required if not cfg[k] or cfg[k] == "CHANGE_ME"]
    if cfg["GLPI_LEGACY_APP_TOKEN"] == "CHANGE_ME":
        missing.append("GLPI_LEGACY_APP_TOKEN")
    if missing:
        raise SystemExit(
            f"[ERROR] Missing configuration: {', '.join(missing)}. "
            "Copy .env.example to .env and fill in your values."
        )


def encoded_itemtype(cfg: Dict[str, str]) -> str:
    return quote(cfg["GLPI_ITEMTYPE"], safe="")


def init_legacy_session(cfg: Dict[str, str]) -> str:
    """
    Legacy API initSession with Basic Auth + App-Token (optional but recommended).
    """
    timeout = int(cfg["GLPI_HTTP_TIMEOUT"])
    url = f"{cfg['GLPI_LEGACY_API_URL']}/initSession"

    headers = {
        "Content-Type": "application/json",
    }

    if cfg["GLPI_LEGACY_APP_TOKEN"]:
        headers["App-Token"] = cfg["GLPI_LEGACY_APP_TOKEN"]

    r = requests.get(
        url,
        headers=headers,
        auth=(cfg["GLPI_API_USERNAME"], cfg["GLPI_API_PASSWORD"]),
        timeout=timeout,
    )

    if r.status_code >= 400:
        print(f"[ERROR] initSession HTTP {r.status_code}: {r.text.strip()}", file=sys.stderr)

    r.raise_for_status()

    data = r.json()
    session_token = data.get("session_token")
    if not session_token:
        raise RuntimeError(f"No session_token received from initSession: {data}")

    return session_token


def kill_legacy_session(cfg: Dict[str, str], session_token: str) -> None:
    timeout = int(cfg["GLPI_HTTP_TIMEOUT"])
    url = f"{cfg['GLPI_LEGACY_API_URL']}/killSession"

    headers = {
        "Session-Token": session_token,
        "Content-Type": "application/json",
    }
    if cfg["GLPI_LEGACY_APP_TOKEN"]:
        headers["App-Token"] = cfg["GLPI_LEGACY_APP_TOKEN"]

    try:
        requests.get(url, headers=headers, timeout=timeout)
    except Exception:
        pass


def parse_normalized_json(path: str) -> List[Dict[str, Any]]:
    """
    Supports:
    1) a plain list of hosts
    2) {"hosts": [...]}
    3) {"assets": [...]}
    4) {"results": [...]}
    5) {"data": [...]}
    6) {"items": [...]}
    7) {"devices": [...]}
    8) a dictionary keyed by id / keyed by IP
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    candidate = None

    if isinstance(data, list):
        candidate = data
    elif isinstance(data, dict):
        for key in ("hosts", "assets", "results", "data", "items", "devices"):
            if key in data and isinstance(data[key], list):
                candidate = data[key]
                break

        if candidate is None:
            values = list(data.values())
            if values and all(isinstance(v, dict) for v in values):
                candidate = values

    if candidate is None:
        raise ValueError(
            "Unsupported JSON format. Expected: a plain list, "
            "an object with a hosts/assets/results/data/items/devices key, "
            "or a dictionary keyed by id."
        )

    out: List[Dict[str, Any]] = []

    for item in candidate:
        if not isinstance(item, dict):
            continue

        ip = (
            item.get("ip")
            or item.get("ipv4")
            or item.get("address")
            or item.get("primary_ip")
            or item.get("ip_address")
        )

        ports = (
            item.get("ports")
            or item.get("open_ports")
            or item.get("services")
            or []
        )

        if not ip and isinstance(item.get("network"), dict):
            ip = item["network"].get("ip") or item["network"].get("primary_ip")

        if not ip:
            continue

        normalized_ports = []
        for p in ports:
            if not isinstance(p, dict):
                continue

            proto = p.get("proto") or p.get("protocol") or "tcp"
            port = p.get("port") or p.get("portid") or p.get("number")
            service = p.get("service") or p.get("name")
            product = p.get("product")
            version = p.get("version")
            extrainfo = p.get("extrainfo") or p.get("banner")

            try:
                port = int(port)
            except (TypeError, ValueError):
                continue

            normalized_ports.append({
                "proto": proto,
                "port": port,
                "service": service,
                "product": product,
                "version": version,
                "extrainfo": extrainfo,
            })

        out.append({
            "ip": ip,
            "ports": normalized_ports,
        })

    if not out:
        raise ValueError("No valid host with an IP found in the JSON.")

    return out


def compact_ports(host: Dict[str, Any], proto: str) -> str:
    vals = sorted(
        {str(p["port"]) for p in host["ports"] if p.get("proto") == proto},
        key=lambda x: int(x)
    )
    return ",".join(vals)


def compact_services(host: Dict[str, Any]) -> str:
    """
    Hybrid format:
    - GLPI detail view: one service per line
    - GLPI list view: the \n are flattened, but the bullets stay visible

    Example:
    • 22/ssh [OpenSSH 9.x protocol 2.0]
    • 80/http [nginx 1.x]
    • 123/ntp
    """
    vals = []
    seen = set()

    for p in host["ports"]:
        port = p.get("port")
        svc = p.get("service") or "unknown"
        product = p.get("product") or ""
        version = p.get("version") or ""
        extra = p.get("extrainfo") or ""

        detail = " ".join(x for x in [product, version, extra] if x).strip()

        if detail:
            item = f"• {port}/{svc} [{detail}]"
        else:
            item = f"• {port}/{svc}"

        if item not in seen:
            seen.add(item)
            vals.append(item)

    return "\n".join(vals)


def build_payload(host: Dict[str, Any], cfg: Dict[str, str]) -> Dict[str, Any]:
    """
    Rules:
    - name = IP
    - only 3 custom text fields:
      * tcp_ports
      * udp_ports
      * services
    """
    ip = host["ip"]

    payload = {
        "name": ip,
        cfg["FIELD_TCP_KEY"]: compact_ports(host, "tcp"),
        cfg["FIELD_UDP_KEY"]: compact_ports(host, "udp"),
        cfg["FIELD_SERVICES_KEY"]: compact_services(host),
    }
    return payload


def load_state(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except Exception:
            return {}


def save_state(path: str, state: Dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def extract_id_from_response(resp: requests.Response) -> int:
    """
    Try to extract the ID from the various response shapes of the Legacy API.
    """
    try:
        data = resp.json()
    except Exception:
        return 0

    if isinstance(data, dict):
        if "id" in data:
            if isinstance(data["id"], int):
                return data["id"]
            if isinstance(data["id"], str):
                try:
                    return int(data["id"])
                except Exception:
                    pass
            if isinstance(data["id"], list) and data["id"]:
                try:
                    return int(data["id"][0])
                except Exception:
                    pass

    return 0


def legacy_headers(cfg: Dict[str, str], session_token: str) -> Dict[str, str]:
    headers = {
        "Session-Token": session_token,
        "Content-Type": "application/json",
    }
    if cfg["GLPI_LEGACY_APP_TOKEN"]:
        headers["App-Token"] = cfg["GLPI_LEGACY_APP_TOKEN"]
    return headers


def create_item(cfg: Dict[str, str], session_token: str, payload: Dict[str, Any], verbose: bool = False) -> requests.Response:
    timeout = int(cfg["GLPI_HTTP_TIMEOUT"])
    endpoint = f"{cfg['GLPI_LEGACY_API_URL']}/{encoded_itemtype(cfg)}"
    if verbose:
        print("[DEBUG] endpoint create:", endpoint)
        print("[DEBUG] payload:", json.dumps(payload, ensure_ascii=False))
    headers = legacy_headers(cfg, session_token)

    # Legacy API: body {"input": ...}
    r = requests.post(endpoint, headers=headers, json={"input": payload}, timeout=timeout)
    return r


def update_item(cfg: Dict[str, str], session_token: str, item_id: int, payload: Dict[str, Any], verbose: bool = False) -> requests.Response:
    timeout = int(cfg["GLPI_HTTP_TIMEOUT"])
    endpoint = f"{cfg['GLPI_LEGACY_API_URL']}/{encoded_itemtype(cfg)}/{item_id}"
    if verbose:
        print("[DEBUG] endpoint update:", endpoint)
        print("[DEBUG] payload:", json.dumps(payload, ensure_ascii=False))
    headers = legacy_headers(cfg, session_token)

    r = requests.put(endpoint, headers=headers, json={"input": payload}, timeout=timeout)
    return r


def main() -> None:
    parser = argparse.ArgumentParser(description="Push Nmap JSON to the GLPI 'Nmap' custom asset via the Legacy API")
    parser.add_argument("-i", "--input", required=True, help="Normalized JSON file")
    parser.add_argument("-f", "--format", choices=["json"], required=True, help="Input format")
    parser.add_argument("--dry-run", action="store_true", help="Only print the payloads, send nothing")
    parser.add_argument("--only-ip", help="Process a single host, by IP")
    parser.add_argument("-v", "--verbose", action="store_true", help="Print endpoint and payload of every request")
    args = parser.parse_args()

    cfg = load_env()
    hosts = parse_normalized_json(args.input)

    if args.only_ip:
        hosts = [h for h in hosts if h["ip"] == args.only_ip]

    if not hosts:
        print("No hosts to process.")
        return

    state = load_state(cfg["STATE_FILE"])

    session_token = None
    if not args.dry_run:
        check_required_env(cfg)
        session_token = init_legacy_session(cfg)
        print("[+] Legacy API session token obtained.")

    ok = 0
    ko = 0

    try:
        for host in hosts:
            ip = host["ip"]
            payload = build_payload(host, cfg)

            if args.dry_run:
                print(json.dumps(payload, indent=2, ensure_ascii=False))
                continue

            try:
                item_id = state.get(ip, 0)

                if item_id:
                    r = update_item(cfg, session_token, item_id, payload, args.verbose)

                    # If the update fails because the ID no longer exists, recreate it
                    if r.status_code == 404:
                        r = create_item(cfg, session_token, payload, args.verbose)
                        new_id = extract_id_from_response(r)
                        if new_id:
                            state[ip] = new_id
                            save_state(cfg["STATE_FILE"], state)
                else:
                    r = create_item(cfg, session_token, payload, args.verbose)
                    new_id = extract_id_from_response(r)
                    if new_id:
                        state[ip] = new_id
                        save_state(cfg["STATE_FILE"], state)

                body = r.text.strip()

                if r.ok:
                    print(f"[OK] {ip} -> HTTP {r.status_code} -> {body}")
                    ok += 1
                else:
                    print(f"[KO] {ip} -> HTTP {r.status_code} -> {body}")
                    ko += 1

            except Exception as e:
                print(f"[EXC] {ip} -> {e}")
                ko += 1

    finally:
        if session_token:
            kill_legacy_session(cfg, session_token)

    print(f"\nDone. Succeeded: {ok} | Errors: {ko}")
    if ko:
        raise SystemExit(1)


if __name__ == "__main__":
    main()