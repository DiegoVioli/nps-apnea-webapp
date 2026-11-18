from django.contrib import admin
from django.contrib import messages
from django import forms
from django.core.exceptions import ValidationError
from django.forms.models import BaseInlineFormSet
from django.http import HttpResponse
from django.template.loader import render_to_string
from datetime import date, timedelta 
from .gare import conferma_iscrizione_gara, invia_email_conferma_gara
from .models import (
    ConsensoSocio,
    DichiarazioneGara,
    Gara,
    IscrizioneGara,
    RisultatoGara,
    Socio,
    TurnoAllenamento,
    PacchettoAbbonamento,
    StagioneAbbonamento,
    Corso,
    EdizioneCorso,
    ModificaScadenzaCertificato,
    RichiestaInformazioni,
)


class GaraAdminForm(forms.ModelForm):
    discipline = forms.MultipleChoiceField(
        choices=Gara.DISCIPLINE_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        label="Discipline",
    )

    class Meta:
        model = Gara
        fields = "__all__"


class DichiarazioneGaraInlineFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        if self.instance.pk or not self.instance.gara_id or any(self.errors):
            return

        for form in self.forms:
            if not form.cleaned_data or form.cleaned_data.get("DELETE"):
                continue
            form.instance.iscrizione = self.instance
            try:
                form.instance.full_clean(exclude=("iscrizione",))
            except ValidationError as error:
                form.add_error(None, error)


class DichiarazioneGaraInline(admin.TabularInline):
    model = DichiarazioneGara
    formset = DichiarazioneGaraInlineFormSet
    extra = 1
    can_delete = False
    fields = ("disciplina", "distanza_m", "profondita_m", "tempo")
    validate_min = True
    validate_max = True
    max_num = 1

    def get_min_num(self, request, obj=None):
        return 1 if obj is None else 0

    def get_readonly_fields(self, request, obj=None):
        return self.fields if obj is not None else ()

    def has_add_permission(self, request, obj=None):
        return obj is None and super().has_add_permission(request, obj)

    def get_formset(self, request, obj=None, **kwargs):
        formset = super().get_formset(request, obj, **kwargs)
        gara = getattr(obj, "gara", None)
        if gara is None:
            gara_id = request.POST.get("gara") or request.GET.get("gara")
            if gara_id and str(gara_id).isdigit():
                gara = Gara.objects.filter(pk=gara_id).first()
        if gara is not None and "disciplina" in formset.form.base_fields:
            formset.form.base_fields["disciplina"].choices = [
                choice
                for choice in Gara.DISCIPLINE_CHOICES
                if choice[0] in gara.discipline
            ]
        return formset


class RisultatoGaraInline(admin.TabularInline):
    model = RisultatoGara
    extra = 0
    can_delete = False
    fields = ("disciplina", "distanza_m", "profondita_m", "tempo")
    readonly_fields = fields


@admin.register(Gara)
class GaraAdmin(admin.ModelAdmin):
    form = GaraAdminForm
    list_display = (
        "nome",
        "data_gara",
        "termine_iscrizioni",
        "prezzo",
        "pubblicata",
    )
    list_filter = ("pubblicata", "data_gara")
    search_fields = ("nome", "luogo")
    ordering = ("data_gara", "nome")


