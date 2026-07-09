import datetime
import warnings

from django.db.models import QuerySet

from budget.constants import BudgetDuplicateType
from budget.entities import (
    BudgetGroupedItem,
    BudgetItem,
    MonthUsageSum,
)
from budget.models import BudgetSeries
from budget.services.duplication_service import (
    BudgetDuplicationService,
)
from budget.services.entity_transformer import BudgetEntityTransformer
from budget.services.multicurrency_service import BudgetMulticurrencyService
from budget.services.reporting_service import BudgetReportingService
from budget.services.series_service import BudgetSeriesService
from users.models import User
from workspaces.models import Workspace


class BudgetService:
    """Facade service for budget operations.

    This service provides backward-compatible access to specialized budget services.
    All methods in this class are deprecated and delegate to the specialized services:

    - BudgetSeriesService: Budget series materialization and occurrence calculation
    - BudgetMulticurrencyService: Multi-currency conversion operations
    - BudgetReportingService: Monthly/weekly reports and historical analysis
    - BudgetEntityTransformer: Entity transformation for API responses
    - BudgetDuplicationService: Legacy budget duplication (use BudgetSeries instead)

    New code should use the specialized services directly instead of this facade.
    This facade will be removed in a future release after a deprecation period.

    Migration guide:
    - BudgetService.materialize_budgets() → BudgetSeriesService.materialize_budgets()
    - BudgetService.load_budget_v2() → BudgetReportingService.generate_monthly_report()
    - BudgetService.load_weekly_budget() → BudgetReportingService.generate_weekly_report()
    - BudgetService.get_last_months_usage() → BudgetReportingService.get_historical_usage()
    - BudgetService.make_budgets() → BudgetEntityTransformer.transform_to_budget_items()
    - BudgetService.make_grouped_budgets() → BudgetEntityTransformer.group_budgets()
    - BudgetService.make_transactions() → BudgetEntityTransformer.transform_transactions()
    - BudgetService.get_duplicate_budget_candidates() → BudgetDuplicationService.get_duplicate_candidates()
    - BudgetService.duplicate_budget() → BudgetDuplicationService.duplicate_budgets()
    """

    @classmethod
    def _calculate_occurrences(
        cls, series: BudgetSeries, to_date: datetime.date | datetime.datetime
    ) -> list[datetime.date]:
        """Calculate occurrence dates for a budget series.

        DEPRECATED: Use BudgetSeriesService.calculate_occurrences instead.
        This wrapper will be removed in a future release.
        """
        warnings.warn(
            "BudgetService._calculate_occurrences is deprecated. "
            "Use BudgetSeriesService.calculate_occurrences instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return BudgetSeriesService.calculate_occurrences(series, to_date)

    @classmethod
    def _calculate_smart_amount(
        cls, series: BudgetSeries, use_smart_amount: bool = False
    ) -> float:
        """Calculate smart budget amount based on historical spending.

        DEPRECATED: Use BudgetSeriesService.calculate_smart_amount instead.
        This wrapper will be removed in a future release.
        """
        warnings.warn(
            "BudgetService._calculate_smart_amount is deprecated. "
            "Use BudgetSeriesService.calculate_smart_amount instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return BudgetSeriesService.calculate_smart_amount(series, use_smart_amount)

    @classmethod
    def materialize_budgets(
        cls,
        workspace: Workspace,
        date_to: datetime.datetime,
    ) -> None:
        """Materialize budget series into individual Budget instances.

        DEPRECATED: Use BudgetSeriesService.materialize_budgets instead.
        This wrapper will be removed in a future release.
        """
        warnings.warn(
            "BudgetService.materialize_budgets is deprecated. "
            "Use BudgetSeriesService.materialize_budgets instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return BudgetSeriesService.materialize_budgets(workspace, date_to)

    @staticmethod
    def _get_latest_rates():
        """Get the latest exchange rate for each currency.

        DEPRECATED: Use BudgetMulticurrencyService._get_latest_rates instead.
        This wrapper will be removed in a future release.
        """
        warnings.warn(
            "BudgetService._get_latest_rates is deprecated. "
            "Use BudgetMulticurrencyService._get_latest_rates instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return BudgetMulticurrencyService._get_latest_rates()

    @classmethod
    def _initialize_category_map(cls, parent_categories, available_currencies) -> dict:
        """Create map of all categories from workspace with minimum data.

        DEPRECATED: Use BudgetReportingService._initialize_category_map instead.
        This wrapper will be removed in a future release.
        """
        warnings.warn(
            "BudgetService._initialize_category_map is deprecated. "
            "Use BudgetReportingService._initialize_category_map instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return BudgetReportingService._initialize_category_map(
            parent_categories, available_currencies
        )

    @classmethod
    def _populate_budget_groups(cls, budgets, categories_map, available_currencies):
        """Create grouped budgets with planned values.

        DEPRECATED: Use BudgetReportingService._populate_budget_groups instead.
        This wrapper will be removed in a future release.
        """
        warnings.warn(
            "BudgetService._populate_budget_groups is deprecated. "
            "Use BudgetReportingService._populate_budget_groups instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return BudgetReportingService._populate_budget_groups(
            budgets, categories_map, available_currencies
        )

    @classmethod
    def _populate_budget_spending(
        cls,
        transactions,
        categories_map,
        available_currencies,
        date_from_parsed,
        date_to_parsed,
    ):
        """Fill in budget spending from transactions.

        DEPRECATED: Use BudgetReportingService._populate_budget_spending instead.
        This wrapper will be removed in a future release.
        """
        warnings.warn(
            "BudgetService._populate_budget_spending is deprecated. "
            "Use BudgetReportingService._populate_budget_spending instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return BudgetReportingService._populate_budget_spending(
            transactions,
            categories_map,
            available_currencies,
            date_from_parsed,
            date_to_parsed,
        )

    @classmethod
    def _finalize_output(cls, categories_map) -> list[dict]:
        """Convert category map to output list format.

        DEPRECATED: Use BudgetReportingService._finalize_output instead.
        This wrapper will be removed in a future release.
        """
        warnings.warn(
            "BudgetService._finalize_output is deprecated. "
            "Use BudgetReportingService._finalize_output instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return BudgetReportingService._finalize_output(categories_map)

    @classmethod
    def load_budget_v2(
        cls,
        *,
        workspace: Workspace,
        budgets_qs: QuerySet,
        categories_qs: QuerySet,
        currencies_qs: QuerySet,
        transactions_qs: QuerySet,
        date_from: str,
        date_to: str,
        user: str | None,
    ):
        """Generate monthly budget report with spending analysis.

        DEPRECATED: Use BudgetReportingService.generate_monthly_report instead.
        This wrapper will be removed in a future release.
        """
        warnings.warn(
            "BudgetService.load_budget_v2 is deprecated. "
            "Use BudgetReportingService.generate_monthly_report instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return BudgetReportingService.generate_monthly_report(
            workspace=workspace,
            budgets_qs=budgets_qs,
            categories_qs=categories_qs,
            currencies_qs=currencies_qs,
            transactions_qs=transactions_qs,
            date_from=date_from,
            date_to=date_to,
            user=user,
        )

    @classmethod
    def load_weekly_budget(
        cls,
        qs: QuerySet,
        currency_qs: QuerySet,
        date_from,
        date_to,
        workspace: Workspace,
        user: str | None,
    ) -> list[BudgetItem]:
        """Generate weekly budget report.

        DEPRECATED: Use BudgetReportingService.generate_weekly_report instead.
        This wrapper will be removed in a future release.
        """
        warnings.warn(
            "BudgetService.load_weekly_budget is deprecated. "
            "Use BudgetReportingService.generate_weekly_report instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return BudgetReportingService.generate_weekly_report(
            qs=qs,
            currency_qs=currency_qs,
            date_from=date_from,
            date_to=date_to,
            workspace=workspace,
            user=user,
        )

    @classmethod
    def make_grouped_budgets(
        cls, budgets, latest_rates, available_currencies, base_currency
    ) -> list[BudgetGroupedItem]:
        """Group budgets by title and aggregate spending/planning.

        DEPRECATED: Use BudgetEntityTransformer.group_budgets instead.
        This wrapper will be removed in a future release.
        """
        warnings.warn(
            "BudgetService.make_grouped_budgets is deprecated. "
            "Use BudgetEntityTransformer.group_budgets instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return BudgetEntityTransformer.group_budgets(
            budgets, latest_rates, available_currencies, base_currency
        )

    @classmethod
    def make_budgets(
        cls, budgets, latest_rates, available_currencies, base_currency
    ) -> list[BudgetItem]:
        """Transform budget QuerySet into BudgetItem TypedDicts.

        DEPRECATED: Use BudgetEntityTransformer.transform_to_budget_items instead.
        This wrapper will be removed in a future release.
        """
        warnings.warn(
            "BudgetService.make_budgets is deprecated. "
            "Use BudgetEntityTransformer.transform_to_budget_items instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return BudgetEntityTransformer.transform_to_budget_items(
            budgets, latest_rates, available_currencies, base_currency
        )

    @classmethod
    def make_transactions(
        cls, transactions, latest_rates, base_currency_code: str
    ) -> list[dict]:
        """Transform transaction QuerySet into TypedDict list.

        DEPRECATED: Use BudgetEntityTransformer.transform_transactions instead.
        This wrapper will be removed in a future release.
        """
        warnings.warn(
            "BudgetService.make_transactions is deprecated. "
            "Use BudgetEntityTransformer.transform_transactions instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return BudgetEntityTransformer.transform_transactions(
            transactions, latest_rates, base_currency_code
        )

    @classmethod
    def get_duplicate_budget_candidates(
        cls, qs, recurrent_type: BudgetDuplicateType, pivot_date: str | None = None
    ) -> list[dict[datetime.date, str]]:
        """Find budgets that can be duplicated for the next period.

        DEPRECATED: Use BudgetDuplicationService.get_duplicate_candidates instead.
        This wrapper will be removed in a future release.

        LEGACY: This is part of the old manual duplication system.
        For new recurring budgets, use BudgetSeries instead.
        """
        warnings.warn(
            "BudgetService.get_duplicate_budget_candidates is deprecated. "
            "Use BudgetDuplicationService.get_duplicate_candidates instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return BudgetDuplicationService.get_duplicate_candidates(
            qs, recurrent_type, pivot_date
        )

    @classmethod
    def duplicate_budget(cls, budgets: list[dict[str, int]], workspace: Workspace):
        """Duplicate budgets for the next period.

        DEPRECATED: Use BudgetDuplicationService.duplicate_budgets instead.
        This wrapper will be removed in a future release.

        LEGACY: This is part of the old manual duplication system.
        For new recurring budgets, use BudgetSeries instead.
        """
        warnings.warn(
            "BudgetService.duplicate_budget is deprecated. "
            "Use BudgetDuplicationService.duplicate_budgets instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return BudgetDuplicationService.duplicate_budgets(budgets, workspace)

    @classmethod
    def get_last_months_usage(
        cls,
        *,
        transactions: QuerySet,
        transfers: QuerySet | None,
        month: datetime.date,
        category_uuid: str,
        user: User,
        filter_by_user: str | None = None,
    ) -> list[MonthUsageSum]:
        """Get historical spending for a category over the last 6 months.

        DEPRECATED: Use BudgetReportingService.get_historical_usage instead.
        This wrapper will be removed in a future release.
        """
        warnings.warn(
            "BudgetService.get_last_months_usage is deprecated. "
            "Use BudgetReportingService.get_historical_usage instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return BudgetReportingService.get_historical_usage(
            transactions=transactions,
            transfers=transfers,
            month=month,
            category_uuid=category_uuid,
            user=user,
            filter_by_user=filter_by_user,
        )
