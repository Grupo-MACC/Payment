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

async def create_wallet(user_id):
    try:
        async for db in get_db():
            db_wallet = await crud.create_wallet(db=db, user_id=user_id)
            return db_wallet
    except Exception as exc:
        return None

async def add_money_to_wallet(user_id, amount):
    try:
        async for db in get_db():
            db_wallet = await crud.get_element_by_id(db=db, model=models.CustomerWallet, element_id=user_id)
            new_amount = db_wallet.amount + amount
            db_wallet = await crud.update_wallet(db=db, user_id=user_id, amount=new_amount)
            return db_wallet
    except Exception as exc:
        return None

async def view_wallet(user_id: int):
    try:
        async for db in get_db():
            db_wallet = await crud.get_element_by_id(db=db, model=models.CustomerWallet, element_id=user_id)
            return db_wallet
    except Exception as exc:
        return None

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
                #else:
                    #todo
            db_payment = await crud.update_payment_status(
                db=db,
                payment_id=payment_id,
                status=models.Payment.STATUS_PAYED
            )
            return db_payment
    except Exception as exc:
        print(exc)
        return None