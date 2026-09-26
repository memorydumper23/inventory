# Installazione

## Requisiti

### Sistema

| Requisito | Note |
|---|---|
| Linux con `bash`, `sudo`, `flock` (util-linux) e `git` | Testato su Debian 12 (sudo 1.9.13, Nmap 7.93, Python 3.11) |
| Nmap in `/usr/bin/nmap` | Il pacchetto della distribuzione; il wrapper usa questo percorso |
| Python 3 di sistema in `/usr/bin/python3` con `requests` e `PyYAML` | Usato dagli script in `nmap/scripts/` |
| Python 3.10 o superiore per il virtualenv GLPI | Richiesto da `requests` 2.34 e `python-dotenv` 1.2. Vanno bene Debian 12+ e Ubuntu 22.04+ |

### Rete

- Il server che esegue la pipeline deve raggiungere le subnet da scansionare senza
  firewall che filtrino il traffico di scansione, altrimenti i risultati saranno incompleti.
- Sulle subnet collegate direttamente (stesso segmento di rete) gli host vengono trovati
  via ARP, il metodo più affidabile. Sulle subnet dietro un router Nmap usa invece ping
  ICMP, TCP SYN sulla 443, TCP ACK sulla 80 e ICMP timestamp: un host che non risponde a
  nessuna di queste sonde non viene rilevato.
- Accesso HTTPS alle API di NetBox e GLPI, se usate.

## Preparare NetBox

Salta questa sezione se non usi NetBox (`PUSH_TO_NETBOX="false"`).

### Campi personalizzati

Crea tre campi personalizzati sul tipo di oggetto **IPAM › IP Address**. I nomi sono
quelli predefiniti: se ne usi altri, indicali in `netbox.env`
(`NETBOX_CF_TCP_PORTS`, `NETBOX_CF_UDP_PORTS`, `NETBOX_CF_SERVICES_DETAIL`).

| Nome | Tipo consigliato | Contenuto |
|---|---|---|
| `porte_tcp` | Text | Porte TCP aperte, per esempio `22, 80, 443` |
| `porte_udp` | Text | Porte UDP aperte o candidate, per esempio `53, 161?` |
| `servizi_dettaglio` | Text (long) | Un servizio per riga, con prodotto e versione |

### Token API

Crea un token per un utente dedicato alla pipeline. L'utente deve poter vedere, creare
e modificare gli IP Address (`ipam.view_ipaddress`, `ipam.add_ipaddress`,
`ipam.change_ipaddress`) e il token deve avere la scrittura abilitata. Non servono altri
permessi. Lo script riconosce da solo il tipo di token: quelli di nuova generazione
(prefisso `nbt_`) vengono inviati con lo schema `Bearer`, quelli classici con lo schema `Token`.

## Preparare GLPI

Salta questa sezione se non usi GLPI (`PUSH_TO_GLPI="false"`). I nomi dei menu possono
cambiare con la versione e con la lingua dell'interfaccia.

### Asset personalizzato

1. In GLPI 11 crea una definizione di asset personalizzato con nome di sistema `Nmap`.
   GLPI la espone come tipo `Glpi\CustomAsset\NmapAsset`, il valore predefinito di
   `GLPI_ITEMTYPE`.
2. Aggiungi tre campi personalizzati di tipo testo: porte TCP, porte UDP e servizi.
   Per i servizi usa un campo multilinea: contiene un servizio per riga.
3. Dai al profilo dell'utente API i diritti di lettura, creazione e modifica su questo
   tipo di asset.

### API Legacy

1. Nella configurazione dell'API (Configurazione › Generale › API) abilita l'API REST
   legacy e l'accesso con credenziali (login e password).
2. Crea un client API e copia il suo *application token* in `GLPI_LEGACY_APP_TOKEN`.
   Limita il client all'indirizzo IP del server che esegue la pipeline.
3. Crea un utente GLPI dedicato alla pipeline, con il profilo del passo precedente.

### Verificare i nomi dei campi

