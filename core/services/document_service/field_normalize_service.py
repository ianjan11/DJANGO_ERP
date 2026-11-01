from decimal import Decimal, InvalidOperation
from datetime import datetime, date
from django.utils import timezone

class FieldNormalizerService:

    @staticmethod
    def to_int(value):
        try:
            return int(value) if value not in (None, "") else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def to_decimal(value):
        if value in (None, ""):
            return None
        try:
            return Decimal(str(value).strip())
        except InvalidOperation:
            return None

    @staticmethod
    def to_bool(value):
        return str(value).lower() in ("1", "true", "on", "yes")

    @staticmethod
    def to_str(value):
        if value is None:
            return None
        value = str(value).strip()
        return value or None

    @staticmethod
    def to_datetime(value):
        if not value:
            return None

        dt = None
        if isinstance(value, datetime):
            dt = value
        elif isinstance(value, date):
            dt = datetime.combine(value, datetime.min.time())
        else:
            try:
                # Parses 'YYYY-MM-DDTHH:MM' or 'YYYY-MM-DD HH:MM:SS'
                dt = datetime.fromisoformat(str(value))
            except (ValueError, TypeError):
                return None

        # Convert naive datetime to timezone-aware using settings.TIME_ZONE
        if dt and timezone.is_naive(dt):
            return timezone.make_aware(dt)

        return dt

    @staticmethod
    def to_date(value):
        """Coerces input into a datetime.date object.

        Handles:
          - None / empty string -> None
          - date objects -> returned directly
          - datetime objects -> extract date()
          - strings ("2026-10-16", "2026-10-16T11:48:00") -> parsed to date
        """
        if not value:
            return None

        if isinstance(value, date) and not isinstance(value, datetime):
            return value

        if isinstance(value, datetime):
            if timezone.is_aware(value):
                value = timezone.localtime(value)
            return value.date()

        # Parse string formats
        val_str = str(value).strip()
        try:
            # First attempt standard ISO format (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)
            return datetime.fromisoformat(val_str).date()
        except (ValueError, TypeError):
            pass

        # Fallbacks for common alternate date string formats
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
            try:
                return datetime.strptime(val_str, fmt).date()
            except (ValueError, TypeError):
                continue

        return None