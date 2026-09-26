# Risoluzione problemi

Parti sempre da `nmap/logs/run_all_<data>.log`, poi guarda il log della fase che ha
fallito (vedi [Esecuzione → Log](esecuzione.md#log)).

## Permessi e sudo

### `sudo: a password is required`

**Causa**: la regola sudoers non è installata, riguarda un altro utente oppure il
comando non è esattamente `/usr/local/sbin/inventory-nmap`.

**Soluzione**: `sudo -l -U inventory` deve mostrare
`(root) NOPASSWD: /usr/local/sbin/inventory-nmap`. Se non compare, reinstalla la regola
(vedi [Installazione](installazione.md#4-wrapper-e-regola-sudo)) e controlla che
l'ultima riga contenga il nome giusto dell'utente di servizio.

### `[ERRORE] Comando non trovato: /usr/local/sbin/inventory-nmap`

**Causa**: il wrapper non è installato.

**Soluzione**: `sudo install -o root -g root -m 0755 deploy/inventory-nmap /usr/local/sbin/inventory-nmap`.

### `inventory-nmap: lista porte non valida` o `il profilo non accetta argomenti`

**Causa**: il wrapper ha ricevuto argomenti non ammessi. Nella pipeline succede solo se
hai modificato `UDP_PORTS` con un formato non valido (spazi, intervalli con trattino).

**Soluzione**: usa solo numeri separati da virgole, per esempio `53,123,161`.

### `/usr/bin/env: 'bash\r': No such file or directory`

**Causa**: gli script hanno fine riga Windows (CRLF), di solito perché la cartella è
stata copiata da un PC Windows invece di essere clonata sul server.

**Soluzione**: clona il repository direttamente sul server. Il file `.gitattributes`
forza i fine riga Linux anche su checkout Windows recenti. Per correggere una copia
esistente: `find /opt/inventory -name '*.sh' -exec sed -i 's/\r$//' {} +` (lo stesso
per `deploy/inventory-nmap` e i file `.py`).

### `Permission denied` scrivendo in `nmap/scans/`

**Causa**: esistono file scritti come root da una versione precedente della pipeline.

**Soluzione**: `sudo chown -R inventory: /opt/inventory/nmap`.

### `[ERRORE] Un'altra esecuzione è già in corso. Esco.`

**Causa**: un'altra esecuzione di `run_all_inventory.sh` è ancora attiva, per esempio
quella del cron precedente non ancora terminata.

**Soluzione**: attendi che finisca (`pgrep -af run_all_inventory`). Il lock si libera
da solo alla fine del processo: non va cancellato a mano. Se le esecuzioni si
sovrappongono spesso, distanziale nel cron o riduci i target.

## Scansione

### `[ERRORE] File mancante: .../nmap/targets.txt`

**Soluzione**: `cp nmap/targets.txt.example nmap/targets.txt` e inserisci le tue subnet.

### `Nessun host up trovato`

**Causa possibili**:

- target sbagliati in `targets.txt`;
- subnet remote in cui gli host non rispondono né al ping ICMP né alle sonde TCP sulle
  porte 80 e 443 (l'ARP funziona solo sulle subnet collegate direttamente);
- un firewall tra il server e le subnet filtra le sonde.

**Verifica**: `echo 192.0.2.10 | sudo -u inventory sudo -n /usr/local/sbin/inventory-nmap discovery`
su un host che sai essere attivo: nell'XML cerca `state="up"`.

### Tutti gli indirizzi di una subnet risultano attivi e la scansione dura ore

**Causa**: un firewall o un proxy risponde al posto degli host, anche per indirizzi
inesistenti (per esempio con un reset TCP sulla porta 80 o 443). Nmap li considera
tutti attivi e scansiona 65.535 porte per ciascuno.

**Soluzione**: controlla `nmap/work/hosts_up_<data>.txt`: se contiene indirizzi che
sai essere liberi, restringi `targets.txt` agli intervalli effettivamente usati oppure
esegui la scansione da un punto della rete che non passi da quel firewall.

### Alcuni host non hanno porte

**Cause possibili**: l'host filtra tutte le porte, oppure la sua scansione ha superato
10 minuti ed è stata abbandonata (`--host-timeout 10m`). Nel secondo caso l'XML in
`nmap/scans/open_ports_<data>.xml` contiene per quell'host l'attributo `timedout="true"`.

### La scansione è molto lenta

Vedi [Esecuzione → Durata e impatto sulla rete](esecuzione.md#durata-e-impatto-sulla-rete).
Le cause tipiche sono molti host attivi, collegamenti lenti, firewall che scartano i
pacchetti in silenzio e limiti alle risposte ICMP nella fase UDP.

## NetBox

### `[ERRORE] Variabile ambiente mancante: NETBOX_URL` (o `NETBOX_TOKEN`)

**Causa**: `nmap/netbox.env` manca, la variabile è vuota o vale ancora `CHANGE_ME`.

**Soluzione**: compila `netbox.env` (vedi [Configurazione](configurazione.md#nmapnetboxenv)).
Se non usi NetBox, imposta `export PUSH_TO_NETBOX="false"`.

### Errori `403 Forbidden`

**Causa**: il token non ha la scrittura abilitata oppure l'utente non ha i permessi su
IP Address (`view`, `add`, `change`).

### Errori `400 Bad Request` che citano i custom field

**Causa**: i campi personalizzati non esistono sul tipo IP Address oppure hanno nomi
diversi da quelli in `NETBOX_CF_*`.

**Soluzione**: crea i campi (vedi [Installazione → Preparare NetBox](installazione.md#preparare-netbox))
o correggi i nomi in `netbox.env`.

### In NetBox compaiono IP duplicati

**Causa**: l'IP era già registrato con la maschera della subnet (per esempio
`192.0.2.10/24`), mentre la pipeline cerca e crea indirizzi `/32`.

**Soluzione**: uniforma gli IP gestiti dalla pipeline a `/32`, oppure cancella i
duplicati creati e registra gli host a `/32`.

### Su un IP esistente `dns_name`, `description` o `status` non cambiano

È voluto: sugli IP già presenti in NetBox la pipeline aggiorna solo i tre campi
personalizzati, per non cancellare valori curati a mano. Stato, descrizione e nome DNS
vengono scritti solo quando la pipeline crea l'IP (vedi
[Architettura → NetBox](architettura.md#netbox)).

## GLPI

### `[ERRORE] Configurazione mancante: ...`

**Causa**: `glpi-nmap-adapter/.env` manca, oppure le variabili elencate sono vuote o
valgono ancora `CHANGE_ME`.

**Soluzione**: compila `.env`. Se non usi GLPI, imposta `export PUSH_TO_GLPI="false"`
in `nmap/netbox.env`.

### `[ERRORE] initSession HTTP 4xx: ...`

Il messaggio riporta la risposta di GLPI. Codici di errore frequenti:

| Codice GLPI | Causa |
|---|---|
| `ERROR_GLPI_LOGIN` | Utente o password errati |
| `ERROR_LOGIN_WITH_CREDENTIALS_DISABLED` | Nell'API di GLPI il login con credenziali è disabilitato |
| `ERROR_WRONG_APP_TOKEN_PARAMETER` | `GLPI_LEGACY_APP_TOKEN` errato |
| `ERROR_NOT_ALLOWED_IP` | Il client API non accetta l'IP del server di scansione |

Se la risposta è una pagina HTML o un 404, controlla `GLPI_BASE_URL` o
`GLPI_LEGACY_API_URL` e che l'API legacy sia abilitata.

### `[KO] <ip> -> HTTP 4xx` sulla creazione o sull'aggiornamento

**Cause possibili**: `GLPI_ITEMTYPE` non corrisponde al tipo di asset (nella risposta
compare `ERROR_ITEMTYPE_NOT_FOUND_NOR_COMMONDBTM`), il profilo dell'utente API non ha i
diritti di creazione e modifica su quel tipo di asset (`ERROR_RIGHT_MISSING`), oppure i
nomi `FIELD_*_KEY` non corrispondono ai campi.

**Soluzione**: verifica i nomi con la procedura in
[Installazione → Verificare i nomi dei campi](installazione.md#verificare-i-nomi-dei-campi)
e prova su un solo host con `--only-ip <ip> --verbose`.

### In GLPI compaiono asset duplicati

**Causa**: il file di stato `glpi_nmap_state_legacy.json` è stato cancellato o
sostituito, quindi lo script non conosce più gli ID e crea nuovi asset.

**Soluzione**: ripristina il file da backup. Se non è possibile, cancella in GLPI i
duplicati più vecchi e lascia che la pipeline riparta dal nuovo file di stato.

## Python e certificati

### `SSLError` o `CERTIFICATE_VERIFY_FAILED`

**Causa**: il certificato di NetBox o GLPI è emesso da una CA che Python non riconosce,
tipicamente una CA interna.

**Soluzione**: installa la CA nel sistema e, per GLPI, aggiungi `REQUESTS_CA_BUNDLE`
a `.env` (vedi [Configurazione](configurazione.md#certificati-di-una-ca-interna)). Non
disattivare la verifica se non per una diagnosi temporanea.

### `error: externally-managed-environment`

**Causa**: su Debian e Ubuntu recenti `pip install` nel Python di sistema è bloccato (PEP 668).

**Soluzione**: `sudo apt install python3-requests python3-yaml`.

### `The virtual environment was not created successfully because ensurepip is not available`

**Soluzione**: `sudo apt install python3-venv`, poi ricrea il virtualenv.

### `No matching distribution found for requests==2.34.2`

**Causa**: il Python usato per il virtualenv è più vecchio di 3.10, oppure pip non
raggiunge PyPI (in quel caso l'output mostra prima errori di rete o di certificato).

**Soluzione**: usa una distribuzione con Python 3.10 o superiore (Debian 12+, Ubuntu
22.04+), oppure risolvi l'accesso a PyPI (proxy, CA interna).

### `[ERRORE] PyYAML non installato`

**Causa**: `ANSIBLE_INVENTORY_FILE` è impostata ma il Python di sistema non ha PyYAML.

**Soluzione**: `sudo apt install python3-yaml`.
