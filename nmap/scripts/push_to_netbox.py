#!/usr/bin/env python3
import argparse
import ipaddress
import json
import os
import sys
from typing import List, Dict, Any, Tuple

import requests


USEFUL_SERVICE_NAMES = {
    "ssh",
    "http",
    "https",
    "dns",
    "domain",
    "dhcp",
    "dhcps",
    "dhcpc",
    "ntp",
    "snmp",
    "isakmp",
    "syslog",
    "zeroconf",
    "mdns",
    "upnp",
    "ldap",
    "ldaps",
    "microsoft-ds",
    "netbios-ssn",
    "rpcbind",
    "nfs",
    "msrpc",
    "rdp",
    "winbox",
    "bandwidth-test",
    "sip",
    "sip-tls",
    "ipp",
    "printer",
    "bootps",
    "bootpc",
    "amqp",
}

NOISY_SERVICE_NAMES = {
    "unknown",
    "tcpwrapped",
}


SERVICE_LABELS = {
    "ssh": "SSH",
    "http": "HTTP",
    "https": "HTTPS",
    "dns": "DNS",
    "dhcp": "DHCP",
    "dhcp-client": "DHCP Client",
    "ntp": "NTP",
    "snmp": "SNMP",
    "isakmp": "ISAKMP",
    "syslog": "SYSLOG",
    "zeroconf": "Zeroconf",
    "mdns": "mDNS",
    "upnp": "UPnP",
    "ldap": "LDAP",
    "ldaps": "LDAPS",
    "smb": "SMB",
    "netbios": "NetBIOS",
    "rpcbind": "RPCBind",
    "nfs": "NFS",
    "msrpc": "MSRPC",
    "rdp": "RDP",
    "winbox": "Winbox",
    "bandwidth-test": "Bandwidth Test",
    "sip": "SIP",
    "sip-tls": "SIP-TLS",
    "ipp": "IPP",
    "printer": "Printer",
    "amqp": "AMQP",
}


PRODUCT_LABELS = {
    "nginx": "NGINX",
    "apache httpd": "Apache",
    "openssh": "OpenSSH",
    "mikrotik bandwidth-test server": "MikroTik Bandwidth Test",
    "mikrotik routeros winbox": "MikroTik Winbox",
}


def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


def load_env_file(path: str):
    """
    Carica un file tipo netbox.env se esiste, senza sovrascrivere env già presenti.
    Supporta righe tipo:
      export NAME="value"
      NAME="value"
    """
    if not os.path.isfile(path):
        return

    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue

                if line.startswith("export "):
                    line = line[len("export "):].strip()

                if "=" not in line:
                    continue

                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")

                if key and key not in os.environ:
                    os.environ[key] = value
    except Exception as exc:
        eprint(f"[WARN] Impossibile leggere {path}: {exc}")


def get_env(name: str, required: bool = True, default: str = None) -> str:
    value = os.getenv(name, default)
    if required and (not value or value == "CHANGE_ME"):
        eprint(f"[ERRORE] Variabile ambiente mancante: {name}")
        sys.exit(1)
    return value


def as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return True
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


def build_cidr_address(ip: str) -> str:
    addr = ipaddress.ip_address(ip)
    return f"{ip}/32" if addr.version == 4 else f"{ip}/128"


def normalize_protocol(proto: str) -> str:
    if not proto:
        return "tcp"
    return proto.strip().lower()


def normalize_service_name(name: str) -> str:
    if not name:
        return "unknown"

    name = name.strip().lower()

    mapping = {
        "domain": "dns",
        "dhcps": "dhcp",
        "bootps": "dhcp",
        "dhcpc": "dhcp-client",
        "bootpc": "dhcp-client",
        "microsoft-ds": "smb",
        "netbios-ssn": "netbios",
    }

    return mapping.get(name, name)


def human_service_name(name: str) -> str:
    norm = normalize_service_name(name)
    return SERVICE_LABELS.get(norm, norm.upper())


def normalize_product_name(product: str) -> str:
    if not product:
        return ""
    p = product.strip()
    return PRODUCT_LABELS.get(p.lower(), p)


def service_sort_key(svc: Dict[str, Any]) -> Tuple:
    return (
        svc.get("port", 0),
        normalize_protocol(svc.get("protocol")),
        normalize_service_name(svc.get("name") or "unknown"),
        svc.get("product") or "",
        svc.get("version") or "",
        svc.get("extrainfo") or "",
        svc.get("state") or "",
    )


