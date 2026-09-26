# Running

## Manual run

```bash
sudo -u inventory /opt/inventory/nmap/run_all_inventory.sh
```

The script can be started from any directory: every path is computed from its own
location. Never run it as root: the pipeline gets the privileges it needs only through
the wrapper.

## Scheduled runs (cron)

In the crontab of the `inventory` user (`sudo crontab -u inventory -e`):

```
# network inventory every night at 2:00
0 2 * * * umask 077; /opt/inventory/nmap/run_all_inventory.sh > /dev/null

# delete results older than 30 days
30 3 * * * find /opt/inventory/nmap/scans /opt/inventory/nmap/work /opt/inventory/nmap/logs -type f -mtime +30 -delete
```

- `umask 077` makes scans and logs readable by the `inventory` user only: they contain
  the map of the network (see [Security](security.md#generated-data)).
- `> /dev/null` discards the progress messages, which are in the logs anyway. Errors
  written to standard error are kept, and cron mails them to the user if a mail
  service is configured on the server.
- Pick a time when the network is quiet: the full TCP scan generates a lot of traffic
  (see [Duration and network impact](#duration-and-network-impact)).
- The lock file prevents two runs from overlapping: if the previous one has not
  finished yet, the new one exits immediately with an error.

## What happens during a run

A successful run writes lines like these to `logs/run_all_<date>.log`:

```
[2026-09-26 02:00:00] Starting run_all_inventory
[2026-09-26 02:00:00] Running TCP pipeline
[2026-09-26 02:14:31] Running UDP enrichment
[2026-09-26 02:16:02] Running final push to NetBox from the merged JSON
[2026-09-26 02:16:09] NetBox push completed successfully
[2026-09-26 02:16:09] Using the GLPI virtualenv Python: /opt/inventory/glpi-nmap-adapter/.venv/bin/python3
[2026-09-26 02:16:09] Running final push to GLPI from the merged JSON
[2026-09-26 02:16:12] GLPI push completed successfully
[2026-09-26 02:16:12] run_all_inventory completed successfully
[2026-09-26 02:16:12] Run log: /opt/inventory/nmap/logs/run_all_2026-09-26.log
```

After "Running TCP pipeline" and after "Running UDP enrichment" the log also contains
the detailed messages of those two phases, omitted here. The full sequence of phases
is described in [Architecture](architecture.md#data-flow).

## Logs

All logs are in `/opt/inventory/nmap/logs/`, one file per type and per day. Repeated
runs on the same day append to the same file.

| File | Contents |
|---|---|
| `run_all_<date>.log` | Main log: start, outcome of each phase, errors. Includes the output of the TCP and UDP phases |
| `run_<date>.log` | Messages of the TCP phase only (`run_inventory.sh`) |
| `run_udp_<date>.log` | Messages of the UDP phase only (`run_udp_enrichment.sh`) |
| `netbox_sync_<date>.log` | Outcome of the NetBox push: one `[CREATE]` or `[UPDATE]` line per IP, errors and summary |
| `glpi_sync_<date>.log` | Outcome of the GLPI push: one `[OK]`, `[KO]` or `[EXC]` line per IP and summary |

When something goes wrong, start from `run_all_<date>.log` and then look at the log of
the phase that failed.

## Exit codes

| Script | Code | Meaning |
|---|---|---|
| `run_all_inventory.sh` | `0` | Pipeline completed, or no hosts found (in that case NetBox and GLPI are not touched) |
| | non-zero | Error. Typical cases: a failed push (the other one still ran), a missing required file, another run in progress (all with code `1`), or a phase stopped by Nmap, sudo or a Python script (code of the failed command). The log shows the cause |
| `inventory-nmap` | `2` | Unknown profile or invalid arguments |
| `push_to_netbox.py` | `0` / `1` | All IPs pushed / at least one error or missing configuration |
| `nmap_to_glpi_nmap_asset.py` | `0` / `1` | All hosts pushed / at least one error, missing configuration or failed login |

The exit code of `run_all_inventory.sh` is the one to use in a monitoring system.

## Repeated runs on the same day

All the files of a run carry its start date (`DATE_TAG`), set at the beginning and kept
even if the run goes past midnight. When the pipeline runs again on the same day:

- the files in `scans/` and `work/` are overwritten;
- the logs are appended to;
- NetBox and GLPI are updated with the new results.

## Partial runs

Each phase can be run on its own, which is useful for troubleshooting and testing.

**TCP phase only**, without pushes:

```bash
sudo -u inventory /opt/inventory/nmap/run_inventory.sh
```

Run on its own, `run_inventory.sh` sends nothing to NetBox unless `PUSH_TO_NETBOX` is
`true` in the environment or in `netbox.env`: in that case it pushes the TCP data only.

**UDP phase only**: needs the files of the TCP phase from the same day.

```bash
sudo -u inventory /opt/inventory/nmap/run_udp_enrichment.sh
```

To work on the files of another day, set the date:
`sudo -u inventory env DATE_TAG=2026-09-25 /opt/inventory/nmap/run_udp_enrichment.sh`.

**NetBox push only**, of a result already produced:

```bash
sudo -u inventory python3 /opt/inventory/nmap/scripts/push_to_netbox.py \
  --input /opt/inventory/nmap/work/normalized_assets_merged_2026-09-26.json
```

**GLPI push only**, with the test options:

```bash
cd /opt/inventory/glpi-nmap-adapter
F=../nmap/work/normalized_assets_merged_2026-09-26.json

# simulation: prints the data that would be sent, needs no credentials
sudo -u inventory .venv/bin/python nmap_to_glpi_nmap_asset.py -i "$F" -f json --dry-run

# a single host, showing endpoint and data of every request
sudo -u inventory .venv/bin/python nmap_to_glpi_nmap_asset.py -i "$F" -f json \
  --only-ip 192.0.2.10 --verbose
```

## Duration and network impact

The duration depends almost entirely on the full TCP scan (`tcp-ports` profile), which
checks all 65,535 ports of every host at a minimum rate of 5,000 packets per second
across the whole scan.

- **Order of magnitude**: 100 live hosts mean about 6.5 million probes. At the minimum
  rate that is about 22 minutes; Nmap may go faster, but retransmissions and slow hosts
  make it longer.
- **Slow hosts**: a host whose scan takes more than 10 minutes (`--host-timeout 10m`) is
  abandoned and shows up without ports.
- **UDP**: 12 ports per host, but many systems rate-limit ICMP replies, which slows the
  UDP scan down.
- **Load**: 5,000 packets per second is sustainable for a corporate network, but it can
  saturate slow links (branch offices, VPNs) or upset fragile devices: printers, IoT
  devices and above all industrial systems (OT). Service detection (`-sV`) sends
  application-level requests that some devices handle badly.
- **Security systems**: IDS, IPS and firewalls will recognize the scan for what it is.
  Warn the SOC and agree on a fixed time and source address for the pipeline, so it
  can be told apart from a real attack.

## Maintenance

- **Cleaning up results**: scans, JSON files and logs pile up every day. The second
  cron example above deletes them after 30 days; adjust the period to your retention policy.
- **GLPI state file**: include `glpi-nmap-adapter/glpi_nmap_state_legacy.json` in your
  backups. If it is lost, the next run creates duplicate assets in GLPI.
- **Credentials**: when you rotate the NetBox token or the GLPI password, update
  `netbox.env` and `.env`.
- **Upgrades**: see [Installation → Upgrading](installation.md#upgrading).
