# in anagrafica/models.py

from datetime import date
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

# DEFINIZIONE 1: SOCIO
class Socio(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, null=True, blank=True)
    codice_fiscale = models.CharField(max_length=16, unique=True, help_text="Codice Fiscale univoco")
    data_nascita = models.DateField()
    indirizzo = models.CharField(max_length=255, blank=True)
    telefono = models.CharField(max_length=20, blank=True)
    STATO_SOCIO_CHOICES = [
        ('ATTIVO', 'Attivo'), ('SOSPESO', 'Sospeso'),
        ('NON_RINNOVATO', 'Non Rinnovato'), ('PRE_ISCRITTO', 'Pre-Iscritto'),
    ]
    stato = models.CharField(max_length=20, choices=STATO_SOCIO_CHOICES, default='PRE_ISCRITTO')
    data_iscrizione = models.DateField(auto_now_add=True)
    scadenza_quota_sociale = models.DateField(null=True, blank=True)
    scadenza_certificato_medico = models.DateField(null=True, blank=True)
    brevetti = models.TextField(blank=True, help_text="Elenco brevetti conseguiti, separati da virgola")
    
    # RELAZIONE CORRETTA CON STRINGA
    abbonamento_sottoscritto = models.ForeignKey(
        'StagioneAbbonamento', 
        on_delete=models.SET_NULL, null=True, blank=True
    )
    
    gettoni_recupero = models.PositiveIntegerField(default=0)

    @property
    def is_in_regola(self):
        """
        Restituisce True se il socio è ATTIVO e in regola sia con la
        quota sociale che con il certificato medico.
        """
        today = date.today()
        
        # Controlliamo che la data di scadenza esista e sia maggiore o uguale a oggi
        quota_ok = self.scadenza_quota_sociale is not None and self.scadenza_quota_sociale >= today
        certificato_ok = self.scadenza_certificato_medico is not None and self.scadenza_certificato_medico >= today
        
        return self.stato == 'ATTIVO' and quota_ok and certificato_ok
    
    def __str__(self):
        if self.user:
            return f"{self.user.first_name} {self.user.last_name}"
        return f"Socio con CF: {self.codice_fiscale}"

    class Meta:
        verbose_name = "Socio"
        verbose_name_plural = "Soci"


class ModificaScadenzaCertificato(models.Model):
    socio = models.ForeignKey(
        Socio,
        on_delete=models.CASCADE,
        related_name="modifiche_scadenza_certificato",
    )
    scadenza_precedente = models.DateField(null=True, blank=True)
    nuova_scadenza = models.DateField()
    modificato_il = models.DateTimeField(auto_now_add=True)
    modificato_da = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="modifiche_scadenza_certificati",
    )

    class Meta:
        ordering = ("-modificato_il",)
        verbose_name = "Modifica scadenza certificato"
        verbose_name_plural = "Modifiche scadenza certificati"


class RichiestaInformazioni(models.Model):
    TIPI_ATTIVITA = (
        ("corso", "Corso"),
        ("allenamento", "Allenamento"),
    )

    tipo_attivita = models.CharField(max_length=20, choices=TIPI_ATTIVITA)
    nome_attivita = models.CharField(max_length=150)
    edizione_corso = models.ForeignKey(
        "EdizioneCorso",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="richieste_informazioni",
    )
    abbonamento = models.ForeignKey(
        "StagioneAbbonamento",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="richieste_informazioni",
    )
    nome = models.CharField(max_length=100)
    email = models.EmailField()
    messaggio = models.TextField(max_length=2000)
    creata_il = models.DateTimeField(auto_now_add=True)
    email_notificata_il = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-creata_il",)
        verbose_name = "Richiesta informazioni"
        verbose_name_plural = "Richieste informazioni"

    def __str__(self):
        return f"{self.nome} — {self.nome_attivita}"


class ConsensoSocio(models.Model):
    TIPI = [
        ("REGOLAMENTO", "Regolamento ASD"),
        ("PRIVACY", "Trattamento dati personali"),
        ("FOTO_VIDEO", "Foto e video"),
    ]

    socio = models.ForeignKey(
        Socio, on_delete=models.CASCADE, related_name="consensi"
    )
    tipo = models.CharField(max_length=20, choices=TIPI)
    versione_modulo = models.CharField(max_length=50)
    accettato_il = models.DateTimeField()
    indirizzo_ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ("tipo", "-accettato_il")
        indexes = [
            models.Index(fields=("socio", "tipo", "-accettato_il")),
        ]

    def __str__(self):
        return f"{self.get_tipo_display()} v{self.versione_modulo} - {self.socio}"