@admin.register(IscrizioneGara)
class IscrizioneGaraAdmin(admin.ModelAdmin):
    list_display = (
        "gara",
        "socio",
        "stato",
        "richiesta_il",
        "certificato_valido_alla_gara",
        "email_conferma_inviata_il",
    )
    list_filter = ("stato", "gara")
    search_fields = (
        "gara__nome",
        "socio__user__first_name",
        "socio__user__last_name",
        "socio__user__email",
    )
    readonly_fields = (
        "gara",
        "socio",
        "stato",
        "richiesta_il",
        "confermata_il",
        "certificato_valido_alla_gara",
        "email_conferma_inviata_il",
    )
    inlines = (DichiarazioneGaraInline, RisultatoGaraInline)
    actions = ("conferma_iscrizioni", "reinvia_email_conferme")

    def get_fields(self, request, obj=None):
        if obj is None:
            return ("gara", "socio")
        return super().get_fields(request, obj)

    def get_readonly_fields(self, request, obj=None):
        if obj is None:
            return ()
        return self.readonly_fields

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "socio":
            kwargs["queryset"] = Socio.objects.filter(stato="ATTIVO").select_related(
                "user"
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(
        boolean=True,
        description="Certificato valido alla data della gara",
    )
    def certificato_valido_alla_gara(self, obj):
        return obj.certificato_valido_alla_data_gara

    @admin.action(description="Conferma le iscrizioni selezionate")
    def conferma_iscrizioni(self, request, queryset):
        confermate = 0
        email_inviate = 0
        email_da_inviare = 0
        certificati_non_validi = 0
        for iscrizione in queryset.select_related("gara", "socio__user"):
            if not iscrizione.certificato_valido_alla_data_gara:
                certificati_non_validi += 1
                continue
            modificata, email_inviata = conferma_iscrizione_gara(iscrizione)
            if modificata:
                confermate += 1
                if email_inviata:
                    email_inviate += 1
                else:
                    email_da_inviare += 1
        self.message_user(
            request,
            f"Iscrizioni confermate: {confermate}. Email inviate: {email_inviate}.",
            level=messages.SUCCESS,
        )
        if email_da_inviare:
            self.message_user(
                request,
                f"Email non inviate: {email_da_inviare}. Verifica gli indirizzi "
                "e la configurazione SMTP; puoi usare l'azione di reinvio.",
                level=messages.WARNING,
            )
        if certificati_non_validi:
            self.message_user(
                request,
                f"Iscrizioni non confermate: {certificati_non_validi}. "
                "Il certificato medico manca o scade prima della gara.",
                level=messages.ERROR,
            )

    @admin.action(description="Reinvia le email di conferma mancanti")
    def reinvia_email_conferme(self, request, queryset):
        da_inviare = queryset.filter(
            stato="ISCRITTO",
            email_conferma_inviata_il__isnull=True,
        ).select_related("gara", "socio__user")
        inviate = 0
        certificati_non_validi = 0
        for iscrizione in da_inviare:
            if not iscrizione.certificato_valido_alla_data_gara:
                certificati_non_validi += 1
                continue
            inviate += invia_email_conferma_gara(iscrizione)
        self.message_user(
            request,
            f"Email di conferma inviate: {inviate}.",
            level=messages.SUCCESS,
        )
        if certificati_non_validi:
            self.message_user(
                request,
                f"Email non inviate: {certificati_non_validi}. Il certificato "
                "medico manca o scade prima della gara.",
                level=messages.ERROR,
            )


#Cosa fa questo codice?
#Registra il nostro modello Socio nell'area di amministrazione.
#list_display definisce quali colonne mostrare nell'elenco principale dei soci, per una visione d'insieme.
#list_filter aggiunge un comodo filtro sulla destra per vedere subito i soci "Attivi", "Sospesi", ecc.
#search_fields aggiunge una barra di ricerca per trovare un socio per nome, cognome, email o codice fiscale.

class ConsensoSocioInline(admin.TabularInline):
    model = ConsensoSocio
    extra = 0
    can_delete = False
    fields = ("tipo", "versione_modulo", "accettato_il", "indirizzo_ip")
    readonly_fields = fields

    def has_view_permission(self, request, obj=None):
        return request.user.is_staff

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(ConsensoSocio)
class ConsensoSocioAdmin(admin.ModelAdmin):
    list_display = (
        "socio_display",
        "tipo",
        "versione_modulo",
        "accettato_il",
        "indirizzo_ip",
    )
    list_filter = ("tipo", "versione_modulo", "accettato_il")
    search_fields = (
        "socio__user__first_name",
        "socio__user__last_name",
        "socio__user__email",
        "socio__codice_fiscale",
    )
    readonly_fields = ("socio", "tipo", "versione_modulo", "accettato_il", "indirizzo_ip")
    ordering = ("-accettato_il",)

    def has_add_permission(self, request):
        return False

    @admin.display(description="Socio", ordering="socio__user__last_name")
    def socio_display(self, obj):
        if obj.socio.user:
            return obj.socio.user.get_full_name() or obj.socio.user.username
        return obj.socio.codice_fiscale

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Socio)
class SocioAdmin(admin.ModelAdmin):
    list_display = ('user', 'stato', 'scadenza_quota_sociale', 'scadenza_certificato_medico')
    list_filter = ('stato',)
    search_fields = ('user__first_name', 'user__last_name', 'user__email', 'codice_fiscale')
    inlines = (ConsensoSocioInline,)


