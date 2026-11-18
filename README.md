# nps-apnea-webapp

## Setup iniziale

Prima di avviare l'applicazione, creare un file `.env` partendo da `.env.example` e personalizzarne i valori:

```powershell
Copy-Item .env.example .env
```

Le variabili principali sono:

- `SECRET_KEY`
- `DEBUG`
- `ALLOWED_HOSTS`
- `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USE_TLS`, `EMAIL_USE_SSL`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL`
- `CERTIFICATI_API_TOKEN`
- `CONSENSO_*_URL` e `CONSENSO_*_VERSIONE`

Il file `.env` non va mai committato nel repository.

## Avvio in produzione

Non usare i valori di sviluppo di `.env.example` in produzione. Configurare
nell'ambiente del server o nel secret manager:

- `DEBUG=False`
- `SECRET_KEY`: chiave casuale dedicata all'ambiente, di almeno 50 caratteri.
  Generarla con `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"`.
- `ALLOWED_HOSTS`: solo i nomi host pubblici, senza schema o porte, separati da
  virgole (per esempio `app.example.org`).
- `CSRF_TRUSTED_ORIGINS`: origini complete con schema HTTPS, separate da
  virgole (per esempio `https://app.example.org`).
- credenziali SMTP e `CERTIFICATI_API_TOKEN`, se si usano le relative
  funzionalità.
- versioni definitive e URL dei documenti di consenso.

Con `DEBUG=False`, Django attiva per default il redirect HTTPS, i cookie
`Secure` e HSTS per un anno. Servire il sito solo tramite HTTPS prima di
abilitare la produzione. Se TLS termina su un reverse proxy, impostare
`USE_X_FORWARDED_PROTO=True` soltanto quando il proxy di fiducia rimuove e
riscrive sempre l'header `X-Forwarded-Proto`; non abilitarlo se quell'header può
essere fornito direttamente dal client. Impostare `SECURE_SSL_REDIRECT=False`
solo se il redirect HTTPS è gestito in modo affidabile a monte.
HSTS per sottodomini e preload non sono attivi per default: abilitarli solo
dopo aver verificato che tutti i sottodomini siano serviti esclusivamente via
HTTPS e aver deciso di rendere permanente tale policy nei browser.

Prima del rilascio, eseguire:

```powershell
python manage.py check --deploy
python manage.py migrate
python manage.py collectstatic --noinput
```

Il database predefinito resta SQLite: conservarlo su disco persistente e
prevedere backup verificati; non condividere lo stesso file SQLite tra più
istanze applicative. Per deployment con più istanze, configurare un database
server gestito e il relativo backend Django.

## Gare agonistiche

Lo staff crea e pubblica le gare da **Amministrazione > Gare**, indicando
quota, data, termine d'iscrizione e discipline (DYN, DNF, STA, CWT, CNF e FIM).
Le gare pubblicate sono visibili nell'area socio ai soci attivi; la quota è
informativa, il gestionale non processa pagamenti.

Ogni socio può iscriversi una sola volta per gara, scegliendo una sola delle
discipline offerte. Dichiara distanza e tempo per DYN/DNF, tempo per STA,
profondità e tempo per CWT/CNF/FIM. La richiesta resta **In attesa di conferma**
fino a quando lo staff la conferma da **Amministrazione > Iscrizioni gare**.
Finché resta in attesa e il termine d'iscrizione non è scaduto, il socio può
modificare la dichiarazione dalla propria area. La conferma invia un'email; se
l'invio fallisce, lo staff può riprovare con l'azione di reinvio nell'admin.
Lo staff può anche aggiungere manualmente un socio attivo da
**Amministrazione > Iscrizioni gare**, selezionando gara e dichiarazione; la
nuova iscrizione resta in attesa fino alla conferma con l'azione dell'admin.
Il certificato medico deve essere presente e valido almeno fino alla data
della gara sia al momento della richiesta sia alla conferma; l'admin mostra
un indicatore e blocca la conferma se il requisito non è soddisfatto. La data
di invio email registrata sull'iscrizione distingue gli invii riusciti da quelli
da riprovare.

Le gare concluse e confermate compaiono nello storico del socio, che può
inserire e aggiornare i risultati personali (distanza, profondità e tempo).
Applicare la migration prima di distribuire la funzionalità:

```powershell
python manage.py migrate
```

## Promemoria certificati medici

Il comando Django `invia_promemoria_certificati` invia un'email ai soci iscritti
a un corso non concluso o a un abbonamento stagionale non scaduto, quando il
certificato medico scade nei prossimi 30 giorni. Gli invii si ripetono al
massimo una volta ogni 7 giorni per la stessa scadenza; i certificati già
scaduti non generano promemoria. Gli amministratori attivi con un indirizzo
email configurato sono messi in CC ai promemoria individuali. Lo stesso comando
invia loro un riepilogo dei certificati in scadenza o scaduti al massimo una
volta ogni 7 giorni, anche quando non ci sono certificati da segnalare.

