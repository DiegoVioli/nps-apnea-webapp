from datetime import date, timedelta
import json
import smtplib
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import User
from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .consensi import TIPI_CONSENSO, consensi_mancanti, versioni_consenso_attuali
from .admin import RichiestaInformazioniAdmin
from .forms import SocioLoginForm
from .gare import conferma_iscrizione_gara, invia_email_conferma_gara
from .models import (
    ConsensoSocio,
    Corso,
    DichiarazioneGara,
    EdizioneCorso,
    Gara,
    IscrizioneGara,
    IscrizioneAbbonamento,
    ModificaScadenzaCertificato,
    PacchettoAbbonamento,
    PromemoriaCertificato,
    RichiestaInformazioni,
    RiepilogoCertificatiAmministratori,
    RisultatoGara,
    Socio,
    StagioneAbbonamento,
    TurnoAllenamento,
)

DOCUMENTI_CONSENSO_TEST = {
    "regolamento": {"versione": "1.0", "url": "/regolamento.pdf"},
    "privacy": {"versione": "2.1", "url": "/privacy.pdf"},
    "foto_video": {"versione": "1.2", "url": "/foto-video.pdf"},
}


class ModuliItalianiTests(TestCase):
    def test_login_fields_have_italian_labels(self):
        form = SocioLoginForm()

        self.assertEqual(form.fields["username"].label, "Nome utente")
        self.assertEqual(form.fields["password"].label, "Password")


class HomepageOfferteTest(TestCase):
    def setUp(self):
        self.pacchetto = PacchettoAbbonamento.objects.create(nome='Abbonamento Base')
        self.inizio = date(2026, 9, 1)
        self.fine = date(2027, 6, 30)

    def crea_offerta(self, stagione, **kwargs):
        return StagioneAbbonamento.objects.create(
            pacchetto=self.pacchetto,
            stagione=stagione,
            prezzo='120.00',
            data_inizio=self.inizio,
            data_fine=self.fine,
            **kwargs,
        )

    def test_homepage_mostra_solo_offerte_attive_selezionate_e_il_prezzo_se_abilitato(self):
        self.crea_offerta('2026/2027')
        self.crea_offerta('2027/2028', attivo=True, mostra_in_homepage=True)
        self.crea_offerta(
            '2028/2029',
            attivo=True,
            mostra_in_homepage=True,
            mostra_prezzo_in_homepage=True,
        )
        self.crea_offerta('2029/2030', attivo=False, mostra_in_homepage=True)

        response = self.client.get(reverse('homepage'))

        self.assertContains(response, '2027/2028')
        self.assertContains(response, '2028/2029')
        self.assertNotContains(response, '2026/2027')
        self.assertNotContains(response, '2029/2030')
        self.assertEqual(response.content.decode().count('Prezzo: €120,00'), 1)


class HomepageAttivitaTests(TestCase):
    def test_homepage_mostra_corsi_aperti_e_solo_offerte_visibili_e_attive(self):
        oggi = timezone.localdate()
        corso = Corso.objects.create(
            nome="Corso pubblico",
            descrizione="Corso aperto alle iscrizioni.",
        )
        edizione = EdizioneCorso.objects.create(
            corso=corso,
            data_inizio=oggi,
            data_fine=oggi + timedelta(days=20),
            posti_massimi=12,
            prezzo="150.00",
            stato="APERTO_ISCRIZIONI",
        )
        pacchetto = PacchettoAbbonamento.objects.create(
            nome="Allenamento esposto",
            descrizione="Allenamento in piscina.",
        )
        offerta = StagioneAbbonamento.objects.create(
            pacchetto=pacchetto,
            stagione="2026/2027",
            prezzo="200.00",
            data_inizio=oggi,
            data_fine=oggi + timedelta(days=60),
            attivo=True,
            mostra_in_homepage=True,
        )
        pacchetto_nascosto = PacchettoAbbonamento.objects.create(
            nome="Allenamento non esposto",
        )
        StagioneAbbonamento.objects.create(
            pacchetto=pacchetto_nascosto,
            stagione="2026/2027",
            prezzo="180.00",
            data_inizio=oggi,
            data_fine=oggi + timedelta(days=60),
            attivo=True,
        )
        pacchetto_inattivo = PacchettoAbbonamento.objects.create(
            nome="Allenamento inattivo",
        )
        StagioneAbbonamento.objects.create(
            pacchetto=pacchetto_inattivo,
            stagione="2026/2027",
            prezzo="100.00",
            data_inizio=oggi,
            data_fine=oggi + timedelta(days=60),
            attivo=False,
            mostra_in_homepage=True,
        )

        response = self.client.get(reverse("homepage"))

        self.assertContains(response, "Corso pubblico")
        self.assertContains(response, "Allenamento esposto")
        self.assertNotContains(response, "Allenamento non esposto")
        self.assertNotContains(response, "Allenamento inattivo")
        self.assertNotContains(response, "€200,00")
        self.assertContains(response, "€150,00")
        self.assertContains(
            response,
            reverse("richiesta_informazioni", args=("corso", edizione.pk)),
        )
        self.assertContains(
            response,
            reverse("richiesta_informazioni", args=("allenamento", offerta.pk)),
        )

    def test_link_staff_visibile_solo_agli_utenti_staff(self):
        staff = User.objects.create_user(username="staff_home", is_staff=True)
        socio = User.objects.create_user(username="socio_home")

        self.client.force_login(staff)
        response_staff = self.client.get(reverse("homepage"))
        self.assertContains(response_staff, reverse("pagina_staff_certificati"))
        self.assertContains(response_staff, reverse("admin:index"))

        self.client.force_login(socio)
        response_socio = self.client.get(reverse("homepage"))
        self.assertNotContains(response_socio, reverse("pagina_staff_certificati"))
        self.assertNotContains(response_socio, reverse("admin:index"))


class RichiestaInformazioniTests(TestCase):
    def setUp(self):
        self.oggi = timezone.localdate()
        self.corso = Corso.objects.create(
            nome="Corso richiesta informazioni",
            descrizione="Dettagli del corso.",
        )
        self.edizione = EdizioneCorso.objects.create(
            corso=self.corso,
            data_inizio=self.oggi + timedelta(days=7),
            data_fine=self.oggi + timedelta(days=30),
            posti_massimi=10,
            prezzo="100.00",
            stato="APERTO_ISCRIZIONI",
        )

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="web@example.com",
    )
    def test_course_request_is_saved_and_notifies_staff(self):
        staff = User.objects.create_user(
            username="staff_richieste",
            email="staff@example.com",
            is_staff=True,
        )
        response = self.client.post(
            reverse(
                "richiesta_informazioni",
                args=("corso", self.edizione.pk),
            ),
            {
                "nome": "Ada Apnea",
                "email": "ada@example.com",
                "messaggio": "Vorrei sapere come partecipare.",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Lo staff ti risponderà")
        richiesta = RichiestaInformazioni.objects.get()
        self.assertEqual(richiesta.edizione_corso, self.edizione)
        self.assertEqual(richiesta.email, "ada@example.com")
        self.assertIsNotNone(richiesta.email_notificata_il)
        self.assertEqual(mail.outbox[0].to, [staff.email])
        self.assertEqual(mail.outbox[0].reply_to, ["ada@example.com"])

    def test_hidden_training_offer_cannot_receive_information_requests(self):
        pacchetto = PacchettoAbbonamento.objects.create(
            nome="Allenamento non pubblicato",
        )
        offerta = StagioneAbbonamento.objects.create(
            pacchetto=pacchetto,
            stagione="Stagione attuale",
            prezzo="150.00",
            data_inizio=self.oggi,
            data_fine=self.oggi + timedelta(days=60),
            attivo=True,
        )

        response = self.client.get(
            reverse("richiesta_informazioni", args=("allenamento", offerta.pk))
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(RichiestaInformazioni.objects.exists())

    def test_invalid_request_is_not_saved(self):
        response = self.client.post(
            reverse(
                "richiesta_informazioni",
                args=("corso", self.edizione.pk),
            ),
            {
                "nome": "Ada",
                "email": "indirizzo-non-valido",
                "messaggio": "Richiesta.",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(RichiestaInformazioni.objects.exists())


class RichiestaInformazioniAdminTests(TestCase):
    def test_requests_are_read_only_in_admin(self):
        model_admin = RichiestaInformazioniAdmin(
            RichiestaInformazioni,
            admin.site,
        )
        request = RequestFactory().get("/admin/")

        self.assertFalse(model_admin.has_add_permission(request))
        self.assertFalse(model_admin.has_change_permission(request))
        self.assertFalse(model_admin.has_delete_permission(request))


class PaginaCertificatiStaffTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(
            username="staff_certificati",
            is_staff=True,
        )
        self.socio_user = User.objects.create_user(
            username="socio_certificati",
            first_name="Mario",
            last_name="Rossi",
        )
        self.socio = Socio.objects.create(
            user=self.socio_user,
            codice_fiscale="RSSMRA80A01H501U",
            data_nascita=date(1980, 1, 1),
            stato="ATTIVO",
            scadenza_certificato_medico=timezone.localdate() - timedelta(days=1),
        )

    def test_pagina_riservata_agli_staff_e_mostra_solo_certificati_scaduti_o_prossimi(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("pagina_staff_certificati"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Mario Rossi")

        socio = User.objects.create_user(username="socio_non_staff")
        self.client.force_login(socio)
        self.assertEqual(
            self.client.get(reverse("pagina_staff_certificati")).status_code,
            403,
        )

        self.client.logout()
        response_anonimo = self.client.get(reverse("pagina_staff_certificati"))
        self.assertRedirects(
            response_anonimo,
            f"{reverse('login')}?next={reverse('pagina_staff_certificati')}",
        )

    def test_staff_puo_aggiornare_la_scadenza_e_l_intervento_viene_registrato(self):
        self.client.force_login(self.staff)
        nuova_scadenza = timezone.localdate() + timedelta(days=365)

        response = self.client.post(
            reverse("modifica_scadenza_certificato", args=(self.socio.pk,)),
            {"nuova_scadenza": nuova_scadenza.isoformat()},
        )

        self.assertRedirects(response, reverse("pagina_staff_certificati"))
        self.socio.refresh_from_db()
        self.assertEqual(self.socio.scadenza_certificato_medico, nuova_scadenza)
        modifica = ModificaScadenzaCertificato.objects.get(socio=self.socio)
        self.assertEqual(modifica.scadenza_precedente, timezone.localdate() - timedelta(days=1))
        self.assertEqual(modifica.nuova_scadenza, nuova_scadenza)
        self.assertEqual(modifica.modificato_da, self.staff)

    def test_aggiornamento_certificato_richiede_staff_e_post_valido(self):
        url = reverse("modifica_scadenza_certificato", args=(self.socio.pk,))
        self.client.force_login(self.staff)
        response = self.client.post(url, {"nuova_scadenza": "non-una-data"})

        self.assertEqual(response.status_code, 400)
        self.socio.refresh_from_db()
        self.assertEqual(
            self.socio.scadenza_certificato_medico,
            timezone.localdate() - timedelta(days=1),
        )
        self.assertFalse(ModificaScadenzaCertificato.objects.exists())

        self.client.force_login(User.objects.create_user(username="non_staff_update"))
        self.assertEqual(self.client.post(url, {"nuova_scadenza": "2030-01-01"}).status_code, 403)


@override_settings(CERTIFICATI_API_TOKEN="token-di-test")
class ApiPromemoriaTests(TestCase):
    def crea_socio(self, username, scadenza, stato="ATTIVO"):
        user = User.objects.create_user(
            username=username,
            email=f"{username}@example.com",
            first_name="Nome",
            last_name=username.title(),
        )
        return Socio.objects.create(
            user=user,
            codice_fiscale=f"API{Socio.objects.count():013d}",
            data_nascita=timezone.localdate() - timedelta(days=365 * 30),
            scadenza_certificato_medico=scadenza,
            stato=stato,
        )

    def api_get(self):
        return self.client.get(
            reverse("api_candidati_promemoria"),
            HTTP_AUTHORIZATION="Bearer token-di-test",
        )

    def test_api_requires_a_valid_bearer_token_and_configuration(self):
        response = self.client.get(reverse("api_candidati_promemoria"))
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response["WWW-Authenticate"], "Bearer")

        with override_settings(CERTIFICATI_API_TOKEN=""):
            response = self.api_get()
        self.assertEqual(response.status_code, 503)

    def test_candidates_include_only_active_members_due_within_30_days(self):
        oggi = timezone.localdate()
        scaduto = self.crea_socio("scaduto_api", oggi - timedelta(days=2))
        in_scadenza = self.crea_socio("scadenza_api", oggi + timedelta(days=10))
        self.crea_socio("fuori_finestra_api", oggi + timedelta(days=31))
        self.crea_socio(
            "sospeso_api",
            oggi + timedelta(days=5),
            stato="SOSPESO",
        )
        response = self.api_get()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {item["socio_id"] for item in response.json()["soci"]},
            {scaduto.pk, in_scadenza.pk},
        )

        PromemoriaCertificato.objects.create(
            socio=in_scadenza,
            scadenza_certificato=in_scadenza.scadenza_certificato_medico,
            ultima_email_inviata=timezone.now(),
        )
        response = self.api_get()
        self.assertEqual(
            {item["socio_id"] for item in response.json()["soci"]},
            {scaduto.pk},
        )

    def test_api_registers_sent_reminders_idempotently_and_rejects_stale_dates(self):
        socio = self.crea_socio(
            "registrazione_api",
            timezone.localdate() + timedelta(days=10),
        )
        payload = {
            "inviati": [
                {
                    "socio_id": socio.pk,
                    "data_scadenza": socio.scadenza_certificato_medico.isoformat(),
                }
            ]
        }
        url = reverse("api_registra_promemoria_inviati")

        response = self.client.post(
            url,
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer token-di-test",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["registrati"], 1)

        response = self.client.post(
            url,
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer token-di-test",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["gia_registrati"], 1)

        payload["inviati"][0]["data_scadenza"] = (
            timezone.localdate() + timedelta(days=11)
        ).isoformat()
        response = self.client.post(
            url,
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer token-di-test",
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(PromemoriaCertificato.objects.count(), 1)

    def test_api_rejects_invalid_json_and_duplicate_members_in_same_batch(self):
        url = reverse("api_registra_promemoria_inviati")

        response = self.client.post(
            url,
            data="not-json",
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer token-di-test",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("JSON valido", response.json()["errore"])

        socio = self.crea_socio(
            "duplicato_api",
            timezone.localdate() + timedelta(days=12),
        )
        payload = {
            "inviati": [
                {"socio_id": socio.pk, "data_scadenza": socio.scadenza_certificato_medico.isoformat()},
                {"socio_id": socio.pk, "data_scadenza": socio.scadenza_certificato_medico.isoformat()},
            ]
        }

        response = self.client.post(
            url,
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer token-di-test",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Elenco non valido", response.json()["errore"])

    def test_api_rejects_inactive_members_and_changed_certificate_dates(self):
        oggi = timezone.localdate()
        socio = self.crea_socio("sospeso_api", oggi + timedelta(days=9), stato="SOSPESO")
        payload = {
            "inviati": [
                {
                    "socio_id": socio.pk,
                    "data_scadenza": socio.scadenza_certificato_medico.isoformat(),
                }
            ]
        }

        response = self.client.post(
            reverse("api_registra_promemoria_inviati"),
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer token-di-test",
        )
        self.assertEqual(response.status_code, 409)

        socio_attivo = self.crea_socio("cambiata_api", oggi + timedelta(days=7))
        payload = {
            "inviati": [
                {
                    "socio_id": socio_attivo.pk,
                    "data_scadenza": (oggi + timedelta(days=6)).isoformat(),
                }
            ]
        }

        response = self.client.post(
            reverse("api_registra_promemoria_inviati"),
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer token-di-test",
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(PromemoriaCertificato.objects.count(), 0)


class FlussoSocioTest(TestCase):
    def test_registrazione_crea_socio_attivo_e_redirige_al_dashboard(self):
        response = self.client.post(
            reverse('registrazione'),
            {
                'username': 'alice',
                'first_name': 'Alice',
                'last_name': 'Rossi',
                'email': 'alice@example.com',
                'password1': 'StrongPass123!',
                'password2': 'StrongPass123!',
                'codice_fiscale': 'RSSALC80A01H501U',
                'data_nascita': '1980-01-01',
                'consenso_regolamento': 'on',
                'consenso_privacy': 'on',
                'consenso_foto_video': 'on',
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('dashboard'))

        socio = Socio.objects.get(user__username='alice')
        self.assertEqual(socio.stato, 'ATTIVO')
        self.assertIsNotNone(socio.scadenza_quota_sociale)
        self.assertIsNotNone(socio.scadenza_certificato_medico)

    def test_sottoscrizione_abbonamento_per_socio_attivo(self):
        user = get_user_model().objects.create_user(
            username='bob',
            email='bob@example.com',
            password='StrongPass123!',
            first_name='Bob',
            last_name='Verdi',
        )
        socio = Socio.objects.create(
            user=user,
            codice_fiscale='VRDBOB80A01H501U',
            data_nascita=date(1980, 1, 1),
            stato='ATTIVO',
            scadenza_quota_sociale=date.today() + timedelta(days=365),
            scadenza_certificato_medico=date.today() + timedelta(days=365),
        )
        versioni = versioni_consenso_attuali()
        for tipo, _, _ in TIPI_CONSENSO:
            ConsensoSocio.objects.create(
                socio=socio,
                tipo=tipo,
                versione_modulo=versioni[tipo],
                accettato_il=timezone.now(),
            )

        turno = TurnoAllenamento.objects.create(
            nome_turno='Lunedì sera',
            giorno=1,
            orario_inizio='18:00:00',
            orario_fine='19:30:00',
            luogo='Piscina',
            posti_massimi=12,
        )
        pacchetto = PacchettoAbbonamento.objects.create(nome='Base')
        pacchetto.turni.add(turno)

        stagione = StagioneAbbonamento.objects.create(
            pacchetto=pacchetto,
            stagione='Stagione 2026/2027',
            prezzo='120.00',
            data_inizio=date.today(),
            data_fine=date.today() + timedelta(days=180),
            attivo=True,
        )

        self.client.force_login(user)
        response = self.client.get(reverse('sottoscrivi_abbonamento', args=[stagione.pk]))

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('dashboard'))

        user.socio.refresh_from_db()
        self.assertEqual(user.socio.abbonamento_sottoscritto, stagione)

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

    def test_staff_links_are_visible_in_dashboard_only_for_staff(self):
        for username, is_staff, codice_fiscale in (
            ("staff_dashboard", True, "STAFFDASHBOARD000"),
            ("socio_dashboard", False, "SOCIODASHBOARD000"),
        ):
            user = User.objects.create_user(
                username=username,
                is_staff=is_staff,
            )
            socio = Socio.objects.create(
                user=user,
                codice_fiscale=codice_fiscale,
                data_nascita=timezone.localdate() - timedelta(days=365 * 30),
                stato="ATTIVO",
            )
            self.registra_consensi(socio)

            self.client.force_login(user)
            response = self.client.get(reverse("dashboard"))

            self.assertEqual(response.status_code, 200)
            if is_staff:
                self.assertContains(
                    response,
                    reverse("pagina_staff_certificati"),
                )
                self.assertContains(response, reverse("admin:index"))
            else:
                self.assertNotContains(
                    response,
                    reverse("pagina_staff_certificati"),
                )
                self.assertNotContains(response, reverse("admin:index"))

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

    def test_outdated_consents_are_treated_as_missing_until_renewed(self):
        ConsensoSocio.objects.create(
            socio=self.socio,
            tipo="REGOLAMENTO",
            versione_modulo="0.9",
            accettato_il=timezone.now() - timedelta(days=10),
            indirizzo_ip="127.0.0.1",
        )
        ConsensoSocio.objects.create(
            socio=self.socio,
            tipo="PRIVACY",
            versione_modulo="0.9",
            accettato_il=timezone.now() - timedelta(days=10),
            indirizzo_ip="127.0.0.1",
        )

        self.assertEqual(
            consensi_mancanti(self.socio),
            ["REGOLAMENTO", "PRIVACY", "FOTO_VIDEO"],
        )

        self.client.force_login(self.user)
        response = self.client.post(reverse("consensi"), self.dati_consensi())

        self.assertRedirects(response, reverse("dashboard"))
        self.assertEqual(
            ConsensoSocio.objects.filter(socio=self.socio).count(),
            5,
        )

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


@override_settings(
    DOCUMENTI_CONSENSO=DOCUMENTI_CONSENSO_TEST,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="gare@example.com",
)
class GareTests(TestCase):
    def setUp(self):
        self.oggi = timezone.localdate()
        self.user = User.objects.create_user(
            username="atleta_gare",
            email="atleta@example.com",
            first_name="Ada",
            last_name="Apnea",
        )
        self.socio = Socio.objects.create(
            user=self.user,
            codice_fiscale="ATLETAGARE000001",
            data_nascita=date(1990, 1, 1),
            stato="ATTIVO",
            scadenza_certificato_medico=self.oggi + timedelta(days=365),
        )
        ConsensoSocio.objects.bulk_create(
            [
                ConsensoSocio(
                    socio=self.socio,
                    tipo=tipo,
                    versione_modulo=DOCUMENTI_CONSENSO_TEST[chiave]["versione"],
                    accettato_il=timezone.now(),
                    indirizzo_ip="127.0.0.1",
                )
                for tipo, chiave, _ in TIPI_CONSENSO
            ]
        )
        self.gara = self.crea_gara()

    def crea_gara(self, **kwargs):
        defaults = {
            "nome": "Trofeo NPS",
            "luogo": "Piscina comunale",
            "data_gara": self.oggi + timedelta(days=30),
            "termine_iscrizioni": self.oggi + timedelta(days=20),
            "prezzo": "25.00",
            "discipline": ["DYN", "STA", "CNF", "FIM", "DNF", "CWT"],
        }
        defaults.update(kwargs)
        return Gara.objects.create(**defaults)

    def test_dashboard_lists_published_races_and_shows_enrollment_state(self):
        self.crea_gara(
            nome="Gara bozza",
            pubblicata=False,
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Trofeo NPS")
        self.assertNotContains(response, "Gara bozza")
        self.assertContains(response, "€ 25,00")
        self.assertContains(
            response,
            reverse("richiedi_iscrizione_gara", args=(self.gara.pk,)),
        )

        IscrizioneGara.objects.create(socio=self.socio, gara=self.gara)
        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, "In attesa di conferma")
        self.assertNotContains(
            response,
            reverse("richiedi_iscrizione_gara", args=(self.gara.pk,)),
        )

    def test_staff_can_create_a_race_from_django_admin(self):
        staff = User.objects.create_superuser(
            username="staff_gare",
            email="staff@example.com",
            password="StrongPass!4831",
        )
        self.client.force_login(staff)

        response = self.client.post(
            reverse("admin:anagrafica_gara_add"),
            {
                "nome": "Gara creata dallo staff",
                "luogo": "Piscina",
                "data_gara": (self.oggi + timedelta(days=40)).isoformat(),
                "termine_iscrizioni": (self.oggi + timedelta(days=30)).isoformat(),
                "prezzo": "35.00",
                "discipline": ["DYN", "STA", "FIM"],
                "pubblicata": "on",
                "_save": "Salva",
            },
        )

        self.assertEqual(response.status_code, 302)
        gara = Gara.objects.get(nome="Gara creata dallo staff")
        self.assertEqual(set(gara.discipline), {"DYN", "STA", "FIM"})

    def test_staff_can_add_an_athlete_to_a_race_from_django_admin(self):
        staff = User.objects.create_superuser(
            username="staff_iscrizioni",
            email="staff-iscrizioni@example.com",
            password="StrongPass!4831",
        )
        self.client.force_login(staff)

        response = self.client.post(
            reverse("admin:anagrafica_iscrizionegara_add"),
            {
                "gara": str(self.gara.pk),
                "socio": str(self.socio.pk),
                "dichiarazioni-TOTAL_FORMS": "1",
                "dichiarazioni-INITIAL_FORMS": "0",
                "dichiarazioni-MIN_NUM_FORMS": "1",
                "dichiarazioni-MAX_NUM_FORMS": "1",
                "dichiarazioni-0-disciplina": "DYN",
                "dichiarazioni-0-distanza_m": "100",
                "dichiarazioni-0-profondita_m": "",
                "dichiarazioni-0-tempo": "00:03:00",
                "risultati-TOTAL_FORMS": "0",
                "risultati-INITIAL_FORMS": "0",
                "risultati-MIN_NUM_FORMS": "0",
                "risultati-MAX_NUM_FORMS": "1000",
                "_save": "Salva",
            },
        )

        self.assertEqual(response.status_code, 302)
        iscrizione = IscrizioneGara.objects.get(socio=self.socio, gara=self.gara)
        self.assertEqual(iscrizione.stato, "IN_ATTESA")
        self.assertEqual(iscrizione.dichiarazioni.count(), 1)
        dichiarazione = iscrizione.dichiarazioni.get()
        self.assertEqual(dichiarazione.disciplina, "DYN")
        self.assertEqual(str(dichiarazione.distanza_m), "100.00")
        self.assertEqual(dichiarazione.tempo, timedelta(minutes=3))

    def test_staff_can_open_existing_enrollment_with_readonly_declaration(self):
        iscrizione = IscrizioneGara.objects.create(
            socio=self.socio,
            gara=self.gara,
        )
        DichiarazioneGara.objects.create(
            iscrizione=iscrizione,
            disciplina="DYN",
            distanza_m="100",
            tempo=timedelta(minutes=3),
        )
        staff = User.objects.create_superuser(
            username="staff_visualizza_iscrizione",
            email="staff-visualizza@example.com",
            password="StrongPass!4831",
        )
        self.client.force_login(staff)

        response = self.client.get(
            reverse("admin:anagrafica_iscrizionegara_change", args=(iscrizione.pk,))
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "DYN")

    def test_staff_cannot_add_a_declaration_for_a_discipline_not_offered(self):
        gara_solo_dyn = self.crea_gara(
            nome="Gara solo DYN",
            discipline=["DYN"],
        )
        staff = User.objects.create_superuser(
            username="staff_disciplina",
            email="staff-disciplina@example.com",
            password="StrongPass!4831",
        )
        self.client.force_login(staff)

        response = self.client.post(
            reverse("admin:anagrafica_iscrizionegara_add"),
            {
                "gara": str(gara_solo_dyn.pk),
                "socio": str(self.socio.pk),
                "dichiarazioni-TOTAL_FORMS": "1",
                "dichiarazioni-INITIAL_FORMS": "0",
                "dichiarazioni-MIN_NUM_FORMS": "1",
                "dichiarazioni-MAX_NUM_FORMS": "1",
                "dichiarazioni-0-disciplina": "STA",
                "dichiarazioni-0-tempo": "00:03:00",
                "risultati-TOTAL_FORMS": "0",
                "risultati-INITIAL_FORMS": "0",
                "risultati-MIN_NUM_FORMS": "0",
                "risultati-MAX_NUM_FORMS": "1000",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(IscrizioneGara.objects.filter(gara=gara_solo_dyn).exists())

    def test_staff_must_provide_required_declaration_values(self):
        staff = User.objects.create_superuser(
            username="staff_dichiarazione",
            email="staff-dichiarazione@example.com",
            password="StrongPass!4831",
        )
        self.client.force_login(staff)

        response = self.client.post(
            reverse("admin:anagrafica_iscrizionegara_add"),
            {
                "gara": str(self.gara.pk),
                "socio": str(self.socio.pk),
                "dichiarazioni-TOTAL_FORMS": "1",
                "dichiarazioni-INITIAL_FORMS": "0",
                "dichiarazioni-MIN_NUM_FORMS": "1",
                "dichiarazioni-MAX_NUM_FORMS": "1",
                "dichiarazioni-0-disciplina": "DYN",
                "dichiarazioni-0-distanza_m": "",
                "dichiarazioni-0-profondita_m": "",
                "dichiarazioni-0-tempo": "",
                "risultati-TOTAL_FORMS": "0",
                "risultati-INITIAL_FORMS": "0",
                "risultati-MIN_NUM_FORMS": "0",
                "risultati-MAX_NUM_FORMS": "1000",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(IscrizioneGara.objects.filter(gara=self.gara).exists())

    def test_member_submits_one_required_declaration_for_one_selected_discipline(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("richiedi_iscrizione_gara", args=(self.gara.pk,)),
            {
                "disciplina": "CNF",
                "distanza_DYN": "100",
                "tempo_DYN": "00:03:00",
                "tempo_STA": "00:04:30",
                "profondita_CNF": "40",
                "tempo_CNF": "00:02:00",
            },
        )

        self.assertRedirects(response, reverse("dashboard"))
        iscrizione = IscrizioneGara.objects.get(socio=self.socio, gara=self.gara)
        self.assertEqual(iscrizione.stato, "IN_ATTESA")
        self.assertEqual(iscrizione.dichiarazioni.count(), 1)
        dichiarazione_cnf = iscrizione.dichiarazioni.get(disciplina="CNF")
        self.assertEqual(str(dichiarazione_cnf.profondita_m), "40.00")
        self.assertEqual(dichiarazione_cnf.tempo, timedelta(minutes=2))
        self.assertEqual(len(mail.outbox), 0)

    def test_member_can_edit_declaration_while_enrollment_is_pending(self):
        iscrizione = IscrizioneGara.objects.create(
            socio=self.socio,
            gara=self.gara,
        )
        dichiarazione = DichiarazioneGara.objects.create(
            iscrizione=iscrizione,
            disciplina="DYN",
            distanza_m="100",
            tempo=timedelta(minutes=3),
        )
        dichiarazione.refresh_from_db()
        self.client.force_login(self.user)
        url = reverse("modifica_dichiarazione_gara", args=(iscrizione.pk,))

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Salva modifiche")
        self.assertEqual(response.context["form"]["disciplina"].value(), "DYN")
        self.assertEqual(
            response.context["form"]["distanza_DYN"].value(),
            dichiarazione.distanza_m,
        )
        self.assertContains(
            self.client.get(reverse("dashboard")),
            reverse("modifica_dichiarazione_gara", args=(iscrizione.pk,)),
        )

        response = self.client.post(
            url,
            {
                "disciplina": "DYN",
                "distanza_DYN": "125.5",
                "tempo_DYN": "00:03:30",
            },
        )

        self.assertRedirects(response, reverse("dashboard"))
        iscrizione.refresh_from_db()
        dichiarazione.refresh_from_db()
        self.assertEqual(iscrizione.stato, "IN_ATTESA")
        self.assertEqual(iscrizione.dichiarazioni.count(), 1)
        self.assertEqual(str(dichiarazione.distanza_m), "125.50")
        self.assertEqual(dichiarazione.tempo, timedelta(minutes=3, seconds=30))

        response = self.client.post(
            url,
            {
                "disciplina": "CNF",
                "profondita_CNF": "42",
                "tempo_CNF": "00:02:45",
            },
        )

        self.assertRedirects(response, reverse("dashboard"))
        self.assertEqual(iscrizione.dichiarazioni.count(), 1)
        dichiarazione_cnf = iscrizione.dichiarazioni.get()
        self.assertEqual(dichiarazione_cnf.disciplina, "CNF")
        self.assertEqual(str(dichiarazione_cnf.profondita_m), "42.00")
        self.assertEqual(dichiarazione_cnf.tempo, timedelta(minutes=2, seconds=45))

    def test_declaration_edit_is_blocked_after_confirmation_or_registration_deadline(self):
        iscrizione = IscrizioneGara.objects.create(
            socio=self.socio,
            gara=self.gara,
        )
        self.client.force_login(self.user)
        url = reverse("modifica_dichiarazione_gara", args=(iscrizione.pk,))

        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertContains(
            self.client.get(reverse("dashboard")),
            reverse("modifica_dichiarazione_gara", args=(iscrizione.pk,)),
        )

        iscrizione.stato = "ISCRITTO"
        iscrizione.save(update_fields=("stato",))
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertNotContains(
            self.client.get(reverse("dashboard")),
            reverse("modifica_dichiarazione_gara", args=(iscrizione.pk,)),
        )

        iscrizione.stato = "IN_ATTESA"
        iscrizione.save(update_fields=("stato",))
        self.gara.termine_iscrizioni = self.oggi
        self.gara.save(update_fields=("termine_iscrizioni",))
        self.assertEqual(self.client.get(url).status_code, 200)

        self.gara.termine_iscrizioni = self.oggi - timedelta(days=1)
        self.gara.save(update_fields=("termine_iscrizioni",))
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_invalid_declarations_do_not_create_an_enrollment(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("richiedi_iscrizione_gara", args=(self.gara.pk,)),
            {"disciplina": "DYN", "tempo_DYN": "00:04:30"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(IscrizioneGara.objects.exists())

        gara_solo_dyn = self.crea_gara(
            nome="Gara solo DYN",
            discipline=["DYN"],
        )
        response = self.client.post(
            reverse("richiedi_iscrizione_gara", args=(gara_solo_dyn.pk,)),
            {
                "disciplina": "STA",
                "tempo_STA": "00:04:30",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(IscrizioneGara.objects.exists())

    def test_inactive_member_cannot_enroll(self):
        self.client.force_login(self.user)
        self.socio.stato = "SOSPESO"
        self.socio.save(update_fields=("stato",))

        response = self.client.post(
            reverse("richiedi_iscrizione_gara", args=(self.gara.pk,)),
            {},
        )

        self.assertRedirects(response, reverse("dashboard"))
        self.assertFalse(IscrizioneGara.objects.exists())

    def test_closed_registration_cannot_enroll(self):
        self.client.force_login(self.user)
        gara_chiusa = self.crea_gara(
            nome="Gara chiusa",
            termine_iscrizioni=self.oggi - timedelta(days=1),
        )

        response = self.client.get(
            reverse("richiedi_iscrizione_gara", args=(gara_chiusa.pk,))
        )

        self.assertRedirects(response, reverse("dashboard"))
        self.assertFalse(IscrizioneGara.objects.exists())

    def test_certificate_must_cover_race_date_for_registration(self):
        self.client.force_login(self.user)
        self.socio.scadenza_certificato_medico = self.gara.data_gara - timedelta(days=1)
        self.socio.save(update_fields=("scadenza_certificato_medico",))

        dashboard = self.client.get(reverse("dashboard"))
        self.assertContains(dashboard, "Certificato medico mancante o non valido")
        self.assertNotContains(
            dashboard,
            reverse("richiedi_iscrizione_gara", args=(self.gara.pk,)),
        )

        response = self.client.post(
            reverse("richiedi_iscrizione_gara", args=(self.gara.pk,)),
            {},
        )

        self.assertRedirects(response, reverse("dashboard"))
        self.assertFalse(IscrizioneGara.objects.exists())

        self.socio.scadenza_certificato_medico = self.gara.data_gara
        self.socio.save(update_fields=("scadenza_certificato_medico",))
        response = self.client.get(
            reverse("richiedi_iscrizione_gara", args=(self.gara.pk,))
        )
        self.assertEqual(response.status_code, 200)

    def test_admin_confirmation_sends_email_only_once(self):
        iscrizione = IscrizioneGara.objects.create(
            socio=self.socio,
            gara=self.gara,
        )
        model_admin = admin.site._registry[IscrizioneGara]
        request = RequestFactory().post("/admin/")

        with patch.object(model_admin, "message_user"):
            model_admin.conferma_iscrizioni(
                request,
                IscrizioneGara.objects.filter(pk=iscrizione.pk),
            )

        iscrizione.refresh_from_db()
        self.assertEqual(iscrizione.stato, "ISCRITTO")
        self.assertIsNotNone(iscrizione.confermata_il)
        self.assertIsNotNone(iscrizione.email_conferma_inviata_il)
        self.assertEqual(mail.outbox[0].to, ["atleta@example.com"])
        self.assertIn(self.gara.nome, mail.outbox[0].subject)
        self.client.force_login(self.user)
        self.assertContains(self.client.get(reverse("dashboard")), "Iscritto")

        with patch.object(model_admin, "message_user"):
            model_admin.conferma_iscrizioni(
                request,
                IscrizioneGara.objects.filter(pk=iscrizione.pk),
            )
        self.assertEqual(len(mail.outbox), 1)

    @patch("anagrafica.gare.send_mail", return_value=0)
    def test_failed_confirmation_email_can_be_retried(self, send_mail_mock):
        iscrizione = IscrizioneGara.objects.create(
            socio=self.socio,
            gara=self.gara,
        )

        modificata, email_inviata = conferma_iscrizione_gara(iscrizione)

        self.assertTrue(modificata)
        self.assertFalse(email_inviata)
        iscrizione.refresh_from_db()
        self.assertEqual(iscrizione.stato, "ISCRITTO")
        self.assertIsNone(iscrizione.email_conferma_inviata_il)
        send_mail_mock.assert_called_once()

        with patch("anagrafica.gare.send_mail", return_value=1):
            self.assertTrue(invia_email_conferma_gara(iscrizione))
        iscrizione.refresh_from_db()
        self.assertIsNotNone(iscrizione.email_conferma_inviata_il)

    def test_admin_cannot_confirm_registration_with_expired_certificate(self):
        iscrizione = IscrizioneGara.objects.create(
            socio=self.socio,
            gara=self.gara,
        )
        self.socio.scadenza_certificato_medico = self.gara.data_gara - timedelta(days=1)
        self.socio.save(update_fields=("scadenza_certificato_medico",))
        model_admin = admin.site._registry[IscrizioneGara]

        with patch.object(model_admin, "message_user"):
            model_admin.conferma_iscrizioni(
                RequestFactory().post("/admin/"),
                IscrizioneGara.objects.filter(pk=iscrizione.pk),
            )

        iscrizione.refresh_from_db()
        self.assertEqual(iscrizione.stato, "IN_ATTESA")
        self.assertFalse(model_admin.certificato_valido_alla_gara(iscrizione))
        self.assertEqual(len(mail.outbox), 0)

    def test_retry_action_does_not_resend_confirmed_email(self):
        iscrizione = IscrizioneGara.objects.create(
            socio=self.socio,
            gara=self.gara,
            stato="ISCRITTO",
            confermata_il=timezone.now(),
            email_conferma_inviata_il=timezone.now(),
        )
        model_admin = admin.site._registry[IscrizioneGara]

        with (
            patch.object(model_admin, "message_user"),
            patch("anagrafica.admin.invia_email_conferma_gara") as invia_email,
        ):
            model_admin.reinvia_email_conferme(
                RequestFactory().post("/admin/"),
                IscrizioneGara.objects.filter(pk=iscrizione.pk),
            )

        invia_email.assert_not_called()
        self.assertEqual(len(mail.outbox), 0)

    def test_results_are_unavailable_before_race_or_before_confirmation(self):
        iscrizione = IscrizioneGara.objects.create(
            socio=self.socio,
            gara=self.gara,
            stato="IN_ATTESA",
        )
        self.client.force_login(self.user)
        url = reverse("modifica_risultati_gara", args=(iscrizione.pk,))
        self.assertEqual(self.client.get(url).status_code, 404)

        iscrizione.stato = "ISCRITTO"
        iscrizione.save(update_fields=("stato",))
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_member_can_add_and_edit_results_only_for_past_confirmed_races(self):
        self.gara.data_gara = self.oggi
        self.gara.termine_iscrizioni = self.oggi - timedelta(days=5)
        self.gara.save()
        iscrizione = IscrizioneGara.objects.create(
            socio=self.socio,
            gara=self.gara,
            stato="ISCRITTO",
            confermata_il=timezone.now(),
        )
        DichiarazioneGara.objects.create(
            iscrizione=iscrizione,
            disciplina="DYN",
            distanza_m="100",
            tempo=timedelta(minutes=3),
        )
        self.client.force_login(self.user)
        url = reverse("modifica_risultati_gara", args=(iscrizione.pk,))
        dati = {
            "distanza_DYN": "112.5",
            "tempo_DYN": "00:02:30",
        }

        response = self.client.post(url, dati)

        self.assertRedirects(response, reverse("dashboard"))
        self.assertEqual(iscrizione.risultati.count(), 1)
        risultato_dyn = iscrizione.risultati.get(disciplina="DYN")
        self.assertEqual(str(risultato_dyn.distanza_m), "112.50")
        self.assertEqual(risultato_dyn.tempo, timedelta(minutes=2, seconds=30))
        dashboard = self.client.get(reverse("dashboard"))
        self.assertContains(dashboard, "Storico gare e prestazioni")
        self.assertContains(dashboard, "DYN - apnea dinamica con pinne")

        dati["distanza_DYN"] = "115"
        self.client.post(url, dati)
        risultato_dyn.refresh_from_db()
        self.assertEqual(str(risultato_dyn.distanza_m), "115.00")

        altro_user = User.objects.create_user(username="altro_atleta")
        Socio.objects.create(
            user=altro_user,
            codice_fiscale="ALTROATLETA00001",
            data_nascita=date(1991, 1, 1),
            stato="ATTIVO",
        )
        self.client.force_login(altro_user)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_dashboard_compares_declared_and_achieved_performances_and_shows_charts(self):
        gare = [
            (
                self.crea_gara(
                    nome="Gara più vecchia",
                    data_gara=self.oggi - timedelta(days=60),
                    termine_iscrizioni=self.oggi - timedelta(days=70),
                ),
                "100",
                "110",
                timedelta(minutes=3),
                timedelta(minutes=2, seconds=50),
            ),
            (
                self.crea_gara(
                    nome="Gara recente",
                    data_gara=self.oggi - timedelta(days=30),
                    termine_iscrizioni=self.oggi - timedelta(days=40),
                ),
                "120",
                "125",
                timedelta(minutes=4),
                timedelta(minutes=3, seconds=45),
            ),
        ]
        for gara, distanza_dichiarata, distanza_realizzata, tempo_dichiarato, tempo_realizzato in gare:
            iscrizione = IscrizioneGara.objects.create(
                socio=self.socio,
                gara=gara,
                stato="ISCRITTO",
                confermata_il=timezone.now(),
            )
            DichiarazioneGara.objects.create(
                iscrizione=iscrizione,
                disciplina="DYN",
                distanza_m=distanza_dichiarata,
                tempo=tempo_dichiarato,
            )
            RisultatoGara.objects.create(
                iscrizione=iscrizione,
                disciplina="DYN",
                distanza_m=distanza_realizzata,
                tempo=tempo_realizzato,
            )

        gara_senza_risultato = self.crea_gara(
            nome="Gara senza risultato",
            data_gara=self.oggi - timedelta(days=10),
            termine_iscrizioni=self.oggi - timedelta(days=20),
        )
        iscrizione_senza_risultato = IscrizioneGara.objects.create(
            socio=self.socio,
            gara=gara_senza_risultato,
            stato="ISCRITTO",
            confermata_il=timezone.now(),
        )
        DichiarazioneGara.objects.create(
            iscrizione=iscrizione_senza_risultato,
            disciplina="DYN",
            distanza_m="130",
            tempo=timedelta(minutes=4, seconds=30),
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Distanza dichiarata")
        self.assertContains(response, "Distanza realizzata")
        self.assertContains(response, "130")
        self.assertContains(response, "Non inserito")
        self.assertContains(response, "Andamento delle prestazioni")
        self.assertContains(response, "Gara più vecchia: dichiarato 100")
        self.assertContains(response, "Gara più vecchia: realizzato 110")
        self.assertEqual(len(response.context["grafici_performance"]), 2)
        grafico_distanza = next(
            grafico
            for grafico in response.context["grafici_performance"]
            if grafico["titolo"] == "DYN - apnea dinamica con pinne — Distanza (m)"
        )
        self.assertEqual(
            [punto["x"] for punto in grafico_distanza["dichiarati"]],
            [58.0, 622.0],
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
