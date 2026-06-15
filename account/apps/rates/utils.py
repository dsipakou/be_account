import datetime

from budget.models import Budget
from currencies.models import Currency
from rates.models import Rate
from transactions.models import Transaction, Transfer


def generate_date_seq(days_count):
    return [
        datetime.date.today() - datetime.timedelta(days=x) for x in range(days_count)
    ]


def generate_amount_map(
    instance: Transaction | Budget | Transfer,
    rates: list[Rate],
    workspace,
) -> dict[str, int]:
    amount_mapping = {}
    rate_map = {}
    for rate in rates:
        rate_map[rate.currency_id] = rate
    for currency in Currency.objects.filter(workspace=workspace):
        if currency.uuid not in rate_map:
            rate = (
                Rate.objects.filter(currency_id=currency.uuid, workspace=workspace)
                .order_by("-rate_date")
                .first()
            )
            if rate is not None:
                rate_map[currency.uuid] = rate
    for rate in rate_map.values():
        if instance.currency == rate.currency:
            # current rate currency and instance currency are the same no need to modify amount
            amount = instance.amount
        elif instance.currency == rate.base_currency:
            # instance currency is base currency so just divide - no need to convert to base currency beforehand
            amount = round(instance.amount / rate.rate, 5)
        else:
            # need to convert amount to base currency first than to current rate currency

            current_rate = rate_map[instance.currency.uuid]
            amount = round(instance.amount * current_rate.rate / rate.rate, 5)
        amount_mapping[rate.currency.code] = amount
    # Create a record for base currency as well
    if rate_map:
        # if instance currency is already base currency - save it as is
        base_currency = next(iter(rate_map.values())).base_currency
        if instance.currency.uuid == base_currency.uuid:
            amount_mapping[instance.currency.code] = instance.amount
        else:
            # else searching instance currency in rate_map and do convert
            amount = instance.amount * rate_map[instance.currency.uuid].rate
            amount_mapping[base_currency.code] = round(amount, 5)

    # TODO: in case if no any rate/currency found
    # assuming that instance's currency is base
    # and put it as is into amount map
    if not len(amount_mapping):
        amount_mapping[instance.currency.code] = instance.amount
    return amount_mapping