class PromemoriaCertificato(models.Model):
    socio = models.ForeignKey(
        Socio, on_delete=models.CASCADE, related_name="promemoria_certificati"
    )
    scadenza_certificato = models.DateField()
    ultima_email_inviata = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("socio", "scadenza_certificato"),
                name="unique_socio_certificato_reminder",
            )
        ]


class RiepilogoCertificatiAmministratori(models.Model):
    ultima_email_inviata = models.DateTimeField(null=True, blank=True)


# DEFINIZIONE 2: TURNO ALLENAMENTO
class TurnoAllenamento(models.Model):
    GIORNI_SETTIMANA = [
        (1, 'Lunedì'), (2, 'Martedì'), (3, 'Mercoledì'), (4, 'Giovedì'),
        (5, 'Venerdì'), (6, 'Sabato'), (7, 'Domenica'),
    ]
    nome_turno = models.CharField(max_length=100)
    giorno = models.IntegerField(choices=GIORNI_SETTIMANA)
    orario_inizio = models.TimeField()
    orario_fine = models.TimeField()
    luogo = models.CharField(max_length=100)
    posti_massimi = models.PositiveIntegerField(default=10)

    def __str__(self):
        return self.nome_turno

    class Meta:
        verbose_name = "Turno di Allenamento"
        verbose_name_plural = "Turni di Allenamento"

# DEFINIZIONE 3: PACCHETTO ABBONAMENTO
class PacchettoAbbonamento(models.Model):
    nome = models.CharField(max_length=100, unique=True)
    descrizione = models.TextField(blank=True)
    
    # RELAZIONE CORRETTA CON STRINGA
    turni = models.ManyToManyField('TurnoAllenamento', related_name="pacchetti")
    
    def __str__(self):
        return self.nome

    class Meta:
        verbose_name = "Template Abbonamento"
        verbose_name_plural = "Templates Abbonamenti"

# DEFINIZIONE 4: STAGIONE ABBONAMENTO
class StagioneAbbonamento(models.Model):
    # RELAZIONE CORRETTA CON STRINGA
    pacchetto = models.ForeignKey('PacchettoAbbonamento', on_delete=models.CASCADE)
    stagione = models.CharField(max_length=100, help_text="Es. 'Stagione 2025/2026'")
    prezzo = models.DecimalField(max_digits=6, decimal_places=2)
    data_inizio = models.DateField()
    data_fine = models.DateField()
    termine_disiscrizione = models.DateField(
        null=True,
        blank=True,
        verbose_name="Disiscrizioni entro",
    )
    caparra = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Caparra (€)",
    )
    attivo = models.BooleanField(default=True, help_text="Se attivo, questa offerta stagionale è acquistabile")
    mostra_in_homepage = models.BooleanField(
        default=False,
        verbose_name="Mostra in homepage",
        help_text="Se attivo, l'offerta acquistabile viene mostrata nella homepage pubblica",
    )
    mostra_prezzo_in_homepage = models.BooleanField(
        default=False,
        verbose_name="Mostra prezzo in homepage",
        help_text="Mostra il prezzo in homepage solo se l'offerta è visibile",
    )

    def __str__(self):
        return f"{self.pacchetto.nome} ({self.stagione})"

    def clean(self):
        from django.core.exceptions import ValidationError

        super().clean()
        errors = {}
        if self.termine_disiscrizione is None:
            errors["termine_disiscrizione"] = (
                "Specifica il termine entro cui è possibile disiscriversi."
            )
        elif self.data_inizio and self.termine_disiscrizione > self.data_inizio:
            errors["termine_disiscrizione"] = (
                "Il termine delle disiscrizioni non può essere successivo "
                "all'inizio dell'abbonamento."
            )
        if self.caparra is not None and self.caparra < 0:
            errors["caparra"] = "La caparra non può essere negativa."
        if errors:
            raise ValidationError(errors)
            
    class Meta:
        verbose_name = "Offerta Abbonamento Stagionale"
        verbose_name_plural = "Offerte Abbonamenti Stagionali"


