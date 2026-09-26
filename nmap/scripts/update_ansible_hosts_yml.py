#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("[ERRORE] PyYAML non installato. Installa python3-yaml.", file=sys.stderr)
    sys.exit(1)


def read_hosts_txt(path):
    hosts = []
    seen = set()

    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                host = line.strip()
                if not host:
                    continue
                if host not in seen:
                    seen.add(host)
                    hosts.append(host)
    except Exception as exc:
        raise RuntimeError(f"Impossibile leggere {path}: {exc}") from exc

    return sorted(hosts)


def load_yaml(path):
    if not Path(path).exists():
        return {}

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data
    except Exception as exc:
        raise RuntimeError(f"Impossibile leggere YAML {path}: {exc}") from exc


def save_yaml(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(
                data,
                f,
                sort_keys=False,
                default_flow_style=False,
                allow_unicode=True
            )
    except Exception as exc:
        raise RuntimeError(f"Impossibile scrivere YAML {path}: {exc}") from exc


def main():
    parser = argparse.ArgumentParser(
        description="Aggiorna un hosts.yml Ansible aggiungendo gli host da hosts_up.txt"
    )
    parser.add_argument("--input", required=True, help="File TXT input (un host per riga)")
    parser.add_argument("--inventory", required=True, help="File hosts.yml da aggiornare")
    args = parser.parse_args()

    try:
        discovered_hosts = read_hosts_txt(args.input)
        data = load_yaml(args.inventory)

        if "all" not in data or not isinstance(data["all"], dict):
            data["all"] = {}

        if "vars" not in data["all"] or not isinstance(data["all"]["vars"], dict):
            data["all"]["vars"] = {}

        if "hosts" not in data["all"] or not isinstance(data["all"]["hosts"], dict):
            data["all"]["hosts"] = {}

        # preserva gli host già presenti e aggiunge quelli scoperti
        for host in discovered_hosts:
            if host not in data["all"]["hosts"]:
                data["all"]["hosts"][host] = {}

        # opzionale: riordino host per IP
        sorted_hosts = dict(sorted(data["all"]["hosts"].items(), key=lambda x: x[0]))
        data["all"]["hosts"] = sorted_hosts

        save_yaml(args.inventory, data)

    except Exception as exc:
        print(f"[ERRORE] {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()