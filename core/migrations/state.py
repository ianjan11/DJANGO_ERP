# core/migrations/0004_load_country_states_and_groups.py
from django.db import migrations

# (country_code, [(state_code, state_name), ...])
STATES_BY_COUNTRY = {
    "US": [
        ("AL", "Alabama"), ("AK", "Alaska"), ("AZ", "Arizona"), ("AR", "Arkansas"),
        ("CA", "California"), ("CO", "Colorado"), ("CT", "Connecticut"), ("DE", "Delaware"),
        ("FL", "Florida"), ("GA", "Georgia"), ("HI", "Hawaii"), ("ID", "Idaho"),
        ("IL", "Illinois"), ("IN", "Indiana"), ("IA", "Iowa"), ("KS", "Kansas"),
        ("KY", "Kentucky"), ("LA", "Louisiana"), ("ME", "Maine"), ("MD", "Maryland"),
        ("MA", "Massachusetts"), ("MI", "Michigan"), ("MN", "Minnesota"), ("MS", "Mississippi"),
        ("MO", "Missouri"), ("MT", "Montana"), ("NE", "Nebraska"), ("NV", "Nevada"),
        ("NH", "New Hampshire"), ("NJ", "New Jersey"), ("NM", "New Mexico"), ("NY", "New York"),
        ("NC", "North Carolina"), ("ND", "North Dakota"), ("OH", "Ohio"), ("OK", "Oklahoma"),
        ("OR", "Oregon"), ("PA", "Pennsylvania"), ("RI", "Rhode Island"), ("SC", "South Carolina"),
        ("SD", "South Dakota"), ("TN", "Tennessee"), ("TX", "Texas"), ("UT", "Utah"),
        ("VT", "Vermont"), ("VA", "Virginia"), ("WA", "Washington"), ("WV", "West Virginia"),
        ("WI", "Wisconsin"), ("WY", "Wyoming"), ("DC", "District of Columbia"),
    ],
    "CA": [
        ("AB", "Alberta"), ("BC", "British Columbia"), ("MB", "Manitoba"),
        ("NB", "New Brunswick"), ("NL", "Newfoundland and Labrador"), ("NS", "Nova Scotia"),
        ("ON", "Ontario"), ("PE", "Prince Edward Island"), ("QC", "Quebec"),
        ("SK", "Saskatchewan"), ("NT", "Northwest Territories"), ("NU", "Nunavut"),
        ("YT", "Yukon"),
    ],
    "IN": [
        ("AP", "Andhra Pradesh"), ("AR", "Arunachal Pradesh"), ("AS", "Assam"),
        ("BR", "Bihar"), ("CT", "Chhattisgarh"), ("GA", "Goa"), ("GJ", "Gujarat"),
        ("HR", "Haryana"), ("HP", "Himachal Pradesh"), ("JH", "Jharkhand"),
        ("KA", "Karnataka"), ("KL", "Kerala"), ("MP", "Madhya Pradesh"),
        ("MH", "Maharashtra"), ("MN", "Manipur"), ("ML", "Meghalaya"), ("MZ", "Mizoram"),
        ("NL", "Nagaland"), ("OR", "Odisha"), ("PB", "Punjab"), ("RJ", "Rajasthan"),
        ("SK", "Sikkim"), ("TN", "Tamil Nadu"), ("TG", "Telangana"), ("TR", "Tripura"),
        ("UP", "Uttar Pradesh"), ("UT", "Uttarakhand"), ("WB", "West Bengal"),
        ("DL", "Delhi"), ("JK", "Jammu and Kashmir"), ("LA", "Ladakh"),
        ("PY", "Puducherry"), ("CH", "Chandigarh"),
    ],
    "AU": [
        ("NSW", "New South Wales"), ("QLD", "Queensland"), ("SA", "South Australia"),
        ("TAS", "Tasmania"), ("VIC", "Victoria"), ("WA", "Western Australia"),
        ("ACT", "Australian Capital Territory"), ("NT", "Northern Territory"),
    ],
    "BR": [
        ("AC", "Acre"), ("AL", "Alagoas"), ("AP", "Amapa"), ("AM", "Amazonas"),
        ("BA", "Bahia"), ("CE", "Ceara"), ("DF", "Distrito Federal"),
        ("ES", "Espirito Santo"), ("GO", "Goias"), ("MA", "Maranhao"),
        ("MT", "Mato Grosso"), ("MS", "Mato Grosso do Sul"), ("MG", "Minas Gerais"),
        ("PA", "Para"), ("PB", "Paraiba"), ("PR", "Parana"), ("PE", "Pernambuco"),
        ("PI", "Piaui"), ("RJ", "Rio de Janeiro"), ("RN", "Rio Grande do Norte"),
        ("RS", "Rio Grande do Sul"), ("RO", "Rondonia"), ("RR", "Roraima"),
        ("SC", "Santa Catarina"), ("SP", "Sao Paulo"), ("SE", "Sergipe"), ("TO", "Tocantins"),
    ],
}

# (group_name, [country_code, ...])
COUNTRY_GROUPS = {
    "European Union": [
        "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR",
        "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK",
        "SI", "ES", "SE",
    ],
    "North America": ["US", "CA", "MX"],
    "GCC": ["SA", "AE", "QA", "KW", "BH", "OM"],
    "ASEAN": ["BN", "KH", "ID", "LA", "MY", "MM", "PH", "SG", "TH", "VN"],
}


def load_states_and_groups(apps, schema_editor):
    Country = apps.get_model('core', 'Country')
    CountryState = apps.get_model('core', 'CountryState')
    CountryGroup = apps.get_model('core', 'CountryGroup')
    db_alias = schema_editor.connection.alias

    countries_by_code = {
        c.code: c for c in Country.objects.using(db_alias).all()
    }

    # --- states ---
    state_objs = []
    for country_code, states in STATES_BY_COUNTRY.items():
        country = countries_by_code.get(country_code)
        if not country:
            continue  # country wasn't seeded — skip rather than fail the migration
        for code, name in states:
            state_objs.append(CountryState(country=country, code=code, name=name))

    CountryState.objects.using(db_alias).bulk_create(state_objs, ignore_conflicts=True)

    # --- groups ---
    for group_name, country_codes in COUNTRY_GROUPS.items():
        group, _ = CountryGroup.objects.using(db_alias).get_or_create(name=group_name)
        members = [countries_by_code[cc] for cc in country_codes if cc in countries_by_code]
        group.countries.set(members)


def unload_states_and_groups(apps, schema_editor):
    CountryState = apps.get_model('core', 'CountryState')
    CountryGroup = apps.get_model('core', 'CountryGroup')
    db_alias = schema_editor.connection.alias

    CountryState.objects.using(db_alias).filter(
        country__code__in=STATES_BY_COUNTRY.keys()
    ).delete()
    CountryGroup.objects.using(db_alias).filter(
        name__in=COUNTRY_GROUPS.keys()
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', 'country'),
    ]

    operations = [
        migrations.RunPython(load_states_and_groups, reverse_code=unload_states_and_groups),
    ]