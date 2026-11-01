# core/migrations/000X_load_tax_groups.py — adjust app label / fields to match your real TaxGroup model
from django.db import migrations

TAX_GROUPS = ["VAT", "Withholding Tax", "Statutory Levy"]

def load_tax_groups(apps, schema_editor):
    TaxGroup = apps.get_model('accounting', 'TaxGroup')
    db_alias = schema_editor.connection.alias
    TaxGroup.objects.using(db_alias).bulk_create(
        [TaxGroup(name=n) for n in TAX_GROUPS], ignore_conflicts=True
    )

def unload_tax_groups(apps, schema_editor):
    TaxGroup = apps.get_model('accounting', 'TaxGroup')
    TaxGroup.objects.using(schema_editor.connection.alias).filter(name__in=TAX_GROUPS).delete()

class Migration(migrations.Migration):
    dependencies = [('accounting', 'account_types')]
    operations = [migrations.RunPython(load_tax_groups, reverse_code=unload_tax_groups)]