from django.db import migrations


CURRENCIES = {
    "TZS": {"name": "Tanzanian Shilling", "symbol": "TSh"},
    "USD": {"name": "US Dollar", "symbol": "$"},
    "EUR": {"name": "Euro", "symbol": "€"},
    "GBP": {"name": "British Pound", "symbol": "£"},
    "KES": {"name": "Kenyan Shilling", "symbol": "KSh"},
    "UGX": {"name": "Ugandan Shilling", "symbol": "USh"},
    "JPY": {"name": "Japanese Yen", "symbol": "¥"},
    "CNY": {"name": "Chinese Yuan", "symbol": "¥"},
    "INR": {"name": "Indian Rupee", "symbol": "₹"},
    "ZAR": {"name": "South African Rand", "symbol": "R"},
}


def create_currencies(apps, schema_editor):
    Currency = apps.get_model('core', 'Currency')

    for code, data in CURRENCIES.items():
        Currency.objects.update_or_create(
            code=code,
            defaults={
                "name": data["name"],
                "symbol": data["symbol"],
                "is_active": True,
            }
        )


def delete_currencies(apps, schema_editor):
    Currency = apps.get_model('core', 'Currency')

    codes = list(CURRENCIES.keys())
    Currency.objects.filter(code__in=codes).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_initial'),  # adjust if needed
    ]

    operations = [
        migrations.RunPython(create_currencies, delete_currencies),
    ]