from datetime import timedelta
import smtplib
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import (
    ConsensoSocio,
    Corso,
    EdizioneCorso,
    IscrizioneAbbonamento,
    PromemoriaCertificato,
    RiepilogoCertificatiAmministratori,
    Socio,
    StagioneAbbonamento,
    PacchettoAbbonamento,
)

DOCUMENTI_CONSENSO_TEST = {
    "regolamento": {"versione": "1.0", "url": "/regolamento.pdf"},
    "privacy": {"versione": "2.1", "url": "/privacy.pdf"},
    "foto_video": {"versione": "1.2", "url": "/foto-video.pdf"},
}


class PromemoriaCertificatoTests(TestCase):
    def setUp(self):
        self.amministratore = User.objects.create_user(
            username="admin",
            email="admin@example.com",
            is_staff=True,
        )

    def crea_socio(self, username, scadenza, email=None):
        user = User.objects.create_user(
            username=username,
            email=email or f"{username}@example.com",
            first_name="Socio",
        )
        return Socio.objects.create(
            user=user,
            codice_fiscale=f"CF{username.upper().replace('_', '')[:14]:<14}",
            data_nascita=timezone.localdate() - timedelta(days=365 * 30),
            scadenza_certificato_medico=scadenza,
            stato="ATTIVO",
        )

    def crea_corso(self, socio, stato="IN_SVOLGIMENTO", data_fine=None):
        oggi = timezone.localdate()
        corso = Corso.objects.create(nome="Apnea", descrizione="Corso di apnea")
        edizione = EdizioneCorso.objects.create(
            corso=corso,
            data_inizio=oggi,
            data_fine=data_fine or oggi + timedelta(days=10),
            posti_massimi=10,
            prezzo="100.00",
            stato=stato,
        )
        edizione.iscritti.add(socio)
        return edizione

    def test_sends_to_course_and_training_members_within_30_days(self):
        oggi = timezone.localdate()
        scadenza = oggi + timedelta(days=15)
        socio_corso = self.crea_socio("corso", scadenza)
        self.crea_corso(socio_corso)

        socio_allenamento = self.crea_socio("allenamento", scadenza)
        pacchetto = PacchettoAbbonamento.objects.create(nome="Allenamento")
        abbonamento = StagioneAbbonamento.objects.create(
            pacchetto=pacchetto,
            stagione="2026/2027",
            prezzo="200.00",
            data_inizio=oggi - timedelta(days=30),
            data_fine=oggi + timedelta(days=90),
        )
        socio_allenamento.abbonamento_sottoscritto = abbonamento
        socio_allenamento.save(update_fields=("abbonamento_sottoscritto",))

        call_command("invia_promemoria_certificati")

        self.assertEqual(len(mail.outbox), 3)
        email_socio = next(
            email for email in mail.outbox if email.to == [socio_corso.user.email]
        )
        email_riepilogo = next(
            email
            for email in mail.outbox
            if email.subject == "Riepilogo settimanale certificati medici"
        )
        self.assertEqual(email_socio.cc, ["admin@example.com"])
        self.assertIn(scadenza.strftime("%d/%m/%Y"), email_socio.body)
        self.assertIn("non potrai entrare in acqua", email_socio.body)
        self.assertCountEqual(
            email_riepilogo.to, ["admin@example.com"]
        )
        self.assertIn(str(socio_corso), email_riepilogo.body)
        self.assertIn(str(socio_allenamento), email_riepilogo.body)
        self.assertEqual(
            PromemoriaCertificato.objects.filter(
                ultima_email_inviata__isnull=False
            ).count(),
            2,
        )

    def test_sends_weekly_until_certificate_expiry(self):
        socio = self.crea_socio(
            "settimanale", timezone.localdate() + timedelta(days=10)
        )
        self.crea_corso(socio)

        call_command("invia_promemoria_certificati")
        call_command("invia_promemoria_certificati")
        self.assertEqual(len(mail.outbox), 2)

        promemoria = PromemoriaCertificato.objects.get(socio=socio)
        promemoria.ultima_email_inviata = timezone.now() - timedelta(days=7)
        promemoria.save(update_fields=("ultima_email_inviata",))
        call_command("invia_promemoria_certificati")
        self.assertEqual(len(mail.outbox), 3)

    def test_excludes_non_enrolled_expired_and_out_of_window_members(self):
        oggi = timezone.localdate()
        self.crea_socio("non_iscritto", oggi + timedelta(days=10))

        socio_corso_concluso = self.crea_socio(
            "concluso", oggi + timedelta(days=10)
        )
        self.crea_corso(
            socio_corso_concluso,
            stato="CONCLUSO",
            data_fine=oggi + timedelta(days=5),
        )

        socio_fuori_finestra = self.crea_socio(
            "fuori_finestra", oggi + timedelta(days=31)
        )
        self.crea_corso(socio_fuori_finestra)

        socio_scaduto = self.crea_socio("scaduto", oggi - timedelta(days=1))
        self.crea_corso(socio_scaduto)

        call_command("invia_promemoria_certificati")

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Certificati scaduti:", mail.outbox[0].body)
        self.assertIn("scaduto il", mail.outbox[0].body)

    def test_weekly_summary_lists_expired_certificates(self):
        oggi = timezone.localdate()
        socio = self.crea_socio("scaduto", oggi - timedelta(days=1))
        self.crea_corso(socio)

        call_command("invia_promemoria_certificati")

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["admin@example.com"])
        self.assertIn("Certificati scaduti:", mail.outbox[0].body)
        self.assertIn(str(socio), mail.outbox[0].body)

    def test_weekly_summary_says_when_no_certificates_are_due_or_expired(self):
        call_command("invia_promemoria_certificati")

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["admin@example.com"])
        self.assertIn(
            "Non ci sono certificati in scadenza o scaduti.",
            mail.outbox[0].body,
        )

    def test_weekly_summary_is_sent_only_once_every_seven_days(self):
        call_command("invia_promemoria_certificati")
        call_command("invia_promemoria_certificati")
        self.assertEqual(len(mail.outbox), 1)

        riepilogo = RiepilogoCertificatiAmministratori.objects.get(pk=1)
        riepilogo.ultima_email_inviata = timezone.now() - timedelta(days=7)
        riepilogo.save(update_fields=("ultima_email_inviata",))
        call_command("invia_promemoria_certificati")
        self.assertEqual(len(mail.outbox), 2)

    @patch(
        "anagrafica.management.commands.invia_promemoria_certificati.EmailMessage.send",
        side_effect=[
            smtplib.SMTPException("SMTP non disponibile"),
            1,
        ],
    )
    def test_failed_email_is_reported_without_marking_reminder_as_sent(
        self, send_mail_mock
    ):
        socio = self.crea_socio(
            "errore", timezone.localdate() + timedelta(days=10)
        )
        self.crea_corso(socio)

        with self.assertRaises(CommandError):
            call_command("invia_promemoria_certificati")

        promemoria = PromemoriaCertificato.objects.get(socio=socio)
        self.assertIsNone(promemoria.ultima_email_inviata)
        self.assertEqual(send_mail_mock.call_count, 2)

    def test_administrators_are_not_duplicated_in_member_cc(self):
        socio = self.crea_socio("admin_socio", timezone.localdate() + timedelta(days=5))
        self.amministratore.email = socio.user.email
        self.amministratore.save(update_fields=("email",))
        self.crea_corso(socio)

        call_command("invia_promemoria_certificati")

        email_socio = next(
            email for email in mail.outbox if email.to == [socio.user.email]
        )
        self.assertEqual(email_socio.cc, [])


