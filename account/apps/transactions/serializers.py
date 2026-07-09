from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from accounts import constants as account_constants
from categories import constants
from transactions.models import LastViewed, Transaction, Transfer


class TransactionCategorySerializer(serializers.Serializer):
    name = serializers.CharField()
    parent = serializers.UUIDField()
    parent_name = serializers.CharField()


class TransactionAccountSerializer(serializers.Serializer):
    title = serializers.CharField()
    kind = serializers.CharField()


class TransactionBudgetSerializer(serializers.Serializer):
    title = serializers.CharField()
    is_completed = serializers.BooleanField()


class TransactionCurrencySerializer(serializers.Serializer):
    sign = serializers.CharField()


class TransactionSpentInCurrencySerializer(serializers.Serializer):
    amount = serializers.FloatField()
    sign = serializers.CharField()
    currency = serializers.UUIDField()


class TransactionSerializer(serializers.Serializer):
    uuid = serializers.UUIDField(read_only=True)
    user = serializers.UUIDField()
    category = serializers.UUIDField()
    category_details = TransactionCategorySerializer(read_only=True)
    budget = serializers.UUIDField(allow_null=True)
    budget_details = TransactionBudgetSerializer(read_only=True, allow_null=True)
    currency = serializers.UUIDField()
    currency_details = TransactionCurrencySerializer(read_only=True, allow_null=True)
    amount = serializers.FloatField()
    spent_in_currencies = serializers.DictField(read_only=True)
    account = serializers.UUIDField()
    account_details = TransactionAccountSerializer(read_only=True)
    description = serializers.CharField(allow_blank=True, allow_null=True)
    transaction_date = serializers.CharField()
    created_at = serializers.DateTimeField(read_only=True)
    modified_at = serializers.DateTimeField(read_only=True)


class TransactionBulkSerializer(TransactionSerializer):
    row_id = serializers.IntegerField(read_only=True)


class TransferAccountSerializer(serializers.Serializer):
    title = serializers.CharField()
    kind = serializers.CharField()


class AccountUsageSerializer(serializers.Serializer):
    spent = serializers.FloatField()
    income = serializers.FloatField()


class TransferSerializer(serializers.ModelSerializer):
    from_account_details = TransferAccountSerializer(
        source="from_account", read_only=True
    )
    to_account_details = TransferAccountSerializer(source="to_account", read_only=True)
    currency_details = TransactionCurrencySerializer(source="currency", read_only=True)
    spent_in_currencies = serializers.DictField(
        source="multicurrency_map", read_only=True
    )

    class Meta:
        model = Transfer
        fields = (
            "uuid",
            "user",
            "from_account",
            "from_account_details",
            "to_account",
            "to_account_details",
            "currency",
            "transfer_budget",
            "currency_details",
            "amount",
            "spent_in_currencies",
            "description",
            "transfer_date",
            "created_at",
            "modified_at",
        )


class TransferCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transfer
        fields = (
            "from_account",
            "to_account",
            "currency",
            "transfer_budget",
            "amount",
            "description",
            "transfer_date",
        )

    def validate(self, attrs):
        request = self.context["request"]
        workspace = request.user.active_workspace
        from_account = attrs["from_account"]
        to_account = attrs["to_account"]
        currency = attrs["currency"]
        transfer_budget = attrs.get("transfer_budget")

        if from_account == to_account:
            raise ValidationError("Cannot transfer to the same account")

        if (
            from_account.workspace_id != workspace.uuid
            or to_account.workspace_id != workspace.uuid
        ):
            raise ValidationError(
                "Transfer accounts must belong to the active workspace"
            )

        if currency.workspace_id != workspace.uuid:
            raise ValidationError(
                "Transfer currency must belong to the active workspace"
            )

        if transfer_budget and transfer_budget.workspace_id != workspace.uuid:
            raise ValidationError("Transfer budget must belong to the active workspace")

        if transfer_budget and transfer_budget.currency_id != currency.uuid:
            raise ValidationError("Transfer and transfer budget currencies must match")

        if transfer_budget and transfer_budget.from_account_id:
            if transfer_budget.from_account_id != from_account.uuid:
                raise ValidationError(
                    "Transfer must use the transfer budget from account"
                )

        if transfer_budget and transfer_budget.to_account_id:
            if transfer_budget.to_account_id != to_account.uuid:
                raise ValidationError(
                    "Transfer must use the transfer budget to account"
                )

        if (
            from_account.kind != account_constants.SAVINGS
            and to_account.kind != account_constants.SAVINGS
        ):
            raise ValidationError("Transfers must involve at least one savings account")

        if request.user.is_owner(workspace) or request.user.is_admin(workspace):
            return attrs

        if (
            from_account.user_id != request.user.uuid
            or to_account.user_id != request.user.uuid
        ):
            raise ValidationError(
                "Members can only transfer between their own accounts"
            )

        return attrs

    def create(self, validated_data):
        request = self.context["request"]
        return super().create(
            {
                **validated_data,
                "user": request.user,
                "workspace": request.user.active_workspace,
            }
        )


