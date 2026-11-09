# in anagrafica/views.py

from django.shortcuts import render, redirect
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .consensi import (
    TIPI_CONSENSO,
    consensi_mancanti,
    documenti_consenso_configurati,
    versioni_consenso_attuali,
)
from .forms import ConsensoSocioForm, SocioRegistrationForm
from .models import (
    ConsensoSocio,
    EdizioneCorso,
    IscrizioneAbbonamento,
    Socio,
    StagioneAbbonamento,
)

def homepage(request):
    return render(request, 'homepage.html')

@transaction.atomic
def registrazione_socio(request):
    if request.method == 'POST':
        form = SocioRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            Socio.objects.create(
                user=user,
                codice_fiscale=form.cleaned_data['codice_fiscale'],
                data_nascita=form.cleaned_data['data_nascita'],
                stato='PRE_ISCRITTO'
            )
            registra_consensi(request, user.socio, form)
            login(request, user)
            return redirect('dashboard')
    else:
        form = SocioRegistrationForm()
    return render(
        request,
        'registrazione.html',
        {
            'form': form,
            'documenti_configurati': documenti_consenso_configurati(),
        },
    )


def registra_consensi(request, socio, form):
    ip = request.META.get("REMOTE_ADDR")
    versioni = versioni_consenso_attuali()
    ConsensoSocio.objects.bulk_create(
        [
            ConsensoSocio(
                socio=socio,
                tipo=tipo,
                versione_modulo=versioni[tipo],
                accettato_il=timezone.now(),
                indirizzo_ip=ip,
            )
            for tipo, chiave, _ in TIPI_CONSENSO
            if form.cleaned_data.get(f"consenso_{chiave}")
        ]
    )


@login_required
@transaction.atomic
def consensi_socio(request):
    socio = request.user.socio
    mancanti = consensi_mancanti(socio)

    if request.method == "POST":
        form = ConsensoSocioForm(request.POST)
        if form.is_valid():
            registra_consensi(request, socio, form)
            return redirect("dashboard")
    else:
        form = ConsensoSocioForm()

    return render(
        request,
        "consensi.html",
        {
            "form": form,
            "documenti_configurati": documenti_consenso_configurati(),
            "is_primo_consenso": not socio.consensi.exists(),
            "mancanti": mancanti,
        },
    )


@login_required
def dashboard(request):
    socio = request.user.socio
    if consensi_mancanti(socio):
        return redirect("consensi")

    oggi = timezone.localdate()
    
    # Carichiamo le offerte stagionali di abbonamento che sono attive
    abbonamenti_disponibili = StagioneAbbonamento.objects.filter(
        attivo=True,
        data_fine__gte=oggi,
    )
    
    # Carichiamo le edizioni dei corsi che sono aperte alle iscrizioni
    edizioni_aperte = EdizioneCorso.objects.filter(
        stato='APERTO_ISCRIZIONI',
        data_fine__gte=oggi,
    )
    iscrizioni_storiche_corsi = (
        socio.corsi_iscritti.filter(
            Q(stato='CONCLUSO') | Q(data_fine__lt=oggi)
        )
        .select_related('corso')
        .order_by('-data_fine', 'corso__nome')
    )
    iscrizioni_storiche_abbonamenti = (
        socio.iscrizioni_abbonamento.filter(abbonamento__data_fine__lt=oggi)
        .select_related('abbonamento__pacchetto')
        .order_by('-abbonamento__data_fine')
    )

    context = {
        'socio': socio,
        'abbonamenti_disponibili': abbonamenti_disponibili,
        'abbonamento_attivo': (
            socio.abbonamento_sottoscritto
            if (
                socio.abbonamento_sottoscritto
                and socio.abbonamento_sottoscritto.data_fine >= oggi
            )
            else None
        ),
        'edizioni_aperte': edizioni_aperte,
        'iscrizioni_storiche_abbonamenti': iscrizioni_storiche_abbonamenti,
        'iscrizioni_storiche_corsi': iscrizioni_storiche_corsi,
    }
    return render(request, 'dashboard.html', context)

# Da aggiungere in fondo a anagrafica/views.py

@login_required
def sottoscrivi_abbonamento(request, abbonamento_id):
    socio = request.user.socio
    if consensi_mancanti(socio):
        return redirect('consensi')

    try:
        abbonamento_scelto = StagioneAbbonamento.objects.get(id=abbonamento_id)
    except StagioneAbbonamento.DoesNotExist:
        return redirect('dashboard')

    if (
        socio.stato != 'ATTIVO'
        or not abbonamento_scelto.attivo
        or abbonamento_scelto.data_fine < timezone.localdate()
    ):
        return redirect('dashboard')
    
    IscrizioneAbbonamento.objects.get_or_create(
        socio=socio,
        abbonamento=abbonamento_scelto,
    )
    socio.abbonamento_sottoscritto = abbonamento_scelto
    socio.save()

    return redirect('dashboard')