@override_settings(DOCUMENTI_CONSENSO=DOCUMENTI_CONSENSO_TEST)
class DashboardTests(TestCase):
    def registra_consensi(self, socio):
        ConsensoSocio.objects.bulk_create(
            [
                ConsensoSocio(
                    socio=socio,
                    tipo=tipo,
                    versione_modulo=DOCUMENTI_CONSENSO_TEST[chiave]["versione"],
                    accettato_il=timezone.now(),
                    indirizzo_ip="127.0.0.1",
                )
                for tipo, chiave in (
                    ("REGOLAMENTO", "regolamento"),
                    ("PRIVACY", "privacy"),
                    ("FOTO_VIDEO", "foto_video"),
                )
            ]
        )

    def test_dashboard_shows_member_status_and_activity_sections(self):
        user = User.objects.create_user(username="membro", first_name="Ada")
        today = timezone.localdate()
        Socio.objects.create(
            user=user,
            codice_fiscale="DASHBOARDTEST000",
            data_nascita=today - timedelta(days=365 * 30),
            scadenza_quota_sociale=today + timedelta(days=30),
            scadenza_certificato_medico=today + timedelta(days=30),
            stato="ATTIVO",
        )
        self.registra_consensi(Socio.objects.get(user=user))
        self.client.force_login(user)

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ciao, Ada!")
        self.assertContains(response, "Socio in regola")
        self.assertContains(response, "Certificato medico")
        self.assertContains(response, "Allenamenti")
        self.assertContains(response, "Corsi disponibili")

    def test_dashboard_does_not_show_open_courses_past_their_end_date(self):
        user = User.objects.create_user(username="iscritto")
        oggi = timezone.localdate()
        socio = Socio.objects.create(
            user=user,
            codice_fiscale="DASHBOARDEXPIRED",
            data_nascita=oggi - timedelta(days=365 * 30),
            stato="ATTIVO",
        )
        self.registra_consensi(socio)
        corso = Corso.objects.create(nome="Apnea scaduta", descrizione="Corso terminato")
        EdizioneCorso.objects.create(
            corso=corso,
            data_inizio=oggi - timedelta(days=10),
            data_fine=oggi - timedelta(days=1),
            posti_massimi=10,
            prezzo="100.00",
            stato="APERTO_ISCRIZIONI",
        )
        self.client.force_login(user)

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Apnea scaduta")

    def test_dashboard_requires_current_versions_of_all_consents(self):
        user = User.objects.create_user(username="consensi_obsoleti")
        socio = Socio.objects.create(
            user=user,
            codice_fiscale="DASHBOARDOUTDATED",
            data_nascita=timezone.localdate() - timedelta(days=365 * 30),
            stato="ATTIVO",
        )
        self.registra_consensi(socio)
        ConsensoSocio.objects.filter(
            socio=socio, tipo="PRIVACY"
        ).update(versione_modulo="1.0")
        self.client.force_login(user)

        response = self.client.get(reverse("dashboard"))

        self.assertRedirects(response, reverse("consensi"))

    def test_dashboard_history_includes_only_concluded_enrollments(self):
        user = User.objects.create_user(username="storico")
        oggi = timezone.localdate()
        socio = Socio.objects.create(
            user=user,
            codice_fiscale="DASHBOARDHISTORY",
            data_nascita=oggi - timedelta(days=365 * 30),
            stato="ATTIVO",
        )
        self.registra_consensi(socio)
        corso_concluso = Corso.objects.create(
            nome="Corso concluso",
            descrizione="Edizione conclusa",
        )
        edizione_conclusa = EdizioneCorso.objects.create(
            corso=corso_concluso,
            data_inizio=oggi - timedelta(days=30),
            data_fine=oggi - timedelta(days=1),
            posti_massimi=10,
            prezzo="100.00",
            stato="APERTO_ISCRIZIONI",
        )
        edizione_conclusa.iscritti.add(socio)

        corso_futuro = Corso.objects.create(
            nome="Corso futuro",
            descrizione="Edizione ancora in corso",
        )
        edizione_futura = EdizioneCorso.objects.create(
            corso=corso_futuro,
            data_inizio=oggi,
            data_fine=oggi + timedelta(days=30),
            posti_massimi=10,
            prezzo="100.00",
            stato="IN_SVOLGIMENTO",
        )
        edizione_futura.iscritti.add(socio)
        self.client.force_login(user)

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Storico iscrizioni")
        self.assertContains(response, "Corso concluso")
        self.assertNotContains(response, "Corso futuro")
        self.assertNotContains(
            response, "Non hai ancora iscrizioni concluse da visualizzare."
        )

    def test_expired_subscribed_offer_appears_in_dashboard_history(self):
        user = User.objects.create_user(username="abbonato")
        oggi = timezone.localdate()
        socio = Socio.objects.create(
            user=user,
            codice_fiscale="DASHBOARDSUBSCRIB",
            data_nascita=oggi - timedelta(days=365 * 30),
            stato="ATTIVO",
        )
        self.registra_consensi(socio)
        pacchetto = PacchettoAbbonamento.objects.create(nome="Storico allenamento")
        offerta = StagioneAbbonamento.objects.create(
            pacchetto=pacchetto,
            stagione="Stagione passata",
            prezzo="200.00",
            data_inizio=oggi - timedelta(days=60),
            data_fine=oggi - timedelta(days=1),
            attivo=False,
        )
        IscrizioneAbbonamento.objects.create(
            socio=socio,
            abbonamento=offerta,
        )
        self.client.force_login(user)

        response_iscrizione = self.client.get(
            reverse("sottoscrivi_abbonamento", args=(offerta.pk,))
        )

        self.assertEqual(response_iscrizione.status_code, 302)
        self.assertEqual(
            IscrizioneAbbonamento.objects.filter(socio=socio).count(),
            1,
        )
        socio.refresh_from_db()
        self.assertIsNone(socio.abbonamento_sottoscritto)
        response_dashboard = self.client.get(reverse("dashboard"))

        self.assertContains(response_dashboard, "Storico allenamento")
        self.assertContains(response_dashboard, "Stagione passata")


