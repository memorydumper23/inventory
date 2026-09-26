#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_DIR="$BASE_DIR/scripts"
SCAN_DIR="$BASE_DIR/scans"
WORK_DIR="$BASE_DIR/work"
LOG_DIR="$BASE_DIR/logs"

# nmap gira come root solo attraverso questo wrapper (vedi deploy/inventory-nmap)
NMAP_WRAPPER="/usr/local/sbin/inventory-nmap"

DATE_TAG="${DATE_TAG:-$(date +%F)}"
RUN_LOG="$LOG_DIR/run_udp_${DATE_TAG}.log"

# Porte UDP "importanti"
UDP_PORTS="53,67,68,69,123,161,500,514,520,1900,5353,5683"

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

mkdir -p "$SCRIPT_DIR" "$SCAN_DIR" "$WORK_DIR" "$LOG_DIR"

check_bin /usr/bin/nmap
check_bin /usr/bin/python3
check_bin "$NMAP_WRAPPER"

check_file "$SCRIPT_DIR/extract_open_ports.py"
check_file "$SCRIPT_DIR/build_portspec_from_xml.py"
check_file "$SCRIPT_DIR/normalize_for_netbox.py"
check_file "$SCRIPT_DIR/merge_assets_json.py"

# File prodotti dalla pipeline TCP principale
check_file "$WORK_DIR/hosts_up_${DATE_TAG}.txt"
check_file "$SCAN_DIR/hosts_up_${DATE_TAG}.xml"
check_file "$WORK_DIR/normalized_assets_${DATE_TAG}.json"

log "Avvio enrichment UDP"

###############################################################################
# 1) UDP PORT DISCOVERY
###############################################################################

log "Port discovery UDP sugli host trovati"
sudo -n "$NMAP_WRAPPER" udp-ports "$UDP_PORTS" \
  < "$WORK_DIR/hosts_up_${DATE_TAG}.txt" \
  > "$SCAN_DIR/open_ports_udp_${DATE_TAG}.xml"

log "Estrazione porte UDP candidate in JSON"
/usr/bin/python3 "$SCRIPT_DIR/extract_open_ports.py" \
  --input "$SCAN_DIR/open_ports_udp_${DATE_TAG}.xml" \
  --output "$WORK_DIR/open_ports_udp_${DATE_TAG}.json"

###############################################################################
# 2) COSTRUZIONE PORTSPEC UDP DALLE PORTE CANDIDATE
###############################################################################

log "Costruzione portspec UDP dalle porte candidate"
UDP_SERVICE_PORTSPEC=$(/usr/bin/python3 "$SCRIPT_DIR/build_portspec_from_xml.py" \
  --input "$SCAN_DIR/open_ports_udp_${DATE_TAG}.xml" \
  --protocol udp)

if [[ -z "${UDP_SERVICE_PORTSPEC}" ]]; then
  log "Nessuna porta UDP candidata trovata."

  # Creo un JSON UDP vuoto e il merged uguale al TCP
  cat > "$WORK_DIR/normalized_assets_udp_${DATE_TAG}.json" <<'EOF'
{
  "assets": []
}
EOF

  cp "$WORK_DIR/normalized_assets_${DATE_TAG}.json" \
     "$WORK_DIR/normalized_assets_merged_${DATE_TAG}.json"

  log "Creato JSON UDP vuoto."
  log "Creato merged uguale al JSON TCP."
  log "Enrichment UDP completato."
  exit 0
fi

log "Portspec UDP per service detection: $UDP_SERVICE_PORTSPEC"

###############################################################################
# 3) UDP SERVICE / VERSION DETECTION SOLO SULLE PORTE CANDIDATE
###############################################################################

log "Service/version detection UDP sulle sole porte candidate"
sudo -n "$NMAP_WRAPPER" udp-services "$UDP_SERVICE_PORTSPEC" \
  < "$WORK_DIR/hosts_up_${DATE_TAG}.txt" \
  > "$SCAN_DIR/services_udp_${DATE_TAG}.xml"

log "Normalizzazione dei risultati UDP"
/usr/bin/python3 "$SCRIPT_DIR/normalize_for_netbox.py" \
  --hosts "$SCAN_DIR/hosts_up_${DATE_TAG}.xml" \
  --ports "$SCAN_DIR/open_ports_udp_${DATE_TAG}.xml" \
  --services "$SCAN_DIR/services_udp_${DATE_TAG}.xml" \
  --output "$WORK_DIR/normalized_assets_udp_${DATE_TAG}.json"

###############################################################################
# 4) MERGE TCP + UDP
###############################################################################

log "Merge dei risultati TCP e UDP"
/usr/bin/python3 "$SCRIPT_DIR/merge_assets_json.py" \
  --tcp "$WORK_DIR/normalized_assets_${DATE_TAG}.json" \
  --udp "$WORK_DIR/normalized_assets_udp_${DATE_TAG}.json" \
  --output "$WORK_DIR/normalized_assets_merged_${DATE_TAG}.json"

log "Enrichment UDP completato"
log "Output UDP: $WORK_DIR/normalized_assets_udp_${DATE_TAG}.json"
log "Output merged: $WORK_DIR/normalized_assets_merged_${DATE_TAG}.json"
log "Run log: $RUN_LOG"