# inventory

Pipeline di network inventory basata su Nmap: scopre gli host di una o più subnet,
rileva porte TCP/UDP e servizi, e sincronizza i risultati su **NetBox**, **GLPI**
e (opzionalmente) su un inventory **Ansible**.

```
nmap/
  run_all_inventory.sh      # entrypoint: TCP -> UDP -> push NetBox -> push GLPI
  run_inventory.sh          # host discovery + porte/servizi TCP
  run_udp_enrichment.sh     # porte/servizi UDP + merge con TCP
  scripts/                  # parsing XML Nmap, normalizzazione, push NetBox, Ansible
glpi-nmap-adapter/
  nmap_to_glpi_nmap_asset.py  # push su custom asset GLPI via Legacy API
deploy/
  inventory-nmap            # wrapper root: unico comando concesso via sudo
  sudoers-inventory         # regola sudo ristretta al wrapper
```

## Requisiti

- Linux, `bash`, `nmap`, `python3`, `sudo`
- Il wrapper `deploy/inventory-nmap` installato con la sua regola sudo (sezione seguente)
- NetBox con i custom field sugli IP address (default: `porte_tcp`, `porte_udp`, `servizi_dettaglio`)
- GLPI 11 con un custom asset `Nmap` e i tre campi custom (TCP, UDP, servizi), API Legacy abilitata

## Installazione

La pipeline gira con un utente di servizio senza privilegi (negli esempi `inventory`),
proprietario della cartella del progetto.

```bash
sudo useradd --system --create-home --shell /bin/bash inventory
sudo git clone https://github.com/memorydumper23/inventory.git /opt/inventory
sudo chown -R inventory: /opt/inventory
```

## Configurazione

Nessuna credenziale è inclusa nel repository: ogni installazione deve fornire la propria.
Esegui questi passi come utente `inventory` (`sudo -iu inventory`, poi `cd /opt/inventory`).

```bash
# Target da scansionare (una subnet/host per riga)
cp nmap/targets.txt.example nmap/targets.txt

# NetBox (+ opzioni Ansible / percorso adapter GLPI)
cp nmap/netbox.env.example nmap/netbox.env
chmod 600 nmap/netbox.env

# GLPI
cp glpi-nmap-adapter/.env.example glpi-nmap-adapter/.env
chmod 600 glpi-nmap-adapter/.env
```

Modifica i file copiati sostituendo tutti i valori `CHANGE_ME` e gli URL di esempio.
Gli script si rifiutano di partire se trovano credenziali mancanti o ancora a `CHANGE_ME`.

## Permessi di root per nmap

Le scansioni SYN e UDP richiedono root, ma `sudo nmap` senza restrizioni equivale a
dare root all'utente: `--script` esegue codice arbitrario, `-iL` legge qualunque file,
`-oX` sovrascrive qualunque file. Per questo la pipeline non chiama mai nmap
direttamente: usa il wrapper `inventory-nmap`, che accetta solo cinque profili di
scansione a opzioni fisse, riceve i target da stdin e scrive l'XML su stdout
(nmap come root non apre nessun file). L'unico parametro libero è una lista di porte
numeriche.

Da un utente amministratore, nella cartella `/opt/inventory`, installa wrapper e regola sudo:

```bash
# wrapper: deve essere di root e fuori dalla cartella del progetto,
# altrimenti chi può modificarlo ottiene root
sudo install -o root -g root -m 0755 deploy/inventory-nmap /usr/local/sbin/inventory-nmap

# regola sudo: sostituisci "inventory" con il tuo utente, poi valida e installa
sudo visudo -cf deploy/sudoers-inventory
sudo install -o root -g root -m 0440 deploy/sudoers-inventory /etc/sudoers.d/inventory

# verifica: deve comparire solo /usr/local/sbin/inventory-nmap
sudo -l -U inventory
```

Se in precedenza avevi una regola `NOPASSWD: /usr/bin/nmap`, rimuovila. Dopo ogni
modifica a `deploy/inventory-nmap` ripeti il comando `install`.

## Installazione dipendenze

Gli script in `nmap/` usano il Python di sistema (`/usr/bin/python3`). Su Debian/Ubuntu
recenti `pip install` a livello di sistema è bloccato (PEP 668): installa i pacchetti
della distribuzione.

```bash
# Debian/Ubuntu
sudo apt install nmap python3-requests python3-yaml python3-venv

# altre distribuzioni: pacchetti nell'utente inventory
sudo -u inventory python3 -m pip install --user -r /opt/inventory/nmap/requirements.txt
```

L'adapter GLPI usa un virtualenv proprio, da creare come utente `inventory`:

```bash
cd /opt/inventory/glpi-nmap-adapter
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

`run_all_inventory.sh` usa automaticamente `glpi-nmap-adapter/.venv` se presente.

## Esecuzione

```bash
sudo -u inventory /opt/inventory/nmap/run_all_inventory.sh
```

Esempio cron dell'utente `inventory` (`sudo crontab -u inventory -e`), ogni notte alle 2:00:

```
0 2 * * * /opt/inventory/nmap/run_all_inventory.sh
```

Flusso: host discovery → porte e servizi TCP → porte e servizi UDP → merge in
`normalized_assets_merged_<data>.json` → push su NetBox (IP Address + custom field)
→ push su GLPI (custom asset, nome = IP). I due push sono indipendenti: se uno
fallisce l'altro viene comunque eseguito e lo script termina con exit code 1.
Per disabilitarne uno imposta `PUSH_TO_NETBOX=false` o `PUSH_TO_GLPI=false` in `netbox.env`.

Output in `nmap/scans/` (XML Nmap), `nmap/work/` (JSON normalizzati) e `nmap/logs/`.
Queste cartelle sono escluse da git perché contengono dati sulla rete scansionata.

Test del push GLPI senza inviare nulla:

```bash
cd glpi-nmap-adapter
.venv/bin/python nmap_to_glpi_nmap_asset.py -i ../nmap/work/normalized_assets_merged_YYYY-MM-DD.json -f json --dry-run
```

Aggiungi `--verbose` per stampare endpoint e payload di ogni richiesta durante un push reale.

> ⚠️ Scansiona solo reti di tua proprietà o per cui hai autorizzazione esplicita.

## Licenza

[MIT](LICENSE)
