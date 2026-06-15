import enum


class TransferBudgetDuplicateType(str, enum.Enum):
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    OCCASIONAL = "occasional"


ALLOWED_TRANSFER_BUDGET_RECURRENT_TYPE = (
    TransferBudgetDuplicateType.WEEKLY,
    TransferBudgetDuplicateType.MONTHLY,
    TransferBudgetDuplicateType.OCCASIONAL,
)