class IscrizioneAbbonamento(models.Model):
    STATI = (
        ("ATTIVA", "Attiva"),
        ("ANNULLATA", "Annullata"),
    )

    socio = models.ForeignKey(
        Socio, on_delete=models.CASCADE, related_name="iscrizioni_abbonamento"
    )
    abbonamento = models.ForeignKey(
        StagioneAbbonamento, on_delete=models.CASCADE, related_name="iscrizioni_soci"
    )
    data_iscrizione = models.DateTimeField(auto_now_add=True)
    stato = models.CharField(max_length=20, choices=STATI, default="ATTIVA")
    annullata_il = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("socio", "abbonamento"),
                name="unique_socio_abbonamento",
            )
        ]


# DEFINIZIONE 5: CORSO
class Corso(models.Model):
    nome = models.CharField(max_length=150)
    descrizione = models.TextField()

    def __str__(self):
        return self.nome

    class Meta:
        verbose_name = "Corso a Catalogo"
        verbose_name_plural = "Corsi a Catalogo"

# DEFINIZIONE 6: EDIZIONE CORSO
class EdizioneCorso(models.Model):
    STATO_CORSO_CHOICES = [
        ('APERTO_ISCRIZIONI', 'Aperto alle Iscrizioni'), ('CONFERMATO', 'Confermato'),
        ('ANNULLATO', 'Annullato'), ('IN_SVOLGIMENTO', 'In Svolgimento'), ('CONCLUSO', 'Concluso'),
    ]
    # RELAZIONI CORRETTE CON STRINGA
    corso = models.ForeignKey('Corso', on_delete=models.CASCADE, related_name="edizioni")
    data_inizio = models.DateField()
    data_fine = models.DateField()
    termine_iscrizioni = models.DateField(
        null=True,
        blank=True,
        verbose_name="Iscrizioni entro",
    )
    termine_disiscrizione = models.DateField(
        null=True,
        blank=True,
        verbose_name="Disiscrizioni entro",
    )
    posti_massimi = models.PositiveIntegerField()
    numero_minimo_partecipanti = models.PositiveIntegerField(default=4)
    prezzo = models.DecimalField(max_digits=6, decimal_places=2)
    caparra = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Caparra (€)",
    )
    stato = models.CharField(max_length=20, choices=STATO_CORSO_CHOICES, default='APERTO_ISCRIZIONI')
    iscritti = models.ManyToManyField(
        "Socio",
        related_name="corsi_iscritti",
        blank=True,
        through="IscrizioneCorso",
    )

    def __str__(self):
        return f"{self.corso.nome} - dal {self.data_inizio}"

    def clean(self):
        from django.core.exceptions import ValidationError

        super().clean()
        errors = {}
        if self.termine_iscrizioni is None:
            errors["termine_iscrizioni"] = "Specifica il termine delle iscrizioni."
        elif self.data_inizio and self.termine_iscrizioni > self.data_inizio:
            errors["termine_iscrizioni"] = (
                "Il termine delle iscrizioni non può essere successivo "
                "all'inizio del corso."
            )
        if self.termine_disiscrizione is None:
            errors["termine_disiscrizione"] = (
                "Specifica il termine entro cui è possibile disiscriversi."
            )
        elif self.data_inizio and self.termine_disiscrizione > self.data_inizio:
            errors["termine_disiscrizione"] = (
                "Il termine delle disiscrizioni non può essere successivo "
                "all'inizio del corso."
            )
        if self.caparra is not None and self.caparra < 0:
            errors["caparra"] = "La caparra non può essere negativa."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.data_fine < timezone.localdate() and self.stato != "ANNULLATO":
            self.stato = "CONCLUSO"
            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                kwargs["update_fields"] = {*update_fields, "stato"}
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = "Edizione di un Corso"
        verbose_name_plural = "Edizioni dei Corsi"


