from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.conf import settings
from django.utils.html import format_html

from .consensi import TIPI_CONSENSO, url_documento_consenso


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


class ConsensoSocioForm(ModuloConsensiMixin, forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.aggiungi_campi_consenso()