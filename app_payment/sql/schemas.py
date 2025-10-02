# Payment/app_payment/sql/schemas.py
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, Literal

class Message(BaseModel):
    detail: Optional[str] = Field(example="error or success message")

PaymentStatus = Literal["Initiated","Authorized","Captured","Refunded","Failed","Canceled"]

class PaymentBase(BaseModel):
    order_id: int = Field(description="Id del pedido a cobrar", example=1)
    amount_minor: int = Field(description="Importe en céntimos", example=1999)
    currency: str = Field(description="Moneda ISO-4217", min_length=3, max_length=3, example="EUR")

class PaymentCreate(PaymentBase):
    idempotency_key: Optional[str] = Field(default=None, example="idem-123")

class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)  # ORM mode ON
    id: int
    order_id: int
    amount_minor: int
    currency: str
    status: PaymentStatus
    provider_payment_id: Optional[str] = None
