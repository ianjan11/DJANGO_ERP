from django.db import models


class UserProfile(models.Model):
    """Default warehouse/location/currency/terms for a salesperson."""
    user             = models.OneToOneField(
                           "users.User", on_delete=models.CASCADE,
                           related_name='profile')
    default_location = models.ForeignKey(
                           'inventory.Warehouse', null=True, blank=True,
                           on_delete=models.SET_NULL)
    default_currency = models.ForeignKey(
                           "core.Currency", null=True, blank=True,
                           on_delete=models.SET_NULL)
    default_payment_term = models.ForeignKey(
                           "accounting.PaymentTerm", null=True, blank=True,
                           on_delete=models.SET_NULL)

    def __str__(self):
        return f"{self.user.get_full_name()} — user profile"
