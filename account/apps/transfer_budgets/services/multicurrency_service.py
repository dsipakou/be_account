from uuid import UUID

from rates.models import Rate
from rates.utils import generate_amount_map
from transfer_budgets.models import TransferBudget, TransferBudgetMulticurrency
from workspaces.models import Workspace


class TransferBudgetMulticurrencyService:
    @classmethod
    def create_transfer_budget_multicurrency_amount(
        cls, uuids: list[UUID], workspace: Workspace
    ) -> None:
        transfer_budgets = TransferBudget.objects.select_related("currency").filter(
            uuid__in=uuids, workspace=workspace
        )
        dates = transfer_budgets.values_list("budget_date", flat=True).distinct()
        rates_on_date = Rate.objects.filter(rate_date__in=dates, workspace=workspace)
        for transfer_budget in transfer_budgets:
            amount_mapping = generate_amount_map(
                transfer_budget, rates_on_date, workspace
            )
            TransferBudgetMulticurrency.objects.update_or_create(
                transfer_budget=transfer_budget,
                defaults={"amount_map": amount_mapping},
            )
