# sales/services/invoice/core/result.py


def ok(**data) -> dict:
    """Successful result."""
    return {
        "errors":     {},
        "row_errors": {},
        "warnings": {},
        **data,
    }


def fail(
    errors:     dict = None,
    row_errors: dict = None,
    **data,
) -> dict:
    """Failed result."""
    return {
        "errors":     errors     or {},
        "row_errors": row_errors or {},
        **data,
    }