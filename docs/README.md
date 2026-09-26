# inventory documentation

For a quick start the main [README](../README.md) is enough. This documentation covers
every component, option and behavior of the pipeline in detail.

| Document | Contents |
|---|---|
| [Architecture](architecture.md) | Components, data flow, generated files, JSON formats, known limitations |
| [Installation](installation.md) | Requirements, preparing NetBox and GLPI, step-by-step installation, upgrade, uninstall |
| [Configuration](configuration.md) | Full reference for `targets.txt`, `netbox.env` and `.env` |
| [Running](running.md) | Manual and scheduled runs, logs, exit codes, duration, partial runs, maintenance |
| [Script reference](script-reference.md) | Arguments, input, output and logic of every script and scan profile |
| [Security](security.md) | Threat model, sudo wrapper, credentials, sensitive data, authorized use |
| [Troubleshooting](troubleshooting.md) | Common errors, their causes and fixes |

## Components at a glance

- **Nmap**: the network scanner. It finds live hosts, open ports and listening
  services with their versions. It is the only component that needs root privileges.
- **NetBox**: the technical source of truth for the network (IPAM/DCIM). The pipeline
  creates or updates an *IP Address* for every host found, with ports and services in
  three custom fields.
- **GLPI**: IT asset management and help desk software. The pipeline creates or
  updates an `Nmap` custom asset for every host, with the same three pieces of data.
- **Ansible**: the automation tool. If configured, the pipeline adds the discovered
  hosts to its `hosts.yml` inventory file.
- **Network inventory**: the overall goal, an always up-to-date list of what is on
  the network and what it exposes.

## Conventions

- The project is installed in `/opt/inventory` and runs as the `inventory` service user.
- `<date>` is the run date in `YYYY-MM-DD` format (for example `2026-09-26`).
- Addresses in the examples belong to the `192.0.2.0/24` documentation block
  (RFC 5737) and do not match any real network.
