from sql import crud, models, schemas
from sqlalchemy.ext.asyncio import AsyncSession
import logging
from microservice_chassis_grupo2.core.dependencies import get_db


import logging
logger = logging.getLogger(__name__)

async def _get_or_create_wallet(db: AsyncSession, user_id: int) -> models.CustomerWallet:
    """Obtiene la wallet del usuario o la crea si no existe.

    Motivo:
        - Evita nulls y crashes en add_money/cmd.check.payment cuando la wallet aún no existe.
        - Centraliza el 'lazy creation' en un único punto (sin duplicar lógica).

    Nota:
        - Asumo que `crud.get_element_by_id(CustomerWallet, element_id=user_id)`
          busca por user_id (como ya estás usando en view_wallet).
    """
    wallet = await crud.get_element_by_id(
        db=db,
        model=models.CustomerWallet,
        element_id=int(user_id),
    )
    if wallet is not None:
        return wallet

    # Reutiliza la función existente (no inventes otra vía)
    wallet = await crud.create_wallet(db=db, user_id=int(user_id))
    if wallet is None:
        # Si create_wallet devuelve None, esto es un fallo real (DB, constraint, etc.)
        raise RuntimeError(f"No se pudo crear wallet para user_id={user_id}")

    return wallet

async def create_payment(payment: schemas.PaymentPost) -> models.Payment | None:
    """Crea un Payment en BD con status Initiated.

    Se usa desde el broker cuando llega el comando 'cmd.check.payment'.
    """
    try:
        async for db in get_db():
            return await crud.create_payment_from_schema(db=db, payment=payment)
    except Exception:
        logger.exception("create_payment failed (order_id=%s)", getattr(payment, "order_id", None))
        return None

async def create_wallet(user_id: int) -> models.CustomerWallet | None:
    """Crea la wallet si no existe (idempotente)."""
    try:
        async for db in get_db():
            return await _get_or_create_wallet(db=db, user_id=int(user_id))
    except Exception:
        logger.exception("create_wallet failed (user_id=%s)", user_id)
        return None

async def add_money_to_wallet(user_id: int, order_id: int, amount: int | None):
    """Añade dinero a la wallet del usuario (crea la wallet si no existe).

    Reglas:
        - Si amount es None, se calcula desde el Payment de la order.
        - Si la wallet no existe, se crea automáticamente.
        - Si faltan datos críticos, se lanza error (no se devuelve None silencioso).
    """
    async for db in get_db():
        # 1) Resolver amount si no viene
        if amount is None:
            db_payment = await crud.get_payment_by_order_id(db=db, order_id=order_id)
            if db_payment is None:
                raise ValueError(f"No existe payment para order_id={order_id}")
            amount = int(db_payment.amount_minor)

        # 2) Asegurar wallet
        db_wallet = await _get_or_create_wallet(db=db, user_id=int(user_id))

        # 3) Actualizar saldo
        new_amount = int(db_wallet.amount) + int(amount)
        db_wallet = await crud.update_wallet(db=db, user_id=int(user_id), amount=new_amount)
        return db_wallet


async def view_wallet(user_id: int):
    """Devuelve la wallet del usuario; si no existe, la crea.

    Mejora frente a tu apaño:
        - No devuelve objetos excepción.
        - No oculta errores reales con 'return None' / 'return exc'.
    """
    try:
        async for db in get_db():
            return await _get_or_create_wallet(db=db, user_id=int(user_id))
    except Exception:
        logger.exception("Error viewing wallet for user %s", user_id)
        raise


async def pay_payment(payment_id: int) -> models.Payment | None:
    """Paga un Payment descontando de la wallet.

    Cambio clave:
        - Asegura wallet antes de acceder a .amount (evita crash si no existe).
    """
    try:
        async for db in get_db():
            db_payment = await crud.get_element_by_id(db, models.Payment, payment_id)
            if db_payment is not None:
                user_id = int(db_payment.user_id)
                amount = int(db_payment.amount_minor)

                db_user_wallet = await _get_or_create_wallet(db=db, user_id=user_id)

                if int(db_user_wallet.amount) >= amount:
                    await crud.update_wallet(db, user_id, int(db_user_wallet.amount) - amount)
                else:
                    return None

            db_payment = await crud.update_payment_status(
                db=db,
                payment_id=payment_id,
                status=models.Payment.STATUS_PAYED
            )
            return db_payment
    except Exception as exc:
        logger.exception("pay_payment failed payment_id=%s", payment_id)
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
