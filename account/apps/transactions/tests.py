import datetime
import uuid

from django.test import TestCase
from rest_framework.test import APIClient

from accounts import constants as account_constants
from accounts.models import Account
from budget.models import Budget, BudgetMulticurrency
from budget.services import BudgetService
from categories import constants as category_constants
from categories.models import Category
from currencies.models import Currency
from roles.constants import Roles
from roles.models import Role, UserRole
from transactions.models import Transaction, TransactionMulticurrency, Transfer
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


class TransferTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(
            username="owner-user",
            email="owner@example.com",
            password="testpassword",
        )
        cls.member = User.objects.create_user(
            username="member-user",
            email="member@example.com",
            password="testpassword",
        )
        cls.admin = User.objects.create_user(
            username="admin-user",
            email="admin@example.com",
            password="testpassword",
        )
        cls.workspace = Workspace.objects.create(name="Transfers", owner=cls.owner)
        cls.workspace.members.add(cls.member, cls.admin)

        cls.owner.active_workspace = cls.workspace
        cls.owner.save(update_fields=("active_workspace",))
        cls.member.active_workspace = cls.workspace
        cls.member.save(update_fields=("active_workspace",))
        cls.admin.active_workspace = cls.workspace
        cls.admin.save(update_fields=("active_workspace",))

        cls.admin_role = Role.objects.create(name=Roles.ADMIN)
        cls.member_role = Role.objects.create(name=Roles.MEMBER)
        UserRole.objects.create(
            user=cls.admin, workspace=cls.workspace, role=cls.admin_role
        )
        UserRole.objects.create(
            user=cls.member, workspace=cls.workspace, role=cls.member_role
        )

        cls.currency = Currency.objects.create(
            code="USD",
            sign="$",
            verbal_name="US Dollar",
            is_base=True,
            is_default=True,
            workspace=cls.workspace,
        )
        for user in (cls.owner, cls.member, cls.admin):
            user.default_currency = cls.currency
            user.save(update_fields=("default_currency",))

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

        cls.owner_spending = Account.objects.create(
            uuid=uuid.uuid4(),
            title="Owner Checking",
            kind=account_constants.SPENDING,
            user=cls.owner,
            workspace=cls.workspace,
            category=cls.expense_parent,
        )
        cls.owner_savings = Account.objects.create(
            uuid=uuid.uuid4(),
            title="Owner Savings",
            kind=account_constants.SAVINGS,
            user=cls.owner,
            workspace=cls.workspace,
            category=cls.expense_parent,
        )
        cls.member_spending = Account.objects.create(
            uuid=uuid.uuid4(),
            title="Member Checking",
            kind=account_constants.SPENDING,
            user=cls.member,
            workspace=cls.workspace,
            category=cls.expense_parent,
        )
        cls.member_savings = Account.objects.create(
            uuid=uuid.uuid4(),
            title="Member Savings",
            kind=account_constants.SAVINGS,
            user=cls.member,
            workspace=cls.workspace,
            category=cls.expense_parent,
        )

        cls.other_workspace = Workspace.objects.create(
            name="Other Workspace", owner=cls.owner
        )
        cls.other_account = Account.objects.create(
            uuid=uuid.uuid4(),
            title="Other Savings",
            kind=account_constants.SAVINGS,
            user=cls.owner,
            workspace=cls.other_workspace,
            category=None,
        )

        cls.owner_budget = Budget.objects.create(
            uuid=uuid.uuid4(),
            title="Owner Food Budget",
            user=cls.owner,
            category=cls.expense_parent,
            currency=cls.currency,
            amount=200.0,
            budget_date=datetime.date.today(),
            workspace=cls.workspace,
        )
        BudgetMulticurrency.objects.create(
            budget=cls.owner_budget,
            amount_map={cls.currency.code: cls.owner_budget.amount},
        )

    def setUp(self):
        self.owner_client = APIClient()
        self.owner_client.force_authenticate(self.owner)
        self.member_client = APIClient()
        self.member_client.force_authenticate(self.member)
        self.admin_client = APIClient()
        self.admin_client.force_authenticate(self.admin)

    def test_spending_to_savings_transfer_succeeds(self):
        response = self.owner_client.post(
            "/transactions/transfers/",
            {
                "from_account": str(self.owner_spending.uuid),
                "to_account": str(self.owner_savings.uuid),
                "currency": str(self.currency.uuid),
                "amount": 500,
                "description": "Monthly savings",
                "transfer_date": datetime.date.today().isoformat(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(Transfer.objects.count(), 1)

    def test_savings_to_spending_transfer_succeeds(self):
        response = self.owner_client.post(
            "/transactions/transfers/",
            {
                "from_account": str(self.owner_savings.uuid),
                "to_account": str(self.owner_spending.uuid),
                "currency": str(self.currency.uuid),
                "amount": 200,
                "description": "Cover expenses",
                "transfer_date": datetime.date.today().isoformat(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)

    def test_savings_to_savings_transfer_succeeds(self):
        response = self.owner_client.post(
            "/transactions/transfers/",
            {
                "from_account": str(self.owner_savings.uuid),
                "to_account": str(self.member_savings.uuid),
                "currency": str(self.currency.uuid),
                "amount": 100,
                "description": "Rebalance",
                "transfer_date": datetime.date.today().isoformat(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)

    def test_spending_to_spending_transfer_fails(self):
        response = self.owner_client.post(
            "/transactions/transfers/",
            {
                "from_account": str(self.owner_spending.uuid),
                "to_account": str(self.member_spending.uuid),
                "currency": str(self.currency.uuid),
                "amount": 100,
                "description": "Invalid",
                "transfer_date": datetime.date.today().isoformat(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data["non_field_errors"][0],
            "Transfers must involve at least one savings account",
        )

    def test_same_account_transfer_fails(self):
        response = self.owner_client.post(
            "/transactions/transfers/",
            {
                "from_account": str(self.owner_savings.uuid),
                "to_account": str(self.owner_savings.uuid),
                "currency": str(self.currency.uuid),
                "amount": 100,
                "description": "Invalid",
                "transfer_date": datetime.date.today().isoformat(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data["non_field_errors"][0],
            "Cannot transfer to the same account",
        )

    def test_cross_workspace_transfer_fails(self):
        response = self.owner_client.post(
            "/transactions/transfers/",
            {
                "from_account": str(self.owner_savings.uuid),
                "to_account": str(self.other_account.uuid),
                "currency": str(self.currency.uuid),
                "amount": 100,
                "description": "Invalid",
                "transfer_date": datetime.date.today().isoformat(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data["non_field_errors"][0],
            "Transfer accounts must belong to the active workspace",
        )

    def test_member_cannot_use_another_users_account(self):
        response = self.member_client.post(
            "/transactions/transfers/",
            {
                "from_account": str(self.member_savings.uuid),
                "to_account": str(self.owner_savings.uuid),
                "currency": str(self.currency.uuid),
                "amount": 50,
                "description": "Invalid",
                "transfer_date": datetime.date.today().isoformat(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data["non_field_errors"][0],
            "Members can only transfer between their own accounts",
        )

    def test_admin_can_transfer_across_workspace_accounts(self):
        response = self.admin_client.post(
            "/transactions/transfers/",
            {
                "from_account": str(self.owner_savings.uuid),
                "to_account": str(self.member_spending.uuid),
                "currency": str(self.currency.uuid),
                "amount": 75,
                "description": "Admin transfer",
                "transfer_date": datetime.date.today().isoformat(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(Transfer.objects.get().user, self.admin)

    def test_transfer_visibility_follows_workspace_role_rules(self):
        owner_transfer = Transfer.objects.create(
            uuid=uuid.uuid4(),
            user=self.owner,
            workspace=self.workspace,
            from_account=self.owner_spending,
            to_account=self.owner_savings,
            currency=self.currency,
            amount=100,
            description="Owner transfer",
            transfer_date=datetime.date.today(),
        )
        member_transfer = Transfer.objects.create(
            uuid=uuid.uuid4(),
            user=self.member,
            workspace=self.workspace,
            from_account=self.member_spending,
            to_account=self.member_savings,
            currency=self.currency,
            amount=50,
            description="Member transfer",
            transfer_date=datetime.date.today(),
        )

        owner_response = self.owner_client.get("/transactions/transfers/")
        member_response = self.member_client.get("/transactions/transfers/")
        admin_response = self.admin_client.get("/transactions/transfers/")

        self.assertEqual(owner_response.status_code, 200)
        self.assertEqual(member_response.status_code, 200)
        self.assertEqual(admin_response.status_code, 200)
        self.assertEqual(len(owner_response.data), 2)
        self.assertEqual(len(admin_response.data), 2)
        self.assertEqual(len(member_response.data), 1)
        self.assertEqual(
            str(member_response.data[0]["uuid"]), str(member_transfer.uuid)
        )
        self.assertNotEqual(owner_transfer.uuid, member_transfer.uuid)

    def test_deleting_account_referenced_by_transfer_fails(self):
        Transfer.objects.create(
            uuid=uuid.uuid4(),
            user=self.owner,
            workspace=self.workspace,
            from_account=self.owner_spending,
            to_account=self.owner_savings,
            currency=self.currency,
            amount=100,
            description="Owner transfer",
            transfer_date=datetime.date.today(),
        )

        response = self.owner_client.delete(f"/accounts/{self.owner_savings.uuid}/")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.data["error"],
            "This account has at least one transaction or transfer",
        )

    def test_transfers_do_not_affect_reports_or_budgets(self):
        transaction = Transaction.objects.create(
            uuid=uuid.uuid4(),
            user=self.owner,
            category=self.expense_category,
            budget=self.owner_budget,
            currency=self.currency,
            amount=80,
            account=self.owner_spending,
            description="Groceries",
            transaction_date=datetime.date.today(),
            workspace=self.workspace,
        )
        TransactionMulticurrency.objects.create(
            transaction=transaction,
            amount_map={self.currency.code: transaction.amount},
        )
        Transfer.objects.create(
            uuid=uuid.uuid4(),
            user=self.owner,
            workspace=self.workspace,
            from_account=self.owner_spending,
            to_account=self.owner_savings,
            currency=self.currency,
            amount=500,
            description="Monthly savings",
            transfer_date=datetime.date.today(),
        )

        first_day = datetime.date.today().replace(day=1)
        last_day = (first_day + datetime.timedelta(days=32)).replace(
            day=1
        ) - datetime.timedelta(days=1)

        result = BudgetService.load_budget_v2(
            workspace=self.workspace,
            budgets_qs=Budget.objects.filter(workspace=self.workspace),
            categories_qs=Category.objects.filter(workspace=self.workspace),
            currencies_qs=Currency.objects.filter(workspace=self.workspace),
            transactions_qs=Transaction.objects.filter(workspace=self.workspace),
            date_from=first_day.isoformat(),
            date_to=last_day.isoformat(),
            user=None,
        )

        food_result = next(
            (cat for cat in result if cat["category_name"] == self.expense_parent.name),
            None,
        )
        self.assertIsNotNone(food_result)
        self.assertEqual(food_result["spent"], 80.0)
