import logging
from django.core.exceptions import ValidationError, ObjectDoesNotExist
from django.db import transaction
from accounting.models import AccountMove, AccountMoveLine
from core.services.pricing_service import authoritative_price
from purchases.models import PurchaseOrder, PurchaseOrderLine
from sales.models import SalesOrder, SalesOrderLine
from core.services.currency_exchange_service import exchange_price
from core.services.document_service.field_normalize_service import FieldNormalizerService
from core.utils.result import ok, fail
from decimal import Decimal, ROUND_HALF_UP

normalizer = FieldNormalizerService()
logger = logging.getLogger("sales.invoice")


class ItemsService:
    """
    Persistence layer for line items. document_type is the single
    source of truth for model resolution, FK name, tax scope, and
    pricing — everything else is generic across sales/purchase docs.

    Pricing context: the (company, doc_currency, date) tuple used for
    price resolution is ALWAYS available. If the caller passes
    `currency_conversion` it is used as-is; otherwise it is derived from
    the document itself (_conversion_from_doc) using exactly the fields
    DocumentValidationService reads. This guarantees the writer and the
    validator price from the same context.

    Note: an explicitly passed `currency_conversion` additionally means
    "the payload's price_unit is not authoritative, reprice from source"
    (existing behaviour). A derived context does NOT trigger that, so
    manually typed prices are still respected.
    """

    UPDATABLE_FIELDS = {
        "product_id": int,
        "quant_id": int,
        "description": str,
        "partner_id": int,
        "quantity": Decimal,
        "discount_percent": Decimal,
        "price_unit": Decimal,
        "account_id": int,
        "product_uom_id": int,
        "debit": Decimal,
        "credit": Decimal,
        "memo": str,
    }

    PRODUCT_ONLY_FIELDS = {
        "product_id", "quant_id", "discount_percent", "product_uom_id", "description", "price_unit",
    }

    ZERO_DEFAULT_FIELDS = {"debit", "credit", "discount_percent"}

    # Single config table — add a new document type here and nothing
    # else in this class needs to change.
    #
    # "line_types": True marks document types whose line model has a
    # LineType enum (PRODUCT / PLAIN). Document types without it (orders)
    # only ever have product lines.
    SOURCE_MAP = {
        "sales_invoice": {
            "parent_model": AccountMove,
            "line_model": AccountMoveLine,
            "fk_name": "move",
            "line_types": True,
            "tax_field": "taxes",
            "tax_use": "SALE",
            "tax_source_field": "sales_taxes",
            "price_field": "default_price",
            "account_field": "revenue_account",
            "fallback_account_method": "get_stock_output_account",
        },
        "supplier_invoice": {
            "parent_model": AccountMove,
            "line_model": AccountMoveLine,
            "fk_name": "move",
            "line_types": True,
            "tax_field": "taxes",
            "tax_use": "PURCHASE",
            "tax_source_field": "purchase_taxes",
            "price_field": "cost_price",
            "account_field": "expense_account",
            "fallback_account_method": "get_stock_input_account",
        },
        "sales_order": {
            "parent_model": SalesOrder,
            "line_model": SalesOrderLine,
            "fk_name": "sales_order",
            "tax_field": "taxes",
            "tax_use": "SALE",
            "tax_source_field": "sales_taxes",
            "price_field": "default_price",
        },
        "purchase_order": {
            "parent_model": PurchaseOrder,
            "line_model": PurchaseOrderLine,
            "fk_name": "purchase_order",
            "tax_field": "taxes",
            "tax_use": "PURCHASE",
            "tax_source_field": "purchase_taxes",
            "price_field": "product_cost",
        },
        "entry": {
            "parent_model": AccountMove,
            "line_model": AccountMoveLine,
            "fk_name": "move",
            "line_types": True,
        },
    }

    @transaction.atomic
    def sync(self, items_data, document_type, doc_instance, currency_conversion=None):

        if not doc_instance:
            raise ValueError("ItemsService.sync requires a document instance ('source').")

        config = self._get_config(document_type)

        lines_rel = getattr(doc_instance, "lines", getattr(doc_instance, "items", None))
        if lines_rel is None:
            raise AttributeError(
                f"Model '{type(doc_instance).__name__}' has neither 'lines' nor 'items' relationship."
            )

        existing = {item.id: item for item in lines_rel.all()}

        created, updated, deleted, row_errors = [], [], [], {}

        for row in items_data:

            item_id = row.get("id")

            prefix = row.get("prefix") or f"items-{row.get('index', 0)}"

            if not item_id:
                self._handle_create(doc_instance, config, row, prefix, created, row_errors, currency_conversion)
                continue

            item = existing.get(item_id)
            if not item:
                row_errors[prefix] = {"__all__": [f"Item {item_id} not found."]}
                continue

            if row.get("delete", False):
                self._handle_delete(item, prefix, deleted, row_errors)
            else:
                self._handle_update(item, config, row, prefix, updated, row_errors, doc_instance, currency_conversion)

        if row_errors:
            return fail(row_errors=row_errors, changed=bool(created or updated or deleted),
                        created=created, updated=updated, deleted=deleted)

        return ok(changed=bool(created or updated or deleted),
                  created=created, updated=updated, deleted=deleted)

    # ------------------------------------------------------------------
    # Config resolution — the only place document_type is interpreted
    # ------------------------------------------------------------------

    def _get_config(self, document_type):
        config = self.SOURCE_MAP.get(document_type)
        if not config:
            raise ValueError(
                f"Unknown document_type '{document_type}'. Expected one of: {list(self.SOURCE_MAP)}"
            )
        return config

    def _is_product_line(self, item, config):
        """
        Docs without line types (orders) are always product lines.
        Docs with line types (invoices, entries) are product lines only
        when the row's line_type is PRODUCT.
        """
        if not config.get("line_types"):
            return True
        return item.line_type == item.LineType.PRODUCT

    # ------------------------------------------------------------------
    # Pricing context
    # ------------------------------------------------------------------

    def _conversion_from_doc(self, doc_instance):
        """
        (company, doc_currency, date) derived from the document, using the
        same fields DocumentValidationService reads in _validate_pricing.
        Returns None when the document has no company or currency (e.g.
        plain journal entries), in which case no conversion is applied.
        """
        company = getattr(doc_instance, "company", None)
        doc_currency = getattr(doc_instance, "currency", None)
        date = getattr(doc_instance, "issue_date", None)
        if company is None or doc_currency is None:
            return None
        return (company, doc_currency, date)

    def _effective_conversion(self, doc_instance, currency_conversion):
        """Explicit caller-supplied tuple wins; otherwise derive from the doc."""
        return currency_conversion or self._conversion_from_doc(doc_instance)

    # ------------------------------------------------------------------
    # CRUD Helpers
    # ------------------------------------------------------------------

    def _handle_create(self, doc_instance, config, row, prefix, created, row_errors, currency_conversion=None):
        try:
            item = self._create_item(doc_instance, config, row, currency_conversion)
            created.append(item.id)
        except ValidationError as exc:
            row_errors[prefix] = exc.message_dict if hasattr(exc, "message_dict") else {"__all__": exc.messages}
        except (ValueError, TypeError) as exc:
            row_errors[prefix] = {"__all__": [str(exc)]}

    def _handle_update(self, item, config, row, prefix, updated, row_errors, doc_instance, currency_conversion):
        try:
            changes = self._update_item(item, config, row, doc_instance, currency_conversion)
            if changes:
                updated.append({"id": item.id, "changes": changes})
        except ValidationError as exc:
            row_errors[prefix] = exc.message_dict if hasattr(exc, "message_dict") else {"__all__": exc.messages}
        except (ValueError, TypeError) as exc:
            row_errors[prefix] = {"__all__": [str(exc)]}

    def _handle_delete(self, item, prefix, deleted, row_errors):
        try:
            item_id = item.id
            item.delete()
            deleted.append(item_id)
        except Exception as exc:
            row_errors[prefix] = {"__all__": [str(exc)]}

    # ------------------------------------------------------------------
    # Line Item Creation / Update
    # ------------------------------------------------------------------

    def _resolve_line_type(self, item, data):
        raw = data.get("line_type")
        if raw == "plain":
            return item.LineType.PLAIN
        return item.LineType.PRODUCT

    def _create_item(self, doc_instance, config, data, currency_conversion=None):
        line_model_cls = config["line_model"]
        fk_field_name = config["fk_name"]
        has_line_types = config.get("line_types")

        # Always have a pricing context: explicit if given, else from the doc.
        conversion = self._effective_conversion(doc_instance, currency_conversion)

        item = line_model_cls(**{fk_field_name: doc_instance})

        if has_line_types:
            item.line_type = self._resolve_line_type(item, data)

        self._apply_fields(item, data, config)

        is_product_line = self._is_product_line(item, config)

        if is_product_line:
            if not data.get("account_id"):
                # No-op for order docs (no account_field in their config)
                self._load_default_account(item, config, reload=True)

            if (
                not data.get("product_uom_id")
                and item.product_id
                and hasattr(item, "product_uom")
            ):
                item.product_uom = item.product.uom

            # Default the price from the product, expressed in the line's UoM
            if (
                item.product_id
                and config.get("price_field")
                and data.get("price_unit") in (None, "")
            ):
                item.price_unit = self._resolve_authoritative_price(item, config, conversion)
        elif has_line_types:
            # Safety net: guarantee both sides are set even if the payload
            # omitted debit/credit entirely rather than sending them blank.
            if item.debit is None:
                item.debit = Decimal("0.00")
            if item.credit is None:
                item.credit = Decimal("0.00")

        item.full_clean()
        item.save()
        item.refresh_from_db()

        if is_product_line:
            tax_field = config["tax_field"]
            if data.get(tax_field) or data.get("taxes"):
                self._apply_m2m(item, config, data)
            else:
                self._load_default_taxes(item, config, reload=True)

        return item

    def _update_item(self, item, config, data, doc_instance, currency_conversion=None):
        changes = {}
        product_changed = False
        reprice = False
        has_line_types = config.get("line_types")
        is_product_line = self._is_product_line(item, config)

        # Pricing context used for every price computation below. Derived
        # from the document when the caller didn't pass one, so the writer
        # prices in the same currency space as the validator.
        conversion = self._effective_conversion(doc_instance, currency_conversion)

        # 1. Capture the old UoM instance before any mutation
        old_uom = None
        if is_product_line and getattr(item, "product_uom_id", None):
            try:
                old_uom = item.product_uom
            except ObjectDoesNotExist:
                old_uom = None

        if has_line_types and "line_type" in data:
            new_line_type = self._resolve_line_type(item, data)
            if item.line_type != new_line_type:
                changes["line_type"] = {"old": item.line_type, "new": new_line_type}
                item.line_type = new_line_type

        is_product_line = self._is_product_line(item, config)

        # Reset product fields on plain lines
        if has_line_types and not is_product_line:
            if getattr(item, "product_id", None) is not None:
                changes["product_id"] = {"old": getattr(item, "product_id", None), "new": None}
                item.product_id = None
            if getattr(item, "quantity", None) is not None:
                changes["quantity"] = {"old": getattr(item, "quantity", None), "new": Decimal("0.00")}
                item.quantity = Decimal("0.00")

        for field in self.UPDATABLE_FIELDS:
            if field not in data or not hasattr(item, field):
                continue

            if has_line_types and field in self.PRODUCT_ONLY_FIELDS and not is_product_line:
                continue

            # Authoritative price is resolved AFTER the loop, once the
            # product and UoM are final. Resolving it mid-loop would see the
            # old UoM (price_unit is iterated before product_uom_id).
            #
            # NOTE: this intentionally checks the EXPLICIT `currency_conversion`
            # argument, not the derived `conversion`. Only a caller that
            # passed a conversion tuple is saying "ignore the payload price
            # and reprice from source". A derived context must not override
            # prices the user typed.
            if field == "price_unit" and currency_conversion:
                reprice = True
                continue

            old = getattr(item, field, None)

            if field == "account_id":
                new = self._coerce(field, data[field])
                if not new:
                    continue
            else:
                new = self._coerce(field, data[field])

            if old != new:
                setattr(item, field, new)
                changes[field] = {"old": old, "new": new}
                if field == "product_id":
                    product_changed = True

        # Safety net for plain journal lines
        if has_line_types and not is_product_line:
            if item.debit is None:
                item.debit = Decimal("0.00")
                changes["debit"] = {"old": None, "new": Decimal("0.00")}
            if item.credit is None:
                item.credit = Decimal("0.00")
                changes["credit"] = {"old": None, "new": Decimal("0.00")}

        # 2. UoM / price resolution for product lines
        if is_product_line:
            # Drop stale cached relations so item.product / item.product_uom
            # reflect the new FK values.
            if product_changed:
                self._clear_relation_cache(item, "product")
            if product_changed or "product_uom_id" in changes:
                self._clear_relation_cache(item, "product_uom")

            # New product: its storage UoM replaces the old one unless the
            # payload explicitly set one (the old UoM may be an incompatible
            # category for the new product).
            if product_changed and "product_uom_id" not in data:
                old_uom_id = item.product_uom_id
                result = self._load_default_uom(item, reload=True, persist=False)
                if result:
                    changes["product_uom_id"] = result
                    self._clear_relation_cache(item, "product_uom")

            uom_changed = "product_uom_id" in changes
            can_price = bool(config.get("price_field")) and getattr(item, "product_id", None)

            if can_price and (reprice or (product_changed and "price_unit" not in data)):
                # Authoritative path: product price -> doc currency -> line UoM
                old_price = item.price_unit
                new_price = self._resolve_authoritative_price(item, config, conversion)
                if old_price != new_price:
                    item.price_unit = new_price
                    changes["price_unit"] = {"old": old_price, "new": new_price}

            elif uom_changed and "price_unit" not in changes and item.price_unit is not None:
                old_price = item.price_unit
                new_price = None

                if can_price:
                    # Was the line sitting at the product's default price in the OLD uom?
                    default_old = self._resolve_authoritative_price(
                        item, config, conversion, uom=old_uom
                    )

                    # The stored price and the freshly computed default can
                    # differ by one rounding step (field precision vs.
                    # currency precision), so compare within one quantum.
                    quantum = Decimal(1).scaleb(-item._meta.get_field("price_unit").decimal_places)

                    logger.debug(
                        "uom-change reprice: old_price=%r default_old=%r conv=%r",
                        old_price, default_old, bool(conversion),
                    )

                    if (
                        default_old is not None
                        and abs(Decimal(str(old_price)) - default_old) <= quantum
                    ):
                        # Not manually overridden: reprice from source, converting once
                        new_price = self._resolve_authoritative_price(
                            item, config, conversion
                        )

                if new_price is None:
                    # Manual price: best we can do is rescale (rounding drift possible).
                    # This should only fire for genuinely manual prices; a warning
                    # here flags context/pricing bugs early.
                    logger.warning(
                        "uom-change rescale fallback used: item=%s old_price=%r old_uom=%s new_uom=%s",
                        getattr(item, "pk", None), old_price, old_uom, item.product_uom,
                    )
                    new_price = self._rescale_price_for_uom(
                        item, old_price, item.product, old_uom, item.product_uom
                    )

                if new_price != old_price:
                    item.price_unit = new_price
                    changes["price_unit"] = {"old": old_price, "new": new_price}

        if changes:
            item.full_clean()
            item.save()
            item.refresh_from_db()

        # 3. Taxes + account. M2M can only be written once the row is saved,
        # and it used to never run on update at all (this was an empty stub).
        if is_product_line:
            tax_field = config["tax_field"]

            payload_tax_values = data.get(tax_field)
            if payload_tax_values is None:
                payload_tax_values = data.get("taxes") or []

            payload_tax_ids = {
                normalizer.to_int(t)
                for t in payload_tax_values
                if normalizer.to_int(t) is not None
            }

            tax_manager = getattr(item, tax_field, None)

            current_tax_ids = (
                set(tax_manager.values_list("id", flat=True))
                if tax_manager is not None
                else set()
            )

            # The important distinction:
            #
            # False -> taxes were not touched by the user.
            # True  -> user explicitly changed the tax selection.
            taxes_touched = bool(data.get("taxes_touched"))

            if product_changed:
                if taxes_touched:
                    # User explicitly controls taxes.
                    # An empty set is intentional: remove all taxes.
                    if payload_tax_ids != current_tax_ids:
                        tax_manager.set(payload_tax_ids)
                        changes["taxes"] = {
                            "old": sorted(current_tax_ids),
                            "new": sorted(payload_tax_ids),
                        }
                else:
                    # Product changed, but user did not touch taxes.
                    # Therefore load the NEW product's default taxes.
                    tax_changes = self._load_default_taxes(
                        item,
                        config,
                        reload=True,
                    )
                    if tax_changes:
                        changes["taxes"] = tax_changes

                if not data.get("account_id"):
                    account_changes = self._load_default_account(
                        item,
                        config,
                        reload=True,
                    )
                    if account_changes:
                        changes["account_id"] = account_changes

                if not data.get("product_uom_id"):
                    uom_changes = self._load_default_uom(
                        item,
                        reload=True,
                    )
                    if uom_changes:
                        changes["product_uom_id"] = uom_changes

            elif taxes_touched and tax_manager is not None:
                # Existing product, and the user explicitly changed taxes.
                # Empty payload_tax_ids is valid and means "no taxes".
                if payload_tax_ids != current_tax_ids:
                    tax_manager.set(payload_tax_ids)
                    changes["taxes"] = {
                        "old": sorted(current_tax_ids),
                        "new": sorted(payload_tax_ids),
                    }

        return changes

    # ------------------------------------------------------------------
    # UoM / price helpers
    # ------------------------------------------------------------------

    def _uom_factor(self, uom, storage):
        """Storage-UoM units contained in 1 `uom`."""
        if uom.pk == storage.pk:
            return Decimal("1")
        if uom.category_id != storage.category_id:
            raise ValidationError(f"UoM '{uom}' is incompatible with product UoM '{storage}'.")
        factor = uom.convert_to(Decimal("1"), storage)
        if not factor:
            raise ValidationError(f"UoM '{uom}' has an invalid conversion factor to '{storage}'.")
        return Decimal(str(factor))

    def _quantize_price(self, item, value, currency=None):
        field_places = item._meta.get_field("price_unit").decimal_places
        places = getattr(currency, "decimal_places", None)
        places = field_places if places is None else min(places, field_places)
        return Decimal(str(value)).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)

    def _line_uom(self, item):
        """The line's UoM, falling back to the product's storage UoM."""
        uom = item.product_uom if getattr(item, "product_uom_id", None) else None
        return uom or item.product.uom

    def _clear_relation_cache(self, item, name):
        field = item._meta.get_field(name)
        if field.is_cached(item):
            field.delete_cached_value(item)

    def _resolve_authoritative_price(self, item, config, currency_conversion=None, uom=None):
        """Product price, expressed per the line's UoM AND converted to the doc currency.

        Delegates to core.services.pricing_service.authoritative_price so the
        writer (this method) and the validator (DocumentValidationService)
        can never drift — they share one computation.

        Callers should pass the effective conversion tuple (explicit or
        derived via _effective_conversion). If None is passed here, no
        currency conversion is applied.
        """
        product = getattr(item, "product", None)
        price_field = config.get("price_field")
        if not product or not price_field:
            return getattr(item, "price_unit", None)

        # Resolve the conversion tuple into the kwargs the helper expects.
        company = doc_currency = date = None
        if currency_conversion:
            company, doc_currency, date = currency_conversion

        # Pass the line's UoM explicitly, honouring the `uom=` override used
        # by the "was it at the default price?" check in _update_item.
        line_uom = uom if uom is not None else self._line_uom(item)

        return authoritative_price(
            product,
            price_field=price_field,
            line_uom=line_uom,
            doc_currency=doc_currency,
            company=company,
            date=date,
            decimal_places=item._meta.get_field("price_unit").decimal_places,
        )

    def _rescale_price_for_uom(self, item, price, product, old_uom, new_uom):
        """Scale a per-unit price from old_uom to new_uom."""
        if price is None or not product:
            return price
        storage = getattr(product, "uom", None)
        if not storage:
            return price

        old_uom = old_uom or storage
        new_uom = new_uom or storage
        if old_uom.pk == new_uom.pk:
            return price

        scaled = (Decimal(str(price))
                  * self._uom_factor(new_uom, storage)
                  / self._uom_factor(old_uom, storage))
        return self._quantize_price(item, scaled)

    # ------------------------------------------------------------------
    # Defaults
    # ------------------------------------------------------------------

    def _load_default_taxes(self, item, config, reload=False):
        """
        Resolve the product's default taxes and set them onto the line.

        On reload=True (product just changed), the previous product's
        taxes no longer apply. If the new product has taxes, they replace
        whatever was there. If the new product has none, the old ones are
        explicitly cleared rather than left stuck.
        """
        tax_field = config["tax_field"]
        if not item or not item.pk or not hasattr(item, tax_field):
            return {}

        tax_manager = getattr(item, tax_field)
        old_tax_ids = set(tax_manager.values_list("id", flat=True))

        try:
            source_field = getattr(item.product, config["tax_source_field"])
            product_taxes = list(source_field.filter(type_tax_use=config["tax_use"]))
        except AttributeError:
            product_taxes = []

        if not product_taxes:
            if reload and old_tax_ids:
                tax_manager.set([])
                return {"old": sorted(old_tax_ids), "new": []}
            return {}

        if not reload and old_tax_ids:
            return {}

        new_tax_ids = {t.pk for t in product_taxes}
        if old_tax_ids == new_tax_ids:
            return {}

        tax_manager.set(product_taxes)
        return {"old": sorted(old_tax_ids), "new": sorted(new_tax_ids)}

    def _load_default_account(self, item, config, reload=False):
        """
        Resolve and set item.account_id from the product's dedicated account
        field, falling back to the product's category chain (via the
        inheritance-aware get_*_account() methods) when the product itself
        doesn't override it.

        On create (item.pk is None): sets the attribute only: the caller's
        full_clean()/save() persists it.
        On update (item.pk is set): saves immediately, same as taxes' .set().
        """
        account_field = config.get("account_field")
        if not account_field:
            # Doc type has no accounting concept (sales_order / purchase_order).
            return {}

        if not item or not hasattr(item, "account_id"):
            return {}

        product = getattr(item, "product", None)
        if not product:
            return {}

        new_account = getattr(product, account_field, None)

        if not new_account:
            fallback_method = config.get("fallback_account_method")
            category = getattr(product, "category", None)
            if fallback_method and category:
                new_account = getattr(category, fallback_method, lambda: None)()

        if not new_account:
            return {}

        old_account_id = item.account_id
        new_account_id = new_account.pk if hasattr(new_account, "pk") else new_account

        # Same policy as taxes: only overwrite an existing value on reload (product change).
        if not reload and old_account_id:
            return {}

        if old_account_id == new_account_id:
            return {}

        item.account_id = new_account_id

        if item.pk:
            item.save(update_fields=["account"])

        return {"old": old_account_id, "new": new_account_id}

    def _load_default_uom(self, item, reload=False, persist=True):
        """
        Resolve and set item.product_uom from the product's own storage UoM.
        Same reload policy as taxes/account: only overwrite an existing value
        when reload=True (i.e. product just changed).

        persist=False sets the attribute only, leaving the save to the caller
        (used by _update_item so validation runs before anything is written).
        """
        if not item or not hasattr(item, "product_uom_id"):
            return {}

        product = getattr(item, "product", None)
        if not product or not product.uom_id:
            return {}

        old_uom_id = item.product_uom_id
        new_uom_id = product.uom_id

        if not reload and old_uom_id:
            return {}

        if old_uom_id == new_uom_id:
            return {}

        item.product_uom_id = new_uom_id

        if persist and item.pk:
            item.save(update_fields=["product_uom"])

        return {"old": old_uom_id, "new": new_uom_id}

    def _apply_fields(self, item, data, config):

        is_product_line = self._is_product_line(item, config)
        has_line_types = config.get("line_types")

        for field in self.UPDATABLE_FIELDS:
            if field not in data:
                continue
            # Fields the line model doesn't have (e.g. debit/credit/memo on
            # order lines) are ignored instead of being set as stray attributes.
            if not hasattr(item, field):
                continue
            if has_line_types and field in self.PRODUCT_ONLY_FIELDS and not is_product_line:
                continue
            setattr(item, field, self._coerce(field, data[field]))

    def _apply_m2m(self, item, config, data):
        tax_field = config["tax_field"]
        tax_manager = getattr(item, tax_field, None)
        if tax_manager is None:
            return {}

        raw = data.get(tax_field) if tax_field in data else data.get("taxes")
        if raw is None or raw == "":
            raw = []
        elif not isinstance(raw, (list, tuple, set)):
            raw = [raw]
        # Accept ids, numeric strings, or objects/dicts carrying an id
        new_tax_ids = set()
        for t in raw:
            if isinstance(t, dict):
                t = t.get("id")
            t = getattr(t, "pk", t)
            if t not in (None, ""):
                new_tax_ids.add(int(t))
        old_tax_ids = set(tax_manager.values_list("id", flat=True))

        if new_tax_ids == old_tax_ids:
            return {}

        tax_manager.set(new_tax_ids)
        return {"old": sorted(old_tax_ids), "new": sorted(new_tax_ids)}

    def _coerce(self, field, value):
        if value is None or value == "":
            if field in self.ZERO_DEFAULT_FIELDS:
                return Decimal("0.00")
            return None

        cast = self.UPDATABLE_FIELDS.get(field)
        if cast is None:
            return value

        try:
            if cast is Decimal:
                return Decimal(str(value))
            return cast(value)
        except (ValueError, TypeError):
            logger.warning("Coercion failed for field=%s value=%r cast=%s", field, value, cast)
            return value