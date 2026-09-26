# Script reference

All bash scripts use `set -euo pipefail`: a failing command stops the script. The
Python scripts write errors to standard error and exit with code `1`.

## `nmap/run_all_inventory.sh`

Entry point of the pipeline. Takes no arguments.

```bash
sudo -u inventory /opt/inventory/nmap/run_all_inventory.sh
```

**Variables read** (from the environment or `netbox.env`): `PUSH_TO_NETBOX` (default
`true`), `PUSH_TO_GLPI` (default `true`), `GLPI_DIR`. Exports `DATE_TAG` with the start
date, used by every phase.

**Sequence**

1. Creates `logs/` and `work/` if missing.
2. Takes the `/tmp/run_all_inventory.lock` lock with `flock -n`. If another run holds
   it, logs an error and exits with `1`. The lock is released automatically when the
   process ends, even after a crash.
3. Loads `netbox.env` if it exists.
4. Runs `run_inventory.sh` with `INVENTORY_RUN_ALL=1`, which prevents it from sending
   data to NetBox (the push happens once, at step 8, with TCP and UDP data). Its output
   is appended to the main log.
5. If `work/hosts_up_<date>.txt` is empty: no hosts found, exits with `0`.
6. Runs `run_udp_enrichment.sh`.
7. Checks that `work/normalized_assets_merged_<date>.json` exists.
8. If `PUSH_TO_NETBOX` is `true`, runs `scripts/push_to_netbox.py` on the merged JSON;
   the output goes to `logs/netbox_sync_<date>.log`. A failure is logged but does not
   stop the pipeline.
9. If `PUSH_TO_GLPI` is `true`, runs the GLPI adapter from its directory, with the
   Python from `.venv` if it exists or `/usr/bin/python3` otherwise; the output goes to
   `logs/glpi_sync_<date>.log`. Here too, a failure is only logged.
10. Exits with `1` if at least one push failed, with `0` otherwise.

## `nmap/run_inventory.sh`

TCP phases: host discovery, ports, services. Takes no arguments.

**Initial checks**: `/usr/bin/nmap`, `/usr/bin/python3`, the wrapper
`/usr/local/sbin/inventory-nmap`, the required Python scripts and `targets.txt` must
exist. If anything is missing it exits with `1` saying what.

**Variables read**: `DATE_TAG` (default: today's date), `PUSH_TO_NETBOX` (default
`false`), `ANSIBLE_INVENTORY_FILE`, plus the whole of `netbox.env`.
`INVENTORY_RUN_ALL=1`, set by `run_all_inventory.sh`, disables the NetBox push whatever
the value of `PUSH_TO_NETBOX`.

**Sequence**

1. `sudo -n inventory-nmap discovery < targets.txt > scans/hosts_up_<date>.xml`
2. `extract_hosts.py` → `work/hosts_up_<date>.txt`
3. If `ANSIBLE_INVENTORY_FILE` is not empty: `update_ansible_hosts_yml.py` updates the
   Ansible inventory.
4. If there are no hosts: exits with `0`.
5. `sudo -n inventory-nmap tcp-ports < hosts_up.txt > scans/open_ports_<date>.xml`
6. `extract_open_ports.py` → `work/open_ports_<date>.json` (for reference).
7. `build_portspec_from_xml.py --protocol tcp` computes the list of TCP ports open on
   at least one host.
8. If the list is empty: writes `work/normalized_assets_<date>.json` with the hosts and
   no services, and exits with `0`.
9. `sudo -n inventory-nmap tcp-services <ports> < hosts_up.txt > scans/services_<date>.xml`
10. `normalize_for_netbox.py` combines the three XML files → `work/normalized_assets_<date>.json`
11. If `PUSH_TO_NETBOX` is `true` and the script was started on its own: pushes the
    TCP JSON to NetBox.

`sudo -n` makes the command fail immediately if sudo would ask for a password, instead
of hanging: under cron there is nobody to answer.

## `nmap/run_udp_enrichment.sh`

UDP phases and merge. Takes no arguments. Needs the files produced by the TCP phase
with the same `DATE_TAG`: `work/hosts_up_<date>.txt`, `scans/hosts_up_<date>.xml` and
`work/normalized_assets_<date>.json`.

**Sequence**

1. `sudo -n inventory-nmap udp-ports <UDP_PORTS> < hosts_up.txt > scans/open_ports_udp_<date>.xml`
2. `extract_open_ports.py` → `work/open_ports_udp_<date>.json` (for reference).
3. `build_portspec_from_xml.py --protocol udp` computes the candidate UDP ports (`open`
   or `open|filtered`) on at least one host.
