import json
import secrets
from datetime import date, timedelta
from functools import wraps

from django.conf import settings
from django.db import transaction
from django.db.models import Exists, OuterRef, Subquery
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .models import (
    ModificaScadenzaCertificato,
    PromemoriaCertificato,
    Socio,
)


GIORNI_ANTICIPO = 30
INTERVALLO_PROMEMORIA = timedelta(days=7)
NUMERO_MASSIMO_PROMEMORIA = 500


def richiede_token_api(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        token_atteso = settings.CERTIFICATI_API_TOKEN
        if not token_atteso:
            return JsonResponse(
                {"errore": "L'API non è configurata."},
                status=503,
            )

        schema, separatore, token = request.headers.get(
            "Authorization", ""
        ).partition(" ")
        if (
            not separatore
            or schema.lower() != "bearer"
            or not secrets.compare_digest(token, token_atteso)
        ):
            response = JsonResponse(
                {"errore": "Autenticazione non valida."},
                status=401,
            )
            response["WWW-Authenticate"] = "Bearer"
            return response

        return view_func(request, *args, **kwargs)

    return wrapper


def soci_con_certificato_da_verificare(oggi=None):
    oggi = oggi or timezone.localdate()
    limite_scadenza = oggi + timedelta(days=GIORNI_ANTICIPO)
    return (
        Socio.objects.filter(
            stato="ATTIVO",
            user__isnull=False,
            scadenza_certificato_medico__isnull=False,
            scadenza_certificato_medico__lte=limite_scadenza,
        )
        .select_related("user")
        .order_by(
            "scadenza_certificato_medico",
            "user__last_name",
            "user__first_name",
            "pk",
        )
    )


@csrf_exempt
@require_GET
@richiede_token_api
def api_candidati_promemoria(request):
    oggi = timezone.localdate()
    ora_limite = timezone.now() - INTERVALLO_PROMEMORIA
    promemoria_recenti = PromemoriaCertificato.objects.filter(
        socio_id=OuterRef("pk"),
        scadenza_certificato=OuterRef("scadenza_certificato_medico"),
        ultima_email_inviata__gt=ora_limite,
    )
    soci = soci_con_certificato_da_verificare(oggi).annotate(
        promemoria_recente=Exists(promemoria_recenti)
    ).filter(promemoria_recente=False)

    return JsonResponse(
        {
            "data_riferimento": oggi.isoformat(),
            "entro_giorni": GIORNI_ANTICIPO,
            "soci": [
                {
                    "socio_id": socio.pk,
                    "nome": socio.user.first_name,
                    "cognome": socio.user.last_name,
                    "email": socio.user.email,
                    "telefono": socio.telefono,
                    "data_scadenza": socio.scadenza_certificato_medico.isoformat(),
                    "giorni_alla_scadenza": (
                        socio.scadenza_certificato_medico - oggi
                    ).days,
                    "stato_certificato": (
                        "scaduto"
                        if socio.scadenza_certificato_medico < oggi
                        else "in_scadenza"
                    ),
                }
                for socio in soci
            ],
        }
    )


@csrf_exempt
@require_POST
@richiede_token_api
def api_registra_promemoria_inviati(request):
    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"errore": "Il corpo deve essere JSON valido."}, status=400)

    if not isinstance(payload, dict) or not isinstance(payload.get("inviati"), list):
        return JsonResponse(
            {"errore": "È richiesto un elenco 'inviati'."},
            status=400,
        )

    inviati = payload["inviati"]
    if not inviati or len(inviati) > NUMERO_MASSIMO_PROMEMORIA:
        return JsonResponse(
            {
                "errore": (
                    f"L'elenco deve contenere da 1 a "
                    f"{NUMERO_MASSIMO_PROMEMORIA} promemoria."
                )
            },
            status=400,
        )

    scadenze_per_socio = {}
    for elemento in inviati:
        if not isinstance(elemento, dict):
            return JsonResponse(
                {"errore": "Ogni elemento deve contenere socio_id e data_scadenza."},
                status=400,
            )
        socio_id = elemento.get("socio_id")
        data_scadenza = elemento.get("data_scadenza")
        if (
            isinstance(socio_id, bool)
            or not isinstance(socio_id, int)
            or not isinstance(data_scadenza, str)
        ):
            return JsonResponse(
                {"errore": "Ogni elemento deve contenere socio_id e data_scadenza validi."},
                status=400,
            )
        try:
            scadenza = date.fromisoformat(data_scadenza)
        except ValueError:
            return JsonResponse(
                {"errore": "data_scadenza deve essere nel formato AAAA-MM-GG."},
                status=400,
            )
        if scadenza.isoformat() != data_scadenza or socio_id in scadenze_per_socio:
            return JsonResponse(
                {"errore": "Elenco non valido: soci duplicati o date non valide."},
                status=400,
            )
        scadenze_per_socio[socio_id] = scadenza

    soci = {
        socio.pk: socio
        for socio in Socio.objects.filter(
            pk__in=scadenze_per_socio,
            stato="ATTIVO",
            user__isnull=False,
        )
    }
    if len(soci) != len(scadenze_per_socio) or any(
        soci[socio_id].scadenza_certificato_medico != scadenza
        for socio_id, scadenza in scadenze_per_socio.items()
        if socio_id in soci
    ):
        return JsonResponse(
            {
                "errore": (
                    "Uno o più soci non sono attivi o la scadenza del certificato "
                    "è cambiata. Nessun promemoria è stato registrato."
                )
            },
            status=409,
        )

    ora_invio = timezone.now()
    ora_limite = ora_invio - INTERVALLO_PROMEMORIA
    registrati = 0
    gia_registrati = 0
    with transaction.atomic():
        for socio_id, scadenza in scadenze_per_socio.items():
            promemoria, creato = PromemoriaCertificato.objects.get_or_create(
                socio_id=socio_id,
                scadenza_certificato=scadenza,
                defaults={"ultima_email_inviata": ora_invio},
            )
            if creato:
                registrati += 1
            elif (
                promemoria.ultima_email_inviata is not None
                and promemoria.ultima_email_inviata > ora_limite
            ):
                gia_registrati += 1
            else:
                promemoria.ultima_email_inviata = ora_invio
                promemoria.save(update_fields=("ultima_email_inviata",))
                registrati += 1

    return JsonResponse(
        {
            "registrati": registrati,
            "gia_registrati": gia_registrati,
            "registrato_il": ora_invio.isoformat(),
        }
    )


