# Esecuzione

## Avvio manuale

```bash
sudo -u inventory /opt/inventory/nmap/run_all_inventory.sh
```

Lo script si può lanciare da qualunque cartella: tutti i percorsi sono calcolati a
partire dalla sua posizione. Non va mai lanciato come root: la pipeline ottiene i
privilegi necessari solo attraverso il wrapper.

## Avvio programmato (cron)

Nel crontab dell'utente `inventory` (`sudo crontab -u inventory -e`):

```
# inventario di rete ogni notte alle 2:00
0 2 * * * umask 077; /opt/inventory/nmap/run_all_inventory.sh > /dev/null

# pulizia dei risultati più vecchi di 30 giorni
30 3 * * * find /opt/inventory/nmap/scans /opt/inventory/nmap/work /opt/inventory/nmap/logs -type f -mtime +30 -delete
```

- `umask 077` fa sì che scansioni e log siano leggibili solo dall'utente `inventory`:
  contengono la mappa della rete (vedi [Sicurezza](sicurezza.md#dati-prodotti)).
- `> /dev/null` scarta i messaggi di avanzamento, che sono comunque nei log. Gli errori
  scritti su standard error restano, e cron li invia per email all'utente se sul server
  è configurato un servizio di posta.
- Scegli un orario in cui la rete è poco usata: la scansione TCP completa genera molto
  traffico (vedi [Durata e impatto sulla rete](#durata-e-impatto-sulla-rete)).
- Il file di lock impedisce che due esecuzioni si sovrappongano: se la precedente non è
  ancora finita, la nuova termina subito con errore.

## Cosa succede durante un'esecuzione

Un'esecuzione riuscita produce in `logs/run_all_<data>.log` righe come queste:

```
[2026-09-26 02:00:00] Avvio run_all_inventory
[2026-09-26 02:00:00] Eseguo pipeline TCP
[2026-09-26 02:14:31] Eseguo enrichment UDP
[2026-09-26 02:16:02] Eseguo push finale su NetBox dal merged JSON
[2026-09-26 02:16:09] Push NetBox completato con successo
[2026-09-26 02:16:09] Uso Python del virtualenv GLPI: /opt/inventory/glpi-nmap-adapter/.venv/bin/python3
[2026-09-26 02:16:09] Eseguo push finale su GLPI dal merged JSON
[2026-09-26 02:16:12] Push GLPI completato con successo
[2026-09-26 02:16:12] run_all_inventory completato con successo
[2026-09-26 02:16:12] Run log: /opt/inventory/nmap/logs/run_all_2026-09-26.log
```

Dopo "Eseguo pipeline TCP" e dopo "Eseguo enrichment UDP" il log contiene anche i
messaggi dettagliati delle due fasi, omessi qui. La sequenza completa delle fasi è
descritta in [Architettura](architettura.md#flusso-dei-dati).

## Log

Tutti i log sono in `/opt/inventory/nmap/logs/`, un file per tipo e per giorno. Le
esecuzioni ripetute nello stesso giorno accodano allo stesso file.

| File | Contenuto |
|---|---|
| `run_all_<data>.log` | Log principale: avvio, esito di ogni fase, errori. Include l'output delle fasi TCP e UDP |
| `run_<data>.log` | Solo i messaggi della fase TCP (`run_inventory.sh`) |
| `run_udp_<data>.log` | Solo i messaggi della fase UDP (`run_udp_enrichment.sh`) |
| `netbox_sync_<data>.log` | Esito dell'invio a NetBox: una riga `[CREATE]` o `[UPDATE]` per IP, gli errori e il riepilogo |
| `glpi_sync_<data>.log` | Esito dell'invio a GLPI: una riga `[OK]`, `[KO]` o `[EXC]` per IP e il riepilogo |

Quando qualcosa non va, parti da `run_all_<data>.log` e poi guarda il log specifico
della fase che ha fallito.

## Codici di uscita

| Script | Codice | Significato |
|---|---|---|
| `run_all_inventory.sh` | `0` | Pipeline completata, oppure nessun host trovato (in quel caso NetBox e GLPI non vengono toccati) |
| | diverso da `0` | Errore. Casi tipici: un push fallito (l'altro è stato comunque eseguito), un file necessario mancante, un'altra esecuzione in corso (tutti con codice `1`), oppure una fase interrotta da Nmap, sudo o uno script Python (codice del comando fallito). Il log indica la causa |
| `inventory-nmap` | `2` | Profilo inesistente o argomenti non validi |
| `push_to_netbox.py` | `0` / `1` | Tutti gli IP inviati / almeno un errore o configurazione mancante |
| `nmap_to_glpi_nmap_asset.py` | `0` / `1` | Tutti gli host inviati / almeno un errore, configurazione mancante o login fallito |

Il codice di uscita di `run_all_inventory.sh` è quello da usare in un sistema di
monitoraggio.

## Esecuzioni ripetute nello stesso giorno

Tutti i file di un'esecuzione portano la data di avvio (`DATE_TAG`), fissata all'inizio
e mantenuta anche se l'esecuzione supera la mezzanotte. Rieseguendo nello stesso giorno:

- i file in `scans/` e `work/` vengono sovrascritti;
- i log vengono accodati;
- NetBox e GLPI vengono aggiornati con i nuovi risultati.

## Esecuzioni parziali

Ogni fase si può lanciare da sola, utile per diagnosi e prove.

**Solo fase TCP**, senza invii:

```bash
sudo -u inventory /opt/inventory/nmap/run_inventory.sh
```

Lanciato da solo, `run_inventory.sh` non invia nulla a NetBox a meno che
`PUSH_TO_NETBOX` valga `true` nell'ambiente o in `netbox.env`: in quel caso invia i soli
dati TCP.

**Solo fase UDP**: richiede i file della fase TCP dello stesso giorno.

```bash
sudo -u inventory /opt/inventory/nmap/run_udp_enrichment.sh
```

Per lavorare sui file di un altro giorno imposta la data:
`sudo -u inventory env DATE_TAG=2026-09-25 /opt/inventory/nmap/run_udp_enrichment.sh`.

**Solo invio a NetBox** di un risultato già prodotto:

```bash
sudo -u inventory python3 /opt/inventory/nmap/scripts/push_to_netbox.py \
  --input /opt/inventory/nmap/work/normalized_assets_merged_2026-09-26.json
```

**Solo invio a GLPI**, con le opzioni di prova:

```bash
cd /opt/inventory/glpi-nmap-adapter
F=../nmap/work/normalized_assets_merged_2026-09-26.json

# simulazione: stampa i dati che verrebbero inviati, non richiede credenziali
sudo -u inventory .venv/bin/python nmap_to_glpi_nmap_asset.py -i "$F" -f json --dry-run

# un solo host, mostrando endpoint e dati di ogni richiesta
sudo -u inventory .venv/bin/python nmap_to_glpi_nmap_asset.py -i "$F" -f json \
  --only-ip 192.0.2.10 --verbose
```

## Durata e impatto sulla rete

La durata dipende quasi tutta dalla scansione TCP completa (profilo `tcp-ports`), che
controlla tutte le 65.535 porte di ogni host a una velocità minima di 5.000 pacchetti
al secondo sull'intera scansione.

- **Ordine di grandezza**: 100 host attivi sono circa 6,5 milioni di sonde. Alla
  velocità minima sono circa 22 minuti; Nmap può andare più veloce, ma ritrasmissioni
  e host lenti allungano i tempi.
- **Host lenti**: un host la cui scansione supera 10 minuti (`--host-timeout 10m`) viene
  abbandonato e compare senza porte.
- **UDP**: 12 porte per host, ma molti sistemi limitano le risposte ICMP e rallentano
  la scansione UDP.
- **Carico**: 5.000 pacchetti al secondo sono sostenibili per una rete aziendale, ma
  possono saturare collegamenti lenti (sedi remote, VPN) o mettere in difficoltà
  apparati fragili: stampanti, dispositivi IoT e soprattutto sistemi industriali (OT).
  Il riconoscimento dei servizi (`-sV`) invia richieste applicative che alcuni
  dispositivi gestiscono male.
- **Sistemi di sicurezza**: IDS, IPS e firewall riconoscono la scansione come tale.
  Avvisa il SOC e concorda un orario e un indirizzo sorgente fissi per la pipeline, in
  modo da distinguerla da un attacco reale.

## Manutenzione

- **Pulizia dei risultati**: scansioni, JSON e log si accumulano ogni giorno. Il
  secondo esempio della sezione cron li cancella dopo 30 giorni; adatta il periodo alla
  tua politica di conservazione.
- **File di stato GLPI**: includi `glpi-nmap-adapter/glpi_nmap_state_legacy.json` nei
  backup. Se va perso, l'esecuzione successiva crea asset duplicati in GLPI.
- **Credenziali**: quando ruoti il token NetBox o la password GLPI, aggiorna
  `netbox.env` e `.env`.
- **Aggiornamenti**: vedi [Installazione → Aggiornamento](installazione.md#aggiornamento).