4. If there are none: writes an empty `work/normalized_assets_udp_<date>.json`, copies
   the TCP JSON to `work/normalized_assets_merged_<date>.json` and exits with `0`.
5. `sudo -n inventory-nmap udp-services <ports> < hosts_up.txt > scans/services_udp_<date>.xml`
6. `normalize_for_netbox.py` → `work/normalized_assets_udp_<date>.json`
7. `merge_assets_json.py` merges TCP and UDP → `work/normalized_assets_merged_<date>.json`

## `deploy/inventory-nmap`

Wrapper run as root through sudo. It is the only command the sudoers rule grants to
the service user.

```bash
sudo inventory-nmap <profile> [ports] < targets > result.xml
```

**Safeguards**

- Clean environment: fixed `PATH`, `HOME=/root`, `NMAPDIR` removed, so Nmap only uses
  its own system files.
- Targets read from standard input (`-iL -`) and XML written to standard output
  (`-oX -`): Nmap opens no files.
- Profiles without ports reject any argument. Where ports are expected, they must
  match `^[0-9]{1,5}(,[0-9]{1,5})*$`: digits separated by commas only, no spaces,
  dashes or options.
- Any unknown profile or invalid argument ends with code `2` and a message on standard
  error, before Nmap is started.

**Profiles**

| Profile | Argument | Command run |
|---|---|---|
| `discovery` | none | `nmap -PR -sn -n -iL - -oX -` |
| `tcp-ports` | none | `nmap -sS -Pn -n -p- --host-timeout 10m --min-hostgroup 4 --max-hostgroup 10 --min-rate 5000 -iL - -oX -` |
| `tcp-services` | ports | `nmap -sV -Pn -n --version-light -p <ports> -iL - -oX -` |
| `udp-ports` | ports | `nmap -sU -Pn -n -T4 --max-retries 2 -p <ports> -iL - -oX -` |
| `udp-services` | ports | `nmap -sU -sV -Pn -n -T4 --version-light --max-retries 1 -p <ports> -iL - -oX -` |

**What the options do**

| Option | Effect |
|---|---|
| `-PR` | Host discovery via ARP on directly connected subnets. On remote subnets Nmap uses the standard probes: ICMP echo, TCP SYN to 443, TCP ACK to 80, ICMP timestamp |
| `-sn` | Host discovery only, no port scan |
| `-n` | No DNS resolution |
| `-Pn` | Skip host discovery and treat every target as up (they were already found in the first phase) |
| `-sS` | TCP SYN ("half-open") scan: does not complete the connection |
| `-p-` | All ports from 1 to 65535 |
| `-p <ports>` | Only the listed ports |
| `--host-timeout 10m` | Give up on a host after 10 minutes; the host stays in the results but without ports |
| `--min-hostgroup 4 --max-hostgroup 10` | Scan 4 to 10 hosts in parallel |
| `--min-rate 5000` | Send at least 5,000 packets per second across the whole scan |
| `-sV` | Identify the service and version listening on each port |
| `--version-light` | Light detection (intensity 2 instead of 7): faster, identifies fewer rare services |
| `-sU` | UDP scan |
| `-T4` | Aggressive timing, suited to fast and reliable networks |
| `--max-retries N` | At most N retransmissions per probe |
| `-iL -` | Read the targets from standard input |
| `-oX -` | Write the result as XML to standard output (the normal text output is suppressed) |

## `deploy/sudoers-inventory`

Rule to install as `/etc/sudoers.d/inventory`:

```
Defaults!/usr/local/sbin/inventory-nmap !requiretty
inventory ALL=(root) NOPASSWD: /usr/local/sbin/inventory-nmap
```

