# Installation

## Requirements

### System

| Requirement | Notes |
|---|---|
| Linux with `bash`, `sudo`, `flock` (util-linux) and `git` | Tested on Debian 12 (sudo 1.9.13, Nmap 7.93, Python 3.11) |
| Nmap at `/usr/bin/nmap` | The distribution package; the wrapper uses this path |
| System Python 3 at `/usr/bin/python3` with `requests` and `PyYAML` | Used by the scripts in `nmap/scripts/` |
| Python 3.10 or later for the GLPI virtualenv | Required by `requests` 2.34 and `python-dotenv` 1.2. Debian 12+ and Ubuntu 22.04+ are fine |

### Network

- The server running the pipeline must reach the subnets to scan without firewalls
  filtering the scan traffic, otherwise the results will be incomplete.
- On directly connected subnets (same network segment) hosts are found via ARP, the
  most reliable method. On subnets behind a router, Nmap uses ICMP echo, TCP SYN to
  port 443, TCP ACK to port 80 and ICMP timestamp instead: a host that answers none of
  these probes is not detected.
- HTTPS access to the NetBox and GLPI APIs, if used.

## Preparing NetBox

Skip this section if you do not use NetBox (`PUSH_TO_NETBOX="false"`).

### Custom fields

Create three custom fields on the **IPAM › IP Address** object type. The names below
are the defaults: if you use different ones, set them in `netbox.env`
(`NETBOX_CF_TCP_PORTS`, `NETBOX_CF_UDP_PORTS`, `NETBOX_CF_SERVICES_DETAIL`).

| Name | Recommended type | Contents |
|---|---|---|
| `tcp_ports` | Text | Open TCP ports, for example `22, 80, 443` |
| `udp_ports` | Text | Open or candidate UDP ports, for example `53, 161?` |
| `services_detail` | Text (long) | One service per line, with product and version |

### API token

Create a token for a user dedicated to the pipeline. The user must be able to view,
add and change IP Addresses (`ipam.view_ipaddress`, `ipam.add_ipaddress`,
`ipam.change_ipaddress`) and the token must have write access enabled. No other
permissions are needed. The script detects the token type automatically: new-style
tokens (prefix `nbt_`) are sent with the `Bearer` scheme, classic ones with the `Token`
scheme.

## Preparing GLPI

Skip this section if you do not use GLPI (`PUSH_TO_GLPI="false"`). Menu names may vary
with the GLPI version and interface language.

### Custom asset

1. In GLPI 11, create a custom asset definition with the system name `Nmap`. GLPI
   exposes it as the `Glpi\CustomAsset\NmapAsset` type, the default value of
   `GLPI_ITEMTYPE`.
2. Add three text custom fields: TCP ports, UDP ports and services. Use a multi-line
   field for the services: it holds one service per line.
3. Give the API user's profile read, create and update rights on this asset type.

### Legacy API

1. In the API settings (Setup › General › API), enable the legacy REST API and login
   with credentials (user name and password).
2. Create an API client and copy its *application token* into `GLPI_LEGACY_APP_TOKEN`.
   Restrict the client to the IP address of the server running the pipeline.
3. Create a GLPI user dedicated to the pipeline, with the profile from the previous step.

### Checking the field names

The values of `FIELD_TCP_KEY`, `FIELD_UDP_KEY` and `FIELD_SERVICES_KEY` must match the
names under which the API exposes the fields exactly. The safest way to find them is to
create a test `Nmap` asset by hand, fill in its fields and read it through the API:

```bash
# 1. open a session (curl asks for the password, so it does not end up in the shell history)
curl -s -u api-user -H "App-Token: <application token>" \
  https://glpi.example.com/apirest.php/initSession
# response: {"session_token":"..."}

# 2. read the test asset (replace <session token> and <id>)
curl -s -H "Session-Token: <session token>" -H "App-Token: <application token>" \
  "https://glpi.example.com/apirest.php/Glpi%5CCustomAsset%5CNmapAsset/<id>"

# 3. close the session
curl -s -H "Session-Token: <session token>" -H "App-Token: <application token>" \
  https://glpi.example.com/apirest.php/killSession
```

In the response to step 2, look for the fields holding the values you entered: their
names go into `.env` (in the provided example they are `custom_tcp_ports`,
`custom_udp_ports` and `custom_services`).

## Step-by-step installation

Commands with `sudo` are run by an administrator; those marked "as the `inventory`
user" with `sudo -iu inventory`, or by prefixing them with `sudo -u inventory`.

### 1. Packages

```bash
# Debian/Ubuntu
sudo apt install git nmap python3-requests python3-yaml python3-venv
```

On recent Debian and Ubuntu releases `pip install` into the system Python is blocked
(PEP 668), which is why `requests` and `PyYAML` come from the distribution packages.
On other distributions you can install them for the service user, after step 2:

```bash
sudo -u inventory python3 -m pip install --user -r /opt/inventory/nmap/requirements.txt
```

### 2. Service user and code

```bash
sudo useradd --system --create-home --shell /bin/bash inventory
sudo git clone https://github.com/memorydumper23/inventory.git /opt/inventory
sudo chown -R inventory: /opt/inventory
```

The `inventory` user has no privileges: it will only be able to run the wrapper from
step 4 as root.

### 3. Configuration

As the `inventory` user, from `/opt/inventory`:

```bash
cp nmap/targets.txt.example nmap/targets.txt
cp nmap/netbox.env.example nmap/netbox.env && chmod 600 nmap/netbox.env
cp glpi-nmap-adapter/.env.example glpi-nmap-adapter/.env && chmod 600 glpi-nmap-adapter/.env
```

