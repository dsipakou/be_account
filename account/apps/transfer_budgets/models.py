import uuid

from django.db import models

from transfer_budgets.constants import TransferBudgetDuplicateType


class TransferBudgetSeries(models.Model):
    class Frequency(models.TextChoices):
        WEEKLY = "WEEKLY"
        MONTHLY = "MONTHLY"

    uuid = models.UUIDField(unique=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey("users.User", on_delete=models.DO_NOTHING, to_field="uuid")
    workspace = models.ForeignKey(
        "workspaces.Workspace", on_delete=models.DO_NOTHING, to_field="uuid"
    )
    title = models.CharField(max_length=60)
    currency = models.ForeignKey(
        "currencies.Currency", on_delete=models.DO_NOTHING, to_field="uuid"
    )
    amount = models.FloatField()
    from_account = models.ForeignKey(
        "accounts.Account",
        null=True,
        blank=True,
        related_name="transfer_budget_series_from_account",
        on_delete=models.DO_NOTHING,
        to_field="uuid",
    )
    to_account = models.ForeignKey(
        "accounts.Account",
        null=True,
        blank=True,
        related_name="transfer_budget_series_to_account",
        on_delete=models.DO_NOTHING,
        to_field="uuid",
    )
    start_date = models.DateField()
    frequency = models.CharField(max_length=10, choices=Frequency.choices)
    interval = models.PositiveIntegerField(default=1)
    count = models.PositiveIntegerField(null=True, blank=True)
    until = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class TransferBudgetSeriesException(models.Model):
    series = models.ForeignKey(
        TransferBudgetSeries,
        on_delete=models.CASCADE,
        related_name="exceptions",
    )
    date = models.DateField()
    is_skipped = models.BooleanField(default=False)
    override_amount = models.FloatField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["series", "date"],
                name="unique_transfer_budget_series_exception_date",
            )
        ]


class TransferBudget(models.Model):
    RECURRENT_CHOICES = (
        (TransferBudgetDuplicateType.WEEKLY.value, "Weekly"),
        (TransferBudgetDuplicateType.MONTHLY.value, "Monthly"),
    )

    uuid = models.UUIDField(unique=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey("users.User", on_delete=models.DO_NOTHING, to_field="uuid")
    workspace = models.ForeignKey(
        "workspaces.Workspace", to_field="uuid", on_delete=models.DO_NOTHING
    )
    currency = models.ForeignKey(
        "currencies.Currency", on_delete=models.DO_NOTHING, to_field="uuid"
    )
    from_account = models.ForeignKey(
        "accounts.Account",
        null=True,
        blank=True,
        related_name="transfer_budgets_from_account",
        on_delete=models.DO_NOTHING,
        to_field="uuid",
    )
    to_account = models.ForeignKey(
        "accounts.Account",
        null=True,
        blank=True,
        related_name="transfer_budgets_to_account",
        on_delete=models.DO_NOTHING,
        to_field="uuid",
    )
    title = models.CharField(max_length=60)
    amount = models.FloatField()
    budget_date = models.DateField(blank=True, null=True)
    description = models.TextField(null=True, blank=True)
    is_completed = models.BooleanField(default=False)
    recurrent = models.CharField(
        null=True, blank=True, max_length=20, choices=RECURRENT_CHOICES
    )
    series = models.ForeignKey(
        TransferBudgetSeries,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="transfer_budgets",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)

    @property
    def recurrent_type(self) -> str | None:
        if self.series_id:
            frequency_map = {
                "WEEKLY": TransferBudgetDuplicateType.WEEKLY.value,
                "MONTHLY": TransferBudgetDuplicateType.MONTHLY.value,
            }
            return frequency_map.get(self.series.frequency)
        return None

    @property
    def multicurrency_map(self):
        return (
            self.multicurrency.amount_map
            if hasattr(self, "multicurrency") and self.multicurrency
            else {}
        )

    class Meta:
        unique_together = ["title", "budget_date", "user"]
        constraints = [
            models.UniqueConstraint(
                fields=["series", "budget_date"],
                name="unique_transfer_budget_series_budget_date",
            )
        ]


class TransferBudgetMulticurrency(models.Model):
    uuid = models.UUIDField(unique=True, default=uuid.uuid4, editable=False)
    transfer_budget = models.OneToOneField(
        TransferBudget,
        to_field="uuid",
        related_name="multicurrency",
        on_delete=models.CASCADE,
    )
    amount_map = models.JSONField(default=dict)
