import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("transfer_budgets", "0001_initial"),
        ("transactions", "0014_transfermulticurrency"),
    ]

    operations = [
        migrations.AddField(
            model_name="transfer",
            name="transfer_budget",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                to="transfer_budgets.transferbudget",
                to_field="uuid",
            ),
        ),
    ]
