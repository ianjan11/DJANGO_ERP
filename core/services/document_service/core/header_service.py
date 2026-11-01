from datetime import  date
from decimal import Decimal
from django.db import models
from core.services.document_service.document_field_service import DocumentFieldService
from core.services.document_service.field_normalize_service import FieldNormalizerService
from core.utils.result import ok, fail


class HeaderService:

    VALID_STATUSES = {"draft"}

    # =====================================================
    # PUBLIC
    # =====================================================

    def update(self, source, data, updatable_fields):
        if not data:
            return ok(changed=False, fields={}, invalid_fields=[])

        fk_fields = {
            field
            for field, target in updatable_fields.items()
            if isinstance(target, type) and issubclass(target, models.Model)
        }

        changed_fields = {}
        errors = {}

        for field, raw_value in data.items():

            if field not in updatable_fields:
                errors[field] = [f"Field '{field}' is not updatable."]
                continue

            # 1. Coerce
            try:
                coerced = self._coerce(field, raw_value, updatable_fields)
            except ValueError as exc:
                errors[field] = [str(exc)]
                continue

            # 2. Validate
            error = self._validate(field, coerced, fk_fields, data, updatable_fields)
            if error:
                errors[field] = [error]
                continue

            # 3. Resolve FK models
            try:
                resolved = self._resolve(field, coerced, fk_fields, updatable_fields)
            except ValueError as exc:
                errors[field] = [str(exc)]
                continue

            # 4. Compare & Apply changes using DocumentFieldService
            old = DocumentFieldService.normalise(getattr(source, field, None))
            new = DocumentFieldService.normalise(resolved)

            if old != new:
                setattr(source, field, resolved)
                changed_fields.update(DocumentFieldService.build_change(field, old, new))


        if errors:
            mapped_errors = DocumentFieldService.map_errors(errors)
            return fail(errors=mapped_errors, changed=False, fields={}, invalid_fields=list(mapped_errors.keys()))

        return ok(changed=bool(changed_fields), fields=changed_fields, invalid_fields=[])

    # =====================================================
    # COERCE
    # =====================================================

    def _coerce(self, field, value, updatable_fields):
        if value in (None, ""):
            return None

        target = updatable_fields.get(field)

        # Handle Foreign Keys (Expect PK integers)
        if isinstance(target, type) and issubclass(target, models.Model):
            coerced_id = FieldNormalizerService.to_int(value)
            if coerced_id is None:
                raise ValueError(f"'{field}' expects an integer ID.")
            return coerced_id

        # Use DocumentFieldService / FieldNormalizerService for standard types
        if target in (int, str, Decimal, "date"):
            try:
                return DocumentFieldService.coerce_value(target, value)
            except ValueError:
                raise ValueError(f"'{field}' is invalid for type {target if isinstance(target, str) else target.__name__}.")

        if target is bool:
            return FieldNormalizerService.to_bool(value)

        return value

    # =====================================================
    # RESOLVE FK
    # =====================================================

    def _resolve(self, field, value, fk_fields, updatable_fields):
        if field not in fk_fields or value is None:
            return value

        model = updatable_fields.get(field)

        try:
            return model.objects.get(pk=value)
        except model.DoesNotExist:
            raise ValueError(f"{model.__name__} with id '{value}' does not exist.")

    # =====================================================
    # VALIDATION
    # =====================================================

    def _validate(self, field, value, fk_fields, data, updatable_fields):
        if value is None:
            return None

        target = updatable_fields.get(field)

        if field in fk_fields:
            if not isinstance(value, int):
                return f"'{field}' expects integer PK, got {type(value).__name__}."

        elif target == "date":
            if not isinstance(value, date):
                return f"'{field}' expects a valid date."

        elif isinstance(target, type) and not isinstance(value, target):
            return f"'{field}' expects {target.__name__}, got {type(value).__name__}."

        if field == "status":
            return self._validate_status(value)

        if field == "due_date":
            issue_date = data.get("date") or data.get("order_date") or data.get("invoice_date")
            return self._validate_due_date(value, issue_date)

        return None

    # =====================================================
    # BUSINESS RULES
    # =====================================================

    @staticmethod
    def _validate_status(value):
        if str(value).lower() not in HeaderService.VALID_STATUSES:
            valid = ", ".join(sorted(HeaderService.VALID_STATUSES))
            return f"Invalid status '{value}'. Must be one of: {valid}."
        return None

    @staticmethod
    def _validate_due_date(due_date, issue_date=None):
        if due_date and issue_date and due_date < issue_date:
            return "Due date must be on or after the issue date."
        return None

