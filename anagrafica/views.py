# in anagrafica/views.py

from datetime import date, timedelta
import logging
import smtplib

from django.shortcuts import render, redirect
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.core.mail import EmailMessage
from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST

from .consensi import (
    TIPI_CONSENSO,
    consensi_mancanti,
    documenti_consenso_configurati,
    versioni_consenso_attuali,
)
from .api import dati_pagina_staff_certificati
from .forms import (
    AggiornaScadenzaCertificatoForm,
    ConsensoSocioForm,
    IscrizioneGaraForm,
    RichiestaInformazioniForm,
    RisultatoGaraForm,
    SocioRegistrationForm,
)
from .models import (
    Attivita,
    ConsensoSocio,
    DichiarazioneGara,
    EdizioneCorso,
    Gara,
    IscrizioneAttivita,
    IscrizioneCorso,
    IscrizioneGara,
    IscrizioneAbbonamento,
    ModificaScadenzaCertificato,
    RichiestaInformazioni,
    RisultatoGara,
    Socio,
    StagioneAbbonamento,
)
from .performance import prepara_storico_gare

logger = logging.getLogger(__name__)


def homepage(request):
    oggi = timezone.localdate()
    corsi_disponibili = (
        EdizioneCorso.objects.filter(
            stato="APERTO_ISCRIZIONI",
            data_fine__gte=oggi,
        )
        .select_related("corso")
        .order_by("data_inizio", "corso__nome")
    )
    offerte_in_evidenza = StagioneAbbonamento.objects.filter(
        attivo=True,
        mostra_in_homepage=True,
        data_fine__gte=oggi,
    ).select_related('pacchetto')
    offerte_in_evidenza = offerte_in_evidenza.prefetch_related(
        "pacchetto__turni"
    ).order_by("data_inizio", "pacchetto__nome")
    return render(
        request,
        'homepage.html',
        {
            'corsi_disponibili': corsi_disponibili,
            'offerte_in_evidenza': offerte_in_evidenza,
        },
    )


def attivita_pubblica(tipo, attivita_id):
    oggi = timezone.localdate()
    if tipo == "corso":
        attivita = get_object_or_404(
            EdizioneCorso.objects.select_related("corso"),
            pk=attivita_id,
            stato="APERTO_ISCRIZIONI",
            data_fine__gte=oggi,
        )
        return attivita, attivita.corso.nome
    if tipo == "allenamento":
        attivita = get_object_or_404(
            StagioneAbbonamento.objects.select_related("pacchetto"),
            pk=attivita_id,
            attivo=True,
            mostra_in_homepage=True,
            data_fine__gte=oggi,
        )
        return attivita, attivita.pacchetto.nome
    raise Http404


def richiesta_informazioni(request, tipo, attivita_id):
    attivita, nome_attivita = attivita_pubblica(tipo, attivita_id)
    form = RichiestaInformazioniForm(
        request.POST if request.method == "POST" else None
    )
    if request.method == "POST" and form.is_valid():
        richiesta = RichiestaInformazioni.objects.create(
            tipo_attivita=tipo,
            nome_attivita=nome_attivita,
            edizione_corso=attivita if tipo == "corso" else None,
            abbonamento=attivita if tipo == "allenamento" else None,
            **form.cleaned_data,
        )
        destinatari = list(
            User.objects.filter(is_active=True, is_staff=True)
            .exclude(email="")
            .order_by("pk")
            .values_list("email", flat=True)
        )
        if not destinatari:
            logger.warning(
                "Richiesta informazioni %s salvata, ma nessun utente staff "
                "attivo ha un indirizzo email configurato.",
                richiesta.pk,
            )
            messages.warning(
                request,
                "La richiesta è stata salvata, ma non è stato possibile "
                "avvisare lo staff via email.",
            )
        else:
            corpo = (
                f"Nuova richiesta di informazioni su: {nome_attivita}\n"
                f"Tipo attività: "
                f"{dict(RichiestaInformazioni.TIPI_ATTIVITA)[tipo]}\n"
                f"Nome: {richiesta.nome}\n"
                f"Email: {richiesta.email}\n\n"
                f"Messaggio:\n{richiesta.messaggio}"
            )
            try:
                inviato = EmailMessage(
                    "Nuova richiesta di informazioni - NPS Apnea",
                    corpo,
                    settings.DEFAULT_FROM_EMAIL,
                    destinatari,
                    reply_to=[richiesta.email],
                ).send(fail_silently=False)
                if inviato != 1:
                    raise RuntimeError(
                        "Il backend email non ha confermato l'invio."
                    )
            except (OSError, RuntimeError, smtplib.SMTPException):
                logger.exception(
                    "Notifica email non inviata per la richiesta %s.",
                    richiesta.pk,
                )
                messages.warning(
                    request,
                    "La richiesta è stata salvata, ma non è stato possibile "
                    "avvisare lo staff via email.",
                )
            else:
                richiesta.email_notificata_il = timezone.now()
                richiesta.save(update_fields=("email_notificata_il",))
                messages.success(
                    request,
                    "Richiesta inviata. Lo staff ti risponderà all'indirizzo "
                    "email indicato.",
                )
        return redirect("richiesta_informazioni_confermata")

    return render(
        request,
        "richiesta_informazioni.html",
        {
            "attivita": attivita,
            "nome_attivita": nome_attivita,
            "tipo_attivita": dict(RichiestaInformazioni.TIPI_ATTIVITA)[tipo],
            "form": form,
        },
    )


