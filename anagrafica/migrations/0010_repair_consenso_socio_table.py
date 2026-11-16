from django.db import migrations


def ensure_consenso_socio_table(apps, schema_editor):
    model = apps.get_model("anagrafica", "ConsensoSocio")
    tables = schema_editor.connection.introspection.table_names()
    if model._meta.db_table not in tables:
        schema_editor.create_model(model)


class Migration(migrations.Migration):
    dependencies = [
        ("anagrafica", "0009_richiestainformazioni"),
    ]

    operations = [
        migrations.RunPython(
            ensure_consenso_socio_table,
            migrations.RunPython.noop,
        ),
    ]