class EdizioneCorsoTests(TestCase):
    def crea_edizione(self, stato, data_fine):
        corso = Corso.objects.create(nome="Apnea", descrizione="Corso di apnea")
        return EdizioneCorso.objects.create(
            corso=corso,
            data_inizio=timezone.localdate() - timedelta(days=10),
            data_fine=data_fine,
            posti_massimi=10,
            prezzo="100.00",
            stato=stato,
        )

    def test_expired_course_is_concluded_when_saved(self):
        edizione = self.crea_edizione(
            "APERTO_ISCRIZIONI", timezone.localdate() - timedelta(days=1)
        )

        self.assertEqual(edizione.stato, "CONCLUSO")

    def test_expired_course_cannot_be_reopened_when_saved(self):
        edizione = self.crea_edizione(
            "CONCLUSO", timezone.localdate() - timedelta(days=1)
        )
        edizione.stato = "APERTO_ISCRIZIONI"
        edizione.save(update_fields=("stato",))

        edizione.refresh_from_db()
        self.assertEqual(edizione.stato, "CONCLUSO")

    def test_expired_cancelled_course_remains_cancelled(self):
        edizione = self.crea_edizione(
            "ANNULLATO", timezone.localdate() - timedelta(days=1)
        )

        self.assertEqual(edizione.stato, "ANNULLATO")

    def test_management_command_closes_expired_courses_and_preserves_cancellations(self):
        oggi = timezone.localdate()
        scaduto = self.crea_edizione("CONFERMATO", oggi - timedelta(days=1))
        annullato = self.crea_edizione("ANNULLATO", oggi - timedelta(days=1))
        ancora_aperto = self.crea_edizione("APERTO_ISCRIZIONI", oggi)
        EdizioneCorso.objects.filter(pk=scaduto.pk).update(stato="CONFERMATO")

        call_command("chiudi_corsi_scaduti")

        scaduto.refresh_from_db()
        annullato.refresh_from_db()
        ancora_aperto.refresh_from_db()
        self.assertEqual(scaduto.stato, "CONCLUSO")
        self.assertEqual(annullato.stato, "ANNULLATO")
        self.assertEqual(ancora_aperto.stato, "APERTO_ISCRIZIONI")


