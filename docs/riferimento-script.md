# Riferimento script

Tutti gli script bash usano `set -euo pipefail`: un comando che fallisce interrompe lo
script. Gli script Python scrivono gli errori su standard error ed escono con codice `1`.

## `nmap/run_all_inventory.sh`

Punto di ingresso della pipeline. Non accetta argomenti.

```bash
sudo -u inventory /opt/inventory/nmap/run_all_inventory.sh
```

**Variabili lette** (dall'ambiente o da `netbox.env`): `PUSH_TO_NETBOX` (predefinito
`true`), `PUSH_TO_GLPI` (predefinito `true`), `GLPI_DIR`. Esporta `DATE_TAG` con la data
di avvio, usata da tutte le fasi.

**Sequenza**

1. Crea `logs/` e `work/` se mancano.
2. Acquisisce il lock `/tmp/run_all_inventory.lock` con `flock -n`. Se un'altra
   esecuzione lo tiene, scrive un errore ed esce con `1`. Il lock si libera da solo
   quando il processo termina, anche in caso di crash.
3. Carica `netbox.env` se esiste.
4. Esegue `run_inventory.sh` con `INVENTORY_RUN_ALL=1`, che gli impedisce di inviare
   dati a NetBox (l'invio avviene una volta sola, al passo 8, con TCP e UDP). L'output
   viene accodato al log principale.
5. Se `work/hosts_up_<data>.txt` è vuoto: nessun host trovato, esce con `0`.
6. Esegue `run_udp_enrichment.sh`.
7. Verifica che esista `work/normalized_assets_merged_<data>.json`.
8. Se `PUSH_TO_NETBOX` è `true`, esegue `scripts/push_to_netbox.py` con il JSON unito;
   l'output va in `logs/netbox_sync_<data>.log`. Un errore viene registrato ma non
   interrompe la pipeline.
9. Se `PUSH_TO_GLPI` è `true`, esegue l'adapter GLPI dalla sua cartella, con il Python
   di `.venv` se esiste o con `/usr/bin/python3` altrimenti; l'output va in
   `logs/glpi_sync_<data>.log`. Anche qui un errore viene registrato e basta.
10. Esce con `1` se almeno un push è fallito, con `0` altrimenti.

## `nmap/run_inventory.sh`

Fasi TCP: ricerca host, porte, servizi. Non accetta argomenti.

**Controlli iniziali**: devono esistere `/usr/bin/nmap`, `/usr/bin/python3`, il wrapper
`/usr/local/sbin/inventory-nmap`, gli script Python necessari e `targets.txt`. Se manca
qualcosa esce con `1` indicando cosa.

**Variabili lette**: `DATE_TAG` (predefinita: la data odierna), `PUSH_TO_NETBOX`
(predefinita `false`), `ANSIBLE_INVENTORY_FILE`, più tutto `netbox.env`.
`INVENTORY_RUN_ALL=1`, impostata da `run_all_inventory.sh`, disattiva l'invio a NetBox
qualunque sia il valore di `PUSH_TO_NETBOX`.

**Sequenza**

1. `sudo -n inventory-nmap discovery < targets.txt > scans/hosts_up_<data>.xml`
2. `extract_hosts.py` → `work/hosts_up_<data>.txt`
3. Se `ANSIBLE_INVENTORY_FILE` non è vuota: `update_ansible_hosts_yml.py` aggiorna
   l'inventario Ansible.
4. Se non ci sono host: esce con `0`.
5. `sudo -n inventory-nmap tcp-ports < hosts_up.txt > scans/open_ports_<data>.xml`
6. `extract_open_ports.py` → `work/open_ports_<data>.json` (per consultazione).
7. `build_portspec_from_xml.py --protocol tcp` calcola l'elenco delle porte TCP aperte
   su almeno un host.
8. Se l'elenco è vuoto: produce `work/normalized_assets_<data>.json` con gli host senza
   servizi ed esce con `0`.
9. `sudo -n inventory-nmap tcp-services <porte> < hosts_up.txt > scans/services_<data>.xml`
10. `normalize_for_netbox.py` unisce i tre XML → `work/normalized_assets_<data>.json`
11. Se `PUSH_TO_NETBOX` è `true` e lo script è stato lanciato da solo: invia il JSON TCP
    a NetBox.

`sudo -n` fa fallire subito il comando se sudo chiederebbe una password, invece di
restare in attesa: in cron non c'è nessuno a rispondere.

## `nmap/run_udp_enrichment.sh`

Fasi UDP e unione. Non accetta argomenti. Richiede i file prodotti dalla fase TCP con
lo stesso `DATE_TAG`: `work/hosts_up_<data>.txt`, `scans/hosts_up_<data>.xml` e
`work/normalized_assets_<data>.json`.

**Sequenza**

1. `sudo -n inventory-nmap udp-ports <UDP_PORTS> < hosts_up.txt > scans/open_ports_udp_<data>.xml`
2. `extract_open_ports.py` → `work/open_ports_udp_<data>.json` (per consultazione).
3. `build_portspec_from_xml.py --protocol udp` calcola le porte UDP candidate (`open` o
   `open|filtered`) su almeno un host.
4. Se non ce ne sono: scrive un `work/normalized_assets_udp_<data>.json` vuoto, copia il
   JSON TCP in `work/normalized_assets_merged_<data>.json` ed esce con `0`.
5. `sudo -n inventory-nmap udp-services <porte> < hosts_up.txt > scans/services_udp_<data>.xml`
6. `normalize_for_netbox.py` → `work/normalized_assets_udp_<data>.json`
7. `merge_assets_json.py` unisce TCP e UDP → `work/normalized_assets_merged_<data>.json`

## `deploy/inventory-nmap`

Wrapper eseguito come root tramite sudo. È l'unico comando che la regola sudoers
concede all'utente di servizio.

```bash
sudo inventory-nmap <profilo> [porte] < target > risultato.xml
```

**Protezioni**

- Ambiente ripulito: `PATH` fisso, `HOME=/root`, `NMAPDIR` rimossa, così Nmap usa solo
  i propri file di sistema.
- Target letti da standard input (`-iL -`) e XML scritto su standard output (`-oX -`):
  Nmap non apre nessun file.
- I profili senza porte rifiutano qualunque argomento. Dove sono previste, le porte
  devono rispettare `^[0-9]{1,5}(,[0-9]{1,5})*$`: solo cifre separate da virgole, senza
  spazi, trattini o opzioni.
- Qualunque profilo sconosciuto o argomento non valido termina con codice `2` e un
  messaggio su standard error, prima di avviare Nmap.

**Profili**

| Profilo | Argomento | Comando eseguito |
|---|---|---|
| `discovery` | nessuno | `nmap -PR -sn -n -iL - -oX -` |
| `tcp-ports` | nessuno | `nmap -sS -Pn -n -p- --host-timeout 10m --min-hostgroup 4 --max-hostgroup 10 --min-rate 5000 -iL - -oX -` |
| `tcp-services` | porte | `nmap -sV -Pn -n --version-light -p <porte> -iL - -oX -` |
| `udp-ports` | porte | `nmap -sU -Pn -n -T4 --max-retries 2 -p <porte> -iL - -oX -` |
| `udp-services` | porte | `nmap -sU -sV -Pn -n -T4 --version-light --max-retries 1 -p <porte> -iL - -oX -` |

**Significato delle opzioni**

| Opzione | Effetto |
|---|---|
| `-PR` | Ricerca host via ARP sulle subnet collegate direttamente. Sulle subnet remote Nmap usa le sonde standard: ping ICMP, TCP SYN sulla 443, TCP ACK sulla 80, ICMP timestamp |
| `-sn` | Solo ricerca host, nessuna scansione di porte |
| `-n` | Nessuna risoluzione DNS |
| `-Pn` | Salta la ricerca host e considera attivi tutti i target (sono già stati trovati nella prima fase) |
| `-sS` | Scansione TCP SYN ("half-open"): non completa la connessione |
| `-p-` | Tutte le porte da 1 a 65535 |
| `-p <porte>` | Solo le porte indicate |
| `--host-timeout 10m` | Abbandona un host dopo 10 minuti; l'host resta nei risultati ma senza porte |
| `--min-hostgroup 4 --max-hostgroup 10` | Scansiona da 4 a 10 host in parallelo |
| `--min-rate 5000` | Invia almeno 5.000 pacchetti al secondo sull'intera scansione |
| `-sV` | Riconosce servizio e versione in ascolto su ogni porta |
| `--version-light` | Riconoscimento leggero (intensità 2 invece di 7): più veloce, riconosce meno servizi rari |
| `-sU` | Scansione UDP |
| `-T4` | Temporizzazione aggressiva, adatta a reti veloci e affidabili |
| `--max-retries N` | Al massimo N ritrasmissioni per sonda |
| `-iL -` | Legge i target da standard input |
| `-oX -` | Scrive il risultato in XML su standard output (l'output testuale normale viene soppresso) |

## `deploy/sudoers-inventory`

Regola da installare in `/etc/sudoers.d/inventory`:

```
Defaults!/usr/local/sbin/inventory-nmap !requiretty
inventory ALL=(root) NOPASSWD: /usr/local/sbin/inventory-nmap
```

La prima riga permette l'uso da cron anche sulle distribuzioni che richiedono un
terminale per sudo (`requiretty`). La seconda concede all'utente `inventory`, senza
password, solo il wrapper. La validazione degli argomenti è nel wrapper e non nella
regola, per il motivo spiegato in [Sicurezza](sicurezza.md#perché-un-wrapper-e-non-una-regola-sudo-su-nmap).

## Script Python in `nmap/scripts/`

Vengono eseguiti con `/usr/bin/python3`.

### `scripts/extract_hosts.py`

```bash
extract_hosts.py --input <xml ricerca host> --output <file txt>
```

Legge gli host con stato `up` e ne prende il primo indirizzo IPv4. Scrive un IP per
riga, senza duplicati, in ordine alfabetico del testo.

### `scripts/extract_open_ports.py`

```bash
extract_open_ports.py --input <xml porte> --output <file json>
```

Produce `{"assets": [{"ip": ..., "ports": [{"port", "protocol", "state", "service"}]}]}`
con le porte interessanti: `open` per TCP, `open` o `open|filtered` per UDP. Include
anche gli host senza porte. Nella pipeline il risultato serve solo per consultazione.

### `scripts/build_portspec_from_xml.py`

```bash
build_portspec_from_xml.py --input <xml porte> [--protocol tcp|udp|both]
```

Stampa su standard output l'elenco delle porte interessanti trovate su qualunque host
del file, ordinate e separate da virgole (`22,80,443`). Con `--protocol both`
(predefinito) stampa `T:22,80,U:53,161`. Se non ci sono porte stampa una riga vuota.

### `scripts/normalize_for_netbox.py`

```bash
normalize_for_netbox.py --hosts <xml ricerca host> --ports <xml porte> \
  --services <xml servizi> --output <file json>
```

Costruisce il [JSON normalizzato](architettura.md#json-normalizzato) a partire da tre XML:

1. dalla ricerca host prende gli host `up` con IPv4 e l'eventuale hostname;
2. dalla scansione porte aggiunge le porte interessanti con il nome del servizio;
3. dalla scansione servizi aggiunge prodotto, versione e informazioni aggiuntive.

Un host presente nelle scansioni ma non nella ricerca host viene aggiunto senza
hostname. Le voci con stessa porta e protocollo vengono unite: `open` prevale su
`open|filtered` e i campi non vuoti della scansione successiva sovrascrivono i
precedenti. Nonostante il nome, il risultato è usato anche per GLPI.

### `scripts/merge_assets_json.py`

```bash
merge_assets_json.py --tcp <json tcp> --udp <json udp> --output <file json>
```

Unisce due JSON normalizzati per IP, con la stessa regola di unione dei servizi.
L'hostname viene dal JSON TCP, oppure da quello UDP se il primo non lo ha.

### `scripts/push_to_netbox.py`

```bash
push_to_netbox.py --input <json normalizzato>
```

**Configurazione**: carica `nmap/netbox.env` senza sovrascrivere le variabili già
presenti nell'ambiente. Richiede `NETBOX_URL` e `NETBOX_TOKEN` (non vuoti e diversi da
`CHANGE_ME`), altrimenti esce con `1`.

**Autenticazione**: header `Authorization: Bearer <token>` per i token che iniziano con
`nbt_`, `Authorization: Token <token>` per gli altri.

**Per ogni host del JSON**:

1. Calcola l'indirizzo `IP/32` (`IP/128` per IPv6).
2. Cerca in NetBox un IP Address con esattamente quell'indirizzo:
   `GET /api/ipam/ip-addresses/?address=<ip>/32`.
3. Se non esiste lo crea (`POST`) con indirizzo, stato, descrizione, campi
   personalizzati e, se l'host ha un hostname, `dns_name`:

   ```json
   {
     "address": "192.0.2.10/32",
     "status": "active",
     "description": "Scan di Nmap",
     "custom_fields": {
       "porte_tcp": "22, 80",
       "porte_udp": "161?",
       "servizi_dettaglio": "SSH (22/tcp) - OpenSSH 9.x protocol 2.0\n\nHTTP (80/tcp) - NGINX\n\nSNMP (161/udp) - candidate"
     }
   }
   ```

   Se esiste lo aggiorna (`PATCH`) inviando solo i campi personalizzati, così stato,
   descrizione e nome DNS curati a mano restano invariati:

   ```json
   {
     "custom_fields": {
       "porte_tcp": "22, 80",
       "porte_udp": "161?",
       "servizi_dettaglio": "SSH (22/tcp) - OpenSSH 9.x protocol 2.0\n\nHTTP (80/tcp) - NGINX\n\nSNMP (161/udp) - candidate"
     }
   }
   ```

4. Scrive `[UPDATE] <indirizzo>` o `[CREATE] <indirizzo>`. Un errore su un host viene
   registrato e lo script passa al successivo.

Alla fine scrive `Completato. Asset: N | Errori: N` ed esce con `1` se ci sono errori.

**Regole di formattazione**

- `porte_tcp`: porte TCP in ordine numerico, separate da virgola e spazio.
- `porte_udp`: porte UDP in ordine numerico; quelle `open|filtered` hanno un `?` in coda.
- `servizi_dettaglio`: un servizio per riga, con una riga vuota tra un servizio e l'altro.
  Formato `ETICHETTA (porta/protocollo) - prodotto versione info`. Se non ci sono
  dettagli compare solo `ETICHETTA (porta/protocollo)`, oppure `- candidate` per le
  porte UDP `open|filtered`.

**Quali servizi compaiono in `servizi_dettaglio`**

1. I nomi vengono normalizzati: `domain` → `dns`; `dhcps` e `bootps` → `dhcp`;
   `dhcpc` e `bootpc` → `dhcp-client`; `microsoft-ds` → `smb`; `netbios-ssn` → `netbios`.
2. `unknown` e `tcpwrapped` sono sempre esclusi.
3. Un servizio con prodotto, versione o informazioni aggiuntive è sempre incluso.
4. Senza dettagli è incluso solo se il nome normalizzato è uno di: `ssh`, `http`,
   `https`, `dns`, `dhcp`, `dhcp-client`, `ntp`, `snmp`, `isakmp`, `syslog`, `zeroconf`,
   `mdns`, `upnp`, `ldap`, `ldaps`, `smb`, `netbios`, `rpcbind`, `nfs`, `msrpc`, `rdp`,
   `winbox`, `bandwidth-test`, `sip`, `sip-tls`, `ipp`, `printer`, `amqp`.

Le porte escluse dal dettaglio restano comunque in `porte_tcp` e `porte_udp`.

**Etichette**: i nomi noti diventano etichette leggibili (`SSH`, `HTTP`, `DNS`,
`DHCP Client`, `SMB`, `NetBIOS`, `mDNS`, `UPnP`, `Winbox`…); gli altri vengono scritti in
maiuscolo. Alcuni prodotti vengono uniformati: `nginx` → `NGINX`, `Apache httpd` →
`Apache`, `MikroTik bandwidth-test server` → `MikroTik Bandwidth Test`,
`MikroTik RouterOS Winbox` → `MikroTik Winbox`.

### `scripts/update_ansible_hosts_yml.py`

```bash
update_ansible_hosts_yml.py --input <file txt, un host per riga> --inventory <hosts.yml>
```

Crea il file se non esiste. Garantisce la struttura `all.vars` e `all.hosts`, aggiunge
sotto `all.hosts` ogni host non ancora presente e riordina gli host. Non rimuove mai
host e non tocca variabili e gruppi esistenti. Il file viene riscritto per intero con
PyYAML: i commenti vanno persi. Richiede PyYAML (`python3-yaml`).

## `glpi-nmap-adapter/nmap_to_glpi_nmap_asset.py`

```bash
nmap_to_glpi_nmap_asset.py -i <json> -f json [--dry-run] [--only-ip IP] [-v]
```

| Argomento | Obbligatorio | Effetto |
|---|---|---|
| `-i`, `--input` | Sì | File JSON da inviare |
| `-f`, `--format` | Sì | Formato dell'input; l'unico valore ammesso è `json` |
| `--dry-run` | No | Stampa i dati che verrebbero inviati senza contattare GLPI. Non richiede credenziali e non modifica il file di stato |
| `--only-ip IP` | No | Elabora solo l'host con quell'IP; se non c'è, termina senza fare nulla |
| `-v`, `--verbose` | No | Stampa endpoint e dati di ogni richiesta di creazione o aggiornamento |

**Input accettati**: oltre al JSON normalizzato della pipeline, lo script accetta una
lista di host oppure un oggetto con la lista sotto `hosts`, `assets`, `results`, `data`,
`items` o `devices`, oppure un dizionario di host. Per ogni host cerca l'IP nei campi
`ip`, `ipv4`, `address`, `primary_ip`, `ip_address` (o `network.ip`) e le porte in
`ports`, `open_ports` o `services`. Gli host senza IP vengono ignorati; se non ne resta
nessuno lo script termina con errore.

**Dati inviati per ogni host**

```json
{
  "name": "192.0.2.10",
  "custom_tcp_ports": "22,80",
  "custom_udp_ports": "161",
  "custom_services": "• 22/ssh [OpenSSH 9.x protocol 2.0]\n• 80/http [nginx]\n• 161/snmp"
}
```

I nomi dei tre campi sono quelli di `FIELD_TCP_KEY`, `FIELD_UDP_KEY` e
`FIELD_SERVICES_KEY`. Le porte sono in ordine numerico, separate da virgola senza
spazi. Il campo servizi ha una riga per porta, con `unknown` quando il servizio non è
stato riconosciuto.

**Sequenza**

1. Legge la configurazione (vedi [Configurazione](configurazione.md#glpi-nmap-adapterenv))
   e il file JSON.
2. Tranne che in `--dry-run`: verifica le credenziali e apre una sessione
   (`GET /initSession` con autenticazione HTTP Basic e header `App-Token`). Se il login
   fallisce scrive `[ERRORE] initSession HTTP <codice>: <risposta di GLPI>` ed esce con `1`.
3. Per ogni host:
   - se il file di stato contiene già un ID per quell'IP, aggiorna l'asset
     (`PUT /<itemtype>/<id>`); se GLPI risponde 404 (asset non più esistente), ne crea
     uno nuovo;
   - altrimenti crea l'asset (`POST /<itemtype>`);
   - dopo ogni creazione salva il nuovo ID nel file di stato;
   - scrive `[OK] <ip> -> HTTP <codice> -> <risposta>` oppure `[KO] ...`; un'eccezione
     produce `[EXC] <ip> -> <errore>` e lo script passa all'host successivo.
4. Chiude la sessione (`GET /killSession`), anche in caso di errore.
5. Scrive `Completato. Successi: N | Errori: N` ed esce con `1` se ci sono errori.

Le richieste usano `{"input": {...}}` come corpo, il formato dell'API Legacy.
