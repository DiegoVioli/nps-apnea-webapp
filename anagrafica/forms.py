from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.models import User
from django.conf import settings
from django.utils.html import format_html

from .consensi import TIPI_CONSENSO, url_documento_consenso
from .models import Gara


class ModuloConsensiMixin:
    def aggiungi_campi_consenso(self):
        documenti = getattr(settings, "DOCUMENTI_CONSENSO", {})
        self.campi_consenso = {}
        for tipo, chiave, etichetta in TIPI_CONSENSO:
            documento = documenti.get(chiave, {})
            versione = documento.get("versione", "PROVVISORIA")
            url = url_documento_consenso(chiave, documento)
            help_text = (
                format_html(
                    '<a href="{}" target="_blank" rel="noopener noreferrer">'
                    "Leggi il modulo (versione {})</a>",
                    url,
                    versione,
                )
                if url
                else (
                    "PDF non ancora disponibile. Puoi comunque confermare "
                    f"la versione {versione}; dovrai accettare nuovamente "
                    "il modulo quando sarà pubblicato."
                )
            )
            nome_campo = f"consenso_{chiave}"
            self.fields[nome_campo] = forms.BooleanField(
                required=True,
                label=etichetta,
                help_text=help_text,
                error_messages={"required": "Questo consenso è obbligatorio."},
            )
            self.campi_consenso[tipo] = nome_campo

class SocioRegistrationForm(ModuloConsensiMixin, UserCreationForm):
    codice_fiscale = forms.CharField(max_length=16)
    data_nascita = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))
    
    class Meta(UserCreationForm.Meta):
        model = User
        fields = UserCreationForm.Meta.fields + ('first_name', 'last_name', 'email', 'codice_fiscale', 'data_nascita')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.aggiungi_campi_consenso()


class SocioLoginForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Nome utente"
        self.fields["password"].label = "Password"


class ConsensoSocioForm(ModuloConsensiMixin, forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.aggiungi_campi_consenso()


class AggiornaScadenzaCertificatoForm(forms.Form):
    nuova_scadenza = forms.DateField(
        label="Nuova scadenza",
        widget=forms.DateInput(attrs={"type": "date"}),
        error_messages={"required": "Inserisci una data di scadenza."},
    )


class RichiestaInformazioniForm(forms.Form):
    nome = forms.CharField(label="Nome", max_length=100)
    email = forms.EmailField(label="Email")
    messaggio = forms.CharField(
        label="Come possiamo aiutarti?",
        max_length=2000,
        widget=forms.Textarea(attrs={"rows": 5}),
    )


class IscrizioneGaraForm(forms.Form):
    def __init__(self, *args, gara, **kwargs):
        super().__init__(*args, **kwargs)
        etichette = dict(Gara.DISCIPLINE_CHOICES)
        discipline = [
            (codice, etichette[codice])
            for codice in gara.discipline
            if codice in etichette
        ]
        self.fields["disciplina"] = forms.ChoiceField(
            label="Scegli una disciplina",
            choices=discipline,
        )
        self.discipline_groups = []

        for codice in gara.discipline:
            nomi_campi = []
            if codice in Gara.DISCIPLINE_DINAMICHE:
                nome_campo = f"distanza_{codice}"
                self.fields[nome_campo] = forms.DecimalField(
                    label=f"{codice} — distanza dichiarata (m)",
                    max_digits=7,
                    decimal_places=2,
                    min_value=0,
                    required=False,
                )
                nomi_campi.append(nome_campo)
            elif codice in Gara.DISCIPLINE_PROFONDITA:
                nome_campo = f"profondita_{codice}"
                self.fields[nome_campo] = forms.DecimalField(
                    label=f"{codice} — profondità dichiarata (m)",
                    max_digits=6,
                    decimal_places=2,
                    min_value=0,
                    required=False,
                )
                nomi_campi.append(nome_campo)
            nome_campo = f"tempo_{codice}"
            self.fields[nome_campo] = forms.DurationField(
                label=f"{codice} — tempo dichiarato (ore:minuti:secondi)",
                widget=forms.TextInput(attrs={"placeholder": "00:00:00"}),
                required=False,
            )
            nomi_campi.append(nome_campo)
            self.discipline_groups.append(
                {
                    "codice": codice,
                    "etichetta": etichette[codice],
                    "campi": [self[name] for name in nomi_campi],
                }
            )

    def clean(self):
        cleaned_data = super().clean()
        disciplina = cleaned_data.get("disciplina")
        if not disciplina:
            return cleaned_data

        campi_obbligatori = []
        if disciplina in Gara.DISCIPLINE_DINAMICHE:
            campi_obbligatori.append(f"distanza_{disciplina}")
        elif disciplina in Gara.DISCIPLINE_PROFONDITA:
            campi_obbligatori.append(f"profondita_{disciplina}")
        campi_obbligatori.append(f"tempo_{disciplina}")

        for nome_campo in campi_obbligatori:
            if cleaned_data.get(nome_campo) is None:
                self.add_error(nome_campo, "Questo dato è obbligatorio per la disciplina scelta.")
        nome_tempo = f"tempo_{disciplina}"
        tempo = cleaned_data.get(nome_tempo)
        if tempo is not None and tempo.total_seconds() < 0:
            self.add_error(nome_tempo, "Il tempo non può essere negativo.")
        return cleaned_data


class RisultatoGaraForm(forms.Form):
    def __init__(self, *args, iscrizione, **kwargs):
        super().__init__(*args, **kwargs)
        risultati = {
            risultato.disciplina: risultato
            for risultato in iscrizione.risultati.all()
        }
        for dichiarazione in iscrizione.dichiarazioni.all():
            codice = dichiarazione.disciplina
            risultato = risultati.get(codice)
            if codice in Gara.DISCIPLINE_DINAMICHE:
                self.fields[f"distanza_{codice}"] = forms.DecimalField(
                    label=f"{codice} — distanza realizzata (m)",
                    max_digits=7,
                    decimal_places=2,
                    min_value=0,
                    required=False,
                    initial=risultato.distanza_m if risultato else None,
                )
            elif codice in Gara.DISCIPLINE_PROFONDITA:
                self.fields[f"profondita_{codice}"] = forms.DecimalField(
                    label=f"{codice} — profondità realizzata (m)",
                    max_digits=6,
                    decimal_places=2,
                    min_value=0,
                    required=False,
                    initial=risultato.profondita_m if risultato else None,
                )
            self.fields[f"tempo_{codice}"] = forms.DurationField(
                label=f"{codice} — tempo realizzato (ore:minuti:secondi)",
                widget=forms.TextInput(attrs={"placeholder": "00:00:00"}),
                required=False,
                initial=risultato.tempo if risultato else None,
            )

    def clean(self):
        cleaned_data = super().clean()
        for nome_campo, valore in cleaned_data.items():
            if (
                nome_campo.startswith("tempo_")
                and valore is not None
                and valore.total_seconds() < 0
            ):
                self.add_error(nome_campo, "Il tempo non può essere negativo.")
        return cleaned_data