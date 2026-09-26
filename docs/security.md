# Security

The pipeline needs two sensitive things: root privileges for the scans and write
credentials for NetBox and GLPI. It also produces a detailed map of the network. This
document describes how each risk is handled and what is left to whoever installs it.

## Principles

- **Least privilege**: everything runs as an unprivileged user. Only five predefined
  Nmap scans run as root, through a wrapper.
- **No file opened as root**: targets come in and results go out through standard
  input and output; files are always opened by the service user.
- **No credentials in the repository**: the real configuration lives in local files
  excluded from git, with `600` permissions.
- **TLS verification on by default** towards NetBox and GLPI.

## Threat model

| Risk | Countermeasure | Residual risk |
|---|---|---|
| The service user is compromised and tries to get root | It can run only the wrapper as root, which accepts five fixed profiles and numeric port lists only | It can run the intended scans against any reachable destination |
| Someone modifies the code in `/opt/inventory` | The project code runs as the service user; the wrapper run as root is a root-owned copy in `/usr/local/sbin` | Whoever controls the service user can alter the data sent to NetBox and GLPI |
| Theft of the NetBox or GLPI credentials | `600` files owned by the service user; token and profiles with only the permissions needed | Whoever reads the files can do what the token allows: create and change IP Addresses and `Nmap` assets |
| Exposure of the network map | `umask 077` in cron, periodic cleanup, exclusion from git | Copies in backups and in the destination systems |
| Interception of the API traffic | TLS with certificate verification | None, as long as `NETBOX_VERIFY_SSL` stays `true` and the URLs are `https://` |
| Compromised Python dependencies | Pinned versions in `requirements.txt`; distribution packages for the system Python | Trust in the PyPI and distribution repositories |
| Unauthorized or harmful scans | Targets decided only in `targets.txt`; fixed scan profiles | An organizational responsibility (see [Authorized use](#authorized-use-and-operational-impact)) |

## Why a wrapper and not a sudo rule on nmap

Granting a user `sudo nmap` is the same as giving them root. The techniques are well
known and documented (for example on GTFOBins):

- `--script` runs arbitrary Lua scripts, and therefore system commands, as root;
- `-iL <file>` reads any file, such as `/etc/shadow`: its lines end up in Nmap's error
  messages;
- `-oX`, `-oN` and the other output options write or overwrite any file;
- `--datadir` or the `NMAPDIR` variable make Nmap load files and scripts from a user
  directory, which service detection (`-sV`) then runs.

Restricting the arguments directly in the sudoers rule does not work well: in sudoers
the `*` character matches any sequence, spaces included, so a rule like
`nmap -sV -p *` would also allow `nmap -sV -p 22 --script ...`. Regular expressions in
rules only exist since sudo 1.9.10 and would become unreadable for five different profiles.

The wrapper moves the validation into a short, readable file that works with any sudo
version. The sudoers rule shrinks to one line: the user can run the wrapper, and
nothing else.

### Why targets and results go through stdin and stdout

Even with fixed options, passing a file path to the wrapper would be dangerous. The
`nmap/scans/` directory belongs to the service user: if Nmap wrote there as root, it
would be enough to create a symbolic link `scans/hosts_up_<date>.xml → /etc/shadow`
beforehand to make it overwrite a system file. With the redirection done by the user's
shell, files are opened with the user's privileges and the problem does not exist.

## What the wrapper guarantees and what it does not

**It guarantees**

- No arbitrary code run as root: no `--script`, `--datadir` or options other than the
  fixed ones of the five profiles.
- No file read or written as root.
- Free parameters limited to a list of numeric ports.
- A clean environment (fixed `PATH`, `HOME=/root`, `NMAPDIR` removed), on top of the
  cleanup sudo already does with `env_reset`.

**It does not guarantee**

- That the service user scans only the intended networks: targets come from standard
  input and can be anything. If you need to restrict them, use outbound firewall rules
  on the scanning server.
- The security of Nmap itself: Nmap parses the responses of the scanned hosts as root,
  and a hostile host could exploit a vulnerability in it. Keep the `nmap` package up to date.
- The security of the NSE scripts in the *version* category, which `-sV` runs as root
  from Nmap's system directory: they are part of the distribution package.
- Its own integrity: the wrapper must be owned by root, not writable by others, in a
  root-owned directory. After every upgrade, review its changes before reinstalling it
  (see [Installation → Upgrading](installation.md#upgrading)).

## Credentials

- They live only in `nmap/netbox.env` and `glpi-nmap-adapter/.env`, owned by the
  service user with `600` permissions.
- `.gitignore` excludes `.env`, `.env.*` and `*.env`, except the `*.env.example`
  templates: a careless `git add` does not publish them.
- The scripts never pass them on the command line, where other users could see them
  with `ps`.
- The scripts never print tokens or passwords, not even with `--verbose`. When a login
  fails, GLPI's response is printed, and it does not contain them.
- Use credentials dedicated to the pipeline, with minimal permissions:
  - NetBox: a user with permissions on IP Addresses only (view, add, change);
  - GLPI: a profile with rights on the `Nmap` asset only, and an API client restricted
    to the IP of the scanning server.
- Rotate them periodically and revoke them when you decommission the pipeline.

## Generated data

The results describe which hosts exist, which ports they expose and which software
versions they run. For an attacker this is the most useful map for choosing a target,
for example an outdated service.

| Where | What |
|---|---|
| `nmap/scans/`, `nmap/work/` | Full XML and JSON of every run |
| `nmap/logs/` | List of IPs and ports, push outcomes |
| `glpi-nmap-adapter/glpi_nmap_state_legacy.json` | IPs present and their IDs in GLPI |
| NetBox, GLPI, Ansible inventory | The data sent |

Recommended protections:

- `umask 077` in the cron line (see [Running](running.md#scheduled-runs-cron)); for
  directories that already exist:
  `sudo chmod 700 /opt/inventory/nmap/scans /opt/inventory/nmap/work /opt/inventory/nmap/logs`.
- Periodic cleanup of old results, according to your retention policy.
- Encrypted, access-controlled server backups.
- In NetBox and GLPI, check who can see the fields with ports and services.
- Before sharing a log (for example to ask for support), remove addresses and names.

IP addresses and host names of devices assigned to people (for example
`pc-john-smith`) can be personal data under the GDPR: handle their retention and
access like the rest of your system logs.

## TLS

- Certificate verification is on for NetBox and GLPI. Always use `https://` URLs: the
  GLPI adapter sends the password with HTTP Basic authentication.
- `NETBOX_VERIFY_SSL=false` disables verification towards NetBox: anyone able to
  intercept the traffic can read the token. Use it only for temporary troubleshooting.
- The GLPI adapter has no option to disable verification. With an internal CA, use
  `REQUESTS_CA_BUNDLE` (see [Configuration](configuration.md#certificates-from-an-internal-ca)).

## Authorized use and operational impact

- **Authorization**: only scan networks you own or for which you have written
  authorization stating scope, time windows and source address. On client networks,
  the scope must be defined in the engagement.
- **Coordination**: warn the SOC or whoever runs IDS, IPS and firewalls. The scan will
  be recognized for what it is: a fixed time and source IP make it possible to tell it
  apart from a real attack.
- **Fragile systems**: the profiles are designed for IT networks. Leave industrial
  networks (OT/ICS) and fragile devices out of `targets.txt`: 5,000 packets per second
  and the `-sV` probes can hang PLCs, printers and IoT devices.
- **Inventory, not vulnerability assessment**: the detected versions help
  vulnerability management, but the pipeline does not look for vulnerabilities and does
  not replace an assessment.

## Regulatory context

The pipeline produces technical evidence that supports some requirements:

- **ISO/IEC 27001:2022, control A.5.9** (inventory of information and other associated
  assets): an automatically updated network inventory is concrete support. It does not
  replace the inventory the control requires, which assigns an owner to every asset.
- **NIS 2, Art. 21(2)(i)**: asset management is among the cybersecurity risk
  management measures.
