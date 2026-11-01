from typing import Optional

from django.core.exceptions import ValidationError
from django.db.models import F, Q
from django.utils import timezone

from inventory.models import StockLocation, StockPicking, StockPickingType
from users.models import UserProfile


def _virtual_location(usage, company):
    """Company-owned location wins over the shared (company-less) one.
    NULLs are sorted last explicitly so this is DB-independent."""
    return (
        StockLocation.objects
        .filter(usage=usage, active=True)
        .filter(Q(company=company) | Q(company__isnull=True))
        .order_by(F("company_id").asc(nulls_last=True), "id")
        .first()
    )


def _default_warehouse(user, company):
    """The user's profile warehouse, ignored if it belongs to another company."""
    if not user or not user.is_authenticated:
        return None
    profile = (
        UserProfile.objects.select_related("default_location")
        .filter(user=user)
        .first()
    )
    warehouse = profile.default_location if profile else None  # FK to Warehouse
    if warehouse and company and warehouse.company_id != company.id:
        return None
    return warehouse


def _validate_location(label, location, company):
    if not location.active:
        raise ValidationError(f'The {label} location "{location.complete_name}" is archived.')
    if location.usage == StockLocation.Usage.VIEW:
        raise ValidationError(
            f'The {label} location "{location.complete_name}" is a view location '
            'and cannot be used in a move.'
        )
    if company and location.company_id and location.company_id != company.id:
        raise ValidationError(
            f'The {label} location "{location.complete_name}" does not belong to the active company.'
        )


def resolve_picking_locations(request, picking_type=None, source_location=None, dest_location=None):
    company = getattr(request, "company", None)
    user = getattr(request, "user", None)
    U = StockLocation.Usage

    # 1. Warehouse
    if picking_type:
        if not picking_type.active:
            raise ValidationError("Picking type is archived.")
        warehouse = picking_type.warehouse
        if company and warehouse.company_id != company.id:
            raise ValidationError("Picking type does not belong to the active company.")
    else:
        warehouse = _default_warehouse(user, company)

    stock_loc = getattr(warehouse, "lot_stock_location", None) if warehouse else None
    code = picking_type.code if picking_type else None

    # 2. Type-aware fallbacks
    fallback_source = fallback_dest = None
    if code == StockPickingType.Code.INCOMING:
        fallback_source = _virtual_location(U.SUPPLIER, company)
        fallback_dest = stock_loc
    elif code == StockPickingType.Code.OUTGOING:
        fallback_source = stock_loc
        fallback_dest = _virtual_location(U.CUSTOMER, company)
    elif code is None:
        fallback_source = fallback_dest = stock_loc

    source = (source_location
              or (picking_type.default_source_location if picking_type else None)
              or fallback_source)
    dest = (dest_location
            or (picking_type.default_dest_location if picking_type else None)
            or fallback_dest)

    # 3. Must resolve
    if not source:
        raise ValidationError("Could not determine a source location; set one on the picking type or pass it explicitly.")
    if not dest:
        raise ValidationError("Could not determine a destination location; set one on the picking type or pass it explicitly.")

    if source.pk == dest.pk and code != StockPickingType.Code.INTERNAL:
        raise ValidationError("Source and destination locations must differ.")

    # 4. Validity + company isolation
    _validate_location("source", source, company)
    _validate_location("destination", dest, company)

    return source, dest


def create_stock_picking(
    request,
    picking_type: StockPickingType,
    source_location: Optional[StockLocation] = None,
    dest_location: Optional[StockLocation] = None,
) -> StockPicking:
    company = getattr(request, "company", None)
    if not company:
        raise ValidationError("An active company is required.")

    source, dest = resolve_picking_locations(request, picking_type, source_location, dest_location)

    return StockPicking.objects.create(
        picking_type=picking_type,
        company=company,
        warehouse=picking_type.warehouse,
        source_location=source,
        dest_location=dest,
        status=StockPicking.Status.DRAFT,
        scheduled_date=timezone.now(),
    )