class IscrizioneCorso(models.Model):
    STATI = (
        ("ATTIVA", "Attiva"),
        ("ANNULLATA", "Annullata"),
    )

    socio = models.ForeignKey(
        Socio,
        on_delete=models.CASCADE,
        related_name="iscrizioni_corso",
    )
    edizione = models.ForeignKey(
        EdizioneCorso,
        on_delete=models.CASCADE,
        related_name="iscrizioni",
    )
    data_iscrizione = models.DateTimeField(auto_now_add=True)
    stato = models.CharField(max_length=20, choices=STATI, default="ATTIVA")
    annullata_il = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("socio", "edizione"),
                name="unique_socio_edizione_corso",
            )
        ]
        verbose_name = "Iscrizione corso"
        verbose_name_plural = "Iscrizioni corsi"

    def __str__(self):
        return f"{self.socio} - {self.edizione}"


class Attivita(models.Model):
    TIPI = (
        ("USCITA_MARE", "Uscita al mare"),
        ("USCITA_LAGO", "Uscita al lago"),
        ("Y40", "Uscita a Y-40"),
        ("ALTRO", "Altra attività"),
    )

    nome = models.CharField(max_length=150)
    tipo = models.CharField(max_length=20, choices=TIPI, default="ALTRO")
    descrizione = models.TextField(blank=True)
    data = models.DateField(verbose_name="Data attività")
    luogo = models.CharField(max_length=200)
    termine_iscrizioni = models.DateField(verbose_name="Iscrizioni entro")
    termine_disiscrizione = models.DateField(verbose_name="Disiscrizioni entro")
    prezzo = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=0,
        verbose_name="Quota (€)",
    )
    caparra = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Caparra (€)",
    )
    pubblicata = models.BooleanField(
        default=True,
        verbose_name="Pubblicata",
    )

    class Meta:
        ordering = ("data", "nome")
        verbose_name = "Attività"
        verbose_name_plural = "Attività"

    def clean(self):
        from django.core.exceptions import ValidationError

        super().clean()
        errors = {}
        if self.data and self.termine_iscrizioni and self.termine_iscrizioni > self.data:
            errors["termine_iscrizioni"] = (
                "Il termine delle iscrizioni non può essere successivo "
                "alla data dell'attività."
            )
        if (
            self.data
            and self.termine_disiscrizione
            and self.termine_disiscrizione > self.data
        ):
            errors["termine_disiscrizione"] = (
                "Il termine delle disiscrizioni non può essere successivo "
                "alla data dell'attività."
            )
        if self.prezzo is not None and self.prezzo < 0:
            errors["prezzo"] = "La quota non può essere negativa."
        if self.caparra is not None and self.caparra < 0:
            errors["caparra"] = "La caparra non può essere negativa."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return self.nome


class IscrizioneAttivita(models.Model):
    STATI = (
        ("ATTIVA", "Attiva"),
        ("ANNULLATA", "Annullata"),
    )

    socio = models.ForeignKey(
        Socio,
        on_delete=models.CASCADE,
        related_name="iscrizioni_attivita",
    )
    attivita = models.ForeignKey(
        Attivita,
        on_delete=models.CASCADE,
        related_name="iscrizioni",
    )
    data_iscrizione = models.DateTimeField(auto_now_add=True)
    stato = models.CharField(max_length=20, choices=STATI, default="ATTIVA")
    annullata_il = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("socio", "attivita"),
                condition=models.Q(stato="ATTIVA"),
                name="unique_active_socio_attivita",
            )
        ]
        verbose_name = "Iscrizione attività"
        verbose_name_plural = "Iscrizioni attività"

    def __str__(self):
        return f"{self.socio} - {self.attivita}"


