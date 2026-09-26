#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("[ERROR] PyYAML is not installed. Install python3-yaml.", file=sys.stderr)
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
        raise RuntimeError(f"Cannot read {path}: {exc}") from exc

    return sorted(hosts)


def load_yaml(path):
    if not Path(path).exists():
        return {}

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data
    except Exception as exc:
        raise RuntimeError(f"Cannot read YAML {path}: {exc}") from exc


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
        raise RuntimeError(f"Cannot write YAML {path}: {exc}") from exc


def main():
    parser = argparse.ArgumentParser(
        description="Update an Ansible hosts.yml by adding the hosts listed in hosts_up.txt"
    )
    parser.add_argument("--input", required=True, help="Input TXT file (one host per line)")
    parser.add_argument("--inventory", required=True, help="hosts.yml file to update")
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

        # keep the existing hosts and add the discovered ones
        for host in discovered_hosts:
            if host not in data["all"]["hosts"]:
                data["all"]["hosts"][host] = {}

        # sort hosts by IP
        sorted_hosts = dict(sorted(data["all"]["hosts"].items(), key=lambda x: x[0]))
        data["all"]["hosts"] = sorted_hosts

        save_yaml(args.inventory, data)

    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()