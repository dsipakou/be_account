import datetime
import uuid

from django.test import TestCase
from rest_framework.test import APIClient

from accounts import constants as account_constants
from accounts.models import Account
from budget.constants import BudgetDuplicateType
from currencies.models import Currency
from rates.models import Rate
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
        cls.workspace = Workspace.objects.create(
            name="Transfer Budget API", owner=cls.user
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
        self.assertEqual(response.data["fromAccount"], str(self.spending_account.uuid))
