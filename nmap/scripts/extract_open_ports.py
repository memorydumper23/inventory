#!/usr/bin/env python3
import argparse
import json
import sys
import xml.etree.ElementTree as ET


def get_ipv4(host):
    for addr in host.findall("address"):
        if addr.get("addrtype") == "ipv4":
            return addr.get("addr")
    return None


def is_interesting_state(protocol, state):
    if protocol == "udp":
        return state in {"open", "open|filtered"}
    return state == "open"


def main():
    parser = argparse.ArgumentParser(description="Estrae porte candidate da XML Nmap")
    parser.add_argument("--input", required=True, help="File XML Nmap in input")
    parser.add_argument("--output", required=True, help="File JSON output")
    args = parser.parse_args()

    try:
        tree = ET.parse(args.input)
        root = tree.getroot()
    except Exception as exc:
        print(f"[ERRORE] Impossibile leggere XML {args.input}: {exc}", file=sys.stderr)
        sys.exit(1)

    result = {
        "assets": []
    }

    for host in root.findall("host"):
        status = host.find("status")
        if status is None or status.get("state") != "up":
            continue

        ip_addr = get_ipv4(host)
        if not ip_addr:
            continue

        ports_data = []
        ports = host.find("ports")
        if ports is not None:
            for port in ports.findall("port"):
                protocol = port.get("protocol")
                state_elem = port.find("state")

                if state_elem is None:
                    continue

                state = state_elem.get("state")
                if not is_interesting_state(protocol, state):
                    continue

                service = port.find("service")

                item = {
                    "port": int(port.get("portid")),
                    "protocol": protocol,
                    "state": state,
                    "service": service.get("name") if service is not None else None
                }
                ports_data.append(item)

        result["assets"].append({
            "ip": ip_addr,
            "ports": sorted(
                ports_data,
                key=lambda x: (x["port"], x["protocol"] or "")
            )
        })

    try:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
    except Exception as exc:
        print(f"[ERRORE] Impossibile scrivere JSON {args.output}: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()