from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0016_iscrizionegara_annullata_il"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="iscrizioneattivita",
            name="unique_socio_attivita",
        ),
        migrations.AddConstraint(
            model_name="iscrizioneattivita",
            constraint=models.UniqueConstraint(
                condition=models.Q(stato="ATTIVA"),
                fields=("socio", "attivita"),
                name="unique_active_socio_attivita",
            ),
        ),
    ]
