from sql import crud, models, schemas
from microservice_chassis_grupo2.core.dependencies import get_db


import logging
logger = logging.getLogger(__name__)

async def create_payment(payment: schemas.PaymentPost) -> models.Payment | None:
    try:
        async for db in get_db():
            db_payment = await crud.create_payment_from_schema(db=db, payment=payment)
            return db_payment
    except Exception as exc:
        print(exc)
        return None

async def create_wallet(user_id):
    try:
        async for db in get_db():
            db_wallet = await crud.create_wallet(db=db, user_id=user_id)
            return db_wallet
    except Exception as exc:
        return None

async def add_money_to_wallet(user_id, order_id, amount):
    try:
        async for db in get_db():
            if amount is None:
                db_payment = await crud.get_payment_by_order_id(db=db, order_id=order_id)
                amount = db_payment.amount_minor
            db_wallet = await crud.get_element_by_id(db=db, model=models.CustomerWallet, element_id=user_id)
            new_amount = db_wallet.amount + amount
            db_wallet = await crud.update_wallet(db=db, user_id=user_id, amount=new_amount)
            return db_wallet
    except Exception as exc:
        return None

async def view_wallet(user_id: int):
    """
    Devuelve la wallet del usuario.

    Si el usuario no tiene wallet todavía, la crea (lazy creation).
    """
    try:
        async for db in get_db():
            db_wallet = await crud.get_element_by_id(
                db=db,
                model=models.CustomerWallet,
                element_id=user_id
            )

            # Si no existe wallet, la creamos
            if db_wallet is None:
                db_wallet = await crud.create_wallet(db=db, user_id=user_id)

            return db_wallet
    except Exception as exc:
        # OJO: esto oculta errores reales. Ideal: log + raise.
        logger.exception("Error viewing wallet for user %s", user_id)
        return exc

async def pay_payment(payment_id: int) -> models.Payment | None:
    try:
        async for db in get_db():
            
            db_payment = await crud.get_element_by_id(db, models.Payment, payment_id)
            if db_payment is not None:
                user_id = db_payment.user_id
                amount = db_payment.amount_minor
                db_user_wallet = await crud.get_element_by_id(db, models.CustomerWallet, user_id)
                if db_user_wallet.amount >= amount:
                    db_user_wallet = await crud.update_wallet(db, user_id, db_user_wallet.amount - amount)
                else:
                    return None
            db_payment = await crud.update_payment_status(
                db=db,
                payment_id=payment_id,
                status=models.Payment.STATUS_PAYED
            )
            return db_payment
    except Exception as exc:
        print(exc)
        return None