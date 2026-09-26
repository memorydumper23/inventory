# Troubleshooting

Always start from `nmap/logs/run_all_<date>.log`, then look at the log of the phase
that failed (see [Running → Logs](running.md#logs)).

## Permissions and sudo

### `sudo: a password is required`

**Cause**: the sudoers rule is not installed, applies to another user, or the command
is not exactly `/usr/local/sbin/inventory-nmap`.

**Fix**: `sudo -l -U inventory` must show
`(root) NOPASSWD: /usr/local/sbin/inventory-nmap`. If it does not, reinstall the rule
(see [Installation](installation.md#4-wrapper-and-sudo-rule)) and check that its last
line has the right service user name.

### `[ERROR] Command not found: /usr/local/sbin/inventory-nmap`

**Cause**: the wrapper is not installed.

**Fix**: `sudo install -o root -g root -m 0755 deploy/inventory-nmap /usr/local/sbin/inventory-nmap`.

### `inventory-nmap: invalid port list` or `this profile takes no arguments`

**Cause**: the wrapper received arguments it does not accept. In the pipeline this only
happens if you changed `UDP_PORTS` to an invalid format (spaces, ranges with a dash).

**Fix**: use only digits separated by commas, for example `53,123,161`.

### `/usr/bin/env: 'bash\r': No such file or directory`

**Cause**: the scripts have Windows line endings (CRLF), usually because the directory
was copied from a Windows PC instead of being cloned on the server.

**Fix**: clone the repository directly on the server. The `.gitattributes` file forces
Linux line endings even on Windows checkouts. To fix an existing copy:
`find /opt/inventory -name '*.sh' -exec sed -i 's/\r$//' {} +` (and the same for
`deploy/inventory-nmap` and the `.py` files).

### `Permission denied` when writing to `nmap/scans/`

**Cause**: there are files written as root by an earlier version of the pipeline.

**Fix**: `sudo chown -R inventory: /opt/inventory/nmap`.

### `[ERROR] Another run is already in progress. Exiting.`

**Cause**: another run of `run_all_inventory.sh` is still active, for example the
previous cron run has not finished yet.

**Fix**: wait for it to finish (`pgrep -af run_all_inventory`). The lock is released
automatically when the process ends: do not delete it by hand. If runs overlap often,
space them out in cron or reduce the targets.

## Scanning

### `[ERROR] Missing file: .../nmap/targets.txt`

**Fix**: `cp nmap/targets.txt.example nmap/targets.txt` and add your subnets.

### `No hosts up`

**Possible causes**:

- wrong targets in `targets.txt`;
- remote subnets where the hosts answer neither ICMP echo nor the TCP probes on ports
  80 and 443 (ARP only works on directly connected subnets);
- a firewall between the server and the subnets filters the probes.

**Check**: `echo 192.0.2.10 | sudo -u inventory sudo -n /usr/local/sbin/inventory-nmap discovery`
on a host you know is up: look for `state="up"` in the XML.

### Every address in a subnet shows up as live and the scan takes hours

**Cause**: a firewall or proxy answers on behalf of the hosts, even for addresses that
do not exist (for example with a TCP reset on port 80 or 443). Nmap considers them all
live and scans 65,535 ports on each one.

**Fix**: check `nmap/work/hosts_up_<date>.txt`: if it lists addresses you know are
free, narrow `targets.txt` to the ranges actually in use, or run the scan from a point
in the network that does not go through that firewall.

### Some hosts have no ports

**Possible causes**: the host filters every port, or its scan took more than 10 minutes
and was abandoned (`--host-timeout 10m`). In the second case the XML in
`nmap/scans/open_ports_<date>.xml` has the `timedout="true"` attribute for that host.

### The scan is very slow

See [Running → Duration and network impact](running.md#duration-and-network-impact).
Typical causes are many live hosts, slow links, firewalls silently dropping packets and
rate-limited ICMP replies in the UDP phase.

## NetBox

### `[ERROR] Missing environment variable: NETBOX_URL` (or `NETBOX_TOKEN`)

**Cause**: `nmap/netbox.env` is missing, or the variable is empty or still `CHANGE_ME`.

**Fix**: fill in `netbox.env` (see [Configuration](configuration.md#nmapnetboxenv)).
If you do not use NetBox, set `export PUSH_TO_NETBOX="false"`.

### `403 Forbidden` errors

**Cause**: the token does not have write access enabled, or the user lacks permissions
on IP Addresses (`view`, `add`, `change`).

### `400 Bad Request` errors mentioning custom fields

**Cause**: the custom fields do not exist on the IP Address type, or their names differ
from those in `NETBOX_CF_*`. Earlier versions of the pipeline used Italian default names
(`porte_tcp`, `porte_udp`, `servizi_dettaglio`).

**Fix**: create the fields (see [Installation → Preparing NetBox](installation.md#preparing-netbox))
or set the right names in `netbox.env`.

### Duplicate IPs appear in NetBox

**Cause**: the IP was already registered with its subnet mask (for example
`192.0.2.10/24`), while the pipeline looks up and creates `/32` addresses.

**Fix**: register the IPs managed by the pipeline as `/32`, or delete the duplicates it
created and register the hosts as `/32`.

### `dns_name`, `description` or `status` do not change on an existing IP

This is intended: on IPs already in NetBox the pipeline updates only the three custom
fields, so it does not wipe values curated by hand. Status, description and DNS name
are written only when the pipeline creates the IP (see
[Architecture → NetBox](architecture.md#netbox)).

## GLPI

### `[ERROR] Missing configuration: ...`

**Cause**: `glpi-nmap-adapter/.env` is missing, or the listed variables are empty or
still `CHANGE_ME`.

**Fix**: fill in `.env`. If you do not use GLPI, set `export PUSH_TO_GLPI="false"` in
`nmap/netbox.env`.

### `[ERROR] initSession HTTP 4xx: ...`

The message contains GLPI's response. Frequent error codes:

| GLPI code | Cause |
|---|---|
| `ERROR_GLPI_LOGIN` | Wrong user name or password |
| `ERROR_LOGIN_WITH_CREDENTIALS_DISABLED` | Login with credentials is disabled in the GLPI API settings |
| `ERROR_WRONG_APP_TOKEN_PARAMETER` | Wrong `GLPI_LEGACY_APP_TOKEN` |
| `ERROR_NOT_ALLOWED_IP` | The API client does not accept the IP of the scanning server |

If the response is an HTML page or a 404, check `GLPI_BASE_URL` or
`GLPI_LEGACY_API_URL` and that the legacy API is enabled.

### `[KO] <ip> -> HTTP 4xx` on create or update

**Possible causes**: `GLPI_ITEMTYPE` does not match the asset type (the response
contains `ERROR_ITEMTYPE_NOT_FOUND_NOR_COMMONDBTM`), the API user's profile lacks create
and update rights on that asset type (`ERROR_RIGHT_MISSING`), or the `FIELD_*_KEY`
names do not match the fields.

**Fix**: check the names with the procedure in
[Installation → Checking the field names](installation.md#checking-the-field-names)
and try a single host with `--only-ip <ip> --verbose`.

### Duplicate assets appear in GLPI

**Cause**: the state file `glpi_nmap_state_legacy.json` was deleted or replaced, so the
script no longer knows the IDs and creates new assets.

**Fix**: restore the file from a backup. If that is not possible, delete the older
duplicates in GLPI and let the pipeline start over from the new state file.

## Python and certificates

### `SSLError` or `CERTIFICATE_VERIFY_FAILED`

**Cause**: the NetBox or GLPI certificate is issued by a CA Python does not trust,
typically an internal CA.

**Fix**: install the CA in the system and, for GLPI, add `REQUESTS_CA_BUNDLE` to `.env`
(see [Configuration](configuration.md#certificates-from-an-internal-ca)). Do not disable
verification except for temporary troubleshooting.

### `error: externally-managed-environment`

**Cause**: on recent Debian and Ubuntu releases `pip install` into the system Python is
blocked (PEP 668).

**Fix**: `sudo apt install python3-requests python3-yaml`.

### `The virtual environment was not created successfully because ensurepip is not available`

**Fix**: `sudo apt install python3-venv`, then create the virtualenv again.

### `No matching distribution found for requests==2.34.2`

**Cause**: the Python used for the virtualenv is older than 3.10, or pip cannot reach
PyPI (in that case the output first shows network or certificate errors).

**Fix**: use a distribution with Python 3.10 or later (Debian 12+, Ubuntu 22.04+), or
fix the access to PyPI (proxy, internal CA).

### `[ERROR] PyYAML is not installed`

**Cause**: `ANSIBLE_INVENTORY_FILE` is set but the system Python has no PyYAML.

**Fix**: `sudo apt install python3-yaml`.
