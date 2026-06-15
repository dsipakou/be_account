import datetime

from django.db.models import Prefetch, QuerySet

from transactions.models import Transfer
from transfer_budgets.models import TransferBudget
from transfer_budgets.services.series_service import TransferBudgetSeriesService
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
