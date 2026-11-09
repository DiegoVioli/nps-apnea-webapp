from django.contrib import admin
from django.http import HttpResponse
from django.template.loader import render_to_string
from datetime import date, timedelta 
from .models import (
    ConsensoSocio,
    Socio,
    TurnoAllenamento,
    PacchettoAbbonamento,
    StagioneAbbonamento,
    Corso,
    EdizioneCorso,
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
    list_display = ('__str__', 'prezzo', 'data_inizio', 'data_fine', 'attivo')
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