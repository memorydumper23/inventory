# Configurazione

## Panoramica

| File | Si crea da | Letto da | Permessi |
|---|---|---|---|
| `nmap/targets.txt` | `nmap/targets.txt.example` | `run_inventory.sh` | `644` o più restrittivi |
| `nmap/netbox.env` | `nmap/netbox.env.example` | tutti gli script bash (con `source`) e `push_to_netbox.py` | `600`, proprietario `inventory` |
| `glpi-nmap-adapter/.env` | `glpi-nmap-adapter/.env.example` | `nmap_to_glpi_nmap_asset.py` | `600`, proprietario `inventory` |

Nessuno di questi file è tracciato da git. Gli script rifiutano di partire se una
credenziale obbligatoria manca o vale ancora `CHANGE_ME`.

## `nmap/targets.txt`

Elenco di cosa scansionare. Nmap lo riceve così com'è (dal wrapper, via standard input),
quindi vale la sintassi dei target di Nmap:

```
# sede principale
192.0.2.0/24
# range parziale
198.51.100.10-50
# singolo host
203.0.113.7
# per nome: l'hostname finirà in NetBox (dns_name)
server01.example.internal
```

- Una voce per riga (sono ammessi anche spazi come separatore).
- I commenti iniziano con `#`, anche in coda alla riga.
- Sono ammessi indirizzi singoli, notazione CIDR, intervalli (`198.51.100.10-50`,
  `192.0.2.1,5,9`) e nomi host.
- Non esiste una sintassi di esclusione: per saltare alcuni host elenca solo gli
  intervalli da includere.
- Gli hostname vengono registrati solo per i target scritti per nome: le scansioni
  usano `-n` e non fanno risoluzioni DNS inverse.
- Scansiona solo reti di tua proprietà o per cui hai un'autorizzazione esplicita.

## `nmap/netbox.env`

Nonostante il nome, contiene tutte le opzioni della pipeline oltre a quelle di NetBox.

