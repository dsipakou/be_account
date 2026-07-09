import datetime

from dateutil.relativedelta import relativedelta
from dateutil.rrule import MONTHLY, rrule
from django.db.models import FloatField, Prefetch, QuerySet, Sum, Value
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast, Coalesce, TruncMonth

from budget.entities import MonthUsageSum
from transactions.models import Transfer
from transfer_budgets.models import TransferBudget
from transfer_budgets.services.series_service import TransferBudgetSeriesService
from users.models import User
from workspaces.models import Workspace


class TransferBudgetReportingService:
    @classmethod
    def _empty_currency_map(cls, available_currencies: list[dict]) -> dict[str, float]:
        return {currency["code"]: 0 for currency in available_currencies}

    @classmethod
    def _sum_transfer_amounts(
        cls, transfers: list[Transfer], available_currencies: list[dict]
    ) -> dict[str, float]:
        totals = cls._empty_currency_map(available_currencies)
        for transfer in transfers:
            for currency in available_currencies:
                code = currency["code"]
                totals[code] = round(
                    totals[code] + transfer.multicurrency_map.get(code, 0),
                    2,
                )
        return totals

    @classmethod
    def _serialize_transfer(cls, transfer: Transfer) -> dict:
        return {
            "uuid": transfer.uuid,
            "currency": transfer.currency.uuid,
            "currency_code": transfer.currency.code,
            "amount": transfer.amount,
            "spent_in_currencies": transfer.multicurrency_map.copy(),
            "from_account": transfer.from_account.uuid,
            "to_account": transfer.to_account.uuid,
            "transfer_date": transfer.transfer_date,
        }

    @classmethod
    def _serialize_transfer_budget(
        cls, transfer_budget: TransferBudget, available_currencies: list[dict]
    ) -> dict:
        transfers = list(getattr(transfer_budget, "transfers", []))
        spent_in_currencies = cls._sum_transfer_amounts(transfers, available_currencies)
        planned_in_currencies = {
            currency["code"]: transfer_budget.multicurrency_map.get(currency["code"], 0)
            for currency in available_currencies
        }

        return {
            "uuid": transfer_budget.uuid,
            "user": transfer_budget.user.uuid,
            "currency": transfer_budget.currency.uuid,
            "from_account": transfer_budget.from_account.uuid
            if transfer_budget.from_account
            else None,
            "to_account": transfer_budget.to_account.uuid
            if transfer_budget.to_account
            else None,
            "title": transfer_budget.title,
            "budget_date": transfer_budget.budget_date,
            "description": transfer_budget.description,
            "is_completed": transfer_budget.is_completed,
            "recurrent": transfer_budget.recurrent_type,
            "planned": transfer_budget.amount,
            "spent": sum(spent_in_currencies.values())
            if len(spent_in_currencies) == 1
            else 0,
            "planned_in_currencies": planned_in_currencies,
            "spent_in_currencies": spent_in_currencies,
            "transfers": [cls._serialize_transfer(transfer) for transfer in transfers],
            "created_at": transfer_budget.created_at,
            "modified_at": transfer_budget.modified_at,
        }

    @classmethod
    def generate_usage_report(
        cls,
        *,
        workspace: Workspace,
        transfer_budgets_qs: QuerySet,
        currencies_qs: QuerySet,
        date_from: str | datetime.date,
        date_to: str | datetime.date,
        user: str | None,
    ) -> list[dict]:
        if isinstance(date_from, str):
            date_from = datetime.datetime.strptime(date_from, "%Y-%m-%d").date()
        if isinstance(date_to, str):
            date_to = datetime.datetime.strptime(date_to, "%Y-%m-%d").date()

        TransferBudgetSeriesService.materialize_transfer_budgets(workspace, date_to)

        transfer_budgets = transfer_budgets_qs.filter(
            budget_date__gte=date_from,
            budget_date__lte=date_to,
        )
        if user:
            transfer_budgets = transfer_budgets.filter(user__uuid=user)

        transfer_qs = Transfer.objects.filter(
            transfer_date__gte=date_from,
            transfer_date__lte=date_to,
        ).select_related(
            "currency",
            "from_account",
            "to_account",
            "multicurrency",
        )

        transfer_budgets = transfer_budgets.select_related(
            "currency",
            "from_account",
            "to_account",
            "multicurrency",
            "series",
            "user",
        ).prefetch_related(
            Prefetch("transfer_set", queryset=transfer_qs, to_attr="transfers")
        )

        available_currencies = list(currencies_qs.values("code", "is_base"))
        return [
            cls._serialize_transfer_budget(transfer_budget, available_currencies)
            for transfer_budget in transfer_budgets.order_by("budget_date")
        ]

    @classmethod
    def generate_weekly_report(
        cls,
        *,
        workspace: Workspace,
        transfer_budgets_qs: QuerySet,
        currencies_qs: QuerySet,
        date_from: str | datetime.date,
        date_to: str | datetime.date,
        user: str | None,
    ) -> list[dict]:
        return cls.generate_usage_report(
            workspace=workspace,
            transfer_budgets_qs=transfer_budgets_qs,
            currencies_qs=currencies_qs,
            date_from=date_from,
            date_to=date_to,
            user=user,
        )

    @classmethod
    def get_historical_usage(
        cls,
        *,
        transfers: QuerySet,
        month: datetime.date,
        transfer_budget_uuid: str,
        user: User,
        filter_by_user: str | None = None,
    ) -> list[MonthUsageSum]:
        currency_code = user.currency_code()
        if not currency_code:
            return []

        selected_month_first_day = month.replace(day=1)
        six_month_earlier = month - relativedelta(months=6)

        transfers = transfers.filter(
            transfer_budget=transfer_budget_uuid,
            transfer_date__lt=selected_month_first_day,
            transfer_date__gte=six_month_earlier,
        ).prefetch_related("multicurrency")

        if filter_by_user:
            transfers = transfers.filter(user=filter_by_user)

        grouped_transfers = transfers.annotate(
            current_currency_amount=Coalesce(
                Cast(
                    KeyTextTransform(currency_code, "multicurrency__amount_map"),
                    FloatField(),
                ),
                Value(0, output_field=FloatField()),
            )
        )
        grouped_transfers = grouped_transfers.annotate(
            month=TruncMonth("transfer_date")
        ).values("month")
        grouped_transfers = grouped_transfers.annotate(
            amount=Sum("current_currency_amount")
        ).order_by("month")
        all_months = rrule(
            MONTHLY,
            dtstart=six_month_earlier,
            until=selected_month_first_day - relativedelta(months=1),
        )

        clean_transfers: list[MonthUsageSum] = []
        for current_month in all_months:
            if transfer := grouped_transfers.filter(month=current_month).first():
                amount = transfer.get("amount", 0)
            else:
                amount = 0
            clean_transfers.append(
                MonthUsageSum(
                    month=current_month.date(),
                    amount=amount,
                )
            )
        return clean_transfers
