import datetime
import uuid

from django.test import TestCase

from accounts import constants as account_constants
from accounts.models import Account
from budget.models import Budget
from categories import constants as category_constants
from categories.models import Category
from currencies.models import Currency
from transactions.models import Transaction
from transactions.serializers import (
    TransactionBulkCreateSerializer,
    TransactionCreateSerializer,
    TransactionUpdateSerializer,
)
from transactions.services import TransactionService
from users.models import User
from workspaces.models import Workspace


class TransactionSavingsAccountTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="transaction-user",
            email="transaction@example.com",
            password="testpassword",
        )
        cls.workspace = Workspace.objects.create(name="Transactions", owner=cls.user)
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

        cls.income_category = Category.objects.create(
            uuid=uuid.uuid4(),
            name="Salary",
            type=category_constants.INCOME,
            workspace=cls.workspace,
        )
        cls.expense_parent = Category.objects.create(
            uuid=uuid.uuid4(),
            name="Food",
            type=category_constants.EXPENSE,
            workspace=cls.workspace,
            position=0,
        )
        cls.expense_category = Category.objects.create(
            uuid=uuid.uuid4(),
            name="Groceries",
            type=category_constants.EXPENSE,
            workspace=cls.workspace,
            parent=cls.expense_parent,
            position=0,
        )

        cls.spending_account = Account.objects.create(
            uuid=uuid.uuid4(),
            title="Checking",
            kind=account_constants.SPENDING,
            user=cls.user,
            workspace=cls.workspace,
            category=cls.expense_parent,
        )
        cls.savings_account = Account.objects.create(
            uuid=uuid.uuid4(),
            title="Emergency Fund",
            kind=account_constants.SAVINGS,
            user=cls.user,
            workspace=cls.workspace,
            category=cls.expense_parent,
        )

        cls.budget = Budget.objects.create(
            uuid=uuid.uuid4(),
            title="Food Budget",
            user=cls.user,
            category=cls.expense_parent,
            currency=cls.currency,
            amount=200.0,
            budget_date=datetime.date.today(),
            workspace=cls.workspace,
        )

    def test_regular_transaction_on_spending_account_succeeds(self):
        serializer = TransactionCreateSerializer(
            data={
                "user": self.user.uuid,
                "category": self.income_category.uuid,
                "budget": None,
                "currency": self.currency.uuid,
                "amount": 1000,
                "account": self.spending_account.uuid,
                "description": "Salary",
                "transaction_date": datetime.date.today(),
            }
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_regular_transaction_on_savings_account_fails(self):
        serializer = TransactionCreateSerializer(
            data={
                "user": self.user.uuid,
                "category": self.income_category.uuid,
                "budget": None,
                "currency": self.currency.uuid,
                "amount": 1000,
                "account": self.savings_account.uuid,
                "description": "Salary",
                "transaction_date": datetime.date.today(),
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertEqual(
            serializer.errors["non_field_errors"][0],
            "Savings accounts only support transfers",
        )

    def test_bulk_create_on_savings_account_fails(self):
        serializer = TransactionBulkCreateSerializer(
            data={
                "row_id": 1,
                "user": self.user.uuid,
                "category": self.income_category.uuid,
                "budget": None,
                "currency": self.currency.uuid,
                "amount": 1000,
                "account": self.savings_account.uuid,
                "source": "import",
                "description": "Imported",
                "transaction_date": datetime.date.today(),
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertEqual(
            serializer.errors["non_field_errors"][0],
            "Savings accounts only support transfers",
        )

    def test_update_to_savings_account_fails(self):
        transaction = Transaction.objects.create(
            uuid=uuid.uuid4(),
            user=self.user,
            category=self.income_category,
            budget=None,
            currency=self.currency,
            amount=1000,
            account=self.spending_account,
            description="Salary",
            transaction_date=datetime.date.today(),
            workspace=self.workspace,
        )

        serializer = TransactionUpdateSerializer(
            transaction,
            data={"account": self.savings_account.uuid},
            partial=True,
        )

        self.assertFalse(serializer.is_valid())
        self.assertEqual(
            serializer.errors["non_field_errors"][0],
            "Savings accounts only support transfers",
        )

    def test_transaction_payload_includes_account_kind(self):
        transaction = Transaction.objects.create(
            uuid=uuid.uuid4(),
            user=self.user,
            category=self.income_category,
            budget=None,
            currency=self.currency,
            amount=1000,
            account=self.spending_account,
            description="Salary",
            transaction_date=datetime.date.today(),
            workspace=self.workspace,
        )

        payload = TransactionService.get_transaction(transaction)

        self.assertEqual(payload["account_details"]["title"], "Checking")
        self.assertEqual(payload["account_details"]["kind"], account_constants.SPENDING)
