"""The Pydantic input models for the tools."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator

MAX_PAGE_SIZE = 200

GroupId = Annotated[
    str,
    Field(
        min_length=1,
        max_length=128,
        description="The Settle Up group id. Use settleup_list_groups to find it.",
    ),
]
MemberId = Annotated[
    str,
    Field(
        min_length=1,
        max_length=128,
        description="The Settle Up member id. Use settleup_list_members to find it.",
    ),
]
TransactionId = Annotated[
    str,
    Field(
        min_length=1,
        max_length=128,
        description="The transaction id. Use settleup_list_expenses to find it.",
    ),
]


def _decimal_value(value: object) -> str:
    """Check that a value is a decimal number. Give the plain text."""
    text = str(value).strip()
    try:
        Decimal(text)
    except (InvalidOperation, ValueError) as error:
        raise ValueError(
            f"The amount {value!r} is not a number. Use a value such as '250.50'."
        ) from error
    return text


def _optional_decimal(value: object) -> object:
    """Check an amount that the request can leave empty."""
    if value is None:
        return None
    return _decimal_value(value)


def _positive_decimal(value: object) -> str:
    """Check that an amount is more than 0."""
    text = _decimal_value(value)
    if Decimal(text) <= 0:
        raise ValueError(
            f"The amount {value!r} must be more than 0. "
            "Change from_member_id and to_member_id to reverse the direction."
        )
    return text


def _weight_value(value: object) -> str:
    """Check that a weight is a number of 0 or more."""
    text = str(value).strip()
    try:
        number = Decimal(text)
    except (InvalidOperation, ValueError) as error:
        raise ValueError(
            f"The weight {value!r} is not a number. Use a value such as '1'."
        ) from error
    if number < 0:
        raise ValueError("The weight must be 0 or more.")
    return text


def _optional_weight(value: object) -> object:
    """Check a weight that the request can leave empty."""
    if value is None:
        return None
    return _weight_value(value)


def _upper_value(value: object) -> str:
    """Give the text in capital letters."""
    return str(value).strip().upper()


def _upper_or_none(value: object) -> object:
    """Give the text in capital letters, or None."""
    if value is None:
        return None
    return _upper_value(value)


def parse_moment(text: str | None) -> datetime:
    """Read an ISO 8601 text. Give the current time if the text is empty."""
    if not text:
        return datetime.now(tz=timezone.utc)
    try:
        moment = datetime.fromisoformat(text)
    except ValueError as error:
        raise ValueError(
            f"The date {text!r} is not ISO 8601. Use a value such as "
            "'2026-08-05T18:30:00+05:30'."
        ) from error
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


class Page(BaseModel):
    """The pagination values. Each list tool uses them."""

    limit: Annotated[
        int,
        Field(
            default=50,
            ge=1,
            le=MAX_PAGE_SIZE,
            description=f"The maximum number of items to give. 1 to {MAX_PAGE_SIZE}.",
        ),
    ] = 50
    offset: Annotated[
        int,
        Field(
            default=0,
            ge=0,
            description="The number of items to skip before the first item.",
        ),
    ] = 0


class ListGroupsRequest(Page):
    """The input of settleup_list_groups."""


class ListMembersRequest(Page):
    """The input of settleup_list_members."""

    group_id: GroupId
    only_active: Annotated[
        bool,
        Field(
            default=False,
            description="Give only the members that new transactions include.",
        ),
    ] = False


class ListExpensesRequest(Page):
    """The input of settleup_list_expenses."""

    group_id: GroupId
    transaction_type: Annotated[
        Literal["all", "expense", "transfer"],
        Field(
            default="all",
            description="Filter by the transaction type. An income is a negative "
            "expense.",
        ),
    ] = "all"
    member_id: Annotated[
        str | None,
        Field(
            default=None,
            description="Give only the transactions of this member. "
            "The member can be a payer or a debtor.",
        ),
    ] = None
    newest_first: Annotated[
        bool,
        Field(default=True, description="Sort by date. True gives the newest first."),
    ] = True


class GetBalancesRequest(BaseModel):
    """The input of settleup_get_balances."""

    group_id: GroupId


class GetGroupRequest(BaseModel):
    """The input of settleup_get_group."""

    group_id: GroupId


class GetInviteLinkRequest(BaseModel):
    """The input of settleup_get_invite_link."""

    group_id: GroupId


class ListPermissionsRequest(Page):
    """The input of settleup_list_permissions."""

    group_id: GroupId


class ListCategoriesRequest(BaseModel):
    """The input of settleup_list_categories."""

    group_id: GroupId


class RecalculateDebtsRequest(BaseModel):
    """The input of settleup_recalculate_debts."""

    group_id: GroupId


class ListChangesRequest(Page):
    """The input of settleup_list_changes."""

    group_id: GroupId
    newest_first: Annotated[
        bool,
        Field(default=True, description="Sort by time. True gives the newest first."),
    ] = True


class MemberShare(BaseModel):
    """One member and the share of that member."""

    member_id: MemberId
    weight: Annotated[
        str,
        Field(
            default="1",
            description="The share of this member. Use '1' for an equal share.",
        ),
    ] = "1"

    @field_validator("weight", mode="before")
    @classmethod
    def _to_positive_number(cls, value: object) -> str:
        return _weight_value(value)


class AddExpenseRequest(BaseModel):
    """The input of settleup_add_expense."""

    group_id: GroupId
    amount: Annotated[
        str,
        Field(
            description="The total amount of the expense. Use a decimal string, "
            "for example '250.50'. Use a negative value for an income.",
        ),
    ]
    purpose: Annotated[
        str,
        Field(
            min_length=1,
            max_length=200,
            description="The short name of the expense, for example 'Dinner'.",
        ),
    ]
    paid_by: Annotated[
        list[MemberShare],
        Field(
            min_length=1,
            description="The members that paid. Give 1 member for the normal case.",
        ),
    ]
    split_between: Annotated[
        list[MemberShare] | None,
        Field(
            default=None,
            description="The members that share the cost. Leave this empty to "
            "split between all active members.",
        ),
    ] = None
    currency_code: Annotated[
        str | None,
        Field(
            default=None,
            min_length=3,
            max_length=3,
            description="The ISO 4217 currency code, for example 'EUR'. Leave "
            "this empty to use the group currency.",
        ),
    ] = None
    category: Annotated[
        str | None,
        Field(
            default=None,
            max_length=8,
            description="One emoji for the category, for example '☕'.",
        ),
    ] = None
    date_time: Annotated[
        str | None,
        Field(
            default=None,
            description="The date and the time in ISO 8601 format, for example "
            "'2026-08-05T18:30:00+05:30'. Leave this empty to use the "
            "current time.",
        ),
    ] = None

    @field_validator("amount", mode="before")
    @classmethod
    def _to_decimal_string(cls, value: object) -> str:
        return _decimal_value(value)

    @field_validator("currency_code", mode="before")
    @classmethod
    def _to_upper(cls, value: object) -> object:
        return _upper_or_none(value)

    def parsed_date_time(self) -> datetime:
        """Give the date and the time. Give the current time if none is set."""
        return parse_moment(self.date_time)


class GetExpenseRequest(BaseModel):
    """The input of settleup_get_expense."""

    group_id: GroupId
    transaction_id: TransactionId


class DeleteExpenseRequest(BaseModel):
    """The input of settleup_delete_expense."""

    group_id: GroupId
    transaction_id: TransactionId
    confirm: Annotated[
        bool,
        Field(
            description="Set this to true to delete the transaction. "
            "Ask the user first. The delete is permanent.",
        ),
    ]


class UpdateExpenseRequest(BaseModel):
    """The input of settleup_update_expense.

    Give only the fields that change. The server keeps each other field.
    """

    group_id: GroupId
    transaction_id: TransactionId
    amount: Annotated[
        str | None,
        Field(default=None, description="The new total amount, for example '30.00'."),
    ] = None
    purpose: Annotated[
        str | None,
        Field(default=None, max_length=200, description="The new name."),
    ] = None
    paid_by: Annotated[
        list[MemberShare] | None,
        Field(default=None, description="The new list of members that paid."),
    ] = None
    split_between: Annotated[
        list[MemberShare] | None,
        Field(default=None, description="The new list of members that share."),
    ] = None
    category: Annotated[
        str | None,
        Field(default=None, max_length=8, description="The new category emoji."),
    ] = None
    date_time: Annotated[
        str | None,
        Field(default=None, description="The new date and time in ISO 8601 format."),
    ] = None

    _check_amount = field_validator("amount", mode="before")(_optional_decimal)

    def has_changes(self) -> bool:
        """Give True if the request changes at least 1 field."""
        return any(
            value is not None
            for value in (
                self.amount,
                self.purpose,
                self.paid_by,
                self.split_between,
                self.category,
                self.date_time,
            )
        )


class AddTransferRequest(BaseModel):
    """The input of settleup_add_transfer."""

    group_id: GroupId
    amount: Annotated[
        str,
        Field(description="The amount that moves, for example '25.00'."),
    ]
    from_member_id: MemberId
    to_member_id: MemberId
    purpose: Annotated[
        str,
        Field(
            default="Settle up",
            max_length=200,
            description="The name of the transfer.",
        ),
    ] = "Settle up"
    currency_code: Annotated[
        str | None,
        Field(
            default=None,
            min_length=3,
            max_length=3,
            description="The ISO 4217 currency code. Leave this empty to use the "
            "group currency.",
        ),
    ] = None
    date_time: Annotated[
        str | None,
        Field(
            default=None,
            description="The date and the time in ISO 8601 format. Leave this "
            "empty to use the current time.",
        ),
    ] = None

    _check_amount = field_validator("amount", mode="before")(_positive_decimal)
    _upper = field_validator("currency_code", mode="before")(_upper_or_none)

    def parsed_date_time(self) -> datetime:
        """Give the date and the time. Give the current time if none is set."""
        return parse_moment(self.date_time)


class SummarizeSpendingRequest(BaseModel):
    """The input of settleup_summarize_spending."""

    group_id: GroupId
    group_by: Annotated[
        Literal["category", "member", "month"],
        Field(
            default="category",
            description="The key of the summary. 'member' gives the share of "
            "each member.",
        ),
    ] = "category"
    since: Annotated[
        str | None,
        Field(
            default=None,
            description="Count only the transactions at or after this date. "
            "Use ISO 8601, for example '2026-01-01'.",
        ),
    ] = None
    until: Annotated[
        str | None,
        Field(
            default=None,
            description="Count only the transactions before this date. "
            "Use ISO 8601.",
        ),
    ] = None
    top: Annotated[
        int,
        Field(
            default=20,
            ge=1,
            le=MAX_PAGE_SIZE,
            description="The maximum number of rows to give.",
        ),
    ] = 20

    def window(self) -> tuple[int | None, int | None]:
        """Give the time window in milliseconds."""
        start = parse_moment(self.since) if self.since else None
        end = parse_moment(self.until) if self.until else None
        if start and end and end <= start:
            raise ValueError(
                "The value until is at or before the value since. "
                "Give an until value after the since value."
            )
        return (
            int(start.timestamp() * 1000) if start else None,
            int(end.timestamp() * 1000) if end else None,
        )


class AddMemberRequest(BaseModel):
    """The input of settleup_add_member."""

    group_id: GroupId
    name: Annotated[
        str,
        Field(min_length=1, max_length=100, description="The name of the person."),
    ]
    default_weight: Annotated[
        str,
        Field(
            default="1",
            description="The default share in a new expense. Use '0' to leave "
            "the member out by default.",
        ),
    ] = "1"
    active: Annotated[
        bool,
        Field(default=True, description="Include the member in a new transaction."),
    ] = True
    bank_account: Annotated[
        str | None,
        Field(default=None, max_length=100, description="The bank account number."),
    ] = None

    _check_weight = field_validator("default_weight", mode="before")(_weight_value)


class UpdateMemberRequest(BaseModel):
    """The input of settleup_update_member. Give only the fields that change."""

    group_id: GroupId
    member_id: MemberId
    name: Annotated[
        str | None,
        Field(default=None, min_length=1, max_length=100, description="The new name."),
    ] = None
    default_weight: Annotated[
        str | None,
        Field(default=None, description="The new default share."),
    ] = None
    active: Annotated[
        bool | None,
        Field(default=None, description="The new active state."),
    ] = None
    bank_account: Annotated[
        str | None,
        Field(default=None, max_length=100, description="The new bank account."),
    ] = None

    _check_weight = field_validator("default_weight", mode="before")(
        _optional_weight
    )

    def changes(self) -> dict[str, object]:
        """Give the fields for the API. Skip each field that is None."""
        fields = {
            "name": self.name,
            "defaultWeight": self.default_weight,
            "active": self.active,
            "bankAccount": self.bank_account,
        }
        return {key: value for key, value in fields.items() if value is not None}


class DeactivateMemberRequest(BaseModel):
    """The input of settleup_deactivate_member."""

    group_id: GroupId
    member_id: MemberId


class CreateGroupRequest(BaseModel):
    """The input of settleup_create_group."""

    name: Annotated[
        str,
        Field(min_length=1, max_length=100, description="The name of the group."),
    ]
    currency_code: Annotated[
        str,
        Field(
            min_length=3,
            max_length=3,
            description="The ISO 4217 currency code, for example 'EUR'.",
        ),
    ]
    your_member_name: Annotated[
        str,
        Field(
            min_length=1,
            max_length=100,
            description="Your name in the group. The server creates this member "
            "and links it to your account.",
        ),
    ]
    minimize_debts: Annotated[
        bool,
        Field(
            default=True,
            description="Let the server give the smallest number of payments.",
        ),
    ] = True

    _upper = field_validator("currency_code", mode="before")(_upper_value)


class UpdateGroupRequest(BaseModel):
    """The input of settleup_update_group. Give only the fields that change."""

    group_id: GroupId
    name: Annotated[
        str | None,
        Field(default=None, min_length=1, max_length=100, description="The new name."),
    ] = None
    minimize_debts: Annotated[
        bool | None,
        Field(default=None, description="The new debt minimization setting."),
    ] = None
    invite_link_active: Annotated[
        bool | None,
        Field(
            default=None,
            description="Set this to false to stop the invite link.",
        ),
    ] = None

    def changes(self) -> dict[str, object]:
        """Give the fields for the API. Skip each field that is None."""
        fields = {
            "name": self.name,
            "minimizeDebts": self.minimize_debts,
            "inviteLinkActive": self.invite_link_active,
        }
        return {key: value for key, value in fields.items() if value is not None}


class ChangeCurrencyRequest(BaseModel):
    """The input of settleup_change_currency."""

    group_id: GroupId
    target_currency: Annotated[
        str,
        Field(
            min_length=3,
            max_length=3,
            description="The new ISO 4217 currency code, for example 'USD'.",
        ),
    ]

    _upper = field_validator("target_currency", mode="before")(_upper_value)


class DeleteGroupRequest(BaseModel):
    """The input of settleup_delete_group."""

    group_id: GroupId
    confirm: Annotated[
        bool,
        Field(
            description="Set this to true to delete the group. Ask the user "
            "first. The delete removes each member and each transaction.",
        ),
    ]


class ListRecurringRequest(Page):
    """The input of settleup_list_recurring."""

    group_id: GroupId


class DeleteRecurringRequest(BaseModel):
    """The input of settleup_delete_recurring."""

    group_id: GroupId
    template_id: Annotated[
        str,
        Field(
            min_length=1,
            max_length=128,
            description="The template id. Use settleup_list_recurring to find it.",
        ),
    ]
    confirm: Annotated[
        bool,
        Field(
            description="Set this to true to delete the template. Ask the user "
            "first.",
        ),
    ]


class AddRecurringRequest(BaseModel):
    """The input of settleup_add_recurring."""

    group_id: GroupId
    amount: Annotated[
        str,
        Field(description="The amount of each generated expense."),
    ]
    purpose: Annotated[
        str,
        Field(min_length=1, max_length=200, description="The name of the expense."),
    ]
    paid_by: Annotated[
        list[MemberShare],
        Field(min_length=1, description="The members that pay."),
    ]
    split_between: Annotated[
        list[MemberShare] | None,
        Field(
            default=None,
            description="The members that share the cost. Leave this empty to "
            "split between all active members.",
        ),
    ] = None
    period: Annotated[
        Literal["daily", "weekly", "monthly", "yearly"],
        Field(default="monthly", description="How often the server repeats it."),
    ] = "monthly"
    frequency: Annotated[
        int,
        Field(
            default=1,
            ge=1,
            le=365,
            description="The number of periods between 2 expenses. Use 2 with "
            "'weekly' for every 2 weeks.",
        ),
    ] = 1
    start_date: Annotated[
        str | None,
        Field(
            default=None,
            description="The first date in ISO 8601 format. Leave this empty to "
            "start now.",
        ),
    ] = None
    end_date: Annotated[
        str | None,
        Field(default=None, description="The last date in ISO 8601 format."),
    ] = None
    end_count: Annotated[
        int | None,
        Field(
            default=None,
            ge=1,
            description="The maximum number of expenses to generate.",
        ),
    ] = None
    monthly_setting: Annotated[
        Literal["dayOfMonth", "lastDayOfMonth"] | None,
        Field(
            default=None,
            description="The monthly rule. The server needs this value when the "
            "period is 'monthly'.",
        ),
    ] = None
    weekly_setting: Annotated[
        list[Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]] | None,
        Field(
            default=None,
            description="The days of the week. Use this with the period "
            "'weekly'.",
        ),
    ] = None
    category: Annotated[
        str | None,
        Field(default=None, max_length=8, description="One emoji for the category."),
    ] = None
    currency_code: Annotated[
        str | None,
        Field(
            default=None,
            min_length=3,
            max_length=3,
            description="The ISO 4217 currency code. Leave this empty to use the "
            "group currency.",
        ),
    ] = None

    _check_amount = field_validator("amount", mode="before")(_decimal_value)
    _upper = field_validator("currency_code", mode="before")(_upper_or_none)

    def parsed_start(self) -> datetime:
        """Give the start date. Give the current time if none is set."""
        return parse_moment(self.start_date)

    def parsed_end(self) -> datetime | None:
        """Give the end date, or None."""
        return parse_moment(self.end_date) if self.end_date else None