def richiesta_informazioni_confermata(request):
    return render(request, "richiesta_informazioni_confermata.html")


@transaction.atomic
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
    try:
        socio = request.user.socio
    except Socio.DoesNotExist:
        return redirect('homepage')

    if consensi_mancanti(socio):
        return redirect("consensi")

    oggi = timezone.localdate()

    abbonamenti_disponibili = StagioneAbbonamento.objects.filter(
        attivo=True,
        data_fine__gte=oggi,
    ).exclude(
        iscrizioni_soci__socio=socio,
        iscrizioni_soci__stato="ANNULLATA",
    )

    edizioni_aperte = list(
        EdizioneCorso.objects.filter(
            stato='APERTO_ISCRIZIONI',
            data_fine__gte=oggi,
        )
        .select_related("corso")
        .annotate(
            iscritti_attivi_count=Count(
                "iscrizioni",
                filter=Q(iscrizioni__stato="ATTIVA"),
            )
        )
        .prefetch_related(
            Prefetch(
                "iscrizioni",
                queryset=IscrizioneCorso.objects.filter(socio=socio),
                to_attr="iscrizioni_del_socio",
            )
        )
    )
    for edizione in edizioni_aperte:
        edizione.iscrivibile = (
            socio.stato == "ATTIVO"
            and not edizione.iscrizioni_del_socio
            and edizione.termine_iscrizioni is not None
            and edizione.termine_iscrizioni >= oggi
            and edizione.iscritti_attivi_count < edizione.posti_massimi
        )
    edizioni_aperte.sort(
        key=lambda edizione: (
            not edizione.iscrivibile,
            edizione.data_inizio,
            edizione.corso.nome,
        )
    )

    attivita_disponibili = list(
        Attivita.objects.filter(
            pubblicata=True,
            data__gte=oggi,
        ).prefetch_related(
            Prefetch(
                "iscrizioni",
                queryset=IscrizioneAttivita.objects.filter(socio=socio).order_by(
                    "-data_iscrizione", "-pk"
                ),
                to_attr="iscrizioni_del_socio",
            )
        )
    )
    for attivita in attivita_disponibili:
        attivita.iscrizioni_aperte = attivita.termine_iscrizioni >= oggi
        attivita.iscrivibile = (
            socio.stato == "ATTIVO"
            and attivita.iscrizioni_aperte
            and not any(
                iscrizione.stato == "ATTIVA"
                for iscrizione in attivita.iscrizioni_del_socio
            )
        )
    attivita_disponibili.sort(
        key=lambda attivita: (
            not attivita.iscrivibile,
            attivita.data,
            attivita.nome,
        )
    )

    iscrizioni_storiche_corsi = (
        socio.corsi_iscritti.filter(
            Q(stato='CONCLUSO')
            | Q(data_fine__lt=oggi)
            | Q(iscrizioni__stato="ANNULLATA")
        )
        .select_related('corso')
        .order_by('-data_fine', 'corso__nome')
    )
    iscrizioni_storiche_abbonamenti = (
        socio.iscrizioni_abbonamento.filter(
            Q(abbonamento__data_fine__lt=oggi) | Q(stato="ANNULLATA")
        )
        .select_related('abbonamento__pacchetto')
        .order_by('-abbonamento__data_fine')
    )
    iscrizione_abbonamento_attiva = (
        socio.iscrizioni_abbonamento.filter(
            stato="ATTIVA",
            abbonamento__data_fine__gte=oggi,
        )
        .select_related("abbonamento__pacchetto")
        .first()
    )
    gare_prossime = Gara.objects.none()
    if socio.stato == "ATTIVO":
        gare_prossime = Gara.objects.filter(
            pubblicata=True,
            data_gara__gt=oggi,
        ).prefetch_related(
            Prefetch(
                "iscrizioni",
                queryset=IscrizioneGara.objects.filter(socio=socio).prefetch_related(
                    "dichiarazioni"
                ),
                to_attr="iscrizioni_del_socio",
            )
        )
    gare_dashboard = [
        {
            "gara": gara,
            "iscrizione": (
                gara.iscrizioni_del_socio[0]
                if gara.iscrizioni_del_socio
                else None
            ),
            "certificato_valido": (
                socio.scadenza_certificato_medico is not None
                and socio.scadenza_certificato_medico >= gara.data_gara
            ),
        }
        for gara in gare_prossime
    ]
    for elemento in gare_dashboard:
        elemento["iscrivibile"] = (
            socio.stato == "ATTIVO"
            and elemento["iscrizione"] is None
            and elemento["gara"].termine_iscrizioni >= oggi
            and elemento["certificato_valido"]
        )
    gare_dashboard.sort(
        key=lambda elemento: (
            not elemento["iscrivibile"],
            elemento["gara"].data_gara,
            elemento["gara"].nome,
        )
    )
    iscrizioni_gare_passate = list(
        socio.iscrizioni_gara.filter(
            stato="ISCRITTO",
            gara__data_gara__lte=oggi,
        )
        .select_related("gara")
        .prefetch_related("dichiarazioni", "risultati")
        .order_by("-gara__data_gara")
    )
    storico_gare, grafici_performance = prepara_storico_gare(
        iscrizioni_gare_passate
    )

    context = {
        'socio': socio,
        "oggi": oggi,
        'abbonamenti_disponibili': abbonamenti_disponibili,
        "iscrizione_abbonamento_attiva": iscrizione_abbonamento_attiva,
        "abbonamento_attivo": (
            iscrizione_abbonamento_attiva.abbonamento
            if iscrizione_abbonamento_attiva
            else None
        ),
        'edizioni_aperte': edizioni_aperte,
        "attivita_disponibili": attivita_disponibili,
        'iscrizioni_storiche_abbonamenti': iscrizioni_storiche_abbonamenti,
        'iscrizioni_storiche_corsi': iscrizioni_storiche_corsi,
        "gare_prossime": gare_dashboard,
        "storico_gare": storico_gare,
        "grafici_performance": grafici_performance,
    }
    return render(request, 'dashboard.html', context)


