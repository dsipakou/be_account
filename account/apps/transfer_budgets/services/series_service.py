import datetime

from dateutil.relativedelta import relativedelta
from dateutil.rrule import MONTHLY, WEEKLY, rrule
from django.db.models import Q

from transfer_budgets.models import TransferBudget, TransferBudgetSeries
from transfer_budgets.services.multicurrency_service import (
    TransferBudgetMulticurrencyService,
)
from workspaces.models import Workspace


class TransferBudgetSeriesService:
    @classmethod
    def calculate_occurrences(
        cls,
        series: TransferBudgetSeries,
        to_date: datetime.date | datetime.datetime,
    ) -> list[datetime.date]:
        if isinstance(to_date, datetime.datetime):
            to_date = to_date.date()

        if str(series.frequency) == "MONTHLY":
            occurrences = []
            occurrence_num = 0
            end_date = series.until or to_date
            while True:
                if series.count and occurrence_num >= series.count:
                    break

                current_date = series.start_date + relativedelta(
                    months=series.interval * occurrence_num
                )
                if current_date > end_date:
                    break
                occurrences.append(current_date)
                occurrence_num += 1
            return occurrences

        freq_map = {
            "WEEKLY": WEEKLY,
            "MONTHLY": MONTHLY,
        }
        occurrences = rrule(
            freq=freq_map[str(series.frequency)],
            interval=series.interval,
            dtstart=series.start_date,
            until=series.until or to_date,
            count=series.count,
        )
        return [dt.date() for dt in occurrences]

    @classmethod
    def materialize_transfer_budgets(
        cls, workspace: Workspace, date_to: datetime.date | datetime.datetime
    ) -> None:
        if isinstance(date_to, datetime.date) and not isinstance(
            date_to, datetime.datetime
        ):
            date_limit = date_to
        else:
            date_limit = date_to.date()

        series_list = (
            TransferBudgetSeries.objects.filter(workspace=workspace)
            .filter(Q(until__isnull=True) | Q(until__gte=date_limit))
            .prefetch_related("exceptions")
        )
        budgets_to_create = []
        new_uuids = []

        for series in series_list:
            skipped_dates = set(
                series.exceptions.filter(is_skipped=True).values_list("date", flat=True)
            )
            for occurrence in cls.calculate_occurrences(series, date_limit):
                if occurrence in skipped_dates:
                    continue
                existing = TransferBudget.objects.filter(
                    title=series.title,
                    budget_date=occurrence,
                    user=series.user,
                ).exists()
                if existing:
                    continue
                transfer_budget = TransferBudget(
                    user=series.user,
                    workspace=series.workspace,
                    currency=series.currency,
                    from_account=series.from_account,
                    to_account=series.to_account,
                    title=series.title,
                    amount=series.amount,
                    budget_date=occurrence,
                    series=series,
                )
                budgets_to_create.append(transfer_budget)
                new_uuids.append(transfer_budget.uuid)

        if budgets_to_create:
            TransferBudget.objects.bulk_create(budgets_to_create, ignore_conflicts=True)
            TransferBudgetMulticurrencyService.create_transfer_budget_multicurrency_amount(
                new_uuids,
                workspace,
            )

    @classmethod
    def stop_series(
        cls, series: TransferBudgetSeries, until_date: datetime.date
    ) -> int:
        series.until = until_date
        series.save(update_fields=("until",))
        deleted_count, _ = TransferBudget.objects.filter(
            series=series,
            budget_date__gt=until_date,
            transfer_set__isnull=True,
        ).delete()
        return deleted_count
