# Configuration

## Overview

| File | Created from | Read by | Permissions |
|---|---|---|---|
| `nmap/targets.txt` | `nmap/targets.txt.example` | `run_inventory.sh` | `644` or stricter |
| `nmap/netbox.env` | `nmap/netbox.env.example` | every bash script (with `source`) and `push_to_netbox.py` | `600`, owned by `inventory` |
| `glpi-nmap-adapter/.env` | `glpi-nmap-adapter/.env.example` | `nmap_to_glpi_nmap_asset.py` | `600`, owned by `inventory` |

None of these files is tracked by git. The scripts refuse to start if a required
credential is missing or still set to `CHANGE_ME`.

## `nmap/targets.txt`

What to scan. Nmap receives it unchanged (from the wrapper, on standard input), so the
Nmap target syntax applies:

```
# headquarters
192.0.2.0/24
# partial range
198.51.100.10-50
# single host
203.0.113.7
# by name: the host name will end up in NetBox (dns_name)
server01.example.internal
```

- One entry per line (spaces also work as separators).
- Comments start with `#`, including at the end of a line.
- Single addresses, CIDR notation, ranges (`198.51.100.10-50`, `192.0.2.1,5,9`) and
  host names are allowed.
- There is no exclusion syntax: to skip some hosts, list only the ranges to include.
- Host names are recorded only for targets written as names: the scans use `-n` and do
  not perform reverse DNS lookups.
- Only scan networks you own or are explicitly authorized to scan.

## `nmap/netbox.env`

Despite its name, it holds all the pipeline options, not just the NetBox ones.