@login_required
@require_POST
@transaction.atomic
def richiedi_iscrizione_corso(request, edizione_id):
    socio = get_object_or_404(Socio, user=request.user)
    if socio.stato != "ATTIVO":
        messages.error(request, "Solo i soci attivi possono iscriversi ai corsi.")
        return redirect("dashboard")
    if consensi_mancanti(socio):
        return redirect("consensi")

    edizione = get_object_or_404(
        EdizioneCorso.objects.select_for_update(),
        pk=edizione_id,
        stato="APERTO_ISCRIZIONI",
    )
    oggi = timezone.localdate()
    if (
        edizione.data_fine < oggi
        or edizione.termine_iscrizioni is None
        or edizione.termine_iscrizioni < oggi
    ):
        messages.error(request, "Le iscrizioni a questo corso sono chiuse.")
        return redirect("dashboard")

    esistente = IscrizioneCorso.objects.filter(
        socio=socio,
        edizione=edizione,
    ).first()
    if esistente:
        messages.info(request, "Risulti già iscritto a questo corso.")
        return redirect("dashboard")
    if edizione.iscrizioni.filter(stato="ATTIVA").count() >= edizione.posti_massimi:
        messages.error(request, "Non ci sono più posti disponibili per questo corso.")
        return redirect("dashboard")

    IscrizioneCorso.objects.create(socio=socio, edizione=edizione)
    messages.success(request, "Iscrizione al corso completata.")
    return redirect("dashboard")


