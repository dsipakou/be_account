import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("accounts", "0009_account_kind"),
        ("currencies", "0005_alter_currency_code_alter_currency_unique_together"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("workspaces", "0004_alter_workspace_owner"),
    ]

    operations = [
        migrations.CreateModel(
            name="TransferBudgetSeries",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "uuid",
                    models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
                ),
                ("title", models.CharField(max_length=60)),
                ("amount", models.FloatField()),
                ("start_date", models.DateField()),
                (
                    "frequency",
                    models.CharField(
                        choices=[("WEEKLY", "Weekly"), ("MONTHLY", "Monthly")],
                        max_length=10,
                    ),
                ),
                ("interval", models.PositiveIntegerField(default=1)),
                ("count", models.PositiveIntegerField(blank=True, null=True)),
                ("until", models.DateField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "currency",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        to="currencies.currency",
                        to_field="uuid",
                    ),
                ),
                (
                    "from_account",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="transfer_budget_series_from_account",
                        to="accounts.account",
                        to_field="uuid",
                    ),
                ),
                (
                    "to_account",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="transfer_budget_series_to_account",
                        to="accounts.account",
                        to_field="uuid",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        to=settings.AUTH_USER_MODEL,
                        to_field="uuid",
                    ),
                ),
                (
                    "workspace",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        to="workspaces.workspace",
                        to_field="uuid",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="TransferBudget",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "uuid",
                    models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
                ),
                ("title", models.CharField(max_length=60)),
                ("amount", models.FloatField()),
                ("budget_date", models.DateField(blank=True, null=True)),
                ("description", models.TextField(blank=True, null=True)),
                ("is_completed", models.BooleanField(default=False)),
                (
                    "recurrent",
                    models.CharField(
                        blank=True,
                        choices=[("weekly", "Weekly"), ("monthly", "Monthly")],
                        max_length=20,
                        null=True,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("modified_at", models.DateTimeField(auto_now=True)),
                (
                    "currency",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        to="currencies.currency",
                        to_field="uuid",
                    ),
                ),
                (
                    "from_account",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="transfer_budgets_from_account",
                        to="accounts.account",
                        to_field="uuid",
                    ),
                ),
                (
                    "to_account",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="transfer_budgets_to_account",
                        to="accounts.account",
                        to_field="uuid",
                    ),
                ),
                (
                    "series",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="transfer_budgets",
                        to="transfer_budgets.transferbudgetseries",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        to=settings.AUTH_USER_MODEL,
                        to_field="uuid",
                    ),
                ),
                (
                    "workspace",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        to="workspaces.workspace",
                        to_field="uuid",
                    ),
                ),
            ],
            options={
                "unique_together": {("title", "budget_date", "user")},
            },
        ),
        migrations.CreateModel(
            name="TransferBudgetMulticurrency",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "uuid",
                    models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
                ),
                ("amount_map", models.JSONField(default=dict)),
                (
                    "transfer_budget",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="multicurrency",
                        to="transfer_budgets.transferbudget",
                        to_field="uuid",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="TransferBudgetSeriesException",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("date", models.DateField()),
                ("is_skipped", models.BooleanField(default=False)),
                ("override_amount", models.FloatField(blank=True, null=True)),
                (
                    "series",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="exceptions",
                        to="transfer_budgets.transferbudgetseries",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="transferbudgetseriesexception",
            constraint=models.UniqueConstraint(
                fields=("series", "date"),
                name="unique_transfer_budget_series_exception_date",
            ),
        ),
        migrations.AddConstraint(
            model_name="transferbudget",
            constraint=models.UniqueConstraint(
                fields=("series", "budget_date"),
                name="unique_transfer_budget_series_budget_date",
            ),
        ),
    ]
