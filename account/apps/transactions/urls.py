from django.urls import path

from transactions import views

urlpatterns = [
    path("", views.TransactionList.as_view(), name="transaction_list"),
    path("transfers/", views.TransferListCreate.as_view(), name="transfer_list_create"),
    path(
        "transfers/<uuid:uuid>/",
        views.TransferDetails.as_view(),
        name="transfer_details",
    ),
    path(
        "<uuid:uuid>/", views.TransactionDetails.as_view(), name="transaction_details"
    ),
    path(
        "grouped/",
        views.TransactionGroupedList.as_view(),
        name="transaction_grouped_list",
    ),
    path("report/", views.TransactionReportList.as_view(), name="transaction_report"),
    path(
        "report-monthly/",
        views.TransactionReportMonthly.as_view(),
        name="transaction_report_monthly",
    ),
    path("income/", views.TransactionIncomeList.as_view(), name="transaction_income"),
    path(
        "budget/<uuid:uuid>/",
        views.BudgetTransactions.as_view(),
        name="budget_transactions",
    ),
    path(
        "account/<uuid:uuid>/usage/",
        views.AccountUsage.as_view(),
        name="category_transactions",
    ),
    path(
        "category/<uuid:uuid>/",
        views.CategoryTransactions.as_view(),
        name="category_transactions",
    ),
    path(
        "last-added/",
        views.TransactionsLastAddedView.as_view(),
        name="transactions_last_added",
    ),
    path(
        "bulk-create/",
        views.TransactionBulkCreate.as_view(),
        name="transaction_bulk_create",
    ),
    path(
        "date-range/",
        views.TransactionsByDateRange.as_view(),
        name="transactions_by_date_range",
    ),
]
