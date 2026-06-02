from datetime import date, timedelta

from dateutil.relativedelta import relativedelta
from django.db.models import FloatField, Q, Sum, Value
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast, Coalesce, TruncMonth
from rest_framework import status
from rest_framework.generics import (
    CreateAPIView,
    ListCreateAPIView,
    RetrieveUpdateDestroyAPIView,
    ValidationError,
)
from rest_framework.response import Response

from account.apps.categories.constants import EXPENSE, INCOME
from accounts import constants as account_constants
from accounts.models import Account
from accounts.permissions import BaseAccountPermission
from accounts.serializers import AccountReassignSerializer, AccountSerializer
from transactions.models import Transaction, Transfer
from users.filters import FilterByUser
from users.permissions import BaseUserPermission
from workspaces.filters import FilterByWorkspace


class AccountList(ListCreateAPIView):
    queryset = Account.objects.order_by("-is_main", "created_at")
    serializer_class = AccountSerializer
    permission_classes = (BaseUserPermission, BaseAccountPermission)
    filter_backends = (FilterByUser, FilterByWorkspace)


class AccountDetails(RetrieveUpdateDestroyAPIView):
    queryset = Account.objects.all()
    serializer_class = AccountSerializer
    lookup_field = "uuid"
    permission_classes = (BaseAccountPermission,)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if (
            Transaction.objects.filter(account=instance).exists()
            or Transfer.objects.filter(
                Q(from_account=instance) | Q(to_account=instance)
            ).exists()
        ):
            return Response(
                status=status.HTTP_403_FORBIDDEN,
                data={"error": "This account has at least one transaction or transfer"},
            )

        self.perform_destroy(instance)
        return Response(status=status.HTTP_204_NO_CONTENT)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.kind == account_constants.SAVINGS:
            instance.usage = []
            serializer = self.get_serializer(instance)
            return Response(serializer.data)

        today = date.today()
        start_date = (
            (today.replace(day=1) - timedelta(days=1)) - relativedelta(months=2)
        ).replace(day=1)
        end_date = today.replace(day=1)

        currency_code = request.user.currency_code()

        qs = (
            Transaction.objects.filter(
                account_id=instance.uuid,
                transaction_date__gte=start_date,
                transaction_date__lt=end_date,
            )
            .prefetch_related("multicurrency", "category")
            .annotate(month=TruncMonth("transaction_date"))
            .values("month")
            .annotate(
                spendings=Sum(
                    Coalesce(
                        Cast(
                            KeyTextTransform(
                                currency_code, "multicurrency__amount_map"
                            ),
                            FloatField(),
                        ),
                        Value(0, output_field=FloatField()),
                    ),
                    filter=Q(category__type=EXPENSE),
                ),
                income=Sum(
                    Coalesce(
                        Cast(
                            KeyTextTransform(
                                currency_code, "multicurrency__amount_map"
                            ),
                            FloatField(),
                        ),
                        Value(0, output_field=FloatField()),
                    ),
                    filter=Q(category__type=INCOME),
                ),
            )
            .order_by("-month")
        )

        # Convert queryset to list for manipulation
        usage_list = list(qs)

        # Create a set of existing months for quick lookup
        existing_months = {item["month"] for item in usage_list}

        # Generate all three months we need
        current_month = end_date
        for _ in range(3):
            current_month = current_month - relativedelta(months=1)
            if current_month not in existing_months:
                usage_list.append(
                    {"month": current_month, "spendings": 0.0, "income": 0.0}
                )

        # Sort by month in descending order
        usage_list.sort(key=lambda x: x["month"], reverse=True)

        # Take only the last 3 months
        instance.usage = usage_list[:3]
        serializer = self.get_serializer(instance)
        return Response(serializer.data)


class AccountReassignView(CreateAPIView):
    serializer_class = AccountReassignSerializer
    permission_classes = (BaseAccountPermission,)

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        source_account_uuid = kwargs.get("uuid")
        dest_account_uuid = serializer.validated_data["account"]
        if source_account_uuid == dest_account_uuid:
            raise ValidationError("Cannot reassign to the same account")

        transactions = Transaction.objects.filter(account__uuid=source_account_uuid)
        transactions.update(account=dest_account_uuid)
        return Response(status=status.HTTP_200_OK)
