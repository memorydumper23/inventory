# Sicurezza

La pipeline ha bisogno di due cose delicate: privilegi di root per le scansioni e
credenziali di scrittura verso NetBox e GLPI. Produce inoltre una mappa dettagliata
della rete. Questo documento descrive come ciascun rischio è gestito e cosa resta
a carico di chi la installa.

## Principi

- **Privilegio minimo**: tutto gira con un utente senza privilegi. Solo cinque
  scansioni Nmap predefinite girano come root, attraverso un wrapper.
- **Nessun file aperto come root**: i target entrano e i risultati escono tramite
  standard input e output; i file li apre sempre l'utente di servizio.
- **Nessuna credenziale nel repository**: la configurazione reale vive in file locali
  esclusi da git, con permessi `600`.
- **Verifica TLS attiva per impostazione predefinita** verso NetBox e GLPI.

## Modello di minaccia

| Rischio | Contromisura | Rischio residuo |
|---|---|---|
| L'utente di servizio viene compromesso e cerca di ottenere root | Può eseguire come root solo il wrapper, che accetta cinque profili fissi e solo liste di porte numeriche | Può lanciare le scansioni previste verso qualunque destinazione raggiungibile |
| Qualcuno modifica il codice in `/opt/inventory` | Il codice del progetto gira come utente di servizio; il wrapper eseguito come root è una copia di root in `/usr/local/sbin` | Chi controlla l'utente di servizio può alterare i dati inviati a NetBox e GLPI |
| Furto delle credenziali NetBox o GLPI | File `600` dell'utente di servizio; token e profili con i soli permessi necessari | Chi legge i file può fare ciò che il token consente: creare e modificare IP Address e asset `Nmap` |
| Esposizione della mappa di rete | `umask 077` nel cron, pulizia periodica, esclusione da git | Copie in backup e nei sistemi di destinazione |
| Intercettazione del traffico verso le API | TLS con verifica del certificato | Nessuno, se `NETBOX_VERIFY_SSL` resta `true` e gli URL sono `https://` |
| Dipendenze Python compromesse | Versioni fissate in `requirements.txt`; pacchetti della distribuzione per il Python di sistema | Fiducia nei repository di PyPI e della distribuzione |
| Scansioni non autorizzate o dannose per la rete | Target decisi solo in `targets.txt`; profili di scansione fissi | Resta una responsabilità organizzativa (vedi [Uso autorizzato](#uso-autorizzato-e-impatto-operativo)) |

## Perché un wrapper e non una regola sudo su nmap

Concedere `sudo nmap` a un utente equivale a dargli root. Le tecniche sono note e
documentate (per esempio su GTFOBins):

- `--script` esegue script Lua arbitrari, e quindi comandi di sistema, come root;
- `-iL <file>` legge qualunque file, come `/etc/shadow`: le righe finiscono nei messaggi
  di errore di Nmap;
- `-oX`, `-oN` e le altre opzioni di output scrivono o sovrascrivono qualunque file;
- `--datadir` o la variabile `NMAPDIR` fanno caricare a Nmap file e script da una
  cartella dell'utente, eseguiti poi dal riconoscimento servizi (`-sV`).

Limitare gli argomenti direttamente nella regola sudoers non funziona bene: in sudoers
il carattere `*` corrisponde a qualunque sequenza, spazi compresi, quindi una regola
`nmap -sV -p *` concederebbe anche `nmap -sV -p 22 --script ...`. Le espressioni
regolari nelle regole esistono solo da sudo 1.9.10 e diventerebbero illeggibili per
cinque profili diversi.

Il wrapper sposta la validazione in un file breve e leggibile, che funziona con
qualunque versione di sudo. La regola sudoers si riduce a una riga: l'utente può
eseguire il wrapper, e nient'altro.

### Perché target e risultati passano da stdin e stdout

Anche con opzioni fisse, passare al wrapper un percorso di file sarebbe pericoloso.
La cartella `nmap/scans/` appartiene all'utente di servizio: se Nmap scrivesse lì come
root, basterebbe creare in anticipo un collegamento simbolico
`scans/hosts_up_<data>.xml → /etc/shadow` per fargli sovrascrivere un file di sistema.
Con il redirect fatto dalla shell dell'utente, i file vengono aperti con i privilegi
dell'utente e il problema non esiste.

## Cosa garantisce il wrapper e cosa no

**Garantisce**

- Nessun codice arbitrario eseguito come root: niente `--script`, `--datadir` o altre
  opzioni oltre a quelle fisse dei cinque profili.
- Nessun file letto o scritto come root.
- Parametri liberi limitati a una lista di porte numeriche.
- Ambiente ripulito (`PATH` fisso, `HOME=/root`, `NMAPDIR` rimossa), in aggiunta alla
  pulizia che sudo fa già con `env_reset`.

**Non garantisce**

- Che l'utente di servizio scansioni solo le reti previste: i target arrivano da
  standard input e possono essere qualunque cosa. Se serve limitarli, usa regole
  firewall in uscita sul server di scansione.
- La sicurezza di Nmap stesso: Nmap analizza come root le risposte degli host
  scansionati, e un host ostile potrebbe sfruttarne eventuali vulnerabilità. Tieni il
  pacchetto `nmap` aggiornato.
- La sicurezza degli script NSE della categoria *version*, che `-sV` esegue come root
  dalla cartella di sistema di Nmap: sono parte del pacchetto della distribuzione.
- La propria integrità: il wrapper deve essere di proprietà di root, non scrivibile da
  altri, in una cartella di root. Dopo ogni aggiornamento rileggine le modifiche prima di
  reinstallarlo (vedi [Installazione → Aggiornamento](installazione.md#aggiornamento)).

## Credenziali

- Stanno solo in `nmap/netbox.env` e `glpi-nmap-adapter/.env`, di proprietà
  dell'utente di servizio con permessi `600`.
- `.gitignore` esclude `.env`, `.env.*` e `*.env`, tranne i modelli `*.env.example`:
  un `git add` distratto non le pubblica.
- Gli script non le passano mai sulla riga di comando, dove sarebbero visibili ad altri
  utenti con `ps`.
- Gli script non stampano mai token o password, nemmeno con `--verbose`. In caso di
  login fallito viene stampata la risposta di GLPI, che non le contiene.
- Usa credenziali dedicate alla pipeline e con permessi minimi:
  - NetBox: un utente con i soli permessi sugli IP Address (lettura, creazione, modifica);
  - GLPI: un profilo con i soli diritti sull'asset `Nmap` e un client API limitato
    all'IP del server di scansione.
- Ruotale periodicamente e revocale quando dismetti la pipeline.

## Dati prodotti

I risultati descrivono quali host esistono, quali porte espongono e quali versioni di
software eseguono. Per un attaccante è la mappa più utile per scegliere un bersaglio,
per esempio un servizio non aggiornato.

| Dove | Cosa |
|---|---|
| `nmap/scans/`, `nmap/work/` | XML e JSON completi di ogni esecuzione |
| `nmap/logs/` | Elenco di IP e porte, esiti degli invii |
| `glpi-nmap-adapter/glpi_nmap_state_legacy.json` | IP presenti e ID corrispondenti in GLPI |
| NetBox, GLPI, inventario Ansible | I dati inviati |

Protezioni consigliate:

- `umask 077` nella riga di cron (vedi [Esecuzione](esecuzione.md#avvio-programmato-cron));
  per le cartelle già create: `sudo chmod 700 /opt/inventory/nmap/scans /opt/inventory/nmap/work /opt/inventory/nmap/logs`.
- Pulizia periodica dei risultati vecchi, secondo la tua politica di conservazione.
- Backup del server cifrati e con accesso controllato.
- In NetBox e GLPI, verifica chi può vedere i campi con porte e servizi.
- Prima di condividere un log (per esempio per chiedere supporto), rimuovi indirizzi e
  nomi.

Gli indirizzi IP e gli hostname di dispositivi assegnati a persone (per esempio
`pc-mario-rossi`) possono essere dati personali ai sensi del GDPR: valutane
conservazione e accessi come per gli altri log di sistema.

## TLS

- La verifica del certificato è attiva per NetBox e GLPI. Usa sempre URL `https://`:
  l'adapter GLPI invia la password con autenticazione HTTP Basic.
- `NETBOX_VERIFY_SSL=false` disattiva la verifica verso NetBox: chiunque sia in grado di
  intercettare il traffico può leggere il token. Usala solo per una diagnosi temporanea.
- L'adapter GLPI non ha un'opzione per disattivare la verifica. Con una CA interna usa
  `REQUESTS_CA_BUNDLE` (vedi [Configurazione](configurazione.md#certificati-di-una-ca-interna)).

## Uso autorizzato e impatto operativo

- **Autorizzazione**: scansiona solo reti di tua proprietà o per cui hai
  un'autorizzazione scritta che indichi perimetro, orari e indirizzo sorgente. Su reti di
  clienti, il perimetro va definito nell'incarico.
- **Coordinamento**: avvisa il SOC o chi gestisce IDS, IPS e firewall. La scansione
  sarà riconosciuta come tale: un orario e un IP sorgente fissi permettono di
  distinguerla da un attacco reale.
- **Sistemi fragili**: i profili sono pensati per reti IT. Escludi da `targets.txt` le
  reti industriali (OT/ICS) e gli apparati fragili: l'invio di 5.000 pacchetti al secondo
  e le sonde di `-sV` possono bloccare PLC, stampanti e dispositivi IoT.
- **Inventario, non vulnerability assessment**: le versioni rilevate aiutano la
  gestione delle vulnerabilità, ma la pipeline non cerca vulnerabilità e non sostituisce
  un assessment.

## Contesto normativo

La pipeline produce evidenza tecnica utile per alcuni requisiti:

- **ISO/IEC 27001:2022, controllo A.5.9** (inventario delle informazioni e degli altri
  asset associati): un inventario di rete aggiornato automaticamente è un supporto
  concreto. Non sostituisce l'inventario richiesto dal controllo, che assegna a ogni
  asset un responsabile.
- **NIS 2, art. 21, par. 2, lett. i)**: tra le misure di gestione del rischio
  cibernetico rientra la gestione degli asset.
