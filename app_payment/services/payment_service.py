from sql import crud, models, schemas
from microservice_chassis_grupo2.core.dependencies import get_db

async def create_payment(payment: schemas.PaymentPost) -> models.Payment | None:
    try:
        async for db in get_db():
            db_payment = await crud.create_payment_from_schema(db=db, payment=payment)
            return db_payment
    except Exception as exc:
        print(exc)
        return None


async def pay_payment(payment_id: int) -> models.Payment | None:
    try:
        async for db in get_db():
            db_payment = await crud.update_payment_status(
                db=db,
                payment_id=payment_id,
                status=models.Payment.STATUS_PAYED
            )
            return db_payment
    except Exception as exc:
        print(exc)
        return None