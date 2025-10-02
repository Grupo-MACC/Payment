# -*- coding: utf-8 -*-
"""FastAPI router definitions."""
import logging
import httpx
from typing import List
from fastapi import APIRouter, Depends, status, Body
from sqlalchemy.ext.asyncio import AsyncSession
from dependencies import get_db
from sql import crud
from sql import schemas
from .router_utils import raise_and_log_error, ORDER_SERVICE_URL

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get(
    "/",
    summary="Health check endpoint",
    response_model=schemas.Message,
)
async def health_check():
    """Endpoint to check if everything started correctly."""
    logger.debug("GET '/' endpoint called.")
    return {"detail": "OK"}


# Payments #########################################################################################
@router.post(
    "/payment",
    response_model=schemas.PaymentOut,
    summary="Create payment",
    status_code=status.HTTP_201_CREATED,
    tags=["Payment"]
)
async def create_payment(
    payment_schema: schemas.PaymentCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a payment for an order and (simulado) capturarlo."""
    logger.info("Request received to create payment for order %s.", payment_schema.order_id)

    # 1) Validar que el pedido existe en ORDER (igual que Order habla con Machine)
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{ORDER_SERVICE_URL}/order/{payment_schema.order_id}")
            r.raise_for_status()
    except Exception as net_exc:
        raise_and_log_error(
            logger,
            status.HTTP_502_BAD_GATEWAY,
            f"Failed to contact order service or order not found: {net_exc}"
        )

    # 2) Crear el pago en nuestra BD
    try:
        db_payment = await crud.create_payment_from_schema(db, payment_schema)
        # 3) (MVP) Marcarlo como 'Captured' directamente
        db_payment = await crud.update_payment_status(db, db_payment.id, "Captured")

        # 4) Notificar a ORDER (mismo estilo que en Order->Machine)
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                # usando el endpoint que ya tienes en order
                await client.put(
                    f"{ORDER_SERVICE_URL}/update_order_status/{payment_schema.order_id}",
                    params={"status": "Paid"}
                )
        except Exception as net_exc:
            logger.warning("Could not notify order service about payment capture: %s", net_exc)

        logger.info("Payment %s created & captured.", db_payment.id)
        return db_payment

    except ValueError as val_exc:
        raise_and_log_error(logger, status.HTTP_400_BAD_REQUEST, f"Invalid data: {val_exc}")
    except Exception as exc:
        raise_and_log_error(logger, status.HTTP_409_CONFLICT, f"Error creating payment: {exc}")


@router.get(
    "/payment",
    response_model=List[schemas.PaymentOut],
    summary="Retrieve payment list",
    tags=["Payment", "List"]
)
async def get_payment_list(
    db: AsyncSession = Depends(get_db)
):
    """Retrieve payment list."""
    logger.debug("GET '/payment' endpoint called.")
    return await crud.get_payment_list(db)


@router.get(
    "/payment/{payment_id}",
    summary="Retrieve single payment by id",
    responses={
        status.HTTP_200_OK: {"model": schemas.PaymentOut, "description": "Requested Payment."},
        status.HTTP_404_NOT_FOUND: {"model": schemas.Message, "description": "Payment not found"},
    },
    tags=["Payment"]
)
async def get_single_payment(
    payment_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Retrieve single payment by id."""
    logger.debug("GET '/payment/%i' endpoint called.", payment_id)
    payment = await crud.get_payment(db, payment_id)
    if not payment:
        raise_and_log_error(logger, status.HTTP_404_NOT_FOUND, f"Payment {payment_id} not found")
    return payment


@router.put(
    "/update_payment_status/{payment_id}",
    response_model=schemas.PaymentOut,
    tags=["Payment"]
)
async def update_payment_status(
    payment_id: int,
    status: str = Body(...),
    db: AsyncSession = Depends(get_db)
):
    """Update payment status (admin/dev)."""
    return await crud.update_payment_status(db=db, payment_id=payment_id, status=status)


@router.post(
    "/payment/{payment_id}/refund",
    response_model=schemas.PaymentOut,
    status_code=status.HTTP_200_OK,
    summary="Refund payment",
    tags=["Payment"]
)
async def refund_payment(
    payment_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Refund a captured payment."""
    payment = await crud.get_payment(db, payment_id)
    if not payment:
        raise_and_log_error(logger, status.HTTP_404_NOT_FOUND, f"Payment {payment_id} not found")
    if payment.status != "Captured":
        raise_and_log_error(logger, status.HTTP_409_CONFLICT, "Only captured payments can be refunded")

    return await crud.update_payment_status(db=db, payment_id=payment_id, status="Refunded")