
def _format_form_errors(form):
    """Utility to format form field errors for HTMX responses."""
    return {
        field: [str(e) for e in error_list]
        for field, error_list in form.errors.items()
    }