Applicare le migrazioni prima del primo avvio:

```powershell
python manage.py migrate
```

Configurare l'invio SMTP tramite le variabili d'ambiente `EMAIL_HOST`,
`EMAIL_PORT`, `EMAIL_USE_TLS`, `EMAIL_USE_SSL`, `EMAIL_HOST_USER`,
`EMAIL_HOST_PASSWORD` e `DEFAULT_FROM_EMAIL`. `EMAIL_BACKEND` può essere
impostato per usare un backend Django diverso. Le credenziali non vanno inserite
nel repository.

Eseguire manualmente il batch con:

```powershell
python manage.py invia_promemoria_certificati
```

Per l'invio giornaliero, pianificare questo comando una volta al giorno tramite
Utilità di pianificazione di Windows o lo scheduler del server. I promemoria
sono registrati solo dopo l'invio riuscito; un errore viene riportato nel log
del comando, che termina con errore così lo scheduler può rilevarlo.

## Chiusura automatica dei corsi

Un'edizione con data di fine precedente a oggi viene segnata come `CONCLUSO`
quando viene salvata. La dashboard non mostra tra i corsi aperti le edizioni
la cui data di fine è già passata. Per aggiornare ogni giorno anche le edizioni
che nessuno ha modificato, pianificare questo comando tramite Utilità di
pianificazione di Windows o lo scheduler del server:

```powershell
python manage.py chiudi_corsi_scaduti
```

Il comando mantiene invariato lo stato `ANNULLATO` e lascia aperte le edizioni
che terminano oggi.

## Storico iscrizioni

La dashboard mostra nella sezione "Storico iscrizioni" le edizioni dei corsi
concluse a cui il socio era iscritto e le offerte stagionali sottoscritte la cui
data di fine è passata. La migrazione crea lo storico delle offerte attualmente
associate ai soci; le nuove sottoscrizioni vengono registrate automaticamente.
Applicare la migrazione con `python manage.py migrate`.

## Certificati medici e privacy

Il gestionale conserva la data di scadenza del certificato medico, ma non
carica né archivia copie o PDF del certificato. Dopo aver distribuito il
modello aggiornato, applicare la migrazione con `python manage.py migrate`.

Gli utenti staff possono consultare dalla homepage l'elenco dei soci attivi
con certificato scaduto o in scadenza entro 30 giorni. La pagina consente di
aggiornare la scadenza e registra chi ha effettuato la modifica. I corsi aperti
e le offerte di allenamento attive selezionate con "Mostra in homepage" sono
visibili nella homepage; il prezzo delle offerte appare solo se è attiva anche
l'opzione "Mostra prezzo in homepage".

### API per i promemoria

Le API per il sistema esterno di promemoria richiedono un token Bearer. Prima
dell'avvio, configurare `CERTIFICATI_API_TOKEN` nell'ambiente del server con un
valore casuale e mantenerlo fuori dal repository. Senza token configurato le
API rispondono con errore `503`; token mancante o non valido restituisce `401`.

- `GET /api/v1/promemoria/candidati/` restituisce i soci attivi con certificato
  scaduto o in scadenza entro 30 giorni, escludendo quelli già avvisati negli
  ultimi 7 giorni.
- `POST /api/v1/promemoria/inviati/` registra gli invii confermati dal sistema
  esterno. Il JSON deve contenere `inviati`, un elenco di oggetti con
  `socio_id` e `data_scadenza` nel formato `AAAA-MM-GG`. Gli invii duplicati
  entro 7 giorni non vengono registrati nuovamente; una data non più corrente
  viene rifiutata.

## Richieste di informazioni sulle attività

Dalla homepage pubblica è possibile chiedere informazioni sui corsi aperti e
sugli allenamenti attivi pubblicati. La richiesta viene salvata nell'area
amministrativa e notificata via email agli utenti staff con un indirizzo email
configurato; chi invia riceve la risposta all'indirizzo indicato. Configurare
l'invio email con le variabili descritte nella sezione dei promemoria. Lo staff
può consultare le richieste nell'admin, senza modificarle o eliminarle.

Applicare la migration con `python manage.py migrate` in ambienti con una
cronologia migration coerente. Nel database locale ripristinato, la cronologia
è stata riallineata verificando lo schema esistente; la colonna legacy
`file_certificato_medico` è stata mantenuta perché conteneva dati. Per altri
database preesistenti, creare un backup e verificare cronologia e schema prima
di applicare migration. I dati del modulo vengono conservati nel database e
vanno gestiti secondo l'informativa privacy dell'associazione.

## Consensi obbligatori

