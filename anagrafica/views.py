# in anagrafica/views.py

from datetime import date, timedelta

from django.shortcuts import render, redirect
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required

from .forms import SocioRegistrationForm
from .models import Socio, StagioneAbbonamento, EdizioneCorso


def homepage(request):
    offerte_in_evidenza = StagioneAbbonamento.objects.filter(
        attivo=True,
        mostra_in_homepage=True,
    ).select_related('pacchetto')
    return render(request, 'homepage.html', {'offerte_in_evidenza': offerte_in_evidenza})


def registrazione_socio(request):
    if request.method == 'POST':
        form = SocioRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            oggi = date.today()
            Socio.objects.create(
                user=user,
                codice_fiscale=form.cleaned_data['codice_fiscale'],
                data_nascita=form.cleaned_data['data_nascita'],
                stato='ATTIVO',
                scadenza_quota_sociale=oggi + timedelta(days=365),
                scadenza_certificato_medico=oggi + timedelta(days=365),
            )
            login(request, user)
            return redirect('dashboard')
    else:
        form = SocioRegistrationForm()
    return render(request, 'registrazione.html', {'form': form})


@login_required
def dashboard(request):
    try:
        socio = request.user.socio
    except Socio.DoesNotExist:
        return redirect('homepage')

    # Carichiamo le offerte stagionali di abbonamento che sono attive
    abbonamenti_disponibili = StagioneAbbonamento.objects.filter(attivo=True)

    # Carichiamo le edizioni dei corsi che sono aperte alle iscrizioni
    edizioni_aperte = EdizioneCorso.objects.filter(stato='APERTO_ISCRIZIONI')

    context = {
        'socio': socio,
        'abbonamenti_disponibili': abbonamenti_disponibili,
        'edizioni_aperte': edizioni_aperte,
    }
    return render(request, 'dashboard.html', context)


@login_required
def sottoscrivi_abbonamento(request, abbonamento_id):
    try:
        abbonamento_scelto = StagioneAbbonamento.objects.get(id=abbonamento_id)
    except StagioneAbbonamento.DoesNotExist:
        return redirect('dashboard')

    try:
        socio = request.user.socio
    except Socio.DoesNotExist:
        return redirect('homepage')

    if socio.stato not in {'ATTIVO', 'PRE_ISCRITTO'}:
        return redirect('dashboard')

    socio.abbonamento_sottoscritto = abbonamento_scelto
    socio.save()

    return redirect('dashboard')