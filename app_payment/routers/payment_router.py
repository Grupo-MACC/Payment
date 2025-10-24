# -*- coding: utf-8 -*-
"""FastAPI router definitions."""
import logging
from typing import List
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from sql import crud
from sql import schemas
from microservice_chassis_grupo2.core.router_utils import raise_and_log_error
from microservice_chassis_grupo2.core.dependencies import get_current_user, get_db

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/payment",
    tags=["payment"]
)


@router.get(
    "/health",
    summary="Health check endpoint",
    response_model=schemas.Message,
)
async def health_check():
    """Endpoint to check if everything started correctly."""
    logger.debug("GET '/' endpoint called.")
    return {"detail": "OK"}


@router.get(
    "",
    response_model=List[schemas.Payment],
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
    responses={
        status.HTTP_200_OK: {"model": schemas.Payment, "description": "Requested Payment."},
        status.HTTP_404_NOT_FOUND: {"model": schemas.Message, "description": "Payment not found"},
    },
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