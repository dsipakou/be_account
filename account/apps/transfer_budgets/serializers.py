from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from transfer_budgets import constants
from transfer_budgets.models import (
    TransferBudget,
    TransferBudgetSeries,
    TransferBudgetSeriesException,
)


class TransferBudgetSerializer(serializers.ModelSerializer):
    number_of_repetitions = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=1,
    )

    class Meta:
        model = TransferBudget
        fields = (
            "uuid",
            "user",
            "currency",
            "from_account",
            "to_account",
            "title",
            "amount",
            "recurrent",
            "budget_date",
            "description",
            "is_completed",
            "number_of_repetitions",
            "created_at",
            "modified_at",
        )

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["recurrent"] = instance.recurrent_type
        data["number_of_repetitions"] = (
            instance.series.count if instance.series else None
        )
        return data

    def validate(self, attrs):
        user = attrs.get("user") or getattr(self.instance, "user", None)
        workspace = user.active_workspace if user else None
        if not workspace:
            raise ValidationError("User has no active workspace")

        currency = attrs.get("currency") or getattr(self.instance, "currency", None)
        from_account = attrs.get("from_account")
        to_account = attrs.get("to_account")

        if self.instance:
            from_account = (
                from_account if "from_account" in attrs else self.instance.from_account
            )
            to_account = (
                to_account if "to_account" in attrs else self.instance.to_account
            )

        if currency and currency.workspace_id != workspace.uuid:
            raise ValidationError(
                "Transfer budget currency must belong to the active workspace"
            )

        if from_account and from_account.workspace_id != workspace.uuid:
            raise ValidationError(
                "Transfer budget accounts must belong to the active workspace"
            )

        if to_account and to_account.workspace_id != workspace.uuid:
            raise ValidationError(
                "Transfer budget accounts must belong to the active workspace"
            )

        if from_account and to_account and from_account == to_account:
            raise ValidationError("Transfer budget accounts must be different")

        if not from_account and not to_account:
            raise ValidationError("Transfer budget requires at least one account")

        return attrs

    def create(self, validated_data):
        workspace = validated_data["user"].active_workspace
        number_of_repetitions = validated_data.pop("number_of_repetitions", None)

        recurrent = validated_data.get("recurrent")
        series = None
        if recurrent in (
            constants.TransferBudgetDuplicateType.WEEKLY.value,
            constants.TransferBudgetDuplicateType.MONTHLY.value,
        ):
            frequency_map = {
                constants.TransferBudgetDuplicateType.WEEKLY.value: TransferBudgetSeries.Frequency.WEEKLY,
                constants.TransferBudgetDuplicateType.MONTHLY.value: TransferBudgetSeries.Frequency.MONTHLY,
            }
            series = TransferBudgetSeries.objects.create(
                user=validated_data["user"],
                workspace=workspace,
                title=validated_data["title"],
                currency=validated_data["currency"],
                amount=validated_data["amount"],
                from_account=validated_data.get("from_account"),
                to_account=validated_data.get("to_account"),
                start_date=validated_data["budget_date"],
                frequency=frequency_map[recurrent],
                interval=1,
                count=number_of_repetitions,
            )

        transfer_budget = super().create(
            {
                **validated_data,
                "workspace": workspace,
                "series": series,
            }
        )

        if transfer_budget.series and transfer_budget.budget_date:
            TransferBudgetSeriesException.objects.filter(
                series=transfer_budget.series,
                date=transfer_budget.budget_date,
                is_skipped=True,
            ).delete()
        return transfer_budget


class TransferBudgetTransferSerializer(serializers.Serializer):
    uuid = serializers.UUIDField()
    currency = serializers.UUIDField()
    currency_code = serializers.CharField()
    amount = serializers.FloatField()
    spent_in_currencies = serializers.DictField()
    from_account = serializers.UUIDField(allow_null=True)
    to_account = serializers.UUIDField(allow_null=True)
    transfer_date = serializers.DateField()


class TransferBudgetUsageSerializer(serializers.Serializer):
    uuid = serializers.UUIDField()
    user = serializers.UUIDField()
    currency = serializers.UUIDField()
    from_account = serializers.UUIDField(allow_null=True)
    to_account = serializers.UUIDField(allow_null=True)
    title = serializers.CharField()
    budget_date = serializers.DateField()
    description = serializers.CharField(allow_blank=True, allow_null=True)
    is_completed = serializers.BooleanField()
    recurrent = serializers.CharField(allow_null=True)
    planned = serializers.FloatField()
    spent = serializers.FloatField()
    planned_in_currencies = serializers.DictField()
    spent_in_currencies = serializers.DictField()
    transfers = serializers.ListField(child=TransferBudgetTransferSerializer())
    created_at = serializers.DateTimeField()
    modified_at = serializers.DateTimeField()
