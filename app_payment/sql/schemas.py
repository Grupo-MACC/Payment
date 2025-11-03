# Payment/app_payment/sql/schemas.py
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, Literal

class Message(BaseModel):
    detail: Optional[str] = Field(example="error or success message")

PaymentStatus = Literal["Initiated","Authorized","Captured","Refunded","Failed","Canceled"]

class PaymentBase(BaseModel):
    order_id: int = Field(description="Id del pedido a cobrar", example=1)
    user_id: int = Field()
    amount_minor: int = Field(description="Importe en céntimos", example=1999)
    currency: str = Field(description="Moneda ISO-4217", min_length=3, max_length=3, example="EUR")

class PaymentPost(PaymentBase):
    """Schema definition to create a new payment"""
    pass

class Payment(PaymentBase):
    model_config = ConfigDict(from_attributes=True)  # ORM mode ON
    id: int = Field(
        description="Primary key/identifier of the payment.",
        default=None,
        example=1
    )
    status: str = Field(
        description="Current status of the order",
        default="Created",
        example="Finished"
    )

class UserWalletBase(BaseModel):
    user_id: int = Field(example=1)
    amount: int = Field(example=2000)
    currency: str = Field(min_length=3, max_length=3, example="EUR")

class UserWalletPost(UserWalletBase):
    pass