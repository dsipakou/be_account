"""Budget Reporting Service.

Handles budget reporting operations including monthly reports, weekly reports,
and historical usage analysis.
"""

import datetime

from dateutil.relativedelta import relativedelta
from dateutil.rrule import MONTHLY, rrule
from django.db.models import FloatField, Prefetch, QuerySet, Sum, Value
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast, Coalesce, TruncMonth

from accounts import constants as account_constants
from budget import utils
from budget.entities import (
    BudgetItem,
    BudgetModel,
    BudgetTransactionModel,
    CategoryModel,
    GroupedBudgetModel,
    MonthUsageSum,
)
from budget.services.entity_transformer import BudgetEntityTransformer
from budget.services.multicurrency_service import BudgetMulticurrencyService
from budget.services.series_service import BudgetSeriesService
from categories import constants
from transactions.models import Transaction
from users.models import User
from workspaces.models import Workspace


class BudgetReportingService:
    """Service for budget reporting and analysis."""

    TRANSFER_GROUP_NAME = "Transfers"

    @classmethod
    def _initialize_category_map(
        cls,
        parent_categories: QuerySet,
        available_currencies: list[dict[str, str | bool]],
    ) -> dict:
        """Create map of all categories from workspace with minimum data.

        Args:
            parent_categories: QuerySet of parent Category models
            available_currencies: List of currency dicts with code and is_base

        Returns:
            Dict mapping category UUID to CategoryModel instances
        """
        categories_map = {}
        for category in parent_categories:
            categories_map[category.uuid] = CategoryModel.init(
                category, available_currencies
            )
        return categories_map

    @classmethod
    def _populate_budget_groups(
        cls,
        budgets: QuerySet,
        categories_map: dict,
        available_currencies: list[dict[str, str | bool]],
    ) -> None:
        """Create grouped budgets with planned values.

        Args:
            budgets: QuerySet of Budget models
            categories_map: Dict mapping category UUID to CategoryModel
            available_currencies: List of currency dicts with code and is_base

        Mutates categories_map by adding budget groups and planned values.
        """
        for budget in budgets:
            category_for_budget = categories_map[budget.category.uuid]

            transaction_budget_group_key = GroupedBudgetModel.get_grouped_budget_key(
                budget
            )

            # If this budget group isn't exists yet in this category - create it
            if transaction_budget_group_key not in category_for_budget.budgets_map:
                category_for_budget.budgets_map[transaction_budget_group_key] = (
                    GroupedBudgetModel.init(
                        budget,
                        available_currencies,
                    )
                )

            budget_group_item = category_for_budget.budgets_map[
                transaction_budget_group_key
            ]

            # Add budget to budget group
            budget_group_item.items_map[budget.uuid] = BudgetModel.init(
                budget,
                available_currencies,
            )

            # Increase planned values with real budget value
            # TODO: remove this since this value are obsolete
            budget_group_item.planned += budget.amount
            category_for_budget.planned += budget.amount

            budget_group_item.update_planned_values(
                available_currencies, budget.multicurrency_map
            )
            category_for_budget.update_planned_values(
                available_currencies, budget.multicurrency_map
            )

    @classmethod
    def _populate_budget_spending(
        cls,
        transactions: QuerySet,
        categories_map: dict,
        available_currencies: list[dict[str, str | bool]],
        date_from_parsed: datetime.date,
        date_to_parsed: datetime.date,
    ) -> None:
        """Fill in budget spending from transactions.

        Args:
            transactions: QuerySet of Transaction models
            categories_map: Dict mapping category UUID to CategoryModel
            available_currencies: List of currency dicts with code and is_base
            date_from_parsed: Start date as datetime.date
            date_to_parsed: End date as datetime.date

        Mutates categories_map by adding transaction spending to budgets.
        """
        for transaction in transactions:
            # Prepare transaction model
            transaction_model = BudgetTransactionModel.init(transaction)

            transaction_budget = transaction.budget
            transaction_budget_group_key = GroupedBudgetModel.get_grouped_budget_key(
                transaction_budget
            )

            # Actual transaction category might differ from budget category
            transaction_category = transaction.category.parent

            # TODO: make a migration to rid off nullable budgets
            # Legacy support when transaction can be without a budget
            if not transaction_budget:
                continue

            transaction_category_object = categories_map[transaction_category.uuid]

            # TODO: Remove this
            transaction_category_object.spent += transaction.amount
            transaction_category_object.update_spent_values(
                available_currencies, transaction.multicurrency_map
            )

            # Find or append budget group to category
            # title + uuid + year-month uniqueness
            if (
                transaction_budget_group_key
                not in transaction_category_object.budgets_map
            ):
                transaction_category_object.budgets_map[
                    transaction_budget_group_key
                ] = GroupedBudgetModel.build_for_transaction(
                    transaction_budget,
                    transaction_category_object,
                    date_from_parsed,
                    date_to_parsed,
                    available_currencies,
                )

            budget_group_item = transaction_category_object.budgets_map[
                transaction_budget_group_key
            ]

            budget_group_item.spent += transaction.amount
            budget_group_item.update_spent_values(
                available_currencies, transaction.multicurrency_map
            )
            budget_group_item.update_spent_overall_values(
                available_currencies, transaction.multicurrency_map
            )

            # Find or append budget to budget group
            if transaction_budget.uuid not in budget_group_item.items_map:
                budget_group_item.items_map[transaction_budget.uuid] = (
                    BudgetModel.init_for_transaction(
                        transaction_budget, available_currencies
                    )
                )

            simple_budget_item = budget_group_item.items_map[transaction_budget.uuid]

            simple_budget_item.spent += transaction.amount
            simple_budget_item.update_spent_values(
                available_currencies, transaction.multicurrency_map
            )
            simple_budget_item.transactions.append(transaction_model)

            # Logic when transaction and budget categories are no the same
            transaction_budget_category = transaction_budget.category
            if transaction_category != transaction_budget_category:
                transaction_budget_category_object = categories_map[
                    transaction_budget_category.uuid
                ]
                if (
                    transaction_budget_group_key
                    not in transaction_budget_category_object.budgets_map
                ):
                    transaction_budget_category_object.budgets_map[
                        transaction_budget_group_key
                    ] = GroupedBudgetModel.build_for_transaction(
                        transaction_budget,
                        transaction_category_object,
                        date_from_parsed,
                        date_to_parsed,
                        available_currencies,
                    )
                simple_budget_grouped_budget_item = (
                    transaction_budget_category_object.budgets_map[
                        transaction_budget_group_key
                    ]
                )
                simple_budget_grouped_budget_item.update_spent_overall_values(
                    available_currencies, transaction.multicurrency_map
                )
                if (
                    transaction_budget.uuid
                    not in simple_budget_grouped_budget_item.items_map
                ):
                    simple_budget_grouped_budget_item.items_map[
                        transaction_budget.uuid
                    ] = BudgetModel.init_for_transaction(
                        transaction_budget, available_currencies
                    )
                simple_budget_budget_item = simple_budget_grouped_budget_item.items_map[
                    transaction_budget.uuid
                ]
                if transaction_category != transaction_budget_category:
                    simple_budget_budget_item.transactions.append(transaction_model)

    @classmethod
    def _finalize_output(cls, categories_map: dict) -> list[dict]:
        """Convert category map to output list format.

        Args:
            categories_map: Dict mapping category UUID to CategoryModel

        Returns:
            List of category dicts with nested budgets and items
        """
        output = list(categories_map.values())
        for cat in output:
            cat.budgets = list(cat.budgets_map.values())
            for bud in cat.budgets:
                bud.items = list(bud.items_map.values())

        return [item.dict() for item in output]

    @classmethod
    def generate_monthly_report(
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
    ) -> list[dict]:
        """Generate monthly budget report with spending analysis.

        This method orchestrates the budget reporting workflow:
        1. Materialize budget series for the period
        2. Initialize category structure
        3. Populate planned budget values
        4. Add transaction spending data
        5. Format output for API response

        Args:
            workspace: Workspace to filter data
            budgets_qs: QuerySet of Budget models
            categories_qs: QuerySet of Category models
            currencies_qs: QuerySet of Currency models
            transactions_qs: QuerySet of Transaction models
            date_from: Start date string (YYYY-MM-DD)
            date_to: End date string (YYYY-MM-DD)
            user: Optional user UUID to filter budgets/transactions

        Returns:
            List of category dicts with nested budget groups and items
        """
        # Materialize recurring budgets for the period
        date_to_formatted = utils.get_end_of_current_week_datetime(date_to)
        BudgetSeriesService.materialize_budgets(workspace, date_to_formatted)

        # Query budgets and categories for the period
        budgets = (
            budgets_qs.filter(budget_date__lte=date_to, budget_date__gte=date_from)
            .select_related("currency", "category", "multicurrency", "user", "series")
            .order_by("budget_date")
        )
        parent_categories = categories_qs.filter(
            parent__isnull=True, type=constants.EXPENSE
        ).order_by("name")

        # Query transactions with related data
        available_currencies = list(currencies_qs.values("code", "is_base"))
        transactions = transactions_qs.filter(
            transaction_date__lte=date_to,
            transaction_date__gte=date_from,
            category__type=constants.EXPENSE,
        )
        if user:
            transactions = transactions.filter(budget__user__uuid=user)
            budgets = budgets.filter(user__uuid=user)

        transactions = transactions.select_related(
            "multicurrency",
            "budget",
            "budget__category",
            "currency",
            "category",
            "category__parent",
            "user",
        )

        # Parse date strings once
        date_from_parsed = datetime.datetime.strptime(date_from, "%Y-%m-%d").date()
        date_to_parsed = datetime.datetime.strptime(date_to, "%Y-%m-%d").date()

        # Build category map with budget groups and spending
        categories_map = cls._initialize_category_map(
            parent_categories, available_currencies
        )
        cls._populate_budget_groups(budgets, categories_map, available_currencies)
        cls._populate_budget_spending(
            transactions,
            categories_map,
            available_currencies,
            date_from_parsed,
            date_to_parsed,
        )

        # Format output for API
        return cls._finalize_output(categories_map)

    @classmethod
    def generate_weekly_report(
        cls,
        qs: QuerySet,
        currency_qs: QuerySet,
        date_from: str | datetime.date,
        date_to: str | datetime.date,
        workspace: Workspace,
        user: str | None,
    ) -> list[BudgetItem]:
        """Generate weekly budget report.

        Args:
            qs: QuerySet of Budget models
            currency_qs: QuerySet of Currency models
            date_from: Start date
            date_to: End date
            workspace: Workspace to materialize budgets for
            user: Optional user UUID to filter budgets

        Returns:
            List of BudgetItem TypedDicts for the week
        """
        date_to_formatted = utils.get_end_of_current_week_datetime(date_to)
        BudgetSeriesService.materialize_budgets(workspace, date_to_formatted)
        budgets = (
            qs.filter(budget_date__lte=date_to, budget_date__gte=date_from)
            .select_related("series")
            .prefetch_related(
                Prefetch(
                    "transaction_set",
                    queryset=Transaction.objects.select_related("multicurrency").filter(
                        budget__in=qs
                    ),
                    to_attr="transactions",
                ),
            )
            .all()
            .order_by("created_at")
        )
        if user:
            budgets = budgets.filter(user__uuid=user)

        available_currencies = currency_qs.values("code", "is_base")
        base_currency = available_currencies.filter(is_base=True).first()
        if not base_currency:
            return []

        return BudgetEntityTransformer.transform_to_budget_items(
            budgets,
            BudgetMulticurrencyService._get_latest_rates(),
            available_currencies,
            base_currency["code"],
        )

    @classmethod
    def get_historical_usage(
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

        Args:
            transactions: QuerySet of Transaction models
            month: The target month for comparison
            category_uuid: Category UUID to filter by
            user: User object (for currency)
            filter_by_user: Optional user UUID to filter transactions

        Returns:
            List of MonthUsageSum with spending per month
        """
        currency_code = user.currency_code()
        if not currency_code:
            return []

        if category_uuid == cls.TRANSFER_GROUP_NAME:
            return cls._get_transfer_historical_usage(
                transfers=transfers,
                month=month,
                user=user,
                filter_by_user=filter_by_user,
            )

        selected_month_first_day = month.replace(day=1)
        six_month_earlier = month - relativedelta(months=6)

        transactions = transactions.filter(
            category__parent=category_uuid,
            transaction_date__lt=selected_month_first_day,
            transaction_date__gte=six_month_earlier,
        ).prefetch_related("multicurrency")

        if filter_by_user:
            transactions = transactions.filter(user=filter_by_user)

        # get values for current default currency only
        grouped_transactions = transactions.annotate(
            current_currency_amount=Coalesce(
                Cast(
                    KeyTextTransform(currency_code, "multicurrency__amount_map"),
                    FloatField(),
                ),
                Value(0, output_field=FloatField()),
            )
        )
        # trunc dates to months
        grouped_transactions = grouped_transactions.annotate(
            month=TruncMonth("transaction_date")
        ).values("month")
        # group spent amount by months
        grouped_transactions = grouped_transactions.annotate(
            amount=Sum("current_currency_amount")
        ).order_by("month")
        all_months = rrule(
            MONTHLY,
            dtstart=six_month_earlier,
            until=selected_month_first_day - relativedelta(months=1),
        )

        # add empty months with 0 amount
        clean_transactions: list[MonthUsageSum] = []
        for current_month in all_months:
            if transaction := grouped_transactions.filter(month=current_month).first():
                amount = transaction.get("amount", 0)
            else:
                amount = 0
            clean_transactions.append(
                MonthUsageSum(
                    month=current_month.date(),
                    amount=amount,
                )
            )
        return clean_transactions

    @classmethod
    def _get_transfer_historical_usage(
        cls,
        *,
        transfers: QuerySet | None,
        month: datetime.date,
        user: User,
        filter_by_user: str | None = None,
    ) -> list[MonthUsageSum]:
        currency_code = user.currency_code()
        if not currency_code or transfers is None:
            return []

        selected_month_first_day = month.replace(day=1)
        six_month_earlier = month - relativedelta(months=6)

        transfers = transfers.filter(
            from_account__kind=account_constants.SPENDING,
            to_account__kind=account_constants.SAVINGS,
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
