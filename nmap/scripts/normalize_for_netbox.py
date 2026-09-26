#!/usr/bin/env python3
import argparse
import json
import sys
import xml.etree.ElementTree as ET


def get_ipv4_from_host(host):
    for addr in host.findall("address"):
        if addr.get("addrtype") == "ipv4":
            return addr.get("addr")
    return None


def is_interesting_state(protocol, state):
    if protocol == "udp":
        return state in {"open", "open|filtered"}
    return state == "open"


def parse_hosts_xml(path):
    hosts = {}

    try:
        tree = ET.parse(path)
        root = tree.getroot()
    except Exception as exc:
        raise RuntimeError(f"Cannot read host discovery XML {path}: {exc}") from exc

    for host in root.findall("host"):
        status = host.find("status")
        if status is None or status.get("state") != "up":
            continue

        ip_addr = get_ipv4_from_host(host)
        if not ip_addr:
            continue

        hostname = None
        hostnames = host.find("hostnames")
        if hostnames is not None:
            hn = hostnames.find("hostname")
            if hn is not None:
                hostname = hn.get("name")

        hosts[ip_addr] = {
            "ip": ip_addr,
            "hostname": hostname,
            "services": []
        }

    return hosts


def merge_service(host_services, new_service):
    """
    If an entry with the same port/protocol already exists, enrich it.
    """
    for svc in host_services:
        if svc.get("port") == new_service.get("port") and svc.get("protocol") == new_service.get("protocol"):
            # State: prefer "open" over "open|filtered"
            old_state = svc.get("state")
            new_state = new_service.get("state")
            if old_state != "open" and new_state:
                svc["state"] = new_state

            for key in ["name", "product", "version", "extrainfo"]:
                if new_service.get(key):
                    svc[key] = new_service.get(key)
            return

    host_services.append(new_service)


def parse_ports_xml(path, hosts):
    try:
        tree = ET.parse(path)
        root = tree.getroot()
    except Exception as exc:
        raise RuntimeError(f"Cannot read port discovery XML {path}: {exc}") from exc

    for host in root.findall("host"):
        status = host.find("status")
        if status is None or status.get("state") != "up":
            continue

        ip_addr = get_ipv4_from_host(host)
        if not ip_addr:
            continue

        if ip_addr not in hosts:
            hosts[ip_addr] = {
                "ip": ip_addr,
                "hostname": None,
                "services": []
            }

        ports = host.find("ports")
        if ports is None:
            continue

        for port in ports.findall("port"):
            protocol = port.get("protocol")
            portid = port.get("portid")
            state_elem = port.find("state")

            if not protocol or not portid or state_elem is None:
                continue

            state = state_elem.get("state")
            if not is_interesting_state(protocol, state):
                continue

            service = port.find("service")

            base_entry = {
                "port": int(portid),
                "protocol": protocol,
                "state": state,
                "name": service.get("name") if service is not None else None,
                "product": None,
                "version": None,
                "extrainfo": None,
            }

            merge_service(hosts[ip_addr]["services"], base_entry)

    return hosts


def parse_services_xml(path, hosts):
    try:
        tree = ET.parse(path)
        root = tree.getroot()
    except Exception as exc:
        raise RuntimeError(f"Cannot read service/version detection XML {path}: {exc}") from exc

    for host in root.findall("host"):
        status = host.find("status")
        if status is None or status.get("state") != "up":
            continue

        ip_addr = get_ipv4_from_host(host)
        if not ip_addr:
            continue

        if ip_addr not in hosts:
            hosts[ip_addr] = {
                "ip": ip_addr,
                "hostname": None,
                "services": []
            }

        ports = host.find("ports")
        if ports is None:
            continue

        for port in ports.findall("port"):
            protocol = port.get("protocol")
            portid = port.get("portid")
            state_elem = port.find("state")

            if not protocol or not portid or state_elem is None:
                continue

            state = state_elem.get("state")
            if not is_interesting_state(protocol, state):
                continue

            service = port.find("service")

            enriched_entry = {
                "port": int(portid),
                "protocol": protocol,
                "state": state,
                "name": service.get("name") if service is not None else None,
                "product": service.get("product") if service is not None else None,
                "version": service.get("version") if service is not None else None,
                "extrainfo": service.get("extrainfo") if service is not None else None,
            }

            merge_service(hosts[ip_addr]["services"], enriched_entry)

    return hosts


def deduplicate_services(services):
    seen = set()
    unique = []

    for svc in services:
        key = (
            svc.get("port"),
            svc.get("protocol"),
            svc.get("state"),
            svc.get("name"),
            svc.get("product"),
            svc.get("version"),
            svc.get("extrainfo"),
        )
        if key not in seen:
            seen.add(key)
            unique.append(svc)

    return sorted(
        unique,
        key=lambda x: (
            x.get("port", 0),
            x.get("protocol") or "",
            x.get("name") or ""
        )
    )


def main():
    parser = argparse.ArgumentParser(description="Normalize Nmap XML into a per-host JSON")
    parser.add_argument("--hosts", required=True, help="Host discovery XML")
    parser.add_argument("--ports", required=True, help="Port discovery XML")
    parser.add_argument("--services", required=True, help="Service/version detection XML")
    parser.add_argument("--output", required=True, help="Output JSON file")
    args = parser.parse_args()

    try:
        hosts = parse_hosts_xml(args.hosts)
        hosts = parse_ports_xml(args.ports, hosts)
        hosts = parse_services_xml(args.services, hosts)

        assets = []
        for ip_addr, data in sorted(hosts.items(), key=lambda x: x[0]):
            data["services"] = deduplicate_services(data["services"])
            assets.append(data)

        output = {"assets": assets}

        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)

    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()