class Gara(models.Model):
    DISCIPLINE_CHOICES = (
        ("DYN", "DYN - apnea dinamica con pinne"),
        ("DNF", "DNF - apnea dinamica senza pinne"),
        ("STA", "STA - apnea statica"),
        ("CWT", "CWT - assetto costante con pinne"),
        ("CNF", "CNF - assetto costante senza pinne"),
        ("FIM", "FIM - free immersion"),
    )
    DISCIPLINE_DINAMICHE = {"DYN", "DNF"}
    DISCIPLINE_PROFONDITA = {"CWT", "CNF", "FIM"}

    nome = models.CharField(max_length=150, verbose_name="Nome gara")
    luogo = models.CharField(max_length=200, blank=True, verbose_name="Luogo")
    data_gara = models.DateField(verbose_name="Data della gara")
    termine_iscrizioni = models.DateField(verbose_name="Iscrizioni entro")
    prezzo = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        verbose_name="Quota di iscrizione (€)",
    )
    caparra = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Caparra (€)",
    )
    termine_disiscrizione = models.DateField(
        null=True,
        blank=True,
        verbose_name="Disiscrizioni entro",
    )
    discipline = models.JSONField(default=list, verbose_name="Discipline")
    pubblicata = models.BooleanField(
        default=True,
        verbose_name="Pubblicata",
        help_text="Se disattivata, la gara non è visibile ai soci.",
    )

    class Meta:
        ordering = ("data_gara", "nome")
        verbose_name = "Gara"
        verbose_name_plural = "Gare"

    def clean(self):
        from django.core.exceptions import ValidationError

        super().clean()
        codici_validi = {codice for codice, _ in self.DISCIPLINE_CHOICES}
        if (
            not isinstance(self.discipline, list)
            or not self.discipline
            or any(not isinstance(codice, str) for codice in self.discipline)
        ):
            raise ValidationError(
                {"discipline": "Seleziona almeno una disciplina."}
            )
        if (
            len(self.discipline) != len(set(self.discipline))
            or not set(self.discipline).issubset(codici_validi)
        ):
            raise ValidationError(
                {"discipline": "Una o più discipline selezionate non sono valide."}
            )
        if self.termine_iscrizioni and self.data_gara:
            if self.termine_iscrizioni > self.data_gara:
                raise ValidationError(
                    {
                        "termine_iscrizioni": (
                            "La scadenza delle iscrizioni non può essere "
                            "successiva alla data della gara."
                        )
                    }
                )
        if self.prezzo is not None and self.prezzo < 0:
            raise ValidationError({"prezzo": "Il prezzo non può essere negativo."})
        if self.caparra is not None and self.caparra < 0:
            raise ValidationError({"caparra": "La caparra non può essere negativa."})
        if self.termine_disiscrizione is None:
            raise ValidationError(
                {
                    "termine_disiscrizione": (
                        "Specifica il termine entro cui è possibile disiscriversi."
                    )
                }
            )
        if self.termine_disiscrizione > self.data_gara:
            raise ValidationError(
                {
                    "termine_disiscrizione": (
                        "Il termine delle disiscrizioni non può essere "
                        "successivo alla data della gara."
                    )
                }
            )

    @property
    def discipline_display(self):
        labels = dict(self.DISCIPLINE_CHOICES)
        return ", ".join(
            labels[codice]
            for codice in self.discipline
            if isinstance(codice, str) and codice in labels
        )

    def __str__(self):
        return self.nome


class IscrizioneGara(models.Model):
    STATI = (
        ("IN_ATTESA", "In attesa di conferma"),
        ("ISCRITTO", "Iscritto"),
        ("ANNULLATA", "Annullata"),
    )

    socio = models.ForeignKey(
        Socio,
        on_delete=models.CASCADE,
        related_name="iscrizioni_gara",
    )
    gara = models.ForeignKey(
        Gara,
        on_delete=models.CASCADE,
        related_name="iscrizioni",
    )
    stato = models.CharField(
        max_length=20,
        choices=STATI,
        default="IN_ATTESA",
    )
    richiesta_il = models.DateTimeField(auto_now_add=True)
    confermata_il = models.DateTimeField(null=True, blank=True)
    annullata_il = models.DateTimeField(null=True, blank=True)
    email_conferma_inviata_il = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("gara__data_gara", "socio__user__last_name")
        constraints = [
            models.UniqueConstraint(
                fields=("socio", "gara"),
                name="unique_socio_gara",
            )
        ]
        verbose_name = "Iscrizione gara"
        verbose_name_plural = "Iscrizioni gare"

    @property
    def certificato_valido_alla_data_gara(self):
        scadenza = self.socio.scadenza_certificato_medico
        return scadenza is not None and scadenza >= self.gara.data_gara

    def __str__(self):
        return f"{self.socio} - {self.gara}"


