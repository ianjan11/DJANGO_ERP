from django.db import models, transaction
from django.utils import timezone
from django.db.models import F

from core.models import Company
class SequenceRegistry(models.Model):
    SEQUENCE_TYPES = (
        ('PURCHASE_ORDER', 'Purchase Sequence'),
        ("SALES_ORDER", "Sales Sequence"),
        ("INVOICE", "Invoice Sequence"),
        ("ACCOUNT_MOVE", "Account Movement"),
        ('DELIVERY', 'Delivery Sequence'),
        ('RETURN', 'Return Sequence'),
        ('CREDIT_NOTE', 'Credit Note Sequence'),
        ('INCOMING_SHIPMENT', 'Incoming Shipment Sequence'),
    )

    doc_type = models.CharField(max_length=20, choices=SEQUENCE_TYPES)
    date = models.DateField(default=timezone.now)
    last_value = models.PositiveIntegerField(default=0)
    company = models.ForeignKey('core.Company', on_delete=models.CASCADE, null=True, blank=True)


    class Meta:
        unique_together = ('doc_type', 'date', 'company')

    @classmethod
    def get_next_sequence(cls, doc_type, company):
        today = timezone.now().date()

        with transaction.atomic():
            updated = cls.objects.filter(
                doc_type=doc_type, date=today, company=company
            ).update(last_value=F('last_value') + 1)

            if not updated:
                registry, created = cls.objects.get_or_create(
                    company=company,doc_type=doc_type, date=today, defaults={'last_value': 1}
                )
                if not created:
                    cls.objects.filter(pk=registry.pk).update(last_value=F('last_value') + 1)
                    registry.refresh_from_db(fields=['last_value'])
                return registry.last_value

            return cls.objects.get(doc_type=doc_type,company=company ,date=today).last_value
