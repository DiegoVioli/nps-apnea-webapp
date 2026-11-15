from datetime import timedelta
import smtplib

from django.conf import settings
from django.contrib.auth.models import User
from django.core.mail import EmailMessage
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone

from anagrafica.models import (
    PromemoriaCertificato,
    RiepilogoCertificatiAmministratori,
    Socio,
)


GIORNI_ANTICIPO = 30
INTERVALLO_PROMEMORIA = timedelta(days=7)
STATI_CORSO_ATTIVI = (
    "APERTO_ISCRIZIONI",
    "CONFERMATO",
    "IN_SVOLGIMENTO",
)


class Command(BaseCommand):
    help = "Invia promemoria ai soci con il certificato medico in scadenza."

    def handle(self, *args, **options):
        oggi = timezone.localdate()
        limite_scadenza = oggi + timedelta(days=GIORNI_ANTICIPO)
        adesso = timezone.now()
        ultimo_invito_consentito = adesso - INTERVALLO_PROMEMORIA
        email_amministratori = list(
            User.objects.filter(is_active=True, is_staff=True)
            .exclude(email="")
            .order_by("pk")
            .values_list("email", flat=True)
        )

        soci_iscritti = (
            Socio.objects.filter(user__isnull=False)
            .filter(
                Q(
                    corsi_iscritti__stato__in=STATI_CORSO_ATTIVI,
                    corsi_iscritti__data_fine__gte=oggi,
                )
                | Q(abbonamento_sottoscritto__data_fine__gte=oggi)
            )
            .select_related("user")
            .distinct()
        )
        soci = soci_iscritti.filter(
            scadenza_certificato_medico__range=(oggi, limite_scadenza)
        ).order_by("pk")

        inviati = 0
        non_inviati = 0
        errori = 0

        for socio in soci:
            if not socio.user.email:
                non_inviati += 1
                continue

            promemoria, _ = PromemoriaCertificato.objects.get_or_create(
                socio=socio,
                scadenza_certificato=socio.scadenza_certificato_medico,
            )
            if (
                promemoria.ultima_email_inviata is not None
                and promemoria.ultima_email_inviata > ultimo_invito_consentito
            ):
                non_inviati += 1
                continue

            scadenza = socio.scadenza_certificato_medico.strftime("%d/%m/%Y")
            nome = socio.user.first_name or str(socio)
            subject = "Promemoria: certificato medico in scadenza"
            message = (
                f"Ciao {nome},\n\n"
                f"il tuo certificato medico scade il {scadenza}. "
                "Ti ricordiamo di rinnovarlo per tempo: dopo la scadenza "
                "non potrai entrare in acqua fino alla presentazione di un "
                "certificato valido.\n\n"
                "NPS Apnea"
            )
            destinatari_cc = [
                email for email in email_amministratori if email != socio.user.email
            ]

            try:
                inviato = EmailMessage(
                    subject,
                    message,
                    settings.DEFAULT_FROM_EMAIL,
                    [socio.user.email],
                    cc=destinatari_cc,
                ).send(fail_silently=False)
                if inviato != 1:
                    raise RuntimeError("Il backend email non ha confermato l'invio.")
            except (OSError, RuntimeError, smtplib.SMTPException) as exc:
                errori += 1
                self.stderr.write(
                    self.style.ERROR(
                        f"Invio fallito per il socio {socio.pk} "
                        f"({socio.user.email}): {exc}"
                    )
                )
                continue

            promemoria.ultima_email_inviata = timezone.now()
            promemoria.save(update_fields=("ultima_email_inviata",))
            inviati += 1

        if not email_amministratori:
            errori += 1
            self.stderr.write(
                self.style.ERROR(
                    "Riepilogo settimanale non inviato: nessun amministratore "
                    "attivo con un indirizzo email configurato."
                )
            )
        else:
            riepilogo, _ = RiepilogoCertificatiAmministratori.objects.get_or_create(
                pk=1
            )
            if (
                riepilogo.ultima_email_inviata is None
                or riepilogo.ultima_email_inviata <= ultimo_invito_consentito
            ):
                certificati = list(
                    soci_iscritti.filter(
                        scadenza_certificato_medico__lte=limite_scadenza
                    )
                    .exclude(scadenza_certificato_medico__isnull=True)
                    .order_by("scadenza_certificato_medico", "user__last_name", "pk")
                )
                certificati_in_scadenza = [
                    socio
                    for socio in certificati
                    if socio.scadenza_certificato_medico >= oggi
                ]
                certificati_scaduti = [
                    socio
                    for socio in certificati
                    if socio.scadenza_certificato_medico < oggi
                ]
                righe = [
                    "Riepilogo settimanale dei certificati medici dei soci iscritti.",
                    "",
                ]
                if certificati_in_scadenza:
                    righe.append("Certificati in scadenza (entro 30 giorni):")
                    righe.extend(
                        f"- {socio} — scadenza "
                        f"{socio.scadenza_certificato_medico:%d/%m/%Y}"
                        for socio in certificati_in_scadenza
                    )
                    righe.append("")
                if certificati_scaduti:
                    righe.append("Certificati scaduti:")
                    righe.extend(
                        f"- {socio} — scaduto il "
                        f"{socio.scadenza_certificato_medico:%d/%m/%Y}"
                        for socio in certificati_scaduti
                    )
                if not certificati:
                    righe.append(
                        "Non ci sono certificati in scadenza o scaduti."
                    )

                try:
                    inviato = EmailMessage(
                        "Riepilogo settimanale certificati medici",
                        "\n".join(righe),
                        settings.DEFAULT_FROM_EMAIL,
                        email_amministratori,
                    ).send(fail_silently=False)
                    if inviato != 1:
                        raise RuntimeError(
                            "Il backend email non ha confermato l'invio."
                        )
                except (OSError, RuntimeError, smtplib.SMTPException) as exc:
                    errori += 1
                    self.stderr.write(
                        self.style.ERROR(
                            f"Invio del riepilogo agli amministratori fallito: {exc}"
                        )
                    )
                else:
                    riepilogo.ultima_email_inviata = timezone.now()
                    riepilogo.save(update_fields=("ultima_email_inviata",))

        self.stdout.write(
            self.style.SUCCESS(
                f"Promemoria inviati: {inviati}; non inviati: {non_inviati}; "
                f"errori: {errori}."
            )
        )
        if errori:
            raise CommandError(f"Invio non riuscito per {errori} socio/i.")