I valori di `FIELD_TCP_KEY`, `FIELD_UDP_KEY` e `FIELD_SERVICES_KEY` devono corrispondere
esattamente ai nomi con cui l'API espone i campi. Il modo più sicuro per conoscerli è
creare a mano un asset `Nmap` di prova, compilarne i campi e leggerlo via API:

```bash
# 1. apri una sessione (curl chiede la password, che così non resta nella cronologia)
curl -s -u utente-api -H "App-Token: <application token>" \
  https://glpi.example.com/apirest.php/initSession
# risposta: {"session_token":"..."}

# 2. leggi l'asset di prova (sostituisci <session token> e <id>)
curl -s -H "Session-Token: <session token>" -H "App-Token: <application token>" \
  "https://glpi.example.com/apirest.php/Glpi%5CCustomAsset%5CNmapAsset/<id>"

# 3. chiudi la sessione
curl -s -H "Session-Token: <session token>" -H "App-Token: <application token>" \
  https://glpi.example.com/apirest.php/killSession
```

Nella risposta del passo 2 cerca i campi con i valori che hai inserito: i loro nomi
vanno in `.env` (nell'esempio fornito sono `custom_tcp_ports`, `custom_udp_ports` e
`custom_services`).

## Installazione passo per passo

I comandi con `sudo` vanno eseguiti da un utente amministratore; quelli indicati
"come utente `inventory`" con `sudo -iu inventory` oppure anteponendo `sudo -u inventory`.

### 1. Pacchetti

```bash
# Debian/Ubuntu
sudo apt install git nmap python3-requests python3-yaml python3-venv
```

Su Debian e Ubuntu recenti `pip install` nel Python di sistema è bloccato (PEP 668):
per questo `requests` e `PyYAML` si installano dai pacchetti della distribuzione. Su
altre distribuzioni puoi installarli per l'utente di servizio, dopo il passo 2:

```bash
sudo -u inventory python3 -m pip install --user -r /opt/inventory/nmap/requirements.txt
```

### 2. Utente di servizio e codice

```bash
sudo useradd --system --create-home --shell /bin/bash inventory
sudo git clone https://github.com/memorydumper23/inventory.git /opt/inventory
sudo chown -R inventory: /opt/inventory
```

L'utente `inventory` non ha privilegi: potrà eseguire come root solo il wrapper del passo 4.

### 3. Configurazione

Come utente `inventory`, da `/opt/inventory`:

```bash
cp nmap/targets.txt.example nmap/targets.txt
cp nmap/netbox.env.example nmap/netbox.env && chmod 600 nmap/netbox.env
cp glpi-nmap-adapter/.env.example glpi-nmap-adapter/.env && chmod 600 glpi-nmap-adapter/.env
```

Poi compila i tre file seguendo [Configurazione](configurazione.md).

### 4. Wrapper e regola sudo

Da amministratore, in `/opt/inventory`:

```bash
# il wrapper deve essere di root e fuori dalla cartella del progetto:
# se l'utente inventory potesse modificarlo, otterrebbe root
sudo install -o root -g root -m 0755 deploy/inventory-nmap /usr/local/sbin/inventory-nmap

# se l'utente di servizio non si chiama "inventory", correggi l'ultima riga del file
sudo visudo -cf deploy/sudoers-inventory
sudo install -o root -g root -m 0440 deploy/sudoers-inventory /etc/sudoers.d/inventory
```

`visudo -cf` controlla la sintassi prima dell'installazione: un file sudoers sbagliato
in `/etc/sudoers.d/` può bloccare `sudo` per tutto il sistema.

### 5. Virtualenv dell'adapter GLPI

Come utente `inventory`:

```bash
cd /opt/inventory/glpi-nmap-adapter
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

`run_all_inventory.sh` usa questo virtualenv se esiste, altrimenti ripiega sul Python di
sistema (che allora deve avere `requests` e `python-dotenv`).

### 6. Prima esecuzione senza invii

Esegui la pipeline con i due push disattivati e controlla i risultati prima di scrivere
in NetBox e GLPI:

```bash
sudo -u inventory env PUSH_TO_NETBOX=false PUSH_TO_GLPI=false \
  /opt/inventory/nmap/run_all_inventory.sh