class DichiarazioneGara(models.Model):
    iscrizione = models.ForeignKey(
        IscrizioneGara,
        on_delete=models.CASCADE,
        related_name="dichiarazioni",
    )
    disciplina = models.CharField(max_length=3, choices=Gara.DISCIPLINE_CHOICES)
    distanza_m = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Distanza dichiarata (m)",
    )
    profondita_m = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Profondità dichiarata (m)",
    )
    tempo = models.DurationField(null=True, blank=True, verbose_name="Tempo dichiarato")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("iscrizione", "disciplina"),
                name="unique_dichiarazione_iscrizione_disciplina",
            )
        ]
        verbose_name = "Dichiarazione gara"
        verbose_name_plural = "Dichiarazioni gara"

    def clean(self):
        from django.core.exceptions import ValidationError

        super().clean()
        if not self.disciplina:
            return
        iscrizione = self._state.fields_cache.get("iscrizione")
        if iscrizione is None:
            if not self.iscrizione_id:
                return
            iscrizione = self.iscrizione
        if self.disciplina not in iscrizione.gara.discipline:
            raise ValidationError(
                {"disciplina": "La disciplina non è prevista per questa gara."}
            )
        errori = {}
        if self.disciplina in Gara.DISCIPLINE_DINAMICHE:
            if self.distanza_m is None:
                errori["distanza_m"] = "Inserisci la distanza dichiarata."
            if self.tempo is None:
                errori["tempo"] = "Inserisci il tempo dichiarato."
            if self.profondita_m is not None:
                errori["profondita_m"] = "La profondità non si applica a questa disciplina."
        elif self.disciplina == "STA":
            if self.tempo is None:
                errori["tempo"] = "Inserisci il tempo dichiarato."
            if self.distanza_m is not None or self.profondita_m is not None:
                errori["distanza_m"] = "Distanza e profondità non si applicano alla STA."
        else:
            if self.profondita_m is None:
                errori["profondita_m"] = "Inserisci la profondità dichiarata."
            if self.tempo is None:
                errori["tempo"] = "Inserisci il tempo dichiarato."
            if self.distanza_m is not None:
                errori["distanza_m"] = "La distanza non si applica a questa disciplina."
        if self.distanza_m is not None and self.distanza_m < 0:
            errori["distanza_m"] = "La distanza non può essere negativa."
        if self.profondita_m is not None and self.profondita_m < 0:
            errori["profondita_m"] = "La profondità non può essere negativa."
        if self.tempo is not None and self.tempo.total_seconds() < 0:
            errori["tempo"] = "Il tempo non può essere negativo."
        if errori:
            raise ValidationError(errori)


class RisultatoGara(models.Model):
    iscrizione = models.ForeignKey(
        IscrizioneGara,
        on_delete=models.CASCADE,
        related_name="risultati",
    )
    disciplina = models.CharField(max_length=3, choices=Gara.DISCIPLINE_CHOICES)
    distanza_m = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Distanza realizzata (m)",
    )
    profondita_m = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Profondità realizzata (m)",
    )
    tempo = models.DurationField(null=True, blank=True, verbose_name="Tempo realizzato")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("iscrizione", "disciplina"),
                name="unique_risultato_iscrizione_disciplina",
            )
        ]
        verbose_name = "Risultato gara"
        verbose_name_plural = "Risultati gare"

    def clean(self):
        from django.core.exceptions import ValidationError

        super().clean()
        if not self.iscrizione_id or not self.disciplina:
            return
        if self.disciplina not in self.iscrizione.gara.discipline:
            raise ValidationError(
                {"disciplina": "La disciplina non è prevista per questa gara."}
            )
        errori = {}
        if self.disciplina in Gara.DISCIPLINE_DINAMICHE:
            if self.profondita_m is not None:
                errori["profondita_m"] = "La profondità non si applica a questa disciplina."
        elif self.disciplina == "STA":
            if self.distanza_m is not None or self.profondita_m is not None:
                errori["distanza_m"] = "Distanza e profondità non si applicano alla STA."
        elif self.distanza_m is not None:
            errori["distanza_m"] = "La distanza non si applica a questa disciplina."
        if self.distanza_m is not None and self.distanza_m < 0:
            errori["distanza_m"] = "La distanza non può essere negativa."
        if self.profondita_m is not None and self.profondita_m < 0:
            errori["profondita_m"] = "La profondità non può essere negativa."
        if self.tempo is not None and self.tempo.total_seconds() < 0:
            errori["tempo"] = "Il tempo non può essere negativo."
        if errori:
            raise ValidationError(errori)