| Variabile | Predefinito | Obbligatoria | Descrizione |
|---|---|---|---|
| `NETBOX_URL` | nessuno | Sì, se push NetBox attivo | URL base di NetBox, senza `/api` (per esempio `https://netbox.example.com`) |
| `NETBOX_TOKEN` | nessuno | Sì, se push NetBox attivo | Token API (vedi [Installazione](installazione.md#token-api)) |
| `NETBOX_VERIFY_SSL` | `true` | No | Verifica del certificato TLS. `0`, `false`, `no` e `off` la disattivano: da usare solo temporaneamente |
| `NETBOX_CF_TCP_PORTS` | `porte_tcp` | No | Nome del campo personalizzato per le porte TCP |
| `NETBOX_CF_UDP_PORTS` | `porte_udp` | No | Nome del campo personalizzato per le porte UDP |
| `NETBOX_CF_SERVICES_DETAIL` | `servizi_dettaglio` | No | Nome del campo personalizzato per i servizi |
| `ANSIBLE_INVENTORY_FILE` | vuota | No | Percorso di un `hosts.yml` da aggiornare con gli host trovati. Se vuota il passaggio viene saltato |
| `PUSH_TO_NETBOX` | `true` | No | `false` disattiva l'invio a NetBox |
| `PUSH_TO_GLPI` | `true` | No | `false` disattiva l'invio a GLPI |
| `GLPI_DIR` | `../glpi-nmap-adapter` rispetto a `nmap/` | No | Cartella dell'adapter GLPI, se l'hai spostata |

### Regole di scrittura

- Il file viene eseguito da bash (`source`): è codice, e chi può modificarlo può
  eseguire comandi come utente `inventory`. Tienilo con permessi `600`.
- Usa la forma `export NOME="valore"`. Racchiudi sempre i valori tra virgolette doppie.
- Non mettere commenti in coda alla riga: `push_to_netbox.py`, quando viene lanciato da
  solo, legge il file con un parser semplice che li includerebbe nel valore.
- `PUSH_TO_NETBOX` e `PUSH_TO_GLPI` valgono `true` se non impostate: basta scriverle per
  disattivare un invio (`"false"`). Lasciarle commentate permette di disattivarle anche
  per una singola esecuzione dalla riga di comando (vedi [Precedenza](#precedenza)).

### Precedenza

Le variabili già presenti nell'ambiente prevalgono su quelle di `netbox.env` quando
`push_to_netbox.py` viene lanciato da solo. Quando invece la pipeline parte da
`run_all_inventory.sh`, il file viene caricato con `source` e i suoi valori prevalgono.
Per questo `sudo -u inventory env PUSH_TO_GLPI=false /opt/inventory/nmap/run_all_inventory.sh`
disattiva l'invio a GLPI solo se `PUSH_TO_GLPI` non è impostata in `netbox.env`.

## `glpi-nmap-adapter/.env`

| Variabile | Predefinito | Obbligatoria | Descrizione |
|---|---|---|---|
| `GLPI_BASE_URL` | nessuno | Sì, se non c'è `GLPI_LEGACY_API_URL` | URL base di GLPI (per esempio `https://glpi.example.com`) |
| `GLPI_LEGACY_API_URL` | `${GLPI_BASE_URL}/apirest.php` | No | URL completo dell'API legacy, se diverso dal predefinito |
| `GLPI_API_USERNAME` | nessuno | Sì | Utente GLPI della pipeline |
| `GLPI_API_PASSWORD` | nessuno | Sì | Password dell'utente |
| `GLPI_LEGACY_APP_TOKEN` | vuoto | No, ma consigliato | Application token del client API. Vuoto: nessun header `App-Token`. `CHANGE_ME` viene rifiutato |
| `GLPI_ITEMTYPE` | `Glpi\CustomAsset\NmapAsset` | No | Tipo di asset GLPI in cui scrivere |
| `FIELD_TCP_KEY` | `tcp_ports` | No | Nome API del campo porte TCP. Nell'esempio: `custom_tcp_ports` |
| `FIELD_UDP_KEY` | `udp_ports` | No | Nome API del campo porte UDP. Nell'esempio: `custom_udp_ports` |
| `FIELD_SERVICES_KEY` | `services` | No | Nome API del campo servizi. Nell'esempio: `custom_services` |
| `STATE_FILE` | `glpi_nmap_state_legacy.json` | No | File di stato IP → ID GLPI. Un percorso relativo è riferito alla cartella dello script |
| `GLPI_HTTP_TIMEOUT` | `30` | No | Timeout delle richieste HTTP, in secondi |

I valori predefiniti dei tre nomi dei campi nel codice (`tcp_ports`, `udp_ports`,
`services`) sono diversi da quelli dell'esempio: vale quello che scrivi in `.env`.
Per trovare i nomi corretti vedi [Installazione → Verificare i nomi dei campi](installazione.md#verificare-i-nomi-dei-campi).

### Dove viene cercato il file e precedenza

Lo script cerca `.env` partendo dalla propria cartella e risalendo alle cartelle
superiori, indipendentemente dalla cartella da cui viene lanciato. Le variabili già
presenti nell'ambiente prevalgono su quelle del file.

### Certificati di una CA interna

Il virtualenv usa l'elenco di CA fornito con `requests`, non quello del sistema. Se GLPI
usa un certificato emesso da una CA interna, aggiungi a `.env`:

```
REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
```

dopo aver installato la CA nel sistema (su Debian: copiala in
`/usr/local/share/ca-certificates/` e lancia `sudo update-ca-certificates`). Gli script
NetBox usano il Python di sistema: sui pacchetti Debian/Ubuntu basta l'installazione
della CA nel sistema.

## Parametri fissi nel codice

Alcuni parametri non sono configurabili da file e vanno modificati nel codice.

| Parametro | Dove | Valore |
|---|---|---|
| Porte UDP scansionate | `nmap/run_udp_enrichment.sh`, variabile `UDP_PORTS` | `53,67,68,69,123,161,500,514,520,1900,5353,5683` |
| Opzioni di Nmap | `deploy/inventory-nmap` | vedi [Riferimento script](riferimento-script.md#deployinventory-nmap) |
| Percorso del wrapper | `nmap/run_inventory.sh`, `nmap/run_udp_enrichment.sh`, `deploy/sudoers-inventory` | `/usr/local/sbin/inventory-nmap` |
| File di lock | `nmap/run_all_inventory.sh` | `/tmp/run_all_inventory.lock` |
| Stato e descrizione dei nuovi IP in NetBox | `nmap/scripts/push_to_netbox.py` | `active`, `Scan di Nmap` |
| Timeout delle richieste NetBox | `nmap/scripts/push_to_netbox.py` | 30 secondi |

Le porte UDP predefinite:

| Porta | Servizio |
|---|---|
| 53 | DNS |
| 67, 68 | DHCP (server e client) |
| 69 | TFTP |
| 123 | NTP |
| 161 | SNMP |
| 500 | IKE/ISAKMP (VPN IPsec) |
| 514 | Syslog |
| 520 | RIP |
| 1900 | SSDP/UPnP |
| 5353 | mDNS |
| 5683 | CoAP (dispositivi IoT) |

Per cambiarle modifica `UDP_PORTS` mantenendo il formato: solo numeri separati da
virgole, senza spazi. Il wrapper rifiuta qualunque altro formato. Se modifichi le
opzioni di Nmap in `deploy/inventory-nmap`, ricorda di reinstallarlo in
`/usr/local/sbin/` (vedi [Installazione → Aggiornamento](installazione.md#aggiornamento)).

## Esempio completo

`nmap/netbox.env`:

```bash
export NETBOX_URL="https://netbox.example.com"
export NETBOX_TOKEN="<token>"
export NETBOX_VERIFY_SSL="true"

export NETBOX_CF_TCP_PORTS="porte_tcp"
export NETBOX_CF_UDP_PORTS="porte_udp"
export NETBOX_CF_SERVICES_DETAIL="servizi_dettaglio"

export ANSIBLE_INVENTORY_FILE="/home/inventory/ansible/hosts.yml"

# GLPI non ancora pronto: per ora solo NetBox
export PUSH_TO_GLPI="false"
```

`glpi-nmap-adapter/.env`:

```bash
GLPI_BASE_URL=https://glpi.example.com
GLPI_LEGACY_API_URL=
GLPI_API_USERNAME=svc-inventory
GLPI_API_PASSWORD=<password>
GLPI_LEGACY_APP_TOKEN=<application token>
GLPI_ITEMTYPE=Glpi\CustomAsset\NmapAsset
FIELD_TCP_KEY=custom_tcp_ports
FIELD_UDP_KEY=custom_udp_ports
FIELD_SERVICES_KEY=custom_services
STATE_FILE=glpi_nmap_state_legacy.json
GLPI_HTTP_TIMEOUT=30
```
