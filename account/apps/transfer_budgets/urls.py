from django.urls import path

from transfer_budgets import views

urlpatterns = [
    path("", views.TransferBudgetList.as_view(), name="transfer_budget_list"),
    path(
        "<uuid:uuid>/",
        views.TransferBudgetDetails.as_view(),
        name="transfer_budget_details",
    ),
    path(
        "upcoming/",
        views.UpcomingTransferBudgetList.as_view(),
        name="upcoming_transfer_budget",
    ),
    path(
        "usage/",
        views.TransferBudgetUsageList.as_view(),
        name="transfer_budget_usage",
    ),
    path(
        "series/<uuid:uuid>/stop/",
        views.TransferBudgetSeriesStop.as_view(),
        name="transfer_budget_series_stop",
    ),
]
