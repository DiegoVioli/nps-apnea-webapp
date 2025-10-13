# in anagrafica/views.py

from django.shortcuts import render, redirect
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView

from .forms import SocioRegistrationForm
from .models import Socio, StagioneAbbonamento, EdizioneCorso # <-- IMPORT CORRETTI

def homepage(request):
    return render(request, 'homepage.html')

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
            login(request, user)
            return redirect('dashboard')
    else:
        form = SocioRegistrationForm()
    return render(request, 'registrazione.html', {'form': form})

@login_required
def dashboard(request):
    socio = request.user.socio
    
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

# Da aggiungere in fondo a anagrafica/views.py

from .models import StagioneAbbonamento # Assicurarsi che questo import ci sia o aggiungerlo

@login_required
def sottoscrivi_abbonamento(request, abbonamento_id):
    try:
        abbonamento_scelto = StagioneAbbonamento.objects.get(id=abbonamento_id)
    except StagioneAbbonamento.DoesNotExist:
        return redirect('dashboard')

    socio = request.user.socio

    if socio.stato != 'ATTIVO':
        return redirect('dashboard')
    
    socio.abbonamento_sottoscritto = abbonamento_scelto
    socio.save()

    return redirect('dashboard')