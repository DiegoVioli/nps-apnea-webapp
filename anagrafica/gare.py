import logging
import smtplib

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone


logger = logging.getLogger(__name__)


def conferma_iscrizione_gara(iscrizione):
    if (
        iscrizione.stato != "IN_ATTESA"
        or not iscrizione.certificato_valido_alla_data_gara
    ):
        return False, False

    iscrizione.stato = "ISCRITTO"
    iscrizione.confermata_il = timezone.now()
    iscrizione.save(update_fields=("stato", "confermata_il"))
    return True, invia_email_conferma_gara(iscrizione)


def invia_email_conferma_gara(iscrizione):
    if (
        iscrizione.stato != "ISCRITTO"
        or not iscrizione.certificato_valido_alla_data_gara
    ):
        return False
    if iscrizione.email_conferma_inviata_il:
        return True

    email = iscrizione.socio.user.email if iscrizione.socio.user else ""
    if not email:
        logger.warning(
            "Conferma iscrizione gara %s: il socio %s non ha un indirizzo email.",
            iscrizione.pk,
            iscrizione.socio_id,
        )
        return False

    gara = iscrizione.gara
    testo = (
        f"La tua iscrizione alla gara {gara.nome} è stata confermata.\n"
        f"Data: {gara.data_gara:%d/%m/%Y}\n"
        f"Luogo: {gara.luogo or 'Non specificato'}\n"
        f"Quota: € {gara.prezzo}\n"
        "Puoi consultare i dettagli nella tua area socio."
    )
    try:
        inviato = send_mail(
            subject=f"Iscrizione confermata: {gara.nome}",
            message=testo,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
            fail_silently=False,
        )
    except (OSError, RuntimeError, smtplib.SMTPException):
        logger.exception(
            "Email di conferma non inviata per l'iscrizione gara %s.",
            iscrizione.pk,
        )
        return False

    if inviato != 1:
        logger.error(
            "Il backend email non ha confermato l'invio per l'iscrizione gara %s.",
            iscrizione.pk,
        )
        return False

    iscrizione.email_conferma_inviata_il = timezone.now()
    iscrizione.save(update_fields=("email_conferma_inviata_il",))
    return True
