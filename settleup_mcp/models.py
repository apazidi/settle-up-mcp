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
        text = str(value).strip()
        try:
            Decimal(text)
        except (InvalidOperation, ValueError) as error:
            raise ValueError(
                f"The amount {value!r} is not a number. Use a value such as "
                "'250.50'."
            ) from error
        return text

    @field_validator("currency_code", mode="before")
    @classmethod
    def _to_upper(cls, value: object) -> object:
        if value is None:
            return None
        return str(value).strip().upper()

    def parsed_date_time(self) -> datetime:
        """Give the date and the time. Give the current time if none is set."""
        if not self.date_time:
            return datetime.now(tz=timezone.utc)
        try:
            moment = datetime.fromisoformat(self.date_time)
        except ValueError as error:
            raise ValueError(
                f"The date_time {self.date_time!r} is not ISO 8601. Use a value "
                "such as '2026-08-05T18:30:00+05:30'."
            ) from error
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return moment
