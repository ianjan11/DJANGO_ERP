
def _has_field(model, name):
    try:
        model._meta.get_field(name)
        return True
    except Exception:
        return False


def _scope_to_company(form, field_names, model, company):
    """Limit choices to the company's own records (if the model has a company FK)."""
    if not company or not _has_field(model, "company"):
        return
    for name in field_names:
        if name in form.fields:
            form.fields[name].queryset = form.fields[name].queryset.filter(company=company)

