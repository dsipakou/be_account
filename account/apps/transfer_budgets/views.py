import datetime

from django.db import transaction
from rest_framework import status
from rest_framework.generics import (
    GenericAPIView,
    ListAPIView,
    ListCreateAPIView,
    RetrieveUpdateDestroyAPIView,
)
from rest_framework.response import Response

from currencies.models import Currency
from transactions.models import Transfer
from transfer_budgets.models import TransferBudget
from transfer_budgets.serializers import (
    TransferBudgetLastMonthsUsageSerializer,
    TransferBudgetSerializer,
    TransferBudgetUsageSerializer,
)
from transfer_budgets.services.multicurrency_service import (
    TransferBudgetMulticurrencyService,
)
from transfer_budgets.services.reporting_service import TransferBudgetReportingService
from transfer_budgets.services.series_service import TransferBudgetSeriesService
from users.filters import FilterByUser
from users.permissions import BaseUserPermission
from workspaces.filters import FilterByWorkspace


class TransferBudgetList(ListCreateAPIView):
    queryset = TransferBudget.objects.select_related("series").all()
    filter_backends = (FilterByUser, FilterByWorkspace)
    serializer_class = TransferBudgetSerializer

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instance = serializer.save()
        TransferBudgetMulticurrencyService.create_transfer_budget_multicurrency_amount(
            [instance.uuid], workspace=request.user.active_workspace
        )
        headers = self.get_success_headers(serializer.data)
        return Response(
            serializer.data, status=status.HTTP_201_CREATED, headers=headers
        )


class TransferBudgetDetails(RetrieveUpdateDestroyAPIView):
    queryset = TransferBudget.objects.select_related("series").all()
    serializer_class = TransferBudgetSerializer
    permission_classes = (BaseUserPermission,)
    lookup_field = "uuid"

    @transaction.atomic
    def perform_update(self, serializer):
        instance = serializer.save()
        TransferBudgetMulticurrencyService.create_transfer_budget_multicurrency_amount(
            [instance.uuid], workspace=instance.workspace
        )


class UpcomingTransferBudgetList(ListAPIView):
    queryset = TransferBudget.objects.select_related("series").all()
    filter_backends = (FilterByUser, FilterByWorkspace)
    serializer_class = TransferBudgetSerializer

    def list(self, request, *args, **kwargs):
        TransferBudgetSeriesService.materialize_transfer_budgets(
            request.user.active_workspace,
            datetime.date.today() + datetime.timedelta(days=90),
        )
        queryset = (
            self.filter_queryset(self.get_queryset())
            .filter(budget_date__gte=datetime.date.today(), is_completed=False)
            .order_by("budget_date")
        )
        limit = request.query_params.get("limit", 6)
        serializer = self.get_serializer(queryset[:limit], many=True)
        return Response(serializer.data)


class TransferBudgetUsageList(ListAPIView):
    queryset = TransferBudget.objects.all()
    filter_backends = (FilterByUser, FilterByWorkspace)
    serializer_class = TransferBudgetUsageSerializer

    def list(self, request, *args, **kwargs):
        date_from = request.GET.get("dateFrom", datetime.date.today())
        date_to = request.GET.get("dateTo", datetime.date.today())
        user = request.GET.get("user")
        workspace = request.user.active_workspace

        usage = TransferBudgetReportingService.generate_usage_report(
            workspace=workspace,
            transfer_budgets_qs=self.filter_queryset(self.get_queryset()),
            currencies_qs=Currency.objects.filter(workspace=workspace),
            date_from=date_from,
            date_to=date_to,
            user=user,
        )

        serializer = self.get_serializer(usage, many=True)
        return Response(serializer.data)


class TransferBudgetWeeklyUsageList(ListAPIView):
    queryset = TransferBudget.objects.all()
    filter_backends = (FilterByUser, FilterByWorkspace)
    serializer_class = TransferBudgetUsageSerializer

    def list(self, request, *args, **kwargs):
        date_from = request.GET.get(
            "dateFrom", datetime.date.today() - datetime.timedelta(days=30)
        )
        date_to = request.GET.get("dateTo", datetime.date.today())
        user = request.GET.get("user")
        workspace = request.user.active_workspace

        usage = TransferBudgetReportingService.generate_weekly_report(
            workspace=workspace,
            transfer_budgets_qs=self.filter_queryset(self.get_queryset()),
            currencies_qs=Currency.objects.filter(workspace=workspace),
            date_from=date_from,
            date_to=date_to,
            user=user,
        )

        serializer = self.get_serializer(usage, many=True)
        return Response(serializer.data)


class TransferBudgetLastMonthsUsageList(ListAPIView):
    queryset = TransferBudget.objects.all()
    filter_backends = (FilterByUser, FilterByWorkspace)
    serializer_class = TransferBudgetLastMonthsUsageSerializer

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        month_request = request.GET.get("month")
        if month_request:
            month = datetime.datetime.strptime(month_request, "%Y-%m-%d").date()
        else:
            month = datetime.date.today()

        filter_by_user = request.GET.get("user")
        transfer_budget_uuid = request.GET.get("transferBudget")
        if not transfer_budget_uuid:
            return Response(status=status.HTTP_400_BAD_REQUEST)

        usage = TransferBudgetReportingService.get_historical_usage(
            transfers=Transfer.objects.filter(transfer_budget__in=queryset),
            month=month,
            user=request.user,
            filter_by_user=filter_by_user,
            transfer_budget_uuid=transfer_budget_uuid,
        )

        serializer = self.get_serializer(instance=usage, many=True)
        return Response(serializer.data)


class TransferBudgetSeriesStop(GenericAPIView):
    queryset = TransferBudget.objects.all()
    permission_classes = (BaseUserPermission,)
    lookup_field = "uuid"

    @transaction.atomic
    def post(self, request, uuid):
        transfer_budget = self.get_queryset().select_related("series").get(uuid=uuid)
        if not transfer_budget.series:
            return Response(
                {"error": "Transfer budget is not part of a series"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        until_date_str = request.data.get("until")
        if until_date_str:
            until_date = datetime.datetime.strptime(
                until_date_str, "%Y-%m-%d"
            ).date() - datetime.timedelta(days=1)
        else:
            until_date = datetime.date.today() - datetime.timedelta(days=1)

        deleted_count = TransferBudgetSeriesService.stop_series(
            transfer_budget.series,
            until_date,
        )
        return Response(
            {
                "uuid": transfer_budget.series.uuid,
                "title": transfer_budget.series.title,
                "until": until_date,
                "deleted_transfer_budgets": deleted_count,
            }
        )
