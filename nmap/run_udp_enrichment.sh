#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_DIR="$BASE_DIR/scripts"
SCAN_DIR="$BASE_DIR/scans"
WORK_DIR="$BASE_DIR/work"
LOG_DIR="$BASE_DIR/logs"

# nmap runs as root only through this wrapper (see deploy/inventory-nmap)
NMAP_WRAPPER="/usr/local/sbin/inventory-nmap"

DATE_TAG="${DATE_TAG:-$(date +%F)}"
RUN_LOG="$LOG_DIR/run_udp_${DATE_TAG}.log"

# Significant UDP ports
UDP_PORTS="53,67,68,69,123,161,500,514,520,1900,5353,5683"

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

mkdir -p "$SCRIPT_DIR" "$SCAN_DIR" "$WORK_DIR" "$LOG_DIR"

check_bin /usr/bin/nmap
check_bin /usr/bin/python3
check_bin "$NMAP_WRAPPER"

check_file "$SCRIPT_DIR/extract_open_ports.py"
check_file "$SCRIPT_DIR/build_portspec_from_xml.py"
check_file "$SCRIPT_DIR/normalize_for_netbox.py"
check_file "$SCRIPT_DIR/merge_assets_json.py"

# Files produced by the main TCP pipeline
check_file "$WORK_DIR/hosts_up_${DATE_TAG}.txt"
check_file "$SCAN_DIR/hosts_up_${DATE_TAG}.xml"
check_file "$WORK_DIR/normalized_assets_${DATE_TAG}.json"

log "Starting UDP enrichment"

###############################################################################
# 1) UDP PORT DISCOVERY
###############################################################################

log "UDP port discovery on the hosts found"
sudo -n "$NMAP_WRAPPER" udp-ports "$UDP_PORTS" \
  < "$WORK_DIR/hosts_up_${DATE_TAG}.txt" \
  > "$SCAN_DIR/open_ports_udp_${DATE_TAG}.xml"

log "Extracting candidate UDP ports to JSON"
/usr/bin/python3 "$SCRIPT_DIR/extract_open_ports.py" \
  --input "$SCAN_DIR/open_ports_udp_${DATE_TAG}.xml" \
  --output "$WORK_DIR/open_ports_udp_${DATE_TAG}.json"

###############################################################################
# 2) UDP PORT LIST FROM THE CANDIDATE PORTS
###############################################################################

log "Building the UDP port list from the candidate ports"
UDP_SERVICE_PORTSPEC=$(/usr/bin/python3 "$SCRIPT_DIR/build_portspec_from_xml.py" \
  --input "$SCAN_DIR/open_ports_udp_${DATE_TAG}.xml" \
  --protocol udp)

if [[ -z "${UDP_SERVICE_PORTSPEC}" ]]; then
  log "No candidate UDP ports."

  # Write an empty UDP JSON and a merged JSON equal to the TCP one
  cat > "$WORK_DIR/normalized_assets_udp_${DATE_TAG}.json" <<'EOF'
{
  "assets": []
}
EOF

  cp "$WORK_DIR/normalized_assets_${DATE_TAG}.json" \
     "$WORK_DIR/normalized_assets_merged_${DATE_TAG}.json"

  log "Empty UDP JSON created."
  log "Merged JSON created as a copy of the TCP JSON."
  log "UDP enrichment completed."
  exit 0
fi

log "Ports for UDP service detection: $UDP_SERVICE_PORTSPEC"

###############################################################################
# 3) UDP SERVICE / VERSION DETECTION ON THE CANDIDATE PORTS ONLY
###############################################################################

log "UDP service/version detection on the candidate ports only"
sudo -n "$NMAP_WRAPPER" udp-services "$UDP_SERVICE_PORTSPEC" \
  < "$WORK_DIR/hosts_up_${DATE_TAG}.txt" \
  > "$SCAN_DIR/services_udp_${DATE_TAG}.xml"

log "Normalizing the UDP results"
/usr/bin/python3 "$SCRIPT_DIR/normalize_for_netbox.py" \
  --hosts "$SCAN_DIR/hosts_up_${DATE_TAG}.xml" \
  --ports "$SCAN_DIR/open_ports_udp_${DATE_TAG}.xml" \
  --services "$SCAN_DIR/services_udp_${DATE_TAG}.xml" \
  --output "$WORK_DIR/normalized_assets_udp_${DATE_TAG}.json"

###############################################################################
# 4) MERGE TCP + UDP
###############################################################################

log "Merging TCP and UDP results"
/usr/bin/python3 "$SCRIPT_DIR/merge_assets_json.py" \
  --tcp "$WORK_DIR/normalized_assets_${DATE_TAG}.json" \
  --udp "$WORK_DIR/normalized_assets_udp_${DATE_TAG}.json" \
  --output "$WORK_DIR/normalized_assets_merged_${DATE_TAG}.json"

log "UDP enrichment completed"
log "Output UDP: $WORK_DIR/normalized_assets_udp_${DATE_TAG}.json"
log "Output merged: $WORK_DIR/normalized_assets_merged_${DATE_TAG}.json"
log "Run log: $RUN_LOG"