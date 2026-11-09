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
    attivo = models.BooleanField(default=True, help_text="Se attivo, questa offerta stagionale è acquistabile")

    def __str__(self):
        return f"{self.pacchetto.nome} ({self.stagione})"
            
    class Meta:
        verbose_name = "Offerta Abbonamento Stagionale"
        verbose_name_plural = "Offerte Abbonamenti Stagionali"


class IscrizioneAbbonamento(models.Model):
    socio = models.ForeignKey(
        Socio, on_delete=models.CASCADE, related_name="iscrizioni_abbonamento"
    )
    abbonamento = models.ForeignKey(
        StagioneAbbonamento, on_delete=models.CASCADE, related_name="iscrizioni_soci"
    )
    data_iscrizione = models.DateTimeField(auto_now_add=True)

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
    iscritti = models.ManyToManyField('Socio', related_name="corsi_iscritti", blank=True)
    
    data_inizio = models.DateField()
    data_fine = models.DateField()
    posti_massimi = models.PositiveIntegerField()
    numero_minimo_partecipanti = models.PositiveIntegerField(default=4)
    prezzo = models.DecimalField(max_digits=6, decimal_places=2)
    stato = models.CharField(max_length=20, choices=STATO_CORSO_CHOICES, default='APERTO_ISCRIZIONI')

    def __str__(self):
        return f"{self.corso.nome} - dal {self.data_inizio}"

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