@admin.register(ModificaScadenzaCertificato)
class ModificaScadenzaCertificatoAdmin(admin.ModelAdmin):
    list_display = (
        "socio",
        "scadenza_precedente",
        "nuova_scadenza",
        "modificato_il",
        "modificato_da",
    )
    list_filter = ("modificato_il",)
    search_fields = ("socio__user__first_name", "socio__user__last_name")
    readonly_fields = (
        "socio",
        "scadenza_precedente",
        "nuova_scadenza",
        "modificato_il",
        "modificato_da",
    )
    ordering = ("-modificato_il",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(RichiestaInformazioni)
class RichiestaInformazioniAdmin(admin.ModelAdmin):
    list_display = (
        "nome",
        "email",
        "tipo_attivita",
        "nome_attivita",
        "creata_il",
        "email_notificata_il",
    )
    list_filter = ("tipo_attivita", "creata_il", "email_notificata_il")
    search_fields = ("nome", "email", "nome_attivita", "messaggio")
    readonly_fields = (
        "tipo_attivita",
        "nome_attivita",
        "edizione_corso",
        "abbonamento",
        "nome",
        "email",
        "messaggio",
        "creata_il",
        "email_notificata_il",
    )
    ordering = ("-creata_il",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


# --- NUOVE CLASSI ADMIN PER I NUOVI MODELLI ---

# Per gestire i "mattoni" degli allenamenti
@admin.register(TurnoAllenamento)
class TurnoAllenamentoAdmin(admin.ModelAdmin):
    list_display = ('nome_turno', 'giorno', 'orario_inizio', 'luogo', 'posti_massimi')
    list_filter = ('giorno', 'luogo')

# Per gestire i "template" degli abbonamenti (es. "Bisettimanale")
@admin.register(PacchettoAbbonamento)
class PacchettoAbbonamentoAdmin(admin.ModelAdmin):
    list_display = ('nome',)
    # Questo 'filter_horizontal' crea un'interfaccia molto comoda
    # per associare i turni ai pacchetti.
    filter_horizontal = ('turni',)

# Per gestire le "offerte stagionali" che i soci acquistano
@admin.register(StagioneAbbonamento)
class StagioneAbbonamentoAdmin(admin.ModelAdmin):
    list_display = (
        '__str__',
        'prezzo',
        'data_inizio',
        'data_fine',
        'attivo',
        'mostra_in_homepage',
        'mostra_prezzo_in_homepage',
    )
    list_filter = ('attivo', 'stagione', 'pacchetto')

# Per gestire il "catalogo" dei corsi
@admin.register(Corso)
class CorsoAdmin(admin.ModelAdmin):
    list_display = ('nome', 'descrizione', )

# Per gestire le singole "edizioni" dei corsi
@admin.register(EdizioneCorso)
class EdizioneCorsoAdmin(admin.ModelAdmin):
    list_display = ('corso', 'data_inizio', 'data_fine', 'prezzo', 'stato', 'posti_massimi', 'numero_iscritti')
    list_filter = ('stato', 'corso')
    filter_horizontal = ('iscritti',)
    
    # --- INIZIO NUOVO CODICE ---
    actions = ['visualizza_elenco_iscritti']

    @admin.display(description='N. Iscritti')
    def numero_iscritti(self, obj):
        # 'obj' è l'istanza di EdizioneCorso per quella riga.
        # .count() è un modo super efficiente per contare gli oggetti correlati.
        return obj.iscritti.count()

    @admin.action(description='Visualizza elenco iscritti con dati')
    def visualizza_elenco_iscritti(self, request, queryset):
        # Questa azione funziona solo se si seleziona UNA SOLA edizione
        if queryset.count() != 1:
            self.message_user(request, "Per favore, seleziona una sola edizione alla volta per questa azione.", level='warning')
            return

        edizione = queryset.first()
        iscritti = edizione.iscritti.all().select_related('user')

        today = date.today()
        un_mese_da_oggi = today + timedelta(days=30)

        context = {
            'edizione': edizione,
            'iscritti': iscritti,
            'site_header': "Amministrazione NPS Apnea",
            'today': date.today(), # <-- AGGIUNGIAMO LA DATA DI OGGI
            'un_mese_da_oggi': un_mese_da_oggi, # <-- Passiamo la nuova data al template per il warning del certificato medico in scadenza
        }
        
        # Usiamo un template HTML per generare la pagina
        html_string = render_to_string('admin/elenco_iscritti.html', context)
        
        return HttpResponse(html_string)