The first line allows use from cron even on distributions that require a terminal for
sudo (`requiretty`). The second grants the `inventory` user, without a password, the
wrapper and nothing else. Argument validation lives in the wrapper rather than in the
rule, for the reason explained in [Security](security.md#why-a-wrapper-and-not-a-sudo-rule-on-nmap).

## Python scripts in `nmap/scripts/`

They run with `/usr/bin/python3`.

### `scripts/extract_hosts.py`

```bash
extract_hosts.py --input <host discovery xml> --output <txt file>
```

Reads the hosts with state `up` and takes their first IPv4 address. Writes one IP per
line, without duplicates, sorted as text.

### `scripts/extract_open_ports.py`

```bash
extract_open_ports.py --input <ports xml> --output <json file>
```

Produces `{"assets": [{"ip": ..., "ports": [{"port", "protocol", "state", "service"}]}]}`
with the relevant ports: `open` for TCP, `open` or `open|filtered` for UDP. Hosts
without ports are included too. In the pipeline the result is kept for reference only.

### `scripts/build_portspec_from_xml.py`

```bash
build_portspec_from_xml.py --input <ports xml> [--protocol tcp|udp|both]
```

Prints to standard output the relevant ports found on any host in the file, sorted and
separated by commas (`22,80,443`). With `--protocol both` (the default) it prints
`T:22,80,U:53,161`. If there are no ports it prints an empty line.

### `scripts/normalize_for_netbox.py`

```bash
normalize_for_netbox.py --hosts <host discovery xml> --ports <ports xml> \
  --services <services xml> --output <json file>
```

Builds the [normalized JSON](architecture.md#normalized-json) from three XML files:

1. from the host discovery it takes the `up` hosts with IPv4 and the host name, if any;
2. from the port scan it adds the relevant ports with the service name;
3. from the service scan it adds product, version and extra information.

A host present in the scans but not in the host discovery is added without a host
name. Entries with the same port and protocol are merged: `open` wins over
`open|filtered`, and non-empty fields from the later scan replace the earlier ones.
Despite its name, the result is used for GLPI too.

### `scripts/merge_assets_json.py`

```bash
merge_assets_json.py --tcp <tcp json> --udp <udp json> --output <json file>
```

Merges two normalized JSON files by IP, with the same service merge rule. The host
name comes from the TCP JSON, or from the UDP one if the former has none.

### `scripts/push_to_netbox.py`

```bash
push_to_netbox.py --input <normalized json>
```

**Configuration**: loads `nmap/netbox.env` without overriding variables already set in
the environment. Requires `NETBOX_URL` and `NETBOX_TOKEN` (not empty and not
`CHANGE_ME`), otherwise exits with `1`.

**Authentication**: `Authorization: Bearer <token>` header for tokens starting with
`nbt_`, `Authorization: Token <token>` for the others.

**For every host in the JSON**:

1. Computes the `IP/32` address (`IP/128` for IPv6).
2. Looks up an IP Address in NetBox with exactly that address:
   `GET /api/ipam/ip-addresses/?address=<ip>/32`.
3. If it does not exist, creates it (`POST`) with address, status, description,
   custom fields and, if the host has a host name, `dns_name`:

   ```json
   {
     "address": "192.0.2.10/32",
     "status": "active",
     "description": "Nmap scan",
     "custom_fields": {
       "tcp_ports": "22, 80",
       "udp_ports": "161?",
       "services_detail": "SSH (22/tcp) - OpenSSH 9.x protocol 2.0\n\nHTTP (80/tcp) - NGINX\n\nSNMP (161/udp) - candidate"
     }
   }
   ```

   If it exists, updates it (`PATCH`) sending only the custom fields, so status,
   description and DNS name curated by hand stay unchanged:

   ```json
   {
     "custom_fields": {
       "tcp_ports": "22, 80",
       "udp_ports": "161?",
       "services_detail": "SSH (22/tcp) - OpenSSH 9.x protocol 2.0\n\nHTTP (80/tcp) - NGINX\n\nSNMP (161/udp) - candidate"
     }
   }
   ```

4. Prints `[UPDATE] <address>` or `[CREATE] <address>`. An error on a host is logged
   and the script moves on to the next one.

At the end it prints `Done. Assets: N | Errors: N` and exits with `1` if there were errors.

**Formatting rules**

- `tcp_ports`: TCP ports in numeric order, separated by a comma and a space.
- `udp_ports`: UDP ports in numeric order; `open|filtered` ones get a trailing `?`.
- `services_detail`: one service per line, with a blank line between services.
  Format `LABEL (port/protocol) - product version info`. Without details only
  `LABEL (port/protocol)` is shown, or `- candidate` for `open|filtered` UDP ports.

**Which services appear in `services_detail`**

1. Names are normalized: `domain` → `dns`; `dhcps` and `bootps` → `dhcp`;
   `dhcpc` and `bootpc` → `dhcp-client`; `microsoft-ds` → `smb`; `netbios-ssn` → `netbios`.
2. `unknown` and `tcpwrapped` are always excluded.
3. A service with product, version or extra information is always included.
4. Without details, it is included only if its normalized name is one of: `ssh`,
   `http`, `https`, `dns`, `dhcp`, `dhcp-client`, `ntp`, `snmp`, `isakmp`, `syslog`,
   `zeroconf`, `mdns`, `upnp`, `ldap`, `ldaps`, `smb`, `netbios`, `rpcbind`, `nfs`,
   `msrpc`, `rdp`, `winbox`, `bandwidth-test`, `sip`, `sip-tls`, `ipp`, `printer`, `amqp`.

Ports left out of the detail still appear in `tcp_ports` and `udp_ports`.

**Labels**: known names become readable labels (`SSH`, `HTTP`, `DNS`, `DHCP Client`,
`SMB`, `NetBIOS`, `mDNS`, `UPnP`, `Winbox`…); the others are upper-cased. Some products
are normalized: `nginx` → `NGINX`, `Apache httpd` → `Apache`,
`MikroTik bandwidth-test server` → `MikroTik Bandwidth Test`,
`MikroTik RouterOS Winbox` → `MikroTik Winbox`.

### `scripts/update_ansible_hosts_yml.py`

```bash
update_ansible_hosts_yml.py --input <txt file, one host per line> --inventory <hosts.yml>
```

Creates the file if it does not exist. Ensures the `all.vars` and `all.hosts`
structure, adds under `all.hosts` every host not yet present and sorts the hosts. It
never removes hosts and does not touch existing variables and groups. The file is
rewritten in full with PyYAML: comments are lost. Requires PyYAML (`python3-yaml`).

## `glpi-nmap-adapter/nmap_to_glpi_nmap_asset.py`

```bash
nmap_to_glpi_nmap_asset.py -i <json> -f json [--dry-run] [--only-ip IP] [-v]
```

| Argument | Required | Effect |
|---|---|---|
| `-i`, `--input` | Yes | JSON file to push |
| `-f`, `--format` | Yes | Input format; the only accepted value is `json` |
| `--dry-run` | No | Prints the data that would be sent without contacting GLPI. Needs no credentials and does not change the state file |
| `--only-ip IP` | No | Processes only the host with that IP; if it is not there, exits without doing anything |
| `-v`, `--verbose` | No | Prints endpoint and data of every create or update request |

**Accepted input**: besides the pipeline's normalized JSON, the script accepts a list
of hosts, an object with the list under `hosts`, `assets`, `results`, `data`, `items`
or `devices`, or a dictionary of hosts. For every host it looks for the IP in the
`ip`, `ipv4`, `address`, `primary_ip`, `ip_address` fields (or `network.ip`) and for the
ports in `ports`, `open_ports` or `services`. Hosts without an IP are skipped; if none
is left the script ends with an error.

**Data sent for every host**

```json
{
  "name": "192.0.2.10",
  "custom_tcp_ports": "22,80",
  "custom_udp_ports": "161",
  "custom_services": "• 22/ssh [OpenSSH 9.x protocol 2.0]\n• 80/http [nginx]\n• 161/snmp"
}
```

The names of the three fields are those in `FIELD_TCP_KEY`, `FIELD_UDP_KEY` and
`FIELD_SERVICES_KEY`. Ports are in numeric order, separated by commas without spaces.
The services field has one line per port, with `unknown` when the service was not identified.

**Sequence**

1. Reads the configuration (see [Configuration](configuration.md#glpi-nmap-adapterenv))
   and the JSON file.
2. Except in `--dry-run`: checks the credentials and opens a session
   (`GET /initSession` with HTTP Basic authentication and an `App-Token` header). If the
   login fails it prints `[ERROR] initSession HTTP <code>: <GLPI response>` and exits
   with `1`.
3. For every host:
   - if the state file already has an ID for that IP, updates the asset
     (`PUT /<itemtype>/<id>`); if GLPI answers 404 (the asset no longer exists), it
     creates a new one;
   - otherwise it creates the asset (`POST /<itemtype>`);
   - after every creation it saves the new ID in the state file;
   - prints `[OK] <ip> -> HTTP <code> -> <response>` or `[KO] ...`; an exception prints
     `[EXC] <ip> -> <error>` and the script moves on to the next host.
4. Closes the session (`GET /killSession`), even after errors.
5. Prints `Done. Succeeded: N | Errors: N` and exits with `1` if there were errors.

Requests use `{"input": {...}}` as the body, the Legacy API format.
