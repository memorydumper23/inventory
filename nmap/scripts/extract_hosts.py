#!/usr/bin/env python3
import argparse
import sys
import xml.etree.ElementTree as ET


def get_ipv4(host):
    for addr in host.findall("address"):
        if addr.get("addrtype") == "ipv4":
            return addr.get("addr")
    return None


def main():
    parser = argparse.ArgumentParser(description="Estrae host up da XML Nmap")
    parser.add_argument("--input", required=True, help="File XML Nmap in input")
    parser.add_argument("--output", required=True, help="File TXT output (un IP per riga)")
    args = parser.parse_args()

    try:
        tree = ET.parse(args.input)
        root = tree.getroot()
    except Exception as exc:
        print(f"[ERRORE] Impossibile leggere XML {args.input}: {exc}", file=sys.stderr)
        sys.exit(1)

    hosts_found = set()

    for host in root.findall("host"):
        status = host.find("status")
        if status is None or status.get("state") != "up":
            continue

        ip_addr = get_ipv4(host)
        if ip_addr:
            hosts_found.add(ip_addr)

    try:
        with open(args.output, "w", encoding="utf-8") as f:
            for ip in sorted(hosts_found):
                f.write(ip + "\n")
    except Exception as exc:
        print(f"[ERRORE] Impossibile scrivere {args.output}: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()