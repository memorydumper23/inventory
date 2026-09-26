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

    # Percorso relativo dello state file = relativo alla cartella dello script
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
            f"[ERRORE] Configurazione mancante: {', '.join(missing)}. "
            "Copia .env.example in .env e inserisci i tuoi valori."
        )


def encoded_itemtype(cfg: Dict[str, str]) -> str:
    return quote(cfg["GLPI_ITEMTYPE"], safe="")


def init_legacy_session(cfg: Dict[str, str]) -> str:
    """
    Legacy API initSession con Basic Auth + App-Token (opzionale ma consigliato).
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
        print(f"[ERRORE] initSession HTTP {r.status_code}: {r.text.strip()}", file=sys.stderr)

    r.raise_for_status()

    data = r.json()
    session_token = data.get("session_token")
    if not session_token:
        raise RuntimeError(f"Nessun session_token ricevuto da initSession: {data}")

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
    Supporta:
    1) lista diretta di host
    2) {"hosts": [...]}
    3) {"assets": [...]}
    4) {"results": [...]}
    5) {"data": [...]}
    6) {"items": [...]}
    7) {"devices": [...]}
    8) dizionario keyed-by-id / keyed-by-ip
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
            "Formato JSON non supportato. Attesi: lista diretta, "
            "oppure oggetto con chiave hosts/assets/results/data/items/devices, "
            "oppure dizionario keyed-by-id."
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
        raise ValueError("Nessun host valido con IP estratto dal JSON.")

    return out


def compact_ports(host: Dict[str, Any], proto: str) -> str:
    vals = sorted(
        {str(p["port"]) for p in host["ports"] if p.get("proto") == proto},
        key=lambda x: int(x)
    )
    return ",".join(vals)


def compact_services(host: Dict[str, Any]) -> str:
    """
    Formato ibrido:
    - nel dettaglio GLPI: un servizio per riga
    - nella lista GLPI: i \n vengono appiattiti, ma restano i bullet visibili

    Esempio:
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
    Regola richiesta:
    - name = IP
    - solo 3 campi custom text:
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
    Prova a ricavare l'ID da varie forme di risposta della Legacy API.
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
    parser = argparse.ArgumentParser(description="Push Nmap JSON nel custom asset GLPI 'Nmap' via Legacy API")
    parser.add_argument("-i", "--input", required=True, help="File JSON normalizzato")
    parser.add_argument("-f", "--format", choices=["json"], required=True, help="Formato input")
    parser.add_argument("--dry-run", action="store_true", help="Stampa solo i payload, non invia")
    parser.add_argument("--only-ip", help="Processa un solo host per IP")
    parser.add_argument("-v", "--verbose", action="store_true", help="Stampa endpoint e payload di ogni richiesta")
    args = parser.parse_args()

    cfg = load_env()
    hosts = parse_normalized_json(args.input)

    if args.only_ip:
        hosts = [h for h in hosts if h["ip"] == args.only_ip]

    if not hosts:
        print("Nessun host da processare.")
        return

    state = load_state(cfg["STATE_FILE"])

    session_token = None
    if not args.dry_run:
        check_required_env(cfg)
        session_token = init_legacy_session(cfg)
        print("[+] Session token Legacy API ottenuto correttamente.")

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

                    # Se update fallisce perché l'ID non esiste più, ricrea
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

    print(f"\nCompletato. Successi: {ok} | Errori: {ko}")
    if ko:
        raise SystemExit(1)


if __name__ == "__main__":
    main()