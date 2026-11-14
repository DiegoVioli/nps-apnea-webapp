# nps-apnea-webapp

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