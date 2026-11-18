"""
URL configuration for nps_project project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.urls import path
from django.contrib.auth import views as auth_views # Importiamo le view di auth
from anagrafica.api import (
    api_candidati_promemoria,
    api_registra_promemoria_inviati,
)
from anagrafica.views import (
    consensi_socio,
    dashboard,
    homepage,
    modifica_dichiarazione_gara,
    modifica_risultati_gara,
    modifica_scadenza_certificato,
    pagina_staff_certificati,
    richiesta_informazioni,
    richiesta_informazioni_confermata,
    registrazione_socio,
    richiedi_iscrizione_gara,
    sottoscrivi_abbonamento,
)
from anagrafica.forms import SocioLoginForm


urlpatterns = [
    path('admin/', admin.site.urls),
    path('', homepage, name='homepage'), 
    path('registrazione/', registrazione_socio, name='registrazione'),
    path('consensi/', consensi_socio, name='consensi'),
    path(
        'richiedi-informazioni/<str:tipo>/<int:attivita_id>/',
        richiesta_informazioni,
        name='richiesta_informazioni',
    ),
    path(
        'richiesta-informazioni/confermata/',
        richiesta_informazioni_confermata,
        name='richiesta_informazioni_confermata',
    ),

    path('dashboard/', dashboard, name='dashboard'),
    path(
        "gare/<int:gara_id>/iscrizione/",
        richiedi_iscrizione_gara,
        name="richiedi_iscrizione_gara",
    ),
    path(
        "gare/iscrizioni/<int:iscrizione_id>/dichiarazione/",
        modifica_dichiarazione_gara,
        name="modifica_dichiarazione_gara",
    ),
    path(
        "gare/iscrizioni/<int:iscrizione_id>/risultati/",
        modifica_risultati_gara,
        name="modifica_risultati_gara",
    ),
    path(
        'staff/certificati/',
        pagina_staff_certificati,
        name='pagina_staff_certificati',
    ),
    path(
        'staff/certificati/<int:socio_id>/modifica/',
        modifica_scadenza_certificato,
        name='modifica_scadenza_certificato',
    ),
    path(
        'api/v1/promemoria/candidati/',
        api_candidati_promemoria,
        name='api_candidati_promemoria',
    ),
    path(
        'api/v1/promemoria/inviati/',
        api_registra_promemoria_inviati,
        name='api_registra_promemoria_inviati',
    ),
    path(
        'login/',
        auth_views.LoginView.as_view(
            template_name='login.html',
            authentication_form=SocioLoginForm,
        ),
        name='login',
    ),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),

        # NUOVO URL PER LA SOTTOSCRIZIONE
    path('sottoscrivi/abbonamento/<int:abbonamento_id>/', sottoscrivi_abbonamento, name='sottoscrivi_abbonamento'),
]