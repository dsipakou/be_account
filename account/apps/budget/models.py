import uuid

from django.db import models

from budget.constants import BudgetDuplicateType


# Repetitive budget series
class BudgetSeries(models.Model):
    class Frequency(models.TextChoices):
        WEEKLY = "WEEKLY"
        MONTHLY = "MONTHLY"

    uuid = models.UUIDField(unique=True, default=uuid.uuid4, editable=False)

    user = models.ForeignKey("users.User", on_delete=models.DO_NOTHING, to_field="uuid")
    workspace = models.ForeignKey(
        "workspaces.Workspace", on_delete=models.DO_NOTHING, to_field="uuid"
    )

    title = models.CharField(max_length=60)
    category = models.ForeignKey(
        "categories.Category", on_delete=models.CASCADE, to_field="uuid"
    )
    currency = models.ForeignKey(
        "currencies.Currency", on_delete=models.DO_NOTHING, to_field="uuid"
    )
    amount = models.FloatField()

    start_date = models.DateField()

    frequency = models.CharField(max_length=10, choices=Frequency.choices)
    interval = models.PositiveIntegerField(default=1)  # each N weeks/months

    count = models.PositiveIntegerField(null=True, blank=True)
    until = models.DateField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)


# Exclusions or overrides for specific dates in a BudgetSeries
class BudgetSeriesException(models.Model):
    series = models.ForeignKey(
        BudgetSeries,
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
                name="unique_series_exception_date",
            )
        ]


class Budget(models.Model):
    RECURRENT_CHOICES = (
        (BudgetDuplicateType.WEEKLY.value, "Weekly"),
        (BudgetDuplicateType.MONTHLY.value, "Monthly"),
    )

    class Kind(models.TextChoices):
        EXPENSE = "EXPENSE"
        TRANSFER = "TRANSFER"

    uuid = models.UUIDField(unique=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey("users.User", on_delete=models.DO_NOTHING, to_field="uuid")
    workspace = models.ForeignKey(
        "workspaces.Workspace", to_field="uuid", on_delete=models.DO_NOTHING
    )
    kind = models.CharField(
        max_length=20,
        choices=Kind.choices,
        default=Kind.EXPENSE,
    )
    category = models.ForeignKey(
        "categories.Category",
        on_delete=models.CASCADE,
        to_field="uuid",
        null=True,
        blank=True,
    )
    from_account = models.ForeignKey(
        "accounts.Account",
        null=True,
        blank=True,
        related_name="budgets_from_account",
        on_delete=models.DO_NOTHING,
        to_field="uuid",
    )

    to_account = models.ForeignKey(
        "accounts.Account",
        null=True,
        blank=True,
        related_name="budgets_to_account",
        on_delete=models.DO_NOTHING,
        to_field="uuid",
    )
    currency = models.ForeignKey(
        "currencies.Currency", on_delete=models.DO_NOTHING, to_field="uuid"
    )
    title = models.CharField(max_length=60)
    amount = models.FloatField()
    budget_date = models.DateField(blank=True, null=True)
    description = models.TextField(null=True, blank=True)
    is_completed = models.BooleanField(default=False)
    # NOTE: This field is stored for backward compatibility and manual duplication.
    # For OUTPUT, use the `recurrent_type` property which calculates value from `series` relationship.
    # Input: Field accepts values and is stored to support manual budget duplication
    # Output: Serializers override this field with `recurrent_type` property value
    recurrent = models.CharField(
        null=True, blank=True, max_length=20, choices=RECURRENT_CHOICES
    )
    series = models.ForeignKey(
        BudgetSeries,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="budgets",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)

    def __repr__(self) -> str:
        return f"({self.title} / {self.budget_date} / {self.currency.code})"

    @property
    def recurrent_type(self) -> str | None:
        """Calculate recurrent type based on series relationship

        Returns:
        - "weekly" if budget has series with WEEKLY frequency
        - "monthly" if budget has series with MONTHLY frequency
        - None if no series (non-recurrent budget)
        """
        if self.series_id:  # Use series_id to avoid extra query
            # Map BudgetSeries.Frequency to BudgetDuplicateType values
            frequency_map = {
                "WEEKLY": BudgetDuplicateType.WEEKLY.value,
                "MONTHLY": BudgetDuplicateType.MONTHLY.value,
            }
            # Access series.frequency (will use cached value if select_related)
            return frequency_map.get(self.series.frequency)

        # No series = non-recurrent (return None instead of "occasional")
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
                name="unique_series_budget_date",
            )
        ]


class BudgetMulticurrency(models.Model):
    uuid = models.UUIDField(unique=True, default=uuid.uuid4, editable=False)
    budget = models.OneToOneField(
        Budget, to_field="uuid", related_name="multicurrency", on_delete=models.CASCADE
    )
    amount_map = models.JSONField(default=dict)
