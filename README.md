# inventory

Nmap-based network inventory pipeline: it discovers the hosts of one or more subnets,
detects TCP/UDP ports and services, and syncs the results to **NetBox**, **GLPI**
and (optionally) an **Ansible** inventory.

📖 Full documentation in [`docs/`](docs/README.md): architecture, installation,
configuration, running, script reference, security and troubleshooting.

```
nmap/
  run_all_inventory.sh      # entry point: TCP -> UDP -> NetBox push -> GLPI push
  run_inventory.sh          # host discovery + TCP ports/services
  run_udp_enrichment.sh     # UDP ports/services + merge with TCP
  scripts/                  # Nmap XML parsing, normalization, NetBox push, Ansible
glpi-nmap-adapter/
  nmap_to_glpi_nmap_asset.py  # push to a GLPI custom asset via the Legacy API
deploy/
  inventory-nmap            # root wrapper: the only command allowed through sudo
  sudoers-inventory         # sudo rule restricted to the wrapper
docs/                       # full documentation
```

## Requirements

- Linux, `bash`, `nmap`, `python3`, `sudo`
- The `deploy/inventory-nmap` wrapper installed with its sudo rule (see below)
- NetBox with custom fields on IP addresses (defaults: `tcp_ports`, `udp_ports`, `services_detail`)
- GLPI 11 with an `Nmap` custom asset and three custom fields (TCP, UDP, services), Legacy API enabled

## Installation

The pipeline runs as an unprivileged service user (`inventory` in the examples) that
owns the project directory.

```bash
sudo useradd --system --create-home --shell /bin/bash inventory
sudo git clone https://github.com/memorydumper23/inventory.git /opt/inventory
sudo chown -R inventory: /opt/inventory
```

## Configuration

No credentials are included in the repository: every installation provides its own.
Run these steps as the `inventory` user (`sudo -iu inventory`, then `cd /opt/inventory`).

```bash
# Targets to scan (one subnet/host per line)
cp nmap/targets.txt.example nmap/targets.txt

# NetBox (+ Ansible options / GLPI adapter path)
cp nmap/netbox.env.example nmap/netbox.env
chmod 600 nmap/netbox.env

# GLPI
cp glpi-nmap-adapter/.env.example glpi-nmap-adapter/.env
chmod 600 glpi-nmap-adapter/.env
```

Edit the copied files, replacing every `CHANGE_ME` value and the example URLs.
The scripts refuse to start if credentials are missing or still set to `CHANGE_ME`.

## Root privileges for nmap

SYN and UDP scans need root, but unrestricted `sudo nmap` is the same as giving the
user root: `--script` runs arbitrary code, `-iL` reads any file, `-oX` overwrites any
file. This is why the pipeline never calls nmap directly: it uses the `inventory-nmap`
wrapper, which accepts only five scan profiles with fixed options, reads the targets
from stdin and writes the XML to stdout (nmap running as root opens no files). The only
free parameter is a list of numeric ports.

As an administrator, in `/opt/inventory`, install the wrapper and the sudo rule:

```bash
# the wrapper must be owned by root and live outside the project directory,
# otherwise whoever can modify it gets root
sudo install -o root -g root -m 0755 deploy/inventory-nmap /usr/local/sbin/inventory-nmap

# sudo rule: replace "inventory" with your user, then validate and install
sudo visudo -cf deploy/sudoers-inventory
sudo install -o root -g root -m 0440 deploy/sudoers-inventory /etc/sudoers.d/inventory

# check: only /usr/local/sbin/inventory-nmap must be listed
sudo -l -U inventory
```

If you previously had a `NOPASSWD: /usr/bin/nmap` rule, remove it. After every change
to `deploy/inventory-nmap`, run the `install` command again.

## Dependencies

The scripts in `nmap/` use the system Python (`/usr/bin/python3`). On recent
Debian/Ubuntu releases a system-wide `pip install` is blocked (PEP 668): install the
distribution packages.

```bash
# Debian/Ubuntu
sudo apt install nmap python3-requests python3-yaml python3-venv

# other distributions: packages for the inventory user
sudo -u inventory python3 -m pip install --user -r /opt/inventory/nmap/requirements.txt
```

The GLPI adapter uses its own virtualenv, to be created as the `inventory` user:

```bash
cd /opt/inventory/glpi-nmap-adapter
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

`run_all_inventory.sh` automatically uses `glpi-nmap-adapter/.venv` if present.

## Running

```bash
sudo -u inventory /opt/inventory/nmap/run_all_inventory.sh
```

Example cron entry for the `inventory` user (`sudo crontab -u inventory -e`), every
night at 2:00:

```
0 2 * * * umask 077; /opt/inventory/nmap/run_all_inventory.sh > /dev/null
```

Flow: host discovery → TCP ports and services → UDP ports and services → merge into
`normalized_assets_merged_<date>.json` → push to NetBox (IP Address + custom fields)
→ push to GLPI (custom asset, name = IP). The two pushes are independent: if one fails
the other still runs and the script ends with exit code 1.
To disable one, set `PUSH_TO_NETBOX=false` or `PUSH_TO_GLPI=false` in `netbox.env`.

Output goes to `nmap/scans/` (Nmap XML), `nmap/work/` (normalized JSON) and `nmap/logs/`.
These directories are excluded from git because they contain data about the scanned network.

Testing the GLPI push without sending anything:

```bash
cd glpi-nmap-adapter
.venv/bin/python nmap_to_glpi_nmap_asset.py -i ../nmap/work/normalized_assets_merged_YYYY-MM-DD.json -f json --dry-run
```

Add `--verbose` to print endpoint and payload of every request during a real push.

> ⚠️ Only scan networks you own or are explicitly authorized to scan.

## License

[MIT](LICENSE)
