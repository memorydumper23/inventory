#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_DIR="$BASE_DIR/scripts"
SCAN_DIR="$BASE_DIR/scans"
WORK_DIR="$BASE_DIR/work"
LOG_DIR="$BASE_DIR/logs"

# nmap gira come root solo attraverso questo wrapper (vedi deploy/inventory-nmap)
NMAP_WRAPPER="/usr/local/sbin/inventory-nmap"

TARGET_SUBNET="$BASE_DIR/targets.txt"
DATE_TAG="${DATE_TAG:-$(date +%F)}"
RUN_LOG="$LOG_DIR/run_${DATE_TAG}.log"

# true = abilita push su NetBox (solo se lo script è lanciato da solo)
# false = genera solo i file
PUSH_TO_NETBOX="${PUSH_TO_NETBOX:-false}"

mkdir -p "$SCRIPT_DIR" "$SCAN_DIR" "$WORK_DIR" "$LOG_DIR"

log() {
  echo "[$(date '+%F %T')] $*" | tee -a "$RUN_LOG"
}

check_bin() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "[ERRORE] Comando non trovato: $1" >&2
    exit 1
  fi
}

check_file() {
  if [[ ! -f "$1" ]]; then
    echo "[ERRORE] File mancante: $1" >&2
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
  echo "[ERRORE] File mancante: $TARGET_SUBNET (copia targets.txt.example in targets.txt e inserisci le tue subnet)" >&2
  exit 1
fi

# Carica variabili ambiente NetBox se presenti
if [[ -f "$BASE_DIR/netbox.env" ]]; then
  # shellcheck disable=SC1090
  source "$BASE_DIR/netbox.env"
fi

# Lanciato da run_all_inventory.sh: il push su NetBox lo fa lui alla fine, con i
# dati TCP + UDP. Va deciso dopo netbox.env, che potrebbe impostare PUSH_TO_NETBOX
if [[ "${INVENTORY_RUN_ALL:-}" == "1" ]]; then
  PUSH_TO_NETBOX="false"
fi

log "Avvio pipeline inventory TCP"

###############################################################################
# 1) HOST DISCOVERY
###############################################################################

log "Host discovery su $TARGET_SUBNET"
sudo -n "$NMAP_WRAPPER" discovery \
  < "$TARGET_SUBNET" \
  > "$SCAN_DIR/hosts_up_${DATE_TAG}.xml"

/usr/bin/python3 "$SCRIPT_DIR/extract_hosts.py" \
  --input "$SCAN_DIR/hosts_up_${DATE_TAG}.xml" \
  --output "$WORK_DIR/hosts_up_${DATE_TAG}.txt"

# Opzionale: impostare ANSIBLE_INVENTORY_FILE (es. in netbox.env)
ANSIBLE_INV_FILE="${ANSIBLE_INVENTORY_FILE:-}"

if [[ -n "$ANSIBLE_INV_FILE" ]]; then
  log "Aggiornamento inventory Ansible"
  /usr/bin/python3 "$SCRIPT_DIR/update_ansible_hosts_yml.py" \
    --input "$WORK_DIR/hosts_up_${DATE_TAG}.txt" \
    --inventory "$ANSIBLE_INV_FILE"

  log "Inventory Ansible aggiornata: $ANSIBLE_INV_FILE"
else
  log "ANSIBLE_INVENTORY_FILE non impostata - salto aggiornamento inventory Ansible"
fi

if [[ ! -s "$WORK_DIR/hosts_up_${DATE_TAG}.txt" ]]; then
  log "Nessun host up trovato. Esco."
  exit 0
fi

log "Host trovati:"
wc -l "$WORK_DIR/hosts_up_${DATE_TAG}.txt" | tee -a "$RUN_LOG"

###############################################################################
# 2) PORT DISCOVERY TCP
###############################################################################   

log "Port discovery TCP sugli host trovati"
sudo -n "$NMAP_WRAPPER" tcp-ports \
  < "$WORK_DIR/hosts_up_${DATE_TAG}.txt" \
  > "$SCAN_DIR/open_ports_${DATE_TAG}.xml"

/usr/bin/python3 "$SCRIPT_DIR/extract_open_ports.py" \
  --input "$SCAN_DIR/open_ports_${DATE_TAG}.xml" \
  --output "$WORK_DIR/open_ports_${DATE_TAG}.json"

###############################################################################
# 3) COSTRUZIONE PORTSPEC DALLE PORTE APERTE
###############################################################################

log "Costruzione portspec TCP dalle porte aperte"
SERVICE_PORTSPEC=$(/usr/bin/python3 "$SCRIPT_DIR/build_portspec_from_xml.py" \
  --input "$SCAN_DIR/open_ports_${DATE_TAG}.xml" \
  --protocol tcp)

if [[ -z "${SERVICE_PORTSPEC}" ]]; then
  log "Nessuna porta TCP aperta trovata: salto service detection TCP"

  # JSON comunque generato (host senza servizi) per le fasi successive
  /usr/bin/python3 "$SCRIPT_DIR/normalize_for_netbox.py" \
    --hosts "$SCAN_DIR/hosts_up_${DATE_TAG}.xml" \
    --ports "$SCAN_DIR/open_ports_${DATE_TAG}.xml" \
    --services "$SCAN_DIR/open_ports_${DATE_TAG}.xml" \
    --output "$WORK_DIR/normalized_assets_${DATE_TAG}.json"

  log "Pipeline TCP completata"
  exit 0
fi

log "Portspec per service detection TCP: $SERVICE_PORTSPEC"

###############################################################################
# 4) SERVICE / VERSION DETECTION SOLO SULLE PORTE APERTE
###############################################################################

log "Service/version detection TCP sulle sole porte aperte"
sudo -n "$NMAP_WRAPPER" tcp-services "$SERVICE_PORTSPEC" \
  < "$WORK_DIR/hosts_up_${DATE_TAG}.txt" \
  > "$SCAN_DIR/services_${DATE_TAG}.xml"

/usr/bin/python3 "$SCRIPT_DIR/normalize_for_netbox.py" \
  --hosts "$SCAN_DIR/hosts_up_${DATE_TAG}.xml" \
  --ports "$SCAN_DIR/open_ports_${DATE_TAG}.xml" \
  --services "$SCAN_DIR/services_${DATE_TAG}.xml" \
  --output "$WORK_DIR/normalized_assets_${DATE_TAG}.json"

###############################################################################
# 5) SYNC SU NETBOX
###############################################################################

if [[ "$PUSH_TO_NETBOX" == "true" ]]; then
  log "Sync su NetBox"
  /usr/bin/python3 "$SCRIPT_DIR/push_to_netbox.py" \
    --input "$WORK_DIR/normalized_assets_${DATE_TAG}.json" \
    >> "$LOG_DIR/netbox_sync_${DATE_TAG}.log" 2>&1
else
  log "Push su NetBox DISABILITATO - salto sync"
fi

log "Pipeline TCP completata"
log "Run log: $RUN_LOG"