Then fill in the three files following [Configuration](configuration.md).

### 4. Wrapper and sudo rule

As an administrator, in `/opt/inventory`:

```bash
# the wrapper must be owned by root and live outside the project directory:
# if the inventory user could modify it, it would get root
sudo install -o root -g root -m 0755 deploy/inventory-nmap /usr/local/sbin/inventory-nmap

# if the service user is not called "inventory", fix the last line of the file
sudo visudo -cf deploy/sudoers-inventory
sudo install -o root -g root -m 0440 deploy/sudoers-inventory /etc/sudoers.d/inventory
```

`visudo -cf` checks the syntax before installing: a broken sudoers file in
`/etc/sudoers.d/` can lock `sudo` for the whole system.

### 5. GLPI adapter virtualenv

As the `inventory` user:

```bash
cd /opt/inventory/glpi-nmap-adapter
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

`run_all_inventory.sh` uses this virtualenv if it exists, otherwise it falls back to
the system Python (which then needs `requests` and `python-dotenv`).

### 6. First run without pushes

Run the pipeline with both pushes disabled and check the results before writing to
NetBox and GLPI:

```bash
sudo -u inventory env PUSH_TO_NETBOX=false PUSH_TO_GLPI=false \
  /opt/inventory/nmap/run_all_inventory.sh
```

Variables passed this way only apply if the `PUSH_TO_*` lines in `netbox.env` are
commented out: the values in the file take precedence.

Then look at `nmap/work/normalized_assets_merged_<date>.json` and simulate the GLPI push:

```bash
cd /opt/inventory/glpi-nmap-adapter
sudo -u inventory .venv/bin/python nmap_to_glpi_nmap_asset.py \
  -i ../nmap/work/normalized_assets_merged_$(date +%F).json -f json --dry-run
```

The NetBox push has no simulation mode. To try it on a single host, build a reduced
JSON and push it by hand:

```bash
cd /opt/inventory/nmap
sudo -u inventory python3 -c '
import json, sys
d = json.load(open(sys.argv[1]))
d["assets"] = [a for a in d["assets"] if a["ip"] == sys.argv[2]]
json.dump(d, open("/tmp/one-host.json", "w"))
' work/normalized_assets_merged_$(date +%F).json 192.0.2.10
sudo -u inventory python3 scripts/push_to_netbox.py --input /tmp/one-host.json
```

### 7. Full run

```bash
sudo -u inventory /opt/inventory/nmap/run_all_inventory.sh
```

### 8. Scheduling

See [Running → Scheduled runs](running.md#scheduled-runs-cron).

## Checking the installation

```bash
# only /usr/local/sbin/inventory-nmap must be listed
sudo -l -U inventory

# wrapper and rule must be owned by root and not writable by others
ls -l /usr/local/sbin/inventory-nmap /etc/sudoers.d/inventory

# the wrapper works: it must print the beginning of an XML document
echo 127.0.0.1 | sudo -u inventory sudo -n /usr/local/sbin/inventory-nmap discovery | head -3

# running nmap directly must be refused ("a password is required")
sudo -u inventory sudo -n /usr/bin/nmap --version

# git must not see any new files: configuration and results are excluded
sudo -u inventory git -C /opt/inventory status --short
```

## Upgrading

```bash
# 1. fetch the new version
sudo -u inventory git -C /opt/inventory pull

# 2. if the wrapper changed, review it before installing it: it runs as root
sudo diff /usr/local/sbin/inventory-nmap /opt/inventory/deploy/inventory-nmap
sudo install -o root -g root -m 0755 /opt/inventory/deploy/inventory-nmap /usr/local/sbin/inventory-nmap

# 3. if the GLPI adapter dependencies changed
sudo -u inventory /opt/inventory/glpi-nmap-adapter/.venv/bin/pip install \
  -r /opt/inventory/glpi-nmap-adapter/requirements.txt
```

The local configuration files (`targets.txt`, `netbox.env`, `.env`) are excluded from
git and are not touched by an upgrade. Do compare the updated `.example` files with
yours, though, to spot any new options.

### Upgrading from a version with Italian NetBox field names

Earlier versions used `porte_tcp`, `porte_udp` and `servizi_dettaglio` as default names
for the NetBox custom fields. If your NetBox uses those names, set them explicitly in
`netbox.env`:

```bash
export NETBOX_CF_TCP_PORTS="porte_tcp"
export NETBOX_CF_UDP_PORTS="porte_udp"
export NETBOX_CF_SERVICES_DETAIL="servizi_dettaglio"
```

or rename the custom fields in NetBox to `tcp_ports`, `udp_ports` and `services_detail`.

## Migrating from a version with direct `sudo nmap`

Earlier versions called `sudo /usr/bin/nmap` and required a `NOPASSWD: /usr/bin/nmap` rule.

1. Remove that rule: it is equivalent to giving the user root (see [Security](security.md)).
2. Install the wrapper and the new rule (step 4).
3. Make the service user the owner of the old results, which Nmap had written as root:
   `sudo chown -R inventory: /opt/inventory/nmap/scans`.

## Uninstalling

```bash
sudo crontab -u inventory -r          # careful: removes the user's whole crontab
sudo rm /etc/sudoers.d/inventory /usr/local/sbin/inventory-nmap
sudo rm -rf /opt/inventory            # also deletes configuration, scans and logs
sudo userdel -r inventory
```

Data already written to NetBox, GLPI and the Ansible inventory stays where it is.
Revoke the NetBox token, the GLPI API user and the application token used by the pipeline.
