# -*- coding: utf-8 -*-
"""FastAPI router definitions."""
import logging
from typing import List
from fastapi import APIRouter, Depends, status, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sql import crud, schemas
from services import payment_service
from microservice_chassis_grupo2.core.router_utils import raise_and_log_error
from microservice_chassis_grupo2.core.dependencies import get_current_user, get_db, check_public_key

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/payment",
    tags=["payment"]
)


@router.get("/health", include_in_schema=False)
async def health() -> dict:
    """ Healthcheck LIVENESS (para Consul / balanceadores). """
    return {"detail": "OK"}

@router.get(
    "/wallet"
)
async def get_user_wallet(
    user = Depends(get_current_user)
):
    return await payment_service.view_wallet(user)

@router.get(
    "",
    summary="Retrieve payment list",
    tags=["Payment", "List"]
)
async def get_payment_list(
    db: AsyncSession = Depends(get_db),
    user = Depends(get_current_user)
):
    """Retrieve payment list."""
    logger.debug("GET '/payment' endpoint called.")
    return await crud.get_payment_list(db)


@router.get(
    "/{payment_id}",
    summary="Retrieve single payment by id",
    tags=["Payment"]
)
async def get_single_payment(
    payment_id: int,
    db: AsyncSession = Depends(get_db),
    user = Depends(get_current_user)
):
    """Retrieve single payment by id."""
    logger.debug("GET '/payment/%i' endpoint called.", payment_id)
    payment = await crud.get_payment(db, payment_id)
    if not payment:
        raise_and_log_error(logger, status.HTTP_404_NOT_FOUND, f"Payment {payment_id} not found")
    return payment

@router.put(
    "/add/{amount}"
)
async def add_money_to_wallet(
    amount: int,
    db: AsyncSession = Depends(get_db),
    user = Depends(get_current_user)
):
    return await payment_service.add_money_to_wallet(user_id=user, order_id=None, amount=amount)