class DatiCertificatoMedicoTests(TestCase):
    def test_socio_stores_expiry_date_without_a_certificate_file_field(self):
        socio_fields = {field.name: field for field in Socio._meta.get_fields()}

        self.assertIn("scadenza_certificato_medico", socio_fields)
        self.assertNotIn("file_certificato_medico", socio_fields)


class PublicPageStyleTests(TestCase):
    def test_public_pages_render_with_shared_styles_and_navigation(self):
        pages = (
            ("homepage", "Il mondo del silenzio ti aspetta."),
            ("login", "Accedi all’area soci"),
            ("registrazione", "Crea il tuo account"),
        )

        for url_name, heading in pages:
            with self.subTest(page=url_name):
                response = self.client.get(reverse(url_name))

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, heading)
                self.assertContains(response, "--teal: #087f82")
                self.assertContains(response, 'name="viewport"')


@override_settings(DOCUMENTI_CONSENSO=DOCUMENTI_CONSENSO_TEST)
class ConsensoSocioTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="socio_consensi")
        oggi = timezone.localdate()
        self.socio = Socio.objects.create(
            user=self.user,
            codice_fiscale="CONSENSOTEST000",
            data_nascita=oggi - timedelta(days=365 * 30),
            stato="ATTIVO",
        )

    def dati_consensi(self):
        return {
            "consenso_regolamento": "on",
            "consenso_privacy": "on",
            "consenso_foto_video": "on",
        }

    def test_existing_member_must_accept_all_consents_before_dashboard(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("dashboard"))

        self.assertRedirects(response, reverse("consensi"))
        self.assertContains(
            self.client.get(reverse("consensi")),
            "Accetta e continua",
        )

    def test_accepting_consents_records_timestamp_version_and_remote_ip(self):
        self.client.force_login(self.user)
        prima_dell_accettazione = timezone.now()

        response = self.client.post(reverse("consensi"), self.dati_consensi())

        self.assertRedirects(response, reverse("dashboard"))
        consensi = ConsensoSocio.objects.filter(socio=self.socio)
        self.assertEqual(consensi.count(), 3)
        for consenso in consensi:
            self.assertEqual(
                consenso.versione_modulo,
                DOCUMENTI_CONSENSO_TEST[
                    {
                        "REGOLAMENTO": "regolamento",
                        "PRIVACY": "privacy",
                        "FOTO_VIDEO": "foto_video",
                    }[consenso.tipo]
                ]["versione"],
            )
            self.assertGreaterEqual(
                consenso.accettato_il, prima_dell_accettazione
            )
            self.assertEqual(consenso.indirizzo_ip, "127.0.0.1")

    def test_missing_consent_cannot_be_submitted_or_registered(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("consensi"),
            {"consenso_regolamento": "on", "consenso_privacy": "on"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(ConsensoSocio.objects.filter(socio=self.socio).count(), 0)

    def test_registration_requires_each_consent(self):
        response = self.client.post(
            reverse("registrazione"),
            {
                "username": "nuovo_senza_consenso",
                "password1": "StrongPass!4831",
                "password2": "StrongPass!4831",
                "codice_fiscale": "NUOVOSOCIO000003",
                "data_nascita": "1990-01-01",
                "consenso_regolamento": "on",
                "consenso_privacy": "on",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="nuovo_senza_consenso").exists())

    def test_registration_records_all_mandatory_consents(self):
        response = self.client.post(
            reverse("registrazione"),
            {
                "username": "nuovo_socio",
                "password1": "StrongPass!4831",
                "password2": "StrongPass!4831",
                "first_name": "Nuovo",
                "last_name": "Socio",
                "email": "nuovo@example.com",
                "codice_fiscale": "NUOVOSOCIO000001",
                "data_nascita": "1990-01-01",
                **self.dati_consensi(),
            },
        )

        self.assertEqual(response.status_code, 302)
        socio = Socio.objects.get(user__username="nuovo_socio")
        self.assertEqual(ConsensoSocio.objects.filter(socio=socio).count(), 3)

    @override_settings(
        DOCUMENTI_CONSENSO={
            "regolamento": {"versione": "DA_CONFIGURARE", "url": ""},
            "privacy": {"versione": "DA_CONFIGURARE", "url": ""},
            "foto_video": {"versione": "DA_CONFIGURARE", "url": ""},
        }
    )
    def test_placeholder_documents_allow_registration_with_provisional_consents(self):
        response = self.client.post(
            reverse("registrazione"),
            {
                "username": "registrazione_bloccata",
                "password1": "StrongPass!4831",
                "password2": "StrongPass!4831",
                "first_name": "Nuovo",
                "last_name": "Socio",
                "email": "nuovo@example.com",
                "codice_fiscale": "NUOVOSOCIO000002",
                "data_nascita": "1990-01-01",
                **self.dati_consensi(),
            },
        )

        self.assertEqual(response.status_code, 302)
        socio = Socio.objects.get(user__username="registrazione_bloccata")
        consensi = ConsensoSocio.objects.filter(socio=socio)
        self.assertEqual(consensi.count(), 3)
        self.assertEqual(
            set(consensi.values_list("versione_modulo", flat=True)),
            {"DA_CONFIGURARE"},
        )


class ConsensoSocioAdminTests(TestCase):
    def test_administrator_can_view_all_consents_in_read_only_changelist(self):
        admin_user = User.objects.create_superuser(
            username="admin_consensi",
            email="admin@example.com",
            password="StrongPass!4831",
        )
        socio_user = User.objects.create_user(username="socio_consenso")
        socio = Socio.objects.create(
            user=socio_user,
            codice_fiscale="ADMINCONSENSO000",
            data_nascita=timezone.localdate() - timedelta(days=365 * 30),
        )
        ConsensoSocio.objects.create(
            socio=socio,
            tipo="PRIVACY",
            versione_modulo="1.0",
            accettato_il=timezone.now(),
            indirizzo_ip="127.0.0.1",
        )
        self.client.force_login(admin_user)

        response = self.client.get(
            reverse("admin:anagrafica_consensosocio_changelist")
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "socio_consenso")
        self.assertContains(response, "PRIVACY")
        self.assertContains(response, "1.0")
        self.assertContains(response, "127.0.0.1")
