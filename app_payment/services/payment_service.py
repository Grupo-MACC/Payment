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
    
async def refund_payment_by_order_id(order_id: int) -> tuple[bool, dict]:
    """Devuelve el dinero de una order a la wallet del usuario.

    Esta función es la pieza que necesita el SAGA de cancelación:
        - Entrada: order_id (el broker aporta saga_id, pero aquí no se usa)
        - Recupera el Payment asociado a esa order para obtener user_id y amount_minor
        - Suma el amount_minor a la wallet del usuario (creándola si no existe)
        - Marca el Payment como CANCELED para hacer la operación idempotente

    Idempotencia (pragmática y necesaria):
        - Si ya está en STATUS_CANCELED, NO vuelve a sumar dinero.
          Devuelve ok=True con flag already_refunded=True.

    Returns:
        (ok, info)
            ok=True:
                info = {
                    "user_id": int,
                    "amount_minor": int,
                    "already_refunded": bool
                }
            ok=False:
                info = {
                    "reason": str,
                    "order_id": int,
                }
    """
    try:
        async for db in get_db():
            db_payment = await crud.get_payment_by_order_id(db=db, order_id=order_id)
            if db_payment is None:
                return False, {"reason": "payment_not_found", "order_id": int(order_id)}

            # Ya reembolsado (idempotencia)
            if db_payment.status == models.Payment.STATUS_CANCELED:
                return True, {
                    "user_id": int(db_payment.user_id),
                    "amount_minor": int(db_payment.amount_minor),
                    "already_refunded": True,
                }

            # Solo reembolsamos si realmente estaba pagado
            if db_payment.status != models.Payment.STATUS_PAYED:
                return False, {
                    "reason": f"payment_not_refundable_status:{db_payment.status}",
                    "order_id": int(order_id),
                }

            # Asegura wallet (si no existe, la crea)
            db_wallet = await crud.get_element_by_id(
                db=db,
                model=models.CustomerWallet,
                element_id=int(db_payment.user_id),
            )
            if db_wallet is None:
                db_wallet = models.CustomerWallet(
                    user_id=int(db_payment.user_id),
                    amount=0,
                    currency=db_payment.currency,
                )
                db.add(db_wallet)
                await db.flush()

            # Refund + marcar cancelado en la MISMA transacción
            db_wallet.amount = int(db_wallet.amount) + int(db_payment.amount_minor)
            db_payment.status = models.Payment.STATUS_CANCELED

            await db.commit()
            await db.refresh(db_wallet)
            await db.refresh(db_payment)

            return True, {
                "user_id": int(db_payment.user_id),
                "amount_minor": int(db_payment.amount_minor),
                "already_refunded": False,
            }

    except Exception as exc:
        logger.exception("Error refunding order_id=%s", order_id)
        return False, {"reason": f"exception:{exc}", "order_id": int(order_id)}
