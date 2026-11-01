"""
Seed units of measure with EXACT factors, and widen Uom.factor in the same migration, so no
later "factor precision" migration is ever needed.

Why this shape:
  * Every unit is declared by its real SIZE in the category's reference unit
    (1 dozen = 12 units, 1 lb = 0.45359237 kg, 1 ft = 0.3048 m ...). The factor is derived as
    1 / size with exact fraction arithmetic and stored at 12 decimals, so nothing is hand-typed
    as a rounded value like 0.08333333.
  * The field is widened first (max_digits 24, decimal_places 12). decimal_places alone is not
    enough: with max_digits=16 only 4 integer digits would remain and mg (factor 1,000,000)
    would overflow.
  * update_or_create, so re-running on a database that already holds the old rounded rows
    corrects them instead of leaving them as they were.
  * Fixes a bug in the old seed: "gal (US)" was typed as `smaller` with factor 0.264..., but a
    US gallon (3.785 L) is BIGGER than the litre reference. Uom._validate() would reject that row.

REQUIRED model change in Uom.py (so makemigrations stays clean):
    factor = models.DecimalField(max_digits=24, decimal_places=12, default=Decimal('1'))

Usage:
  * Fresh database or one that has NOT applied the old seed: use this file instead of the old one.
  * Database that already applied the old seed migration: editing an applied migration does not
    re-run it, so keep the old file and add this one as a new migration with a new number.
  * Set `dependencies` to your latest inventory migration.
  * Custom UoMs you created yourself (e.g. Case = 24 Units) are not covered here: create them
    with factor = 1/24 at 12 decimals (Uom.save() validates but does not round).
"""
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction

from django.db import migrations, models

Q12 = Decimal("0.000000000001")

# category -> list of (name, uom_type, size_of_one_unit_in_reference_unit, rounding)
# size is a string so Fraction parses it exactly. factor = 1 / size.
UOMS = {
    "Unit": [
        ("Unit", "reference", "1", "1"),
        ("Pair", "bigger", "2", "1"),
        ("Dozen", "bigger", "12", "0.01"),
    ],
    "Weight": [  # reference: kg
        ("kg", "reference", "1", "0.001"),
        ("g", "smaller", "1/1000", "0.01"),
        ("mg", "smaller", "1/1000000", "0.01"),
        ("t", "bigger", "1000", "0.001"),
        ("lb", "smaller", "0.45359237", "0.01"),       # exact by international definition
        ("oz", "smaller", "0.028349523125", "0.01"),   # exact (1/16 lb)
    ],
    "Volume": [  # reference: L
        ("L", "reference", "1", "0.001"),
        ("mL", "smaller", "1/1000", "0.01"),
        ("m³", "bigger", "1000", "0.001"),
        ("gal (US)", "bigger", "3.785411784", "0.01"),  # was wrongly 'smaller'
    ],
    "Length": [  # reference: m
        ("m", "reference", "1", "0.001"),
        ("mm", "smaller", "1/1000", "0.01"),
        ("cm", "smaller", "1/100", "0.01"),
        ("km", "bigger", "1000", "0.001"),
        ("in", "smaller", "0.0254", "0.01"),
        ("ft", "smaller", "0.3048", "0.01"),
        ("yd", "smaller", "0.9144", "0.01"),
        ("mi", "bigger", "1609.344", "0.001"),
    ],
    "Area": [  # reference: m²
        ("m²", "reference", "1", "0.01"),
        ("ft²", "smaller", "0.09290304", "0.01"),
        ("ha", "bigger", "10000", "0.0001"),
        ("acre", "bigger", "4046.8564224", "0.0001"),
        ("km²", "bigger", "1000000", "0.0001"),
    ],
    "Time": [  # reference: Day
        ("Day", "reference", "1", "0.01"),
        ("Hour", "smaller", "1/24", "0.01"),
        ("Minute", "smaller", "1/1440", "0.01"),
    ],
}


def exact_factor(size: str) -> Decimal:
    """1 / size, computed exactly as a fraction, then stored at 12 decimals."""
    f = 1 / Fraction(size)
    return (Decimal(f.numerator) / Decimal(f.denominator)).quantize(Q12, rounding=ROUND_HALF_UP)


def seed_uoms(apps, schema_editor):
    UomCategory = apps.get_model("inventory", "UomCategory")
    Uom = apps.get_model("inventory", "Uom")

    for cat_name, rows in UOMS.items():
        category, _ = UomCategory.objects.get_or_create(name=cat_name)
        for name, uom_type, size, rounding in rows:
            factor = exact_factor(size)

            # Same rules as Uom._validate(), which historical models do not run.
            if uom_type == "reference" and factor != 1:
                raise ValueError(f"{cat_name}/{name}: reference unit must have factor 1")
            if uom_type == "bigger" and not (0 < factor < 1):
                raise ValueError(f"{cat_name}/{name}: 'bigger' needs factor in (0, 1), got {factor}")
            if uom_type == "smaller" and factor <= 1:
                raise ValueError(f"{cat_name}/{name}: 'smaller' needs factor > 1, got {factor}")

            Uom.objects.update_or_create(
                category=category,
                name=name,
                defaults={
                    "uom_type": uom_type,
                    "factor": factor,
                    "rounding": Decimal(rounding),
                },
            )


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0002_initial"),  # TODO: your latest inventory migration
    ]

    operations = [
        # Schema first, data second (the reverse order can trip PostgreSQL's
        # "pending trigger events" error inside one transaction).
        migrations.AlterField(
            model_name="uom",
            name="factor",
            field=models.DecimalField(max_digits=24, decimal_places=12, default=Decimal("1")),
        ),
        migrations.RunPython(seed_uoms, migrations.RunPython.noop),
    ]