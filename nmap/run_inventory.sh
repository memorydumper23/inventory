#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_DIR="$BASE_DIR/scripts"
SCAN_DIR="$BASE_DIR/scans"
WORK_DIR="$BASE_DIR/work"
LOG_DIR="$BASE_DIR/logs"

# nmap runs as root only through this wrapper (see deploy/inventory-nmap)
NMAP_WRAPPER="/usr/local/sbin/inventory-nmap"

TARGET_SUBNET="$BASE_DIR/targets.txt"
DATE_TAG="${DATE_TAG:-$(date +%F)}"
RUN_LOG="$LOG_DIR/run_${DATE_TAG}.log"

# true = push to NetBox (only when this script is run on its own)
# false = only generate the files
PUSH_TO_NETBOX="${PUSH_TO_NETBOX:-false}"

mkdir -p "$SCRIPT_DIR" "$SCAN_DIR" "$WORK_DIR" "$LOG_DIR"

log() {
  echo "[$(date '+%F %T')] $*" | tee -a "$RUN_LOG"
}

check_bin() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "[ERROR] Command not found: $1" >&2
    exit 1
  fi
}

check_file() {
  if [[ ! -f "$1" ]]; then
    echo "[ERROR] Missing file: $1" >&2
    exit 1
  fi
}

check_bin /usr/bin/nmap
check_bin /usr/bin/python3
check_bin "$NMAP_WRAPPER"

check_file "$SCRIPT_DIR/extract_hosts.py"
check_file "$SCRIPT_DIR/extract_open_ports.py"
check_file "$SCRIPT_DIR/normalize_for_netbox.py"
check_file "$SCRIPT_DIR/push_to_netbox.py"
check_file "$SCRIPT_DIR/build_portspec_from_xml.py"

if [[ ! -f "$TARGET_SUBNET" ]]; then
  echo "[ERROR] Missing file: $TARGET_SUBNET (copy targets.txt.example to targets.txt and add your subnets)" >&2
  exit 1
fi

# Load the NetBox environment variables if present
if [[ -f "$BASE_DIR/netbox.env" ]]; then
  # shellcheck disable=SC1090
  source "$BASE_DIR/netbox.env"
fi

# Started by run_all_inventory.sh: it pushes to NetBox itself at the end, with
# TCP + UDP data. Decided after netbox.env, which may set PUSH_TO_NETBOX
if [[ "${INVENTORY_RUN_ALL:-}" == "1" ]]; then
  PUSH_TO_NETBOX="false"
fi

log "Starting TCP inventory pipeline"

###############################################################################
# 1) HOST DISCOVERY
###############################################################################

log "Host discovery on $TARGET_SUBNET"
sudo -n "$NMAP_WRAPPER" discovery \
  < "$TARGET_SUBNET" \
  > "$SCAN_DIR/hosts_up_${DATE_TAG}.xml"

/usr/bin/python3 "$SCRIPT_DIR/extract_hosts.py" \
  --input "$SCAN_DIR/hosts_up_${DATE_TAG}.xml" \
  --output "$WORK_DIR/hosts_up_${DATE_TAG}.txt"

# Optional: set ANSIBLE_INVENTORY_FILE (e.g. in netbox.env)
ANSIBLE_INV_FILE="${ANSIBLE_INVENTORY_FILE:-}"

if [[ -n "$ANSIBLE_INV_FILE" ]]; then
  log "Updating Ansible inventory"
  /usr/bin/python3 "$SCRIPT_DIR/update_ansible_hosts_yml.py" \
    --input "$WORK_DIR/hosts_up_${DATE_TAG}.txt" \
    --inventory "$ANSIBLE_INV_FILE"

  log "Ansible inventory updated: $ANSIBLE_INV_FILE"
else
  log "ANSIBLE_INVENTORY_FILE not set - skipping Ansible inventory update"
fi

if [[ ! -s "$WORK_DIR/hosts_up_${DATE_TAG}.txt" ]]; then
  log "No hosts up. Exiting."
  exit 0
fi

log "Hosts found:"
wc -l "$WORK_DIR/hosts_up_${DATE_TAG}.txt" | tee -a "$RUN_LOG"

###############################################################################
# 2) PORT DISCOVERY TCP
###############################################################################   

log "TCP port discovery on the hosts found"
sudo -n "$NMAP_WRAPPER" tcp-ports \
  < "$WORK_DIR/hosts_up_${DATE_TAG}.txt" \
  > "$SCAN_DIR/open_ports_${DATE_TAG}.xml"

/usr/bin/python3 "$SCRIPT_DIR/extract_open_ports.py" \
  --input "$SCAN_DIR/open_ports_${DATE_TAG}.xml" \
  --output "$WORK_DIR/open_ports_${DATE_TAG}.json"

###############################################################################
# 3) PORT LIST FROM THE OPEN PORTS
###############################################################################

log "Building the TCP port list from the open ports"
SERVICE_PORTSPEC=$(/usr/bin/python3 "$SCRIPT_DIR/build_portspec_from_xml.py" \
  --input "$SCAN_DIR/open_ports_${DATE_TAG}.xml" \
  --protocol tcp)

if [[ -z "${SERVICE_PORTSPEC}" ]]; then
  log "No open TCP ports: skipping TCP service detection"

  # JSON generated anyway (hosts without services) for the next phases
  /usr/bin/python3 "$SCRIPT_DIR/normalize_for_netbox.py" \
    --hosts "$SCAN_DIR/hosts_up_${DATE_TAG}.xml" \
    --ports "$SCAN_DIR/open_ports_${DATE_TAG}.xml" \
    --services "$SCAN_DIR/open_ports_${DATE_TAG}.xml" \
    --output "$WORK_DIR/normalized_assets_${DATE_TAG}.json"

  log "TCP pipeline completed"
  exit 0
fi

log "Ports for TCP service detection: $SERVICE_PORTSPEC"

###############################################################################
# 4) SERVICE / VERSION DETECTION ON THE OPEN PORTS ONLY
###############################################################################

log "TCP service/version detection on the open ports only"
sudo -n "$NMAP_WRAPPER" tcp-services "$SERVICE_PORTSPEC" \
  < "$WORK_DIR/hosts_up_${DATE_TAG}.txt" \
  > "$SCAN_DIR/services_${DATE_TAG}.xml"

/usr/bin/python3 "$SCRIPT_DIR/normalize_for_netbox.py" \
  --hosts "$SCAN_DIR/hosts_up_${DATE_TAG}.xml" \
  --ports "$SCAN_DIR/open_ports_${DATE_TAG}.xml" \
  --services "$SCAN_DIR/services_${DATE_TAG}.xml" \
  --output "$WORK_DIR/normalized_assets_${DATE_TAG}.json"

###############################################################################
# 5) SYNC TO NETBOX
###############################################################################

if [[ "$PUSH_TO_NETBOX" == "true" ]]; then
  log "Syncing to NetBox"
  /usr/bin/python3 "$SCRIPT_DIR/push_to_netbox.py" \
    --input "$WORK_DIR/normalized_assets_${DATE_TAG}.json" \
    >> "$LOG_DIR/netbox_sync_${DATE_TAG}.log" 2>&1
else
  log "NetBox push DISABLED - skipping sync"
fi

log "TCP pipeline completed"
log "Run log: $RUN_LOG"