class GroupedByCategorySerializer(serializers.Serializer):
    category_name = serializers.CharField()
    parent_name = serializers.CharField()
    spent_in_base_currency = serializers.FloatField()
    spent_in_currencies = serializers.DictField(read_only=True)
    items = serializers.ListField(child=TransactionSerializer())


class GroupedTransactionSerializer(serializers.Serializer):
    category_name = serializers.CharField()
    spent_in_base_currency = serializers.FloatField()
    spent_in_currencies = serializers.DictField(read_only=True)
    items = serializers.ListField(child=GroupedByCategorySerializer())

    def validate_spent_in_base_currency(self, value):
        return round(value, 4)


class TransactionCreateSerializer(serializers.ModelSerializer):
    def validate(self, attrs):
        _validate_regular_transaction_account(attrs)
        return attrs

    class Meta:
        model = Transaction
        fields = (
            "user",
            "category",
            "budget",
            "currency",
            "amount",
            "account",
            "description",
            "transaction_date",
        )

    def create(self, validated_data):
        workspace = validated_data["user"].active_workspace
        if not workspace:
            raise ValidationError("User has no active workspace")
        category_type = validated_data["category"].type
        if category_type == constants.EXPENSE and validated_data["budget"] is None:
            raise ValidationError("Expsense should contain budget specified")
        data = {
            **validated_data,
            "workspace": workspace,
        }
        return super().create(data)


class TransactionBulkCreateSerializer(serializers.ModelSerializer):
    row_id = serializers.IntegerField(write_only=True, required=True)

    def validate(self, attrs):
        _validate_regular_transaction_account(attrs)
        return attrs

    class Meta:
        model = Transaction
        fields = (
            "row_id",
            "user",
            "category",
            "budget",
            "currency",
            "amount",
            "account",
            "source",
            "description",
            "transaction_date",
        )

    def create(self, validated_data):
        workspace = validated_data["user"].active_workspace
        validated_data.pop("row_id")
        if not workspace:
            raise ValidationError("User has no active workspace")
        category_type = validated_data["category"].type
        if category_type == constants.EXPENSE and validated_data["budget"] is None:
            raise ValidationError("Expsense should contain budget specified")
        data = {
            **validated_data,
            "workspace": workspace,
        }
        return super().create(data)


class TransactionDetailsSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transaction
        fields = (
            "uuid",
            "user",
            "category",
            "budget",
            "currency",
            "amount",
            "account",
            "description",
            "transaction_date",
            "created_at",
            "modified_at",
        )


class TransactionUpdateSerializer(serializers.ModelSerializer):
    def validate(self, attrs):
        _validate_regular_transaction_account(attrs, self.instance)
        return attrs

    class Meta:
        model = Transaction
        fields = (
            "uuid",
            "user",
            "category",
            "budget",
            "currency",
            "amount",
            "account",
            "description",
            "transaction_date",
            "created_at",
            "modified_at",
        )


class TransactionBulkUpdateSerializer(serializers.Serializer):
    row_id = serializers.IntegerField(write_only=True, required=True)

    class Meta:
        model = Transaction
        fields = TransactionUpdateSerializer.Meta.fields + ("row_id",)


class ReportByMonthSerializer(serializers.Serializer):
    month = serializers.CharField()
    day = serializers.IntegerField()
    grouped_amount = serializers.FloatField()


class ReportCategoryDetailsSerializer(serializers.Serializer):
    name = serializers.CharField()
    value = serializers.FloatField()
    category_type = serializers.CharField(max_length=3)


class ReportChartSerializer(serializers.Serializer):
    date = serializers.DateField(format="%Y-%m")
    categories = serializers.ListField(child=ReportCategoryDetailsSerializer())


class IncomeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transaction
        fields = (
            "transaction_date",
            "amount",
            "currency",
        )


class LastViewedSerializer(serializers.ModelSerializer):
    class Meta:
        model = LastViewed
        fields = (
            "user",
            "transaction",
        )


def _validate_regular_transaction_account(attrs, instance=None):
    account = attrs.get("account")
    if account is None and instance is not None:
        account = instance.account

    if account is not None and account.kind == account_constants.SAVINGS:
        raise ValidationError("Savings accounts only support transfers")
