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
from rates.models import Rate
from rates.services import RateService
from roles.constants import Roles
from roles.models import Role, UserRole
from transactions.models import (
    Transaction,
    TransactionMulticurrency,
    Transfer,
    TransferMulticurrency,
)
from transactions.serializers import (
    TransactionBulkCreateSerializer,
    TransactionCreateSerializer,
    TransactionUpdateSerializer,
)
from transactions.services import ReportService, TransactionService
from transfer_budgets.models import TransferBudget, TransferBudgetMulticurrency
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
        cls.eur_currency = Currency.objects.create(
            code="EU",
            sign="EU",
            verbal_name="Euro",
            is_base=False,
            is_default=False,
            workspace=cls.workspace,
        )
        Rate.objects.create(
            currency=cls.eur_currency,
            rate_date=datetime.date.today(),
            rate=0.8,
            workspace=cls.workspace,
            base_currency=cls.currency,
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
        cls.transfer_budget = TransferBudget.objects.create(
            uuid=uuid.uuid4(),
            title="Emergency Fund",
            user=cls.owner,
            currency=cls.currency,
            amount=500.0,
            budget_date=datetime.date.today(),
            workspace=cls.workspace,
            from_account=cls.owner_spending,
            to_account=cls.owner_savings,
        )
        TransferBudgetMulticurrency.objects.create(
            transfer_budget=cls.transfer_budget,
            amount_map={cls.currency.code: cls.transfer_budget.amount},
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
                "currency": str(self.eur_currency.uuid),
                "amount": 500,
                "description": "Monthly savings",
                "transfer_date": datetime.date.today().isoformat(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(Transfer.objects.count(), 1)
        self.assertEqual(response.data["spent_in_currencies"]["EU"], 500.0)
        self.assertEqual(response.data["spent_in_currencies"]["USD"], 400.0)

        multicurrency = TransferMulticurrency.objects.get(
            transfer__uuid=response.data["uuid"]
        )
        self.assertEqual(multicurrency.amount_map["EU"], 500.0)
        self.assertEqual(multicurrency.amount_map["USD"], 400.0)

    def test_transfer_with_matching_transfer_budget_succeeds(self):
        response = self.owner_client.post(
            "/transactions/transfers/",
            {
                "from_account": str(self.owner_spending.uuid),
                "to_account": str(self.owner_savings.uuid),
                "currency": str(self.currency.uuid),
                "amount": 200,
                "description": "Planned savings",
                "transfer_date": datetime.date.today().isoformat(),
                "transfer_budget": str(self.transfer_budget.uuid),
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            str(Transfer.objects.get(uuid=response.data["uuid"]).transfer_budget_id),
            str(self.transfer_budget.uuid),
        )

    def test_transfer_with_mismatched_transfer_budget_from_account_fails(self):
        response = self.owner_client.post(
            "/transactions/transfers/",
            {
                "from_account": str(self.member_spending.uuid),
                "to_account": str(self.owner_savings.uuid),
                "currency": str(self.currency.uuid),
                "amount": 200,
                "description": "Invalid planned savings",
                "transfer_date": datetime.date.today().isoformat(),
                "transfer_budget": str(self.transfer_budget.uuid),
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data["non_field_errors"][0],
            "Transfer must use the transfer budget from account",
        )

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
        self.assertIn("spent_in_currencies", owner_response.data[0])
        self.assertEqual(
            str(member_response.data[0]["uuid"]), str(member_transfer.uuid)
        )
        self.assertNotEqual(owner_transfer.uuid, member_transfer.uuid)

    def test_transfer_multicurrency_updates_when_rates_change(self):
        transfer = Transfer.objects.create(
            uuid=uuid.uuid4(),
            user=self.owner,
            workspace=self.workspace,
            from_account=self.owner_spending,
            to_account=self.owner_savings,
            currency=self.eur_currency,
            amount=100,
            description="Monthly savings",
            transfer_date=datetime.date.today(),
        )
        TransferMulticurrency.objects.create(
            transfer=transfer,
            amount_map={"EU": 100.0, "USD": 80.0},
        )

        RateService.create_batched_rates(
            {
                "user": self.owner.uuid,
                "base_currency": self.currency.uuid,
                "rate_date": datetime.date.today(),
                "items": [{"currency": self.eur_currency.uuid, "rate": 0.5}],
            }
        )

        transfer_multicurrency = TransferMulticurrency.objects.get(transfer=transfer)
        self.assertEqual(transfer_multicurrency.amount_map["EU"], 100.0)
        self.assertEqual(transfer_multicurrency.amount_map["USD"], 50.0)

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

    def test_transfers_do_not_affect_budget_spending(self):
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

    def test_year_report_includes_spending_to_savings_transfers(self):
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
        transfer = Transfer.objects.create(
            uuid=uuid.uuid4(),
            user=self.owner,
            workspace=self.workspace,
            from_account=self.owner_spending,
            to_account=self.owner_savings,
            currency=self.currency,
            amount=120,
            description="Monthly savings",
            transfer_date=datetime.date.today(),
            transfer_budget=self.transfer_budget,
        )
        TransferMulticurrency.objects.create(
            transfer=transfer,
            amount_map={self.currency.code: transfer.amount},
        )

        report = ReportService.get_year_report(
            datetime.datetime.combine(datetime.date.today(), datetime.time.min),
            datetime.datetime.combine(datetime.date.today(), datetime.time.max),
            self.currency.code,
            self.workspace.uuid,
        )

        self.assertEqual(len(report), 1)
        self.assertEqual(report[0]["grouped_amount"], 200.0)

    def test_year_report_excludes_non_spending_transfer_directions(self):
        transfer_out = Transfer.objects.create(
            uuid=uuid.uuid4(),
            user=self.owner,
            workspace=self.workspace,
            from_account=self.owner_savings,
            to_account=self.owner_spending,
            currency=self.currency,
            amount=120,
            description="Withdraw",
            transfer_date=datetime.date.today(),
        )
        TransferMulticurrency.objects.create(
            transfer=transfer_out,
            amount_map={self.currency.code: transfer_out.amount},
        )
        transfer_between_savings = Transfer.objects.create(
            uuid=uuid.uuid4(),
            user=self.owner,
            workspace=self.workspace,
            from_account=self.owner_savings,
            to_account=self.member_savings,
            currency=self.currency,
            amount=75,
            description="Move savings",
            transfer_date=datetime.date.today(),
        )
        TransferMulticurrency.objects.create(
            transfer=transfer_between_savings,
            amount_map={self.currency.code: transfer_between_savings.amount},
        )

        report = ReportService.get_year_report(
            datetime.datetime.combine(datetime.date.today(), datetime.time.min),
            datetime.datetime.combine(datetime.date.today(), datetime.time.max),
            self.currency.code,
            self.workspace.uuid,
        )

        self.assertEqual(report, [])

    def test_monthly_chart_report_includes_transfers_bucket(self):
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
        transfer = Transfer.objects.create(
            uuid=uuid.uuid4(),
            user=self.owner,
            workspace=self.workspace,
            from_account=self.owner_spending,
            to_account=self.owner_savings,
            currency=self.currency,
            amount=120,
            description="Monthly savings",
            transfer_date=datetime.date.today(),
            transfer_budget=self.transfer_budget,
        )
        TransferMulticurrency.objects.create(
            transfer=transfer,
            amount_map={self.currency.code: transfer.amount},
        )

        report = ReportService.get_chart_report(
            Transaction.objects.filter(workspace=self.workspace),
            Category.objects.filter(workspace=self.workspace),
            datetime.datetime.combine(
                datetime.date.today().replace(day=1), datetime.time.min
            ),
            datetime.datetime.combine(datetime.date.today(), datetime.time.max),
            self.currency.code,
            None,
            self.workspace,
        )

        self.assertEqual(len(report), 1)
        transfers_category = next(
            category
            for category in report[0]["categories"]
            if category["name"] == "Transfers"
        )
        self.assertEqual(transfers_category["value"], 120.0)

    def test_last_months_budget_usage_supports_transfers_bucket(self):
        spending_transfer = Transfer.objects.create(
            uuid=uuid.uuid4(),
            user=self.owner,
            workspace=self.workspace,
            from_account=self.owner_spending,
            to_account=self.owner_savings,
            currency=self.currency,
            amount=70,
            description="January savings",
            transfer_date=datetime.date(2026, 1, 10),
        )
        TransferMulticurrency.objects.create(
            transfer=spending_transfer,
            amount_map={self.currency.code: spending_transfer.amount},
        )
        non_spending_transfer = Transfer.objects.create(
            uuid=uuid.uuid4(),
            user=self.owner,
            workspace=self.workspace,
            from_account=self.owner_savings,
            to_account=self.owner_spending,
            currency=self.currency,
            amount=45,
            description="Withdrawal",
            transfer_date=datetime.date(2026, 3, 10),
        )
        TransferMulticurrency.objects.create(
            transfer=non_spending_transfer,
            amount_map={self.currency.code: non_spending_transfer.amount},
        )
        later_spending_transfer = Transfer.objects.create(
            uuid=uuid.uuid4(),
            user=self.owner,
            workspace=self.workspace,
            from_account=self.owner_spending,
            to_account=self.owner_savings,
            currency=self.currency,
            amount=90,
            description="May savings",
            transfer_date=datetime.date(2026, 5, 10),
        )
        TransferMulticurrency.objects.create(
            transfer=later_spending_transfer,
            amount_map={self.currency.code: later_spending_transfer.amount},
        )

        response = self.owner_client.get(
            "/budget/last-months/",
            {
                "month": "2026-06-01",
                "category": "Transfers",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 6)
        self.assertEqual(response.data[1]["amount"], 70.0)
        self.assertEqual(response.data[3]["amount"], 0.0)
        self.assertEqual(response.data[5]["amount"], 90.0)
