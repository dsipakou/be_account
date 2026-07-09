import datetime
import textwrap
import uuid

from django.db import connection, models
from django.db.models import QuerySet
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast, Trunc
from django.db.models.functions.datetime import TruncMonth

from categories import constants as category_constants
from currencies.models import Currency
from rates.models import Rate
from transactions.utils import dictfetchall
from users.models import User


class Transaction(models.Model):
    uuid = models.UUIDField(unique=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey("users.User", on_delete=models.DO_NOTHING, to_field="uuid")
    category = models.ForeignKey(
        "categories.Category", on_delete=models.DO_NOTHING, to_field="uuid"
    )
    budget = models.ForeignKey(
        "budget.Budget", on_delete=models.DO_NOTHING, to_field="uuid", null=True
    )
    currency = models.ForeignKey(Currency, on_delete=models.DO_NOTHING, to_field="uuid")
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        to_field="uuid",
        on_delete=models.DO_NOTHING,
    )
    amount = models.FloatField()
    account = models.ForeignKey(
        "accounts.Account", on_delete=models.DO_NOTHING, to_field="uuid"
    )
    description = models.CharField(max_length=255, blank=True)
    transaction_date = models.DateField()
    source = models.CharField(max_length=100, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)

    def __repr__(self) -> str:
        return f"({self.budget.title} / {self.transaction_date} / {self.category.name} / {self.amount} {self.currency.code})"

    @property
    def transaction_type(self):
        parent_category = self.category.parent
        if parent_category:
            return parent_category.type
        return category_constants.EXPENSE

    @property
    def multicurrency_map(self):
        return (
            self.multicurrency.amount_map
            if hasattr(self, "multicurrency") and self.multicurrency
            else {}
        )

    @property
    def spent_in_base_currency(self):
        if self.currency.is_base:
            return self.amount
        rate = self.to_date_rates.get(
            currency=self.currency, rate_date=self.transaction_date
        )
        return self.amount * rate.rate

    @property
    def to_date_rates(self):
        return Rate.objects.filter(rate_date=self.transaction_date).select_related(
            "currency"
        )

    @classmethod
    def grouped_by_month(cls, date_from, date_to, currency_code, workspace):
        raw_sql = textwrap.dedent(
            """
            SELECT
                t1.month,
                t1.day,
                CASE
                    WHEN c1.is_base THEN t1.amount
                    WHEN r1.rate is NULL THEN 0
                    ELSE t1.amount / r1.rate
                END as grouped_amount
            FROM (
                SELECT
                    CONCAT(EXTRACT(YEAR FROM t.transaction_date), '-', LPAD(EXTRACT(MONTH FROM t.transaction_date)::text, 2, '0')) AS month,
                    EXTRACT(DAY FROM t.transaction_date) AS day,
                    SUM(
                        CASE
                            WHEN t.currency_id is NULL THEN t.amount
                            WHEN c.is_base THEN t.amount
                            ELSE t.amount * r.rate
                        END
                    ) as amount,
                    t.transaction_date
                FROM transactions_transaction t
                    LEFT JOIN rates_rate r ON r.currency_id = t.currency_id AND r.rate_date = t.transaction_date
                    LEFT JOIN currencies_currency c ON c.uuid = t.currency_id
                    LEFT JOIN categories_category cc on cc.uuid = t.category_id
                WHERE t.workspace_id = %s
                GROUP BY t.transaction_date, cc.type
                HAVING t.transaction_date >= %s AND t.transaction_date <= %s AND cc.type = %s
                ORDER BY t.transaction_date
            ) as t1
                INNER JOIN currencies_currency c1 ON c1.code = %s
                LEFT JOIN rates_rate r1 ON r1.currency_id = c1.uuid AND r1.rate_date = t1.transaction_date
            ORDER BY r1.rate_date;
        """
        )
        with connection.cursor() as cursor:
            cursor.execute(
                raw_sql,
                [
                    str(workspace),
                    date_from,
                    date_to,
                    category_constants.EXPENSE,
                    currency_code,
                ],
            )
            grouped_transactions = dictfetchall(cursor)

        return grouped_transactions

    @classmethod
    def grouped_by_month_and_category(
        cls,
        qs: QuerySet,
        date_from: str,
        date_to: str,
        currency_code: str,
        till_day: int | None,
    ):
        filtered_qs = (
            qs.select_related("category", "category__parent", "multicurrency")
            .values("category__name", "category__parent", "category__parent__name")
            .annotate(
                parent_sum=models.Sum(
                    Cast(
                        KeyTextTransform(currency_code, "multicurrency__amount_map"),
                        models.FloatField(),
                    )
                )
            )
            .annotate(
                year_month=Trunc(
                    "transaction_date", "month", output_field=models.DateField()
                )
            )
            .annotate(transaction_count=models.Count("pk"))
            .filter(transaction_date__range=(date_from, date_to))
        )

        if till_day is not None:
            filtered_qs = filtered_qs.filter(
                transaction_date__lte=TruncMonth("transaction_date")
                + models.Value(datetime.timedelta(days=int(till_day)))
                - models.Value(datetime.timedelta(seconds=1))
            )

        return filtered_qs

    @classmethod
    def income_grouped_by_income(cls, date_from: str, date_to: str):
        raw_sql = textwrap.dedent(
            """
            SELECT
                CONCAT(EXTRACT(YEAR FROM tt.transaction_date), '-', EXTRACT(MONTH FROM tt.transaction_date)) AS grouped_month,
                SUM(
                    CASE
                        WHEN t.currency_id is NULL THEN t.amount
                        WHEN c.is_base THEN t.amount
                        ELSE t.amount * r.rate
                    END
                ) as amount
            FROM transactions_transaction tt
            INNER JOIN categories_category cc on cc.uuid = tt.category_id
            INNER JOIN rates_rate rr ON rr.currency_id = tt.currency_id AND rr.rate_date = tt.transaction_date
            GROUP BY cc.type, grouped_month
            HAVING t.transaction_date >= %s AND t.transaction_date <= %s AND cc.type='%s';
        """
        )
        with connection.cursor() as cursor:
            cursor.execute(raw_sql, [date_from, date_to, category_constants.INCOME])
            grouped_transactions = dictfetchall(cursor)

        return grouped_transactions


