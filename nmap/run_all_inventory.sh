#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_DIR="$BASE_DIR/scripts"
WORK_DIR="$BASE_DIR/work"
LOG_DIR="$BASE_DIR/logs"

GLPI_DIR_DEFAULT="$(cd "$BASE_DIR/.." && pwd)/glpi-nmap-adapter"

# One date for the whole run (even if it crosses midnight)
export DATE_TAG="$(date +%F)"
RUN_LOG="$LOG_DIR/run_all_${DATE_TAG}.log"
LOCK_FILE="/tmp/run_all_inventory.lock"

mkdir -p "$LOG_DIR" "$WORK_DIR"

log() {
  echo "[$(date '+%F %T')] $*" | tee -a "$RUN_LOG"
}

check_file() {
  if [[ ! -f "$1" ]]; then
    echo "[ERROR] Missing file: $1" >&2
    exit 1
  fi
}

# Lock to prevent concurrent runs from cron
exec 200>"$LOCK_FILE"
if ! flock -n 200; then
  echo "[ERROR] Another run is already in progress. Exiting." | tee -a "$RUN_LOG"
  exit 1
fi

log "Starting run_all_inventory"

# Load the NetBox environment if present
if [[ -f "$BASE_DIR/netbox.env" ]]; then
  # shellcheck disable=SC1090
  source "$BASE_DIR/netbox.env"
fi

GLPI_DIR="${GLPI_DIR:-$GLPI_DIR_DEFAULT}"
GLPI_SCRIPT="$GLPI_DIR/nmap_to_glpi_nmap_asset.py"
GLPI_VENV_PY="$GLPI_DIR/.venv/bin/python3"

# PUSH_TO_NETBOX / PUSH_TO_GLPI = false disables that push
PUSH_TO_NETBOX="${PUSH_TO_NETBOX:-true}"
PUSH_TO_GLPI="${PUSH_TO_GLPI:-true}"

###############################################################################
# 1) TCP
###############################################################################

log "Running TCP pipeline"
# INVENTORY_RUN_ALL: the TCP phase sends nothing, the push happens below with TCP + UDP
/usr/bin/env INVENTORY_RUN_ALL=1 "$BASE_DIR/run_inventory.sh" >> "$RUN_LOG" 2>&1

if [[ ! -s "$WORK_DIR/hosts_up_${DATE_TAG}.txt" ]]; then
  log "No hosts up. Nothing to sync."
  exit 0
fi

###############################################################################
# 2) UDP
###############################################################################

log "Running UDP enrichment"
"$BASE_DIR/run_udp_enrichment.sh" >> "$RUN_LOG" 2>&1

MERGED_JSON="$WORK_DIR/normalized_assets_merged_${DATE_TAG}.json"
check_file "$MERGED_JSON"

# The pushes are independent: a failure in one does not block the other
FAILED=()

###############################################################################
# 3) FINAL PUSH TO NETBOX
###############################################################################

if [[ "$PUSH_TO_NETBOX" == "true" ]]; then
  log "Running final push to NetBox from the merged JSON"
  if /usr/bin/python3 "$SCRIPT_DIR/push_to_netbox.py" \
    --input "$MERGED_JSON" \
    >> "$LOG_DIR/netbox_sync_${DATE_TAG}.log" 2>&1; then
    log "NetBox push completed successfully"
  else
    log "[WARN] NetBox push failed. Check the log: $LOG_DIR/netbox_sync_${DATE_TAG}.log"
    FAILED+=("NetBox")
  fi
else
  log "NetBox push DISABLED - skipping sync"
fi

###############################################################################
# 4) FINAL PUSH TO GLPI
###############################################################################

if [[ "$PUSH_TO_GLPI" == "true" ]]; then
  check_file "$GLPI_SCRIPT"

  if [[ -x "$GLPI_VENV_PY" ]]; then
    GLPI_PY="$GLPI_VENV_PY"
    log "Using the GLPI virtualenv Python: $GLPI_PY"
  else
    GLPI_PY="/usr/bin/python3"
    log "GLPI virtualenv not found, trying the system Python: $GLPI_PY"
  fi

  log "Running final push to GLPI from the merged JSON"
  if (
    cd "$GLPI_DIR"
    "$GLPI_PY" "$GLPI_SCRIPT" \
      -i "$MERGED_JSON" \
      -f json
  ) >> "$LOG_DIR/glpi_sync_${DATE_TAG}.log" 2>&1; then
    log "GLPI push completed successfully"
  else
    log "[WARN] GLPI push failed. Check the log: $LOG_DIR/glpi_sync_${DATE_TAG}.log"
    FAILED+=("GLPI")
  fi
else
  log "GLPI push DISABLED - skipping sync"
fi

if (( ${#FAILED[@]} > 0 )); then
  log "run_all_inventory completed with errors in: ${FAILED[*]}"
  log "Run log: $RUN_LOG"
  exit 1
fi

log "run_all_inventory completed successfully"
log "Run log: $RUN_LOG"