@login_required
@require_POST
@transaction.atomic
def richiedi_iscrizione_attivita(request, attivita_id):
    socio = get_object_or_404(Socio, user=request.user)
    if socio.stato != "ATTIVO":
        messages.error(request, "Solo i soci attivi possono iscriversi alle attività.")
        return redirect("dashboard")
    if consensi_mancanti(socio):
        return redirect("consensi")

    attivita = get_object_or_404(
        Attivita.objects.select_for_update(),
        pk=attivita_id,
        pubblicata=True,
    )
    oggi = timezone.localdate()
    if attivita.data < oggi or attivita.termine_iscrizioni < oggi:
        messages.error(request, "Le iscrizioni a questa attività sono chiuse.")
        return redirect("dashboard")
    if IscrizioneAttivita.objects.filter(
        socio=socio,
        attivita=attivita,
        stato="ATTIVA",
    ).exists():
        messages.info(request, "Risulti già iscritto a questa attività.")
        return redirect("dashboard")

    IscrizioneAttivita.objects.create(socio=socio, attivita=attivita)
    messages.success(request, "Iscrizione all'attività completata.")
    return redirect("dashboard")


@login_required
@require_POST
@transaction.atomic
def annulla_iscrizione(request, tipo, iscrizione_id):
    socio = get_object_or_404(Socio, user=request.user)
    oggi = timezone.localdate()
    adesso = timezone.now()
    if tipo == "corso":
        iscrizione = get_object_or_404(
            IscrizioneCorso.objects.select_for_update().select_related("edizione"),
            pk=iscrizione_id,
            socio=socio,
            stato="ATTIVA",
        )
        termine = iscrizione.edizione.termine_disiscrizione
    elif tipo == "abbonamento":
        iscrizione = get_object_or_404(
            IscrizioneAbbonamento.objects.select_for_update().select_related(
                "abbonamento"
            ),
            pk=iscrizione_id,
            socio=socio,
            stato="ATTIVA",
        )
        termine = iscrizione.abbonamento.termine_disiscrizione
    elif tipo == "gara":
        iscrizione = get_object_or_404(
            IscrizioneGara.objects.select_for_update().select_related("gara"),
            pk=iscrizione_id,
            socio=socio,
        )
        if iscrizione.stato == "ANNULLATA":
            messages.info(request, "L'iscrizione risulta già annullata.")
            return redirect("dashboard")
        termine = iscrizione.gara.termine_disiscrizione
    elif tipo == "attivita":
        iscrizione = get_object_or_404(
            IscrizioneAttivita.objects.select_for_update().select_related(
                "attivita"
            ),
            pk=iscrizione_id,
            socio=socio,
            stato="ATTIVA",
        )
        termine = iscrizione.attivita.termine_disiscrizione
    else:
        raise Http404

    if termine is None or oggi > termine:
        messages.error(
            request,
            "Il termine per annullare l'iscrizione è scaduto; "
            "l'eventuale caparra non è più rimborsabile.",
        )
        return redirect("dashboard")

    iscrizione.stato = "ANNULLATA"
    iscrizione.annullata_il = adesso
    iscrizione.save(update_fields=("stato", "annullata_il"))
    if tipo == "abbonamento":
        Socio.objects.filter(
            pk=socio.pk,
            abbonamento_sottoscritto=iscrizione.abbonamento,
        ).update(abbonamento_sottoscritto=None)

    messages.success(
        request,
        "Iscrizione annullata. L'eventuale rimborso della caparra va gestito "
        "manualmente dalla segreteria.",
    )
    return redirect("dashboard")


