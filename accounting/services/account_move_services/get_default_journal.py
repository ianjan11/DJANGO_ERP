from accounting.models import Journal


def get_default_journal(company):
    journal = Journal.objects.filter(
        type='MISC',
        code='MISC',
        company=company,
    ).first()



    if not journal:
        raise Journal.DoesNotExist(
            f"No default miscellaneous journal configured for company '{company}'."
        )

    return journal