from decimal import Decimal


class DocumentFieldService:

    FORM_FIELD_MAP = {}

    # =====================================================
    # COERCION
    # =====================================================

    @staticmethod
    def coerce_value(target, value):

        if value is None or value == "":
            return None

        try:
            if target is int:
                return int(value)

            if target is str:
                return str(value).strip()

            if target is Decimal:
                return Decimal(str(value))

            if target == "date":
                from datetime import datetime

                return datetime.strptime(
                    str(value),
                    "%Y-%m-%d",
                ).date()

        except (ValueError, TypeError):
            raise ValueError("Invalid value.")

        return value

    # =====================================================
    # NORMALISE
    # =====================================================

    @staticmethod
    def normalise(value):

        if value is None:
            return None

        if isinstance(value, str):
            return value.strip() or None

        return value

    # =====================================================
    # ERROR MAPPING
    # =====================================================

    @classmethod
    def map_errors(cls, errors):

        return {
            cls.FORM_FIELD_MAP.get(field, field): messages
            for field, messages in errors.items()
        }

    # =====================================================
    # CHANGE
    # =====================================================

    @classmethod
    def build_change(cls, field, old, new):

        form_field = cls.FORM_FIELD_MAP.get(
            field,
            field,
        )

        return {
            form_field: {
                "old_value": old,
                "new_value": new,
            }
        }

    # =====================================================
    # DJANGO VALIDATION ERROR
    # =====================================================

    @staticmethod
    def validation_errors(exc):

        if hasattr(exc, "message_dict"):
            return exc.message_dict

        return {
            "__all__": exc.messages
        }