#!/usr/bin/env python3
import argparse
import json
import sys


def load_assets(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("assets", [])
    except Exception as exc:
        raise RuntimeError(f"Impossibile leggere {path}: {exc}") from exc


def merge_service(host_services, new_service):
    for svc in host_services:
        if svc.get("port") == new_service.get("port") and svc.get("protocol") == new_service.get("protocol"):
            # Preferisci "open" a "open|filtered" se disponibile
            old_state = svc.get("state")
            new_state = new_service.get("state")
            if old_state != "open" and new_state:
                svc["state"] = new_state

            for key in ["name", "product", "version", "extrainfo"]:
                if new_service.get(key):
                    svc[key] = new_service.get(key)
            return
    host_services.append(new_service)


def main():
    parser = argparse.ArgumentParser(description="Merge di asset TCP e UDP")
    parser.add_argument("--tcp", required=True, help="JSON normalized TCP")
    parser.add_argument("--udp", required=True, help="JSON normalized UDP")
    parser.add_argument("--output", required=True, help="JSON merged output")
    args = parser.parse_args()

    try:
        tcp_assets = load_assets(args.tcp)
        udp_assets = load_assets(args.udp)
    except Exception as exc:
        print(f"[ERRORE] {exc}", file=sys.stderr)
        sys.exit(1)

    merged = {}

    for asset in tcp_assets:
        ip = asset.get("ip")
        if not ip:
            continue

        merged[ip] = {
            "ip": ip,
            "hostname": asset.get("hostname"),
            "services": list(asset.get("services", [])),
        }

    for asset in udp_assets:
        ip = asset.get("ip")
        if not ip:
            continue

        if ip not in merged:
            merged[ip] = {
                "ip": ip,
                "hostname": asset.get("hostname"),
                "services": [],
            }

        if not merged[ip].get("hostname") and asset.get("hostname"):
            merged[ip]["hostname"] = asset.get("hostname")

        for svc in asset.get("services", []):
            merge_service(merged[ip]["services"], svc)

    for ip, asset in merged.items():
        asset["services"] = sorted(
            asset["services"],
            key=lambda s: (
                s.get("port", 0),
                s.get("protocol") or "",
                s.get("name") or "",
            ),
        )

    result = {
        "assets": sorted(merged.values(), key=lambda x: x["ip"])
    }

    try:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
    except Exception as exc:
        print(f"[ERRORE] Impossibile scrivere {args.output}: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()