@login_required
@transaction.atomic
def richiedi_iscrizione_gara(request, gara_id):
    try:
        socio = request.user.socio
    except Socio.DoesNotExist:
        return redirect("homepage")

    if socio.stato != "ATTIVO":
        messages.error(request, "Solo i soci attivi possono iscriversi alle gare.")
        return redirect("dashboard")
    if consensi_mancanti(socio):
        return redirect("consensi")

    gara = get_object_or_404(Gara, pk=gara_id, pubblicata=True)
    oggi = timezone.localdate()
    if gara.data_gara <= oggi or gara.termine_iscrizioni < oggi:
        messages.error(request, "Le iscrizioni a questa gara sono chiuse.")
        return redirect("dashboard")
    if (
        socio.scadenza_certificato_medico is None
        or socio.scadenza_certificato_medico < gara.data_gara
    ):
        messages.error(
            request,
            "Per iscriverti, il certificato medico deve essere valido fino "
            "alla data della gara.",
        )
        return redirect("dashboard")

    iscrizione_esistente = IscrizioneGara.objects.filter(
        socio=socio,
        gara=gara,
    ).first()
    if iscrizione_esistente:
        return redirect("dashboard")

    form = IscrizioneGaraForm(
        request.POST if request.method == "POST" else None,
        gara=gara,
    )
    if request.method == "POST" and form.is_valid():
        iscrizione, creata = IscrizioneGara.objects.get_or_create(
            socio=socio,
            gara=gara,
        )
        if not creata:
            return redirect("dashboard")
        disciplina = form.cleaned_data["disciplina"]
        dichiarazione = DichiarazioneGara(
            iscrizione=iscrizione,
            disciplina=disciplina,
            distanza_m=form.cleaned_data.get(f"distanza_{disciplina}"),
            profondita_m=form.cleaned_data.get(f"profondita_{disciplina}"),
            tempo=form.cleaned_data.get(f"tempo_{disciplina}"),
        )
        dichiarazione.full_clean()
        dichiarazione.save()
        messages.success(
            request,
            "Richiesta d'iscrizione inviata. È in attesa di conferma dello staff.",
        )
        return redirect("dashboard")

    return render(
        request,
        "gare/iscrizione.html",
        {"gara": gara, "form": form},
    )


@login_required
@transaction.atomic
def modifica_dichiarazione_gara(request, iscrizione_id):
    try:
        socio = request.user.socio
    except Socio.DoesNotExist:
        return redirect("homepage")

    oggi = timezone.localdate()
    iscrizione = get_object_or_404(
        IscrizioneGara.objects.select_for_update()
        .select_related("gara")
        .prefetch_related("dichiarazioni"),
        pk=iscrizione_id,
        socio=socio,
        stato="IN_ATTESA",
        gara__pubblicata=True,
        gara__data_gara__gt=oggi,
        gara__termine_iscrizioni__gte=oggi,
    )
    dichiarazioni = list(iscrizione.dichiarazioni.all())
    dichiarazione = dichiarazioni[0] if dichiarazioni else None
    iniziali = {}
    if dichiarazione:
        disciplina = dichiarazione.disciplina
        iniziali["disciplina"] = disciplina
        if disciplina in Gara.DISCIPLINE_DINAMICHE:
            iniziali[f"distanza_{disciplina}"] = dichiarazione.distanza_m
        elif disciplina in Gara.DISCIPLINE_PROFONDITA:
            iniziali[f"profondita_{disciplina}"] = dichiarazione.profondita_m
        iniziali[f"tempo_{disciplina}"] = dichiarazione.tempo

    form = IscrizioneGaraForm(
        request.POST if request.method == "POST" else None,
        gara=iscrizione.gara,
        initial=iniziali,
    )
    if request.method == "POST" and form.is_valid():
        disciplina = form.cleaned_data["disciplina"]
        iscrizione.dichiarazioni.exclude(disciplina=disciplina).delete()
        dichiarazione, _ = DichiarazioneGara.objects.get_or_create(
            iscrizione=iscrizione,
            disciplina=disciplina,
        )
        dichiarazione.distanza_m = form.cleaned_data.get(f"distanza_{disciplina}")
        dichiarazione.profondita_m = form.cleaned_data.get(
            f"profondita_{disciplina}"
        )
        dichiarazione.tempo = form.cleaned_data.get(f"tempo_{disciplina}")
        dichiarazione.full_clean()
        dichiarazione.save()
        messages.success(request, "La dichiarazione per la gara è stata aggiornata.")
        return redirect("dashboard")

    return render(
        request,
        "gare/iscrizione.html",
        {
            "gara": iscrizione.gara,
            "form": form,
            "modifica": True,
        },
    )


@login_required
@transaction.atomic
def modifica_risultati_gara(request, iscrizione_id):
    try:
        socio = request.user.socio
    except Socio.DoesNotExist:
        return redirect("homepage")

    oggi = timezone.localdate()
    iscrizione = get_object_or_404(
        IscrizioneGara.objects.select_related("gara", "socio").prefetch_related(
            "dichiarazioni",
            "risultati",
        ),
        pk=iscrizione_id,
        socio=socio,
        stato="ISCRITTO",
        gara__data_gara__lte=oggi,
    )
    form = RisultatoGaraForm(
        request.POST if request.method == "POST" else None,
        iscrizione=iscrizione,
    )
    if request.method == "POST" and form.is_valid():
        for dichiarazione in iscrizione.dichiarazioni.all():
            disciplina = dichiarazione.disciplina
            distanza = form.cleaned_data.get(f"distanza_{disciplina}")
            profondita = form.cleaned_data.get(f"profondita_{disciplina}")
            tempo = form.cleaned_data.get(f"tempo_{disciplina}")
            risultato = RisultatoGara.objects.filter(
                iscrizione=iscrizione,
                disciplina=disciplina,
            ).first()
            if distanza is None and profondita is None and tempo is None:
                if risultato:
                    risultato.delete()
                continue
            if risultato is None:
                risultato = RisultatoGara(
                    iscrizione=iscrizione,
                    disciplina=disciplina,
                )
            risultato.distanza_m = distanza
            risultato.profondita_m = profondita
            risultato.tempo = tempo
            risultato.full_clean()
            risultato.save()

        messages.success(request, "I risultati della gara sono stati salvati.")
        return redirect("dashboard")

    return render(
        request,
        "gare/risultati.html",
        {"iscrizione": iscrizione, "form": form},
    )


def _righe_certificati_staff(socio_id_form=None, form=None):
    righe = dati_pagina_staff_certificati()
    for riga in righe:
        socio = riga["socio"]
        if socio.pk == socio_id_form:
            riga["form_scadenza"] = form
        else:
            riga["form_scadenza"] = AggiornaScadenzaCertificatoForm(
                initial={"nuova_scadenza": socio.scadenza_certificato_medico},
                auto_id=f"id_scadenza_{socio.pk}_%s",
            )
    return righe


@login_required(login_url="login")
def pagina_staff_certificati(request):
    if not request.user.is_staff:
        raise PermissionDenied
    return render(
        request,
        "staff/certificati_scadenza.html",
        {"righe": _righe_certificati_staff()},
    )


@login_required(login_url="login")
@require_POST
@transaction.atomic
def modifica_scadenza_certificato(request, socio_id):
    if not request.user.is_staff:
        raise PermissionDenied

    oggi = timezone.localdate()
    socio = get_object_or_404(
        Socio.objects.select_for_update(),
        pk=socio_id,
        stato="ATTIVO",
        user__isnull=False,
        scadenza_certificato_medico__isnull=False,
        scadenza_certificato_medico__lte=oggi + timedelta(days=30),
    )
    form = AggiornaScadenzaCertificatoForm(request.POST)
    if not form.is_valid():
        form.auto_id = f"id_scadenza_{socio.pk}_%s"
        return render(
            request,
            "staff/certificati_scadenza.html",
            {
                "righe": _righe_certificati_staff(socio.pk, form),
            },
            status=400,
        )

    nuova_scadenza = form.cleaned_data["nuova_scadenza"]
    if nuova_scadenza != socio.scadenza_certificato_medico:
        ModificaScadenzaCertificato.objects.create(
            socio=socio,
            scadenza_precedente=socio.scadenza_certificato_medico,
            nuova_scadenza=nuova_scadenza,
            modificato_da=request.user,
        )
        socio.scadenza_certificato_medico = nuova_scadenza
        socio.save(update_fields=("scadenza_certificato_medico",))
        messages.success(request, f"Scadenza del certificato di {socio} aggiornata.")
    else:
        messages.info(request, "La data di scadenza non è cambiata.")

    return redirect("pagina_staff_certificati")


@login_required
def sottoscrivi_abbonamento(request, abbonamento_id):
    try:
        socio = request.user.socio
    except Socio.DoesNotExist:
        return redirect('homepage')

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

    iscrizione, creata = IscrizioneAbbonamento.objects.get_or_create(
        socio=socio,
        abbonamento=abbonamento_scelto,
    )
    if not creata and iscrizione.stato == "ANNULLATA":
        messages.error(
            request,
            "L'iscrizione a questa offerta è già stata annullata e non può "
            "essere riattivata.",
        )
        return redirect("dashboard")
    socio.abbonamento_sottoscritto = abbonamento_scelto
    socio.save()

    return redirect('dashboard')