| Variable | Default | Required | Description |
|---|---|---|---|
| `NETBOX_URL` | none | Yes, if the NetBox push is enabled | NetBox base URL, without `/api` (for example `https://netbox.example.com`) |
| `NETBOX_TOKEN` | none | Yes, if the NetBox push is enabled | API token (see [Installation](installation.md#api-token)) |
| `NETBOX_VERIFY_SSL` | `true` | No | TLS certificate verification. `0`, `false`, `no` and `off` disable it: use only temporarily |
| `NETBOX_CF_TCP_PORTS` | `tcp_ports` | No | Name of the custom field for TCP ports |
| `NETBOX_CF_UDP_PORTS` | `udp_ports` | No | Name of the custom field for UDP ports |
| `NETBOX_CF_SERVICES_DETAIL` | `services_detail` | No | Name of the custom field for services |
| `ANSIBLE_INVENTORY_FILE` | empty | No | Path of a `hosts.yml` to update with the hosts found. If empty, the step is skipped |
| `PUSH_TO_NETBOX` | `true` | No | `false` disables the NetBox push |
| `PUSH_TO_GLPI` | `true` | No | `false` disables the GLPI push |
| `GLPI_DIR` | `../glpi-nmap-adapter` relative to `nmap/` | No | GLPI adapter directory, if you moved it |

### Writing rules

- The file is executed by bash (`source`): it is code, and whoever can edit it can run
  commands as the `inventory` user. Keep it with `600` permissions.
- Use the `export NAME="value"` form. Always wrap values in double quotes.
- Do not put comments at the end of a line: when `push_to_netbox.py` runs on its own it
  reads the file with a simple parser that would include them in the value.
- `PUSH_TO_NETBOX` and `PUSH_TO_GLPI` default to `true` when not set: you only need
  to write them to disable a push (`"false"`). Leaving them commented out lets you
  disable them for a single run from the command line (see [Precedence](#precedence)).

### Precedence

Variables already present in the environment win over those in `netbox.env` when
`push_to_netbox.py` runs on its own. When the pipeline starts from
`run_all_inventory.sh`, instead, the file is loaded with `source` and its values win.
This is why `sudo -u inventory env PUSH_TO_GLPI=false /opt/inventory/nmap/run_all_inventory.sh`
disables the GLPI push only if `PUSH_TO_GLPI` is not set in `netbox.env`.

## `glpi-nmap-adapter/.env`

| Variable | Default | Required | Description |
|---|---|---|---|
| `GLPI_BASE_URL` | none | Yes, unless `GLPI_LEGACY_API_URL` is set | GLPI base URL (for example `https://glpi.example.com`) |
| `GLPI_LEGACY_API_URL` | `${GLPI_BASE_URL}/apirest.php` | No | Full URL of the legacy API, if different from the default |
| `GLPI_API_USERNAME` | none | Yes | GLPI user of the pipeline |
| `GLPI_API_PASSWORD` | none | Yes | That user's password |
| `GLPI_LEGACY_APP_TOKEN` | empty | No, but recommended | Application token of the API client. Empty: no `App-Token` header. `CHANGE_ME` is rejected |
| `GLPI_ITEMTYPE` | `Glpi\CustomAsset\NmapAsset` | No | GLPI asset type to write to |
| `FIELD_TCP_KEY` | `tcp_ports` | No | API name of the TCP ports field. In the example: `custom_tcp_ports` |
| `FIELD_UDP_KEY` | `udp_ports` | No | API name of the UDP ports field. In the example: `custom_udp_ports` |
| `FIELD_SERVICES_KEY` | `services` | No | API name of the services field. In the example: `custom_services` |
| `STATE_FILE` | `glpi_nmap_state_legacy.json` | No | IP → GLPI ID state file. A relative path is relative to the script's directory |
| `GLPI_HTTP_TIMEOUT` | `30` | No | HTTP request timeout, in seconds |

The code defaults for the three field names (`tcp_ports`, `udp_ports`, `services`)
differ from those in the example: what you write in `.env` is what counts. To find the
right names see [Installation → Checking the field names](installation.md#checking-the-field-names).

### Where the file is looked up, and precedence

The script looks for `.env` starting from its own directory and walking up to the
parent directories, regardless of the directory it is started from. Variables already
present in the environment win over those in the file.

### Certificates from an internal CA

The virtualenv uses the CA bundle shipped with `requests`, not the system one. If GLPI
uses a certificate issued by an internal CA, add to `.env`:

```
REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
```

after installing the CA in the system (on Debian: copy it to
`/usr/local/share/ca-certificates/` and run `sudo update-ca-certificates`). The NetBox
scripts use the system Python: with the Debian/Ubuntu packages, installing the CA in
the system is enough.

## Settings fixed in the code

Some settings cannot be changed from the configuration files and must be edited in the code.

| Setting | Where | Value |
|---|---|---|
| Scanned UDP ports | `nmap/run_udp_enrichment.sh`, `UDP_PORTS` variable | `53,67,68,69,123,161,500,514,520,1900,5353,5683` |
| Nmap options | `deploy/inventory-nmap` | see [Script reference](script-reference.md#deployinventory-nmap) |
| Wrapper path | `nmap/run_inventory.sh`, `nmap/run_udp_enrichment.sh`, `deploy/sudoers-inventory` | `/usr/local/sbin/inventory-nmap` |
| Lock file | `nmap/run_all_inventory.sh` | `/tmp/run_all_inventory.lock` |
| Status and description of new IPs in NetBox | `nmap/scripts/push_to_netbox.py` | `active`, `Nmap scan` |
| NetBox request timeout | `nmap/scripts/push_to_netbox.py` | 30 seconds |

The default UDP ports:

| Port | Service |
|---|---|
| 53 | DNS |
| 67, 68 | DHCP (server and client) |
| 69 | TFTP |
| 123 | NTP |
| 161 | SNMP |
| 500 | IKE/ISAKMP (IPsec VPN) |
| 514 | Syslog |
| 520 | RIP |
| 1900 | SSDP/UPnP |
| 5353 | mDNS |
| 5683 | CoAP (IoT devices) |

To change them, edit `UDP_PORTS` keeping the format: digits separated by commas, no
spaces. The wrapper rejects any other format. If you change the Nmap options in
`deploy/inventory-nmap`, remember to reinstall it in `/usr/local/sbin/` (see
[Installation → Upgrading](installation.md#upgrading)).

## Full example

`nmap/netbox.env`:

```bash
export NETBOX_URL="https://netbox.example.com"
export NETBOX_TOKEN="<token>"
export NETBOX_VERIFY_SSL="true"

export NETBOX_CF_TCP_PORTS="tcp_ports"
export NETBOX_CF_UDP_PORTS="udp_ports"
export NETBOX_CF_SERVICES_DETAIL="services_detail"

export ANSIBLE_INVENTORY_FILE="/home/inventory/ansible/hosts.yml"

# GLPI not ready yet: NetBox only for now
export PUSH_TO_GLPI="false"
```

`glpi-nmap-adapter/.env`:

```bash
GLPI_BASE_URL=https://glpi.example.com
GLPI_LEGACY_API_URL=
GLPI_API_USERNAME=svc-inventory
GLPI_API_PASSWORD=<password>
GLPI_LEGACY_APP_TOKEN=<application token>
GLPI_ITEMTYPE=Glpi\CustomAsset\NmapAsset
FIELD_TCP_KEY=custom_tcp_ports
FIELD_UDP_KEY=custom_udp_ports
FIELD_SERVICES_KEY=custom_services
STATE_FILE=glpi_nmap_state_legacy.json
GLPI_HTTP_TIMEOUT=30
```
