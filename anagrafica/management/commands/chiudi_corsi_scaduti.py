from django.core.management.base import BaseCommand
from django.utils import timezone

from anagrafica.models import EdizioneCorso


class Command(BaseCommand):
    help = "Segna come conclusi i corsi terminati."

    def handle(self, *args, **options):
        aggiornati = (
            EdizioneCorso.objects.filter(data_fine__lt=timezone.localdate())
            .exclude(stato__in=("CONCLUSO", "ANNULLATO"))
            .update(stato="CONCLUSO")
        )
        self.stdout.write(
            self.style.SUCCESS(f"Corsi aggiornati a conclusi: {aggiornati}.")
        )
