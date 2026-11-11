"""Request validation schemas for Udhaar APIs."""
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from . import email_delivery


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=200)

    @field_validator('email')
    @classmethod
    def normalize_email(cls, value):
        return email_delivery.normalize_email(value)


class Register(Credentials):
    name: str = Field(min_length=1, max_length=100)

    @field_validator('name')
    @classmethod
    def validate_name(cls, value):
        if not value.strip():
            raise ValueError('Name is required')
        return value.strip()


class RecordCreate(BaseModel):
    direction: Literal['LENT', 'BORROWED']
    mode: Literal['OFF', 'ON'] = 'OFF'
    contact_name: str = Field(min_length=1, max_length=100)
    contact_email: str | None = Field(default=None, max_length=255)
    item_name: str = Field(min_length=1, max_length=160)
    category: str = Field(default='Other', max_length=80)
    quantity: int = Field(default=1, ge=1, le=100000)
    loan_date: date
    due_date: date | None = None
    notes: str = Field(default='', max_length=2000)

    @field_validator('contact_email')
    @classmethod
    def valid_contact_email(cls, value):
        return email_delivery.normalize_email(value) if value else None

    @model_validator(mode='after')
    def check_dates(self):
        if self.mode == 'ON' and not self.contact_email:
            raise ValueError('An email address is required for On the Record')
        if self.due_date and self.due_date < self.loan_date:
            raise ValueError('Return date must be on or after the lending date')
        return self


class RecordEdit(BaseModel):
    item_name: str | None = Field(default=None, min_length=1, max_length=160)
    due_date: date | None = None
    notes: str | None = Field(default=None, max_length=2000)


class ShareResponse(BaseModel):
    accept: bool


class InviteEmail(BaseModel):
    email: str = Field(min_length=3, max_length=255)

    @field_validator('email')
    @classmethod
    def valid_email(cls, value):
        return email_delivery.normalize_email(value)


class QuantityBody(BaseModel):
    quantity: int = Field(ge=1, le=100000)