def deduplicate_services(services: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    unique = []

    for svc in services:
        key = (
            svc.get("port"),
            normalize_protocol(svc.get("protocol")),
            normalize_service_name(svc.get("name") or "unknown"),
            svc.get("product"),
            svc.get("version"),
            svc.get("extrainfo"),
            svc.get("state"),
        )
        if key not in seen:
            seen.add(key)
            unique.append(svc)

    return sorted(unique, key=service_sort_key)


def is_udp_candidate(svc: Dict[str, Any]) -> bool:
    return (
        normalize_protocol(svc.get("protocol")) == "udp"
        and str(svc.get("state") or "").strip().lower() == "open|filtered"
    )


def build_tcp_ports_value(services: List[Dict[str, Any]]) -> str:
    ports = sorted({
        svc.get("port")
        for svc in deduplicate_services(services)
        if normalize_protocol(svc.get("protocol")) == "tcp" and svc.get("port") is not None
    })
    return ", ".join(str(p) for p in ports)


def build_udp_ports_value(services: List[Dict[str, Any]]) -> str:
    """
    Esempi:
      53
      67?
      161?
    """
    items = []
    seen = set()

    for svc in deduplicate_services(services):
        if normalize_protocol(svc.get("protocol")) != "udp":
            continue

        port = svc.get("port")
        state = str(svc.get("state") or "").strip().lower()
        if port is None:
            continue

        key = (port, state)
        if key in seen:
            continue
        seen.add(key)

        suffix = "?" if state == "open|filtered" else ""
        items.append(f"{port}{suffix}")

    return ", ".join(items)


def should_keep_service_in_detail(svc: Dict[str, Any]) -> bool:
    name = normalize_service_name(svc.get("name") or "unknown")
    product = svc.get("product")
    version = svc.get("version")
    extrainfo = svc.get("extrainfo")

    if name in NOISY_SERVICE_NAMES:
        return False

    if product or version or extrainfo:
        return True

    if name in USEFUL_SERVICE_NAMES:
        return True

    return False


def build_detail_line(svc: Dict[str, Any]) -> str:
    """
    Formato:
    SSH (22/tcp) - OpenSSH 9.x

    SNMP (161/udp) - candidate
    """
    service_label = human_service_name(svc.get("name") or "unknown")
    port = svc.get("port")
    proto = normalize_protocol(svc.get("protocol"))

    base = f"{service_label} ({port}/{proto})"

    details_parts = []

    product = normalize_product_name(svc.get("product"))
    version = (svc.get("version") or "").strip()
    extrainfo = (svc.get("extrainfo") or "").strip()

    if product:
        details_parts.append(product)
    if version:
        details_parts.append(version)
    if extrainfo:
        details_parts.append(extrainfo)

    if details_parts:
        return f"{base} - {' '.join(details_parts)}"

    if is_udp_candidate(svc):
        return f"{base} - candidate"

    return base


def build_services_detail_value(services: List[Dict[str, Any]]) -> str:
    """
    Multilinea con una riga vuota tra i servizi.
    """
    lines = []

    for svc in deduplicate_services(services):
        if not should_keep_service_in_detail(svc):
            continue
        lines.append(build_detail_line(svc))

    return "\n\n".join(lines)


def nb_get(session: requests.Session, url: str, params=None) -> Dict[str, Any]:
    r = session.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def nb_post(session: requests.Session, url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    r = session.post(url, json=payload, timeout=30)
    r.raise_for_status()
    return r.json()


def nb_patch(session: requests.Session, url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    r = session.patch(url, json=payload, timeout=30)
    r.raise_for_status()
    return r.json()


def find_ip(session: requests.Session, base_api: str, address: str):
    url = f"{base_api}/ipam/ip-addresses/"
    data = nb_get(session, url, params={"address": address})
    results = data.get("results", [])
    for item in results:
        if item.get("address") == address:
            return item
    return None


def main():
    parser = argparse.ArgumentParser(description="Sincronizza IP address su NetBox")
    parser.add_argument("--input", required=True, help="JSON normalizzato/merged in input")
    args = parser.parse_args()

    # Carica netbox.env se presente
    load_env_file(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "netbox.env"))

    netbox_url = get_env("NETBOX_URL")
    netbox_token = get_env("NETBOX_TOKEN")
    verify_ssl = as_bool(get_env("NETBOX_VERIFY_SSL", required=False, default="true"))

    # Internal name dei custom fields NetBox
    cf_tcp_ports = get_env("NETBOX_CF_TCP_PORTS", required=False, default="porte_tcp")
    cf_udp_ports = get_env("NETBOX_CF_UDP_PORTS", required=False, default="porte_udp")
    cf_services_detail = get_env("NETBOX_CF_SERVICES_DETAIL", required=False, default="servizi_dettaglio")

    base_api = netbox_url.rstrip("/") + "/api"

    session = requests.Session()
    session.verify = verify_ssl

    auth_scheme = "Bearer" if netbox_token.startswith("nbt_") else "Token"

    session.headers.update({
        "Authorization": f"{auth_scheme} {netbox_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    })

    try:
        with open(args.input, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        eprint(f"[ERRORE] Impossibile leggere {args.input}: {exc}")
        sys.exit(1)

    assets = data.get("assets", [])
    errors = 0

    for asset in assets:
        try:
            ip = asset["ip"]
            hostname = asset.get("hostname")
            services = asset.get("services", [])

            address = build_cidr_address(ip)

            tcp_ports_value = build_tcp_ports_value(services)
            udp_ports_value = build_udp_ports_value(services)
            services_detail_value = build_services_detail_value(services)

            payload = {
                "address": address,
                "status": "active",
                "dns_name": hostname or "",
                "description": "Scan di Nmap",
                "custom_fields": {
                    cf_tcp_ports: tcp_ports_value,
                    cf_udp_ports: udp_ports_value,
                    cf_services_detail: services_detail_value,
                }
            }

            existing = find_ip(session, base_api, address)

            if existing:
                detail_url = f"{base_api}/ipam/ip-addresses/{existing['id']}/"
                nb_patch(session, detail_url, payload)
                print(f"[UPDATE] {address}")
            else:
                nb_post(session, f"{base_api}/ipam/ip-addresses/", payload)
                print(f"[CREATE] {address}")

        except requests.exceptions.RequestException as exc:
            eprint(f"[ERRORE] NetBox API per asset {asset}: {exc}")
            errors += 1
        except Exception as exc:
            eprint(f"[ERRORE] Asset non processato {asset}: {exc}")
            errors += 1

    print(f"Completato. Asset: {len(assets)} | Errori: {errors}")
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()