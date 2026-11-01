# core/migrations/0005_load_eac_country_group.py
from django.db import migrations

EAC_MEMBERS = ["TZ", "KE", "UG", "RW", "BI", "SS", "CD"]


def load_eac_group(apps, schema_editor):
    Country = apps.get_model('core', 'Country')
    CountryGroup = apps.get_model('core', 'CountryGroup')
    db_alias = schema_editor.connection.alias

    group, _ = CountryGroup.objects.using(db_alias).get_or_create(name="East African Community (EAC)")
    members = Country.objects.using(db_alias).filter(code__in=EAC_MEMBERS)
    group.countries.set(members)


def unload_eac_group(apps, schema_editor):
    CountryGroup = apps.get_model('core', 'CountryGroup')
    CountryGroup.objects.using(schema_editor.connection.alias).filter(
        name="East African Community (EAC)"
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ('core', 'state'),
    ]
    operations = [
        migrations.RunPython(load_eac_group, reverse_code=unload_eac_group),
    ]