def dati_pagina_staff_certificati():
    oggi = timezone.localdate()
    ultima_notifica = PromemoriaCertificato.objects.filter(
        socio_id=OuterRef("pk"),
        scadenza_certificato=OuterRef("scadenza_certificato_medico"),
    ).values("ultima_email_inviata")[:1]
    ultima_modifica = ModificaScadenzaCertificato.objects.filter(
        socio_id=OuterRef("pk")
    ).order_by("-modificato_il")
    soci = soci_con_certificato_da_verificare(oggi).annotate(
        ultima_notifica=Subquery(ultima_notifica),
        ultima_modifica_il=Subquery(ultima_modifica.values("modificato_il")[:1]),
        ultima_modifica_da=Subquery(
            ultima_modifica.values("modificato_da__username")[:1]
        ),
    )
    return [
        {
            "socio": socio,
            "giorni_alla_scadenza": (
                socio.scadenza_certificato_medico - oggi
            ).days,
            "stato_certificato": (
                "Scaduto"
                if socio.scadenza_certificato_medico < oggi
                else "In scadenza"
            ),
            "ultima_notifica": socio.ultima_notifica,
            "ultima_modifica_il": socio.ultima_modifica_il,
            "ultima_modifica_da": socio.ultima_modifica_da,
        }
        for socio in soci
    ]
