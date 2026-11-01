from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from inventory.models import ProductPrice

class Command(BaseCommand):
    help = "Updates prices based on ProductPrice table"

    def handle(self, *args, **options):
        today = timezone.now().date()

        prices_to_apply = (
            ProductPrice.objects
            .filter(start_date__lte=today)
            .select_related("product")
            .order_by("product_id", "-start_date")
        )

        updated = 0
        processed_products = set()

        with transaction.atomic():
            for price in prices_to_apply:
                product = price.product

                if product.id in processed_products:
                    continue

                product.default_price = price.price
                product.product_cost = price.product_cost
                product.save(update_fields=["default_price", "product_cost"])

                processed_products.add(product.id)
                updated += 1

        self.stdout.write(
            self.style.SUCCESS(f"{updated} products successfully updated")
        )