```

Le variabili passate così valgono solo se in `netbox.env` le righe `PUSH_TO_*` sono
commentate: i valori del file hanno la precedenza.

Poi guarda `nmap/work/normalized_assets_merged_<data>.json` e simula l'invio a GLPI:

```bash
cd /opt/inventory/glpi-nmap-adapter
sudo -u inventory .venv/bin/python nmap_to_glpi_nmap_asset.py \
  -i ../nmap/work/normalized_assets_merged_$(date +%F).json -f json --dry-run
```

Il push verso NetBox non ha una modalità di simulazione. Per provarlo su un solo host
crea un JSON ridotto e invialo a mano:

```bash
cd /opt/inventory/nmap
sudo -u inventory python3 -c '
import json, sys
d = json.load(open(sys.argv[1]))
d["assets"] = [a for a in d["assets"] if a["ip"] == sys.argv[2]]
json.dump(d, open("/tmp/un-host.json", "w"))
' work/normalized_assets_merged_$(date +%F).json 192.0.2.10
sudo -u inventory python3 scripts/push_to_netbox.py --input /tmp/un-host.json
```

### 7. Esecuzione completa

```bash
sudo -u inventory /opt/inventory/nmap/run_all_inventory.sh
```

### 8. Pianificazione

Vedi [Esecuzione → Avvio programmato](esecuzione.md#avvio-programmato-cron).

## Verifica dell'installazione

```bash
# deve comparire solo /usr/local/sbin/inventory-nmap
sudo -l -U inventory

# wrapper e regola devono essere di root e non scrivibili da altri
ls -l /usr/local/sbin/inventory-nmap /etc/sudoers.d/inventory

# il wrapper funziona: deve stampare l'inizio di un XML
echo 127.0.0.1 | sudo -u inventory sudo -n /usr/local/sbin/inventory-nmap discovery | head -3

# nmap diretto deve essere rifiutato ("a password is required")
sudo -u inventory sudo -n /usr/bin/nmap --version

# git non deve vedere file nuovi: configurazioni e risultati sono esclusi
sudo -u inventory git -C /opt/inventory status --short
```

## Aggiornamento

```bash
# 1. scarica la nuova versione
sudo -u inventory git -C /opt/inventory pull

# 2. se è cambiato il wrapper, rileggilo prima di installarlo: girerà come root
sudo diff /usr/local/sbin/inventory-nmap /opt/inventory/deploy/inventory-nmap
sudo install -o root -g root -m 0755 /opt/inventory/deploy/inventory-nmap /usr/local/sbin/inventory-nmap

# 3. se sono cambiate le dipendenze dell'adapter GLPI
sudo -u inventory /opt/inventory/glpi-nmap-adapter/.venv/bin/pip install \
  -r /opt/inventory/glpi-nmap-adapter/requirements.txt
```

Le configurazioni locali (`targets.txt`, `netbox.env`, `.env`) sono escluse da git e non
vengono toccate dall'aggiornamento. Confronta però i file `.example` aggiornati con i
tuoi per scoprire eventuali opzioni nuove.

## Migrazione da una versione con `sudo nmap` diretto

Le versioni precedenti chiamavano `sudo /usr/bin/nmap` e richiedevano una regola
`NOPASSWD: /usr/bin/nmap`.

1. Rimuovi quella regola: equivale a dare root all'utente (vedi [Sicurezza](sicurezza.md)).
2. Installa wrapper e nuova regola (passo 4).
3. Rendi l'utente di servizio proprietario dei vecchi risultati, che Nmap aveva scritto
   come root: `sudo chown -R inventory: /opt/inventory/nmap/scans`.

## Disinstallazione

```bash
sudo crontab -u inventory -r          # attenzione: rimuove tutto il crontab dell'utente
sudo rm /etc/sudoers.d/inventory /usr/local/sbin/inventory-nmap
sudo rm -rf /opt/inventory            # cancella anche configurazioni, scansioni e log
sudo userdel -r inventory
```

I dati già scritti in NetBox, GLPI e nell'inventario Ansible restano dove sono. Revoca
il token NetBox, l'utente API e l'application token GLPI usati dalla pipeline.
