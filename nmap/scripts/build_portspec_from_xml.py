#!/usr/bin/env python3
import argparse
import sys
import xml.etree.ElementTree as ET


def is_interesting_state(protocol, state):
    if protocol == "udp":
        return state in {"open", "open|filtered"}
    return state == "open"


def main():
    parser = argparse.ArgumentParser(
        description="Costruisce una portspec Nmap da un XML di open ports"
    )
    parser.add_argument("--input", required=True, help="File XML Nmap in input")
    parser.add_argument(
        "--protocol",
        choices=["tcp", "udp", "both"],
        default="both",
        help="Protocollo da includere nella portspec"
    )
    args = parser.parse_args()

    try:
        tree = ET.parse(args.input)
        root = tree.getroot()
    except Exception as exc:
        print(f"[ERRORE] Impossibile leggere XML {args.input}: {exc}", file=sys.stderr)
        sys.exit(1)

    tcp_ports = set()
    udp_ports = set()

    for host in root.findall("host"):
        ports = host.find("ports")
        if ports is None:
            continue

        for port in ports.findall("port"):
            protocol = port.get("protocol")
            portid = port.get("portid")

            if not protocol or not portid:
                continue

            state_elem = port.find("state")
            if state_elem is None:
                continue

            state = state_elem.get("state")
            if not is_interesting_state(protocol, state):
                continue

            try:
                portnum = int(portid)
            except ValueError:
                continue

            if protocol == "tcp":
                tcp_ports.add(portnum)
            elif protocol == "udp":
                udp_ports.add(portnum)

    parts = []

    if args.protocol in ("tcp", "both") and tcp_ports:
        if args.protocol == "tcp":
            print(",".join(str(p) for p in sorted(tcp_ports)))
            return
        parts.append("T:" + ",".join(str(p) for p in sorted(tcp_ports)))

    if args.protocol in ("udp", "both") and udp_ports:
        if args.protocol == "udp":
            print(",".join(str(p) for p in sorted(udp_ports)))
            return
        parts.append("U:" + ",".join(str(p) for p in sorted(udp_ports)))

    print(",".join(parts))


if __name__ == "__main__":
    main()