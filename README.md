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