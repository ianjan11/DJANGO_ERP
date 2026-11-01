
def extract_first_error(errors, default_message):
    if not errors or not isinstance(errors, dict):
        return default_message

    first_val = next(iter(errors.values()), None)
    if isinstance(first_val, (list, tuple)) and first_val:
        return str(first_val[0])
    elif isinstance(first_val, str):
        return first_val

    return default_message