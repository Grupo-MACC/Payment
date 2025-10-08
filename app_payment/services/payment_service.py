from sql import crud, models, schemas
from sqlalchemy.ext.asyncio import AsyncSession
from dependencies import get_db

def create_payment(payment: schemas.PaymentPost) -> models.Payment|None: 
    try:
        db_payment = crud.create_payment_from_schema(db=get_db(), payment=payment)
        return db_payment
    except Exception as exc:
        print(exc)
        return None

def pay_payment(payment_id: int) -> models.Payment|None: 
    try:
        db_payment = crud.update_payment_status(db=get_db(), payment_id=payment_id, status=models.Payment.STATUS_PAYED)
        return db_payment
    except Exception as exc:
        print(exc)
        return None