La registrazione richiede l'accettazione del Regolamento ASD, dell'informativa
privacy e del modulo foto/video. Per ogni accettazione vengono registrati il
socio, il tipo e la versione del modulo, la data e ora e l'indirizzo IP visto
dal server. Le accettazioni precedenti vengono conservate; se cambia la
versione di un modulo, il socio deve accettare la nuova versione prima di
accedere alla dashboard.

I moduli legali non sono inclusi né precompilati dal gestionale. Per consentire
i test, registrazione e accettazione sono possibili anche prima che i documenti
siano pronti: in questo caso il sistema registra la versione `PROVVISORIA` (o
`DA_CONFIGURARE` se impostata esplicitamente). Queste accettazioni non
sostituiscono i consensi informati sui documenti approvati. Quando si
configurano le versioni definitive, i soci devono accettarle nuovamente prima
di accedere alla dashboard.

I PDF approvati possono essere salvati in
`anagrafica/static/anagrafica/documenti_consenso/` con i nomi
`regolamento.pdf`, `privacy.pdf` e `foto_video.pdf`; se presenti, vengono
collegati automaticamente nella pagina dei consensi. In alternativa, è
possibile configurare URL pubblici. Configurare le versioni definitive tramite
le variabili d'ambiente
`CONSENSO_REGOLAMENTO_URL`, `CONSENSO_REGOLAMENTO_VERSIONE`,
`CONSENSO_PRIVACY_URL`, `CONSENSO_PRIVACY_VERSIONE`,
`CONSENSO_FOTO_VIDEO_URL` e `CONSENSO_FOTO_VIDEO_VERSIONE`. Gli URL possono
essere omessi quando i PDF sono nella cartella statica indicata sopra.

L'IP è un dato personale: l'informativa privacy deve indicarne la raccolta,
finalità, conservazione e periodo di retention. In ambienti dietro un proxy
`REMOTE_ADDR` può identificare il proxy anziché il dispositivo del socio.
Applicare la migrazione con `python manage.py migrate`.

## Elenco certificati e API promemoria

Gli utenti autenticati con permesso staff possono consultare
`/staff/certificati/`, che mostra i soci attivi con certificato scaduto o in
scadenza entro 30 giorni.

Un batch esterno può ottenere i promemoria attualmente inviabili con:

```text
GET /api/v1/promemoria/candidati/
Authorization: Bearer <CERTIFICATI_API_TOKEN>
```

La risposta include ID socio, nome, cognome, email, telefono, data di scadenza,
giorni alla scadenza e stato del certificato. Sono inclusi solo soci attivi con
un indirizzo utente associato; vengono esclusi i certificati mancanti, quelli
con scadenza oltre 30 giorni e i promemoria già inviati negli ultimi 7 giorni
per la stessa scadenza.

Dopo aver inviato le email, il batch deve comunicare i soli invii riusciti:

```text
POST /api/v1/promemoria/inviati/
Authorization: Bearer <CERTIFICATI_API_TOKEN>
Content-Type: application/json

{
  "inviati": [
    {"socio_id": 123, "data_scadenza": "2026-12-01"}
  ]
}
```

Il server registra l'ora di ricezione del report in
`PromemoriaCertificato.ultima_email_inviata`. Il batch deve inviare il report
solo dopo la conferma SMTP positiva e usare l'ID e la data di scadenza ricevuti
dall'endpoint dei candidati. Le date non più corrispondenti a quelle attuali o
i soci non più attivi vengono rifiutati senza registrare parzialmente la lista.
Il reinvio dello stesso report entro 7 giorni non modifica la data già
registrata.

Configurare `CERTIFICATI_API_TOKEN` come variabile d'ambiente con un valore
casuale robusto, uguale sul server e sul PC del batch. Non inserirlo nel
repository né nei log; usare l'API solo tramite HTTPS. La pagina staff richiede
il normale login alla webapp; gli endpoint API richiedono il token e non
utilizzano la sessione del browser.

Nella stessa pagina staff è possibile aggiornare la scadenza del certificato
dei soci elencati. Ogni variazione effettiva viene salvata insieme alla data
precedente, alla nuova data, al timestamp e all'utente staff che l'ha eseguita.
La cronologia è consultabile nell'area admin Django alla voce "Modifiche
scadenza certificati" ed è in sola lettura.

## Richieste di informazioni sulle attività

Ogni corso aperto e abbonamento attivo in home include un collegamento al
modulo pubblico per chiedere informazioni. Il modulo salva nome, email,
messaggio, attività selezionata e timestamp nella sezione "Richieste
informazioni" dell'admin. Dopo il salvataggio, il sistema invia una notifica
agli utenti staff attivi con email configurata; in caso di errore SMTP, la
richiesta resta salvata e la mancata notifica viene registrata nei log. La data
di notifica email viene registrata solo dopo l'invio riuscito.

L'informativa privacy deve descrivere la raccolta dei recapiti, l'uso per
rispondere alla richiesta, i destinatari interni e il periodo di conservazione.