from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Socio, TurnoAllenamento, PacchettoAbbonamento, StagioneAbbonamento


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
        self.assertEqual(response.content.decode().count('Prezzo: €120.00'), 1)


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
        Socio.objects.create(
            user=user,
            codice_fiscale='VRDBOB80A01H501U',
            data_nascita=date(1980, 1, 1),
            stato='ATTIVO',
            scadenza_quota_sociale=date.today() + timedelta(days=365),
            scadenza_certificato_medico=date.today() + timedelta(days=365),
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