class Transfer(models.Model):
    uuid = models.UUIDField(unique=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey("users.User", on_delete=models.DO_NOTHING, to_field="uuid")
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        to_field="uuid",
        on_delete=models.DO_NOTHING,
    )
    from_account = models.ForeignKey(
        "accounts.Account",
        related_name="outgoing_transfers",
        on_delete=models.DO_NOTHING,
        to_field="uuid",
    )
    to_account = models.ForeignKey(
        "accounts.Account",
        related_name="incoming_transfers",
        on_delete=models.DO_NOTHING,
        to_field="uuid",
    )
    currency = models.ForeignKey(Currency, on_delete=models.DO_NOTHING, to_field="uuid")
    budget = models.ForeignKey(
        "budget.Budget",
        null=True,
        blank=True,
        on_delete=models.DO_NOTHING,
        to_field="uuid",
    )
    amount = models.FloatField()
    description = models.CharField(max_length=255, blank=True)
    transfer_date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)

    @property
    def multicurrency_map(self):
        return (
            self.multicurrency.amount_map
            if hasattr(self, "multicurrency") and self.multicurrency
            else {}
        )


class TransactionMulticurrency(models.Model):
    uuid = models.UUIDField(unique=True, default=uuid.uuid4, editable=False)
    transaction = models.OneToOneField(
        Transaction,
        related_name="multicurrency",
        to_field="uuid",
        on_delete=models.CASCADE,
    )
    amount_map = models.JSONField(default=dict)


class TransferMulticurrency(models.Model):
    uuid = models.UUIDField(unique=True, default=uuid.uuid4, editable=False)
    transfer = models.OneToOneField(
        Transfer,
        related_name="multicurrency",
        to_field="uuid",
        on_delete=models.CASCADE,
    )
    amount_map = models.JSONField(default=dict)


class LastViewed(models.Model):
    uuid = models.UUIDField(unique=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        User,
        to_field="uuid",
        null=True,
        blank=True,
        unique=True,
        on_delete=models.DO_NOTHING,
    )
    transaction = models.ForeignKey(
        Transaction, to_field="uuid", on_delete=models.DO_NOTHING
    )
