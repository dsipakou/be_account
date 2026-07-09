import datetime

import structlog
from django.db import transaction
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.generics import (
    GenericAPIView,
    ListAPIView,
    ListCreateAPIView,
    RetrieveUpdateDestroyAPIView,
)
from rest_framework.response import Response

from account.apps.budget.services.multicurrency_service import (
    BudgetMulticurrencyService,
)
from budget import serializers
from budget.models import Budget
from budget.serializers import DuplicateResponseSerializer
from budget.services import BudgetService
from budget.services.series_service import BudgetSeriesService
from categories.models import Category
from currencies.models import Currency
from transactions.models import Transaction, Transfer
from users.filters import FilterByUser
from users.permissions import BaseUserPermission
from workspaces.filters import FilterByWorkspace

logger = structlog.get_logger()


class BudgetList(ListCreateAPIView):
    queryset = Budget.objects.select_related("category", "series").all()
    filter_backends = (FilterByUser, FilterByWorkspace)
    serializer_class = serializers.BudgetSerializer

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        """Check if category is parent category

        Raises:
            ValidationError: when category is not parent category
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if serializer.validated_data["category"].parent is not None:
            raise ValidationError("Only parent categories can be used for budgets.")
        instance = serializer.save()
        headers = self.get_success_headers(serializer.data)
        workspace = request.user.active_workspace

        BudgetMulticurrencyService.create_budget_multicurrency_amount(
            [instance.uuid], workspace=workspace
        )

        return Response(
            serializer.data, status=status.HTTP_201_CREATED, headers=headers
        )


class BudgetPendingList(ListAPIView):
    queryset = Budget.objects.filter(budget_date__isnull=True).select_related("series")
    filter_backends = (FilterByUser, FilterByWorkspace)
    serializer_class = serializers.BudgetSerializer


class BudgetDetails(RetrieveUpdateDestroyAPIView):
    queryset = Budget.objects.select_related("series").prefetch_related(
        "transaction_set"
    )
    serializer_class = serializers.BudgetSerializer
    permission_classes = (BaseUserPermission,)
    lookup_field = "uuid"

    @transaction.atomic
    def perform_update(self, serializer):
        """Check if category is parent category and handle series changes

        Raises:
            ValidationError: when category is not parent category
        """
        # Get the old instance before changes
        old_instance = self.get_object()

        # Validate category
        category = serializer.validated_data.get("category")
        if category and category.parent is not None:
            raise ValidationError("Only parent categories can be used for budgets.")

        # Handle series changes via service
        new_series, updated_uuids = BudgetSeriesService.update_budget_series(
            budget=old_instance,
            validated_data=serializer.validated_data,
        )

        # Update series in validated data
        if new_series is not None:
            serializer.validated_data["series"] = new_series
        elif (
            "recurrent" in serializer.validated_data
            and not serializer.validated_data["recurrent"]
        ):
            # Explicitly set to None when converting to non-recurrent
            serializer.validated_data["series"] = None

        # Save and create multicurrency
        instance = serializer.save()
        uuids_to_update = updated_uuids if updated_uuids else [instance.uuid]
        BudgetMulticurrencyService.create_budget_multicurrency_amount(
            uuids_to_update, workspace=instance.workspace
        )

    @transaction.atomic
    def perform_destroy(self, instance):
        """Delete budget and track in exceptions if part of a series"""
        BudgetSeriesService.track_deletion(instance)
        instance.delete()


class MonthlyUsageBudgetList(ListAPIView):
    queryset = Budget.objects.all()
    filter_backends = (FilterByUser, FilterByWorkspace)
    serializer_class = serializers.CategoryBudgetV2Serializer

    def list(self, request, *args, **kwargs):
        date_from = request.GET.get("dateFrom", datetime.date.today())
        date_to = request.GET.get("dateTo", datetime.date.today())
        user = request.GET.get("user")
        queryset = self.filter_queryset(self.get_queryset())
        workspace = request.user.active_workspace

        categories = BudgetService.load_budget_v2(
            workspace=workspace,
            budgets_qs=queryset,
            categories_qs=Category.objects.filter(
                workspace=request.user.active_workspace
            ),
            currencies_qs=Currency.objects.filter(
                workspace=request.user.active_workspace
            ),
            transactions_qs=Transaction.objects.prefetch_related("budget").filter(
                workspace=request.user.active_workspace, budget__in=queryset
            ),
            date_from=date_from,
            date_to=date_to,
            user=user,
        )

        serializer = self.get_serializer(categories, many=True)
        logger.info("Monthly usage requested", date_from=date_from, date_to=date_to)
        return Response(serializer.data)


class WeeklyUsageList(ListAPIView):
    queryset = Budget.objects.all()
    filter_backends = (FilterByUser, FilterByWorkspace)
    serializer_class = serializers.BudgetUsageSerializer

    def list(self, request, *args, **kwargs):
        date_from = request.GET.get(
            "dateFrom", datetime.date.today() - datetime.timedelta(days=30)
        )
        date_to = request.GET.get("dateTo", datetime.date.today())
        user = request.GET.get("user")

        budgets = BudgetService.load_weekly_budget(
            self.filter_queryset(self.get_queryset()),
            Currency.objects.filter(workspace=request.user.active_workspace),
            date_from,
            date_to,
            request.user.active_workspace,
            user,
        )

        serializer = self.get_serializer(budgets, many=True)
        return Response(serializer.data)


class UpcomingBudgetList(ListAPIView):
    queryset = Budget.objects.select_related("series").all()
    filter_backends = (FilterByUser, FilterByWorkspace)
    serializer_class = serializers.BudgetSerializer

    def list(self, request, *args, **kwargs):
        queryset = (
            self.filter_queryset(self.get_queryset())
            .filter(budget_date__gte=datetime.date.today(), is_completed=False)
            .order_by("budget_date")
        )
        limit = request.query_params.get("limit", 6)
        serializer = self.get_serializer(queryset[:limit], many=True)
        return Response(serializer.data)


class DuplicateBudgetView(GenericAPIView):
    queryset = Budget.objects.all()
    filter_backends = (FilterByUser, FilterByWorkspace)
    serializer_class = serializers.DuplicateRequestSerializer
    permission_classes = (BaseUserPermission,)

    def get(self, request, *args, **kwargs):
        pivot_date = request.query_params.get("date")
        if (recurrent_type := request.query_params.get("type")) is not None:
            budgets = BudgetService.get_duplicate_budget_candidates(
                self.filter_queryset(self.queryset), recurrent_type, pivot_date
            )
            response_serializer = DuplicateResponseSerializer(data=budgets, many=True)
            response_serializer.is_valid(raise_exception=True)
            return Response(response_serializer.data)
        else:
            return Response(status=status.HTTP_200_OK, data=[])

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        workspace = request.user.active_workspace
        BudgetService.duplicate_budget(serializer.data["budgets"], workspace=workspace)
        return Response(status=status.HTTP_201_CREATED)


class LastMonthsBudgetUsageList(ListAPIView):
    queryset = Budget.objects.all()
    filter_backends = (FilterByUser, FilterByWorkspace)
    serializer_class = serializers.LastMonthsUsageSerializer

    def list(self, request, *args, **kwargs):
        month_request = request.GET.get("month")
        if month_request:
            month = datetime.datetime.strptime(month_request, "%Y-%m-%d").date()
        else:
            month = datetime.date.today()
        user = request.GET.get("user")
        category_uuid = request.GET.get("category")

        if not category_uuid:
            return Response(status=status.HTTP_400_BAD_REQUEST)

        queryset = self.filter_queryset(self.get_queryset())

        grouped_transactions = BudgetService.get_last_months_usage(
            transactions=Transaction.objects.prefetch_related("budget").filter(
                budget__in=queryset
            ),
            transfers=Transfer.objects.filter(workspace=request.user.active_workspace),
            month=month,
            user=request.user,
            filter_by_user=user,
            category_uuid=category_uuid,
        )

        serializer = self.get_serializer(instance=grouped_transactions, many=True)

        return Response(serializer.data)


class BudgetSeriesStop(GenericAPIView):
    """Stop a budget series from materializing future budgets"""

    queryset = Budget.objects.all()
    permission_classes = (BaseUserPermission,)
    lookup_field = "uuid"

    @transaction.atomic
    def post(self, request, uuid):
        """Stop the series at a specified date

        Accepts a budget UUID and stops the series associated with that budget.

        Request body (optional):
        {
            "until": "2024-12-31"  # Stop series at this date (optional, defaults to yesterday)
        }
        """
        # Get the budget and its associated series
        try:
            budget = self.get_queryset().select_related("series").get(uuid=uuid)
        except Budget.DoesNotExist:
            return Response(
                {"error": "Budget not found"}, status=status.HTTP_404_NOT_FOUND
            )

        if not budget.series:
            return Response(
                {"error": "Budget is not part of a series"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        series = budget.series

        # Parse until date from request or use yesterday as default
        until_date_str = request.data.get("until")
        if until_date_str:
            try:
                until_date = datetime.datetime.strptime(
                    until_date_str, "%Y-%m-%d"
                ).date() - datetime.timedelta(days=1)
            except ValueError:
                return Response(
                    {"error": "Invalid date format. Use YYYY-MM-DD"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            # Default to one day before today
            until_date = datetime.date.today() - datetime.timedelta(days=1)

        # Stop series via service
        deleted_count, unlinked_count, deleted_exceptions = (
            BudgetSeriesService.stop_series(series=series, until_date=until_date)
        )

        return Response(
            {
                "uuid": series.uuid,
                "title": series.title,
                "until": until_date,
                "deleted_budgets": deleted_count,
                "unlinked_budgets": unlinked_count,
                "deleted_exceptions": deleted_exceptions,
                "message": f"Series stopped. Deleted {deleted_count} budgets, unlinked {unlinked_count} budgets with transactions, and deleted {deleted_exceptions} exceptions after {until_date}",
            }
        )
