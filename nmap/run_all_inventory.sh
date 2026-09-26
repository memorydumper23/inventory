#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_DIR="$BASE_DIR/scripts"
WORK_DIR="$BASE_DIR/work"
LOG_DIR="$BASE_DIR/logs"

GLPI_DIR_DEFAULT="$(cd "$BASE_DIR/.." && pwd)/glpi-nmap-adapter"

# Data unica per tutta l'esecuzione (anche se si scavalca la mezzanotte)
export DATE_TAG="$(date +%F)"
RUN_LOG="$LOG_DIR/run_all_${DATE_TAG}.log"
LOCK_FILE="/tmp/run_all_inventory.lock"

mkdir -p "$LOG_DIR" "$WORK_DIR"

log() {
  echo "[$(date '+%F %T')] $*" | tee -a "$RUN_LOG"
}

check_file() {
  if [[ ! -f "$1" ]]; then
    echo "[ERRORE] File mancante: $1" >&2
    exit 1
  fi
}

# Lock per evitare esecuzioni concorrenti da cron
exec 200>"$LOCK_FILE"
if ! flock -n 200; then
  echo "[ERRORE] Un'altra esecuzione è già in corso. Esco." | tee -a "$RUN_LOG"
  exit 1
fi

log "Avvio run_all_inventory"

# Carica environment NetBox se presente
if [[ -f "$BASE_DIR/netbox.env" ]]; then
  # shellcheck disable=SC1090
  source "$BASE_DIR/netbox.env"
fi

GLPI_DIR="${GLPI_DIR:-$GLPI_DIR_DEFAULT}"
GLPI_SCRIPT="$GLPI_DIR/nmap_to_glpi_nmap_asset.py"
GLPI_VENV_PY="$GLPI_DIR/.venv/bin/python3"

# PUSH_TO_NETBOX / PUSH_TO_GLPI = false per disabilitare il singolo push
PUSH_TO_NETBOX="${PUSH_TO_NETBOX:-true}"
PUSH_TO_GLPI="${PUSH_TO_GLPI:-true}"

###############################################################################
# 1) TCP
###############################################################################

log "Eseguo pipeline TCP"
/usr/bin/env PUSH_TO_NETBOX=false "$BASE_DIR/run_inventory.sh" >> "$RUN_LOG" 2>&1

if [[ ! -s "$WORK_DIR/hosts_up_${DATE_TAG}.txt" ]]; then
  log "Nessun host up trovato. Niente da sincronizzare."
  exit 0
fi

###############################################################################
# 2) UDP
###############################################################################

log "Eseguo enrichment UDP"
"$BASE_DIR/run_udp_enrichment.sh" >> "$RUN_LOG" 2>&1

MERGED_JSON="$WORK_DIR/normalized_assets_merged_${DATE_TAG}.json"
check_file "$MERGED_JSON"

# I push sono indipendenti: un errore su uno non blocca l'altro
FAILED=()

###############################################################################
# 3) PUSH FINALE SU NETBOX
###############################################################################

if [[ "$PUSH_TO_NETBOX" == "true" ]]; then
  log "Eseguo push finale su NetBox dal merged JSON"
  if /usr/bin/python3 "$SCRIPT_DIR/push_to_netbox.py" \
    --input "$MERGED_JSON" \
    >> "$LOG_DIR/netbox_sync_${DATE_TAG}.log" 2>&1; then
    log "Push NetBox completato con successo"
  else
    log "[WARN] Push NetBox fallito. Controlla il log: $LOG_DIR/netbox_sync_${DATE_TAG}.log"
    FAILED+=("NetBox")
  fi
else
  log "Push su NetBox DISABILITATO - salto sync"
fi

###############################################################################
# 4) PUSH FINALE SU GLPI
###############################################################################

if [[ "$PUSH_TO_GLPI" == "true" ]]; then
  check_file "$GLPI_SCRIPT"

  if [[ -x "$GLPI_VENV_PY" ]]; then
    GLPI_PY="$GLPI_VENV_PY"
    log "Uso Python del virtualenv GLPI: $GLPI_PY"
  else
    GLPI_PY="/usr/bin/python3"
    log "Virtualenv GLPI non trovato, provo con Python di sistema: $GLPI_PY"
  fi

  log "Eseguo push finale su GLPI dal merged JSON"
  if (
    cd "$GLPI_DIR"
    "$GLPI_PY" "$GLPI_SCRIPT" \
      -i "$MERGED_JSON" \
      -f json
  ) >> "$LOG_DIR/glpi_sync_${DATE_TAG}.log" 2>&1; then
    log "Push GLPI completato con successo"
  else
    log "[WARN] Push GLPI fallito. Controlla il log: $LOG_DIR/glpi_sync_${DATE_TAG}.log"
    FAILED+=("GLPI")
  fi
else
  log "Push su GLPI DISABILITATO - salto sync"
fi

if (( ${#FAILED[@]} > 0 )); then
  log "run_all_inventory completato con errori su: ${FAILED[*]}"
  log "Run log: $RUN_LOG"
  exit 1
fi

log "run_all_inventory completato con successo"
log "Run log: $RUN_LOG"
