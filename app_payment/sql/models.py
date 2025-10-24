# -*- coding: utf-8 -*-
"""Database models definitions. Table representations as class."""
from sqlalchemy import Column, Integer, String
from microservice_chassis_grupo2.sql.models import BaseModel

class Payment(BaseModel):
    """Payment database table representation (propia de payment-svc)."""
    STATUS_INITIATED  = "Initiated"
    STATUS_PAYED = "Paid"
    STATUS_FAILED     = "Failed"
    STATUS_CANCELED   = "Canceled"

    __tablename__ = "payment"

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, nullable=False)

    amount_minor = Column(Integer, nullable=False)
    currency = Column(String(3), nullable=False, default="EUR")

    status = Column(String(32), nullable=False, default=STATUS_INITIATED)
