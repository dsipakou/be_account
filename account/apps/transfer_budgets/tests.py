import datetime
import uuid

from django.test import TestCase
from rest_framework.test import APIClient

from accounts import constants as account_constants
from accounts.models import Account
from budget.constants import BudgetDuplicateType
from currencies.models import Currency
from rates.models import Rate
from roles.constants import Roles
from roles.models import Role, UserRole
from transactions.models import Transfer, TransferMulticurrency
from transfer_budgets.models import TransferBudget
from transfer_budgets.serializers import TransferBudgetSerializer
from users.models import User
from workspaces.models import Workspace


class TransferBudgetSerializerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="transfer-budget-user",
            email="transfer-budget@example.com",
            password="testpassword",
        )
        cls.workspace = Workspace.objects.create(
            name="Transfer Budgets", owner=cls.user
        )
        cls.user.active_workspace = cls.workspace
        cls.user.save(update_fields=("active_workspace",))
        cls.currency = Currency.objects.create(
            code="USD",
            sign="$",
            verbal_name="US Dollar",
            is_base=True,
            is_default=True,
            workspace=cls.workspace,
        )
        cls.spending_account = Account.objects.create(
            uuid=uuid.uuid4(),
            title="Checking",
            kind=account_constants.SPENDING,
            user=cls.user,
            workspace=cls.workspace,
        )
        cls.savings_account = Account.objects.create(
            uuid=uuid.uuid4(),
            title="Emergency Fund",
            kind=account_constants.SAVINGS,
            user=cls.user,
            workspace=cls.workspace,
        )

    def test_create_recurring_transfer_budget_creates_series(self):
        serializer = TransferBudgetSerializer(
            data={
                "user": self.user.uuid,
                "currency": self.currency.uuid,
                "from_account": self.spending_account.uuid,
                "to_account": self.savings_account.uuid,
                "title": "Monthly Savings",
                "amount": 500,
                "recurrent": BudgetDuplicateType.MONTHLY.value,
                "budget_date": datetime.date.today().isoformat(),
                "number_of_repetitions": 3,
            }
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        transfer_budget = serializer.save()

        self.assertIsNotNone(transfer_budget.series)
        self.assertEqual(transfer_budget.series.count, 3)
        self.assertEqual(
            transfer_budget.recurrent_type, BudgetDuplicateType.MONTHLY.value
        )


class TransferBudgetApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="transfer-budget-api-user",
            email="transfer-budget-api@example.com",
            password="testpassword",
        )
        cls.member = User.objects.create_user(
            username="transfer-budget-member-user",
            email="transfer-budget-member@example.com",
            password="testpassword",
        )
        cls.workspace = Workspace.objects.create(
            name="Transfer Budget API", owner=cls.user
        )
        cls.workspace.members.add(cls.member)
        cls.user.active_workspace = cls.workspace
        cls.user.save(update_fields=("active_workspace",))
        cls.member.active_workspace = cls.workspace
        cls.member.save(update_fields=("active_workspace",))
        cls.member_role = Role.objects.create(name=Roles.MEMBER)
        UserRole.objects.create(
            user=cls.member,
            workspace=cls.workspace,
            role=cls.member_role,
        )
        cls.currency = Currency.objects.create(
            code="USD",
            sign="$",
            verbal_name="US Dollar",
            is_base=True,
            is_default=True,
            workspace=cls.workspace,
        )
        cls.user.default_currency = cls.currency
        cls.user.save(update_fields=("default_currency",))
        cls.member.default_currency = cls.currency
        cls.member.save(update_fields=("default_currency",))
        Rate.objects.create(
            currency=cls.currency,
            base_currency=cls.currency,
            rate=1,
            rate_date=datetime.date.today(),
            workspace=cls.workspace,
        )
        cls.spending_account = Account.objects.create(
            uuid=uuid.uuid4(),
            title="Checking",
            kind=account_constants.SPENDING,
            user=cls.user,
            workspace=cls.workspace,
        )
        cls.savings_account = Account.objects.create(
            uuid=uuid.uuid4(),
            title="Emergency Fund",
            kind=account_constants.SAVINGS,
            user=cls.user,
            workspace=cls.workspace,
        )
        cls.member_spending_account = Account.objects.create(
            uuid=uuid.uuid4(),
            title="Member Checking",
            kind=account_constants.SPENDING,
            user=cls.member,
            workspace=cls.workspace,
        )
        cls.member_savings_account = Account.objects.create(
            uuid=uuid.uuid4(),
            title="Member Emergency Fund",
            kind=account_constants.SAVINGS,
            user=cls.member,
            workspace=cls.workspace,
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_create_transfer_budget_endpoint(self):
        response = self.client.post(
            "/transfer-budgets/",
            {
                "user": str(self.user.uuid),
                "currency": str(self.currency.uuid),
                "fromAccount": str(self.spending_account.uuid),
                "toAccount": str(self.savings_account.uuid),
                "title": "Emergency Fund",
                "amount": 400,
                "budgetDate": datetime.date.today().isoformat(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(TransferBudget.objects.count(), 1)
        self.assertEqual(response.data["title"], "Emergency Fund")
        self.assertEqual(
            str(response.data["from_account"]), str(self.spending_account.uuid)
        )

    def test_transfer_budget_usage_can_filter_by_user(self):
        budget_date = datetime.date(2026, 6, 16)
        owner_budget = TransferBudget.objects.create(
            uuid=uuid.uuid4(),
            user=self.user,
            workspace=self.workspace,
            currency=self.currency,
            from_account=self.spending_account,
            to_account=self.savings_account,
            title="Owner Savings",
            amount=300,
            budget_date=budget_date,
        )
        member_budget = TransferBudget.objects.create(
            uuid=uuid.uuid4(),
            user=self.member,
            workspace=self.workspace,
            currency=self.currency,
            from_account=self.member_spending_account,
            to_account=self.member_savings_account,
            title="Member Savings",
            amount=150,
            budget_date=budget_date,
        )

        TransferMulticurrency.objects.bulk_create(
            [
                TransferMulticurrency(
                    transfer=Transfer.objects.create(
                        uuid=uuid.uuid4(),
                        user=self.user,
                        workspace=self.workspace,
                        from_account=self.spending_account,
                        to_account=self.savings_account,
                        currency=self.currency,
                        amount=100,
                        transfer_date=budget_date,
                        transfer_budget=owner_budget,
                    ),
                    amount_map={self.currency.code: 100},
                ),
                TransferMulticurrency(
                    transfer=Transfer.objects.create(
                        uuid=uuid.uuid4(),
                        user=self.member,
                        workspace=self.workspace,
                        from_account=self.member_spending_account,
                        to_account=self.member_savings_account,
                        currency=self.currency,
                        amount=50,
                        transfer_date=budget_date,
                        transfer_budget=member_budget,
                    ),
                    amount_map={self.currency.code: 50},
                ),
            ]
        )

        response = self.client.get(
            "/transfer-budgets/usage/",
            {
                "dateFrom": "2026-06-01",
                "dateTo": "2026-06-30",
                "user": str(self.user.uuid),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["title"], "Owner Savings")
        self.assertEqual(response.data[0]["spent"], 100.0)

    def test_transfer_budget_weekly_usage_returns_budget_actuals(self):
        budget_date = datetime.date(2026, 6, 17)
        transfer_budget = TransferBudget.objects.create(
            uuid=uuid.uuid4(),
            user=self.user,
            workspace=self.workspace,
            currency=self.currency,
            from_account=self.spending_account,
            to_account=self.savings_account,
            title="Weekly Savings",
            amount=125,
            budget_date=budget_date,
        )
        transfer = Transfer.objects.create(
            uuid=uuid.uuid4(),
            user=self.user,
            workspace=self.workspace,
            from_account=self.spending_account,
            to_account=self.savings_account,
            currency=self.currency,
            amount=80,
            transfer_date=budget_date,
            transfer_budget=transfer_budget,
        )
        TransferMulticurrency.objects.create(
            transfer=transfer,
            amount_map={self.currency.code: transfer.amount},
        )

        response = self.client.get(
            "/transfer-budgets/weekly-usage/",
            {
                "dateFrom": "2026-06-15",
                "dateTo": "2026-06-21",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["title"], "Weekly Savings")
        self.assertEqual(response.data[0]["planned"], 125.0)
        self.assertEqual(response.data[0]["spent"], 80.0)
        self.assertEqual(len(response.data[0]["transfers"]), 1)

    def test_transfer_budget_last_months_usage_returns_history(self):
        transfer_budget = TransferBudget.objects.create(
            uuid=uuid.uuid4(),
            user=self.user,
            workspace=self.workspace,
            currency=self.currency,
            from_account=self.spending_account,
            to_account=self.savings_account,
            title="Emergency Fund",
            amount=300,
            budget_date=datetime.date(2026, 6, 16),
        )
        transfer_dates = [
            datetime.date(2026, 1, 10),
            datetime.date(2026, 3, 10),
            datetime.date(2026, 5, 10),
        ]
        transfer_amounts = [40, 60, 90]

        for transfer_date, amount in zip(transfer_dates, transfer_amounts, strict=True):
            transfer = Transfer.objects.create(
                uuid=uuid.uuid4(),
                user=self.user,
                workspace=self.workspace,
                from_account=self.spending_account,
                to_account=self.savings_account,
                currency=self.currency,
                amount=amount,
                transfer_date=transfer_date,
                transfer_budget=transfer_budget,
            )
            TransferMulticurrency.objects.create(
                transfer=transfer,
                amount_map={self.currency.code: amount},
            )

        response = self.client.get(
            "/transfer-budgets/last-months/",
            {
                "month": "2026-06-01",
                "transferBudget": str(transfer_budget.uuid),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 6)
        self.assertEqual(response.data[0]["month"], "2025-12-01")
        self.assertEqual(response.data[1]["amount"], 40.0)
        self.assertEqual(response.data[3]["amount"], 60.0)
        self.assertEqual(response.data[5]["amount"], 90.0)
