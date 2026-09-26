# Documentazione di inventory

Per un avvio rapido basta il [README](../README.md) principale. Qui trovi il dettaglio
di ogni componente, opzione e comportamento della pipeline.

| Documento | Contenuto |
|---|---|
| [Architettura](architettura.md) | Componenti, flusso dei dati, file prodotti, formati JSON, limiti noti |
| [Installazione](installazione.md) | Requisiti, preparazione di NetBox e GLPI, installazione passo passo, aggiornamento, disinstallazione |
| [Configurazione](configurazione.md) | Riferimento completo di `targets.txt`, `netbox.env` e `.env` |
| [Esecuzione](esecuzione.md) | Avvio manuale e da cron, log, codici di uscita, durata, esecuzioni parziali, manutenzione |
| [Riferimento script](riferimento-script.md) | Argomenti, input, output e logica di ogni script e di ogni profilo di scansione |
| [Sicurezza](sicurezza.md) | Modello di minaccia, wrapper sudo, credenziali, dati sensibili, uso autorizzato |
| [Risoluzione problemi](risoluzione-problemi.md) | Errori frequenti, cause e soluzioni |

## I componenti in breve

- **Nmap**: lo scanner di rete. Trova gli host attivi, le porte aperte e i servizi in
  ascolto con la loro versione. È l'unico componente che richiede i privilegi di root.
- **NetBox**: il registro tecnico della rete (IPAM/DCIM). La pipeline crea o aggiorna
  un *IP Address* per ogni host trovato, con porte e servizi in tre campi personalizzati.
- **GLPI**: il software di gestione degli asset IT e dell'helpdesk. La pipeline crea o
  aggiorna un asset personalizzato `Nmap` per ogni host, con gli stessi tre dati.
- **Ansible**: lo strumento di automazione. Se configurato, la pipeline aggiunge gli
  host scoperti al file di inventario `hosts.yml`.
- **Network inventory**: l'obiettivo complessivo, cioè un elenco sempre aggiornato di
  cosa è presente in rete e di cosa espone.

## Convenzioni usate in questa documentazione

- Il progetto è installato in `/opt/inventory` e gira con l'utente di servizio `inventory`.
- `<data>` indica la data dell'esecuzione nel formato `AAAA-MM-GG` (per esempio `2026-09-26`).
- Gli indirizzi negli esempi appartengono al blocco di documentazione `192.0.2.0/24`
  (RFC 5737) e non corrispondono a reti reali.
