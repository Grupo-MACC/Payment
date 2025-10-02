# -*- coding: utf-8 -*-
"""Util/Helper functions for router definitions."""
import logging
import os
from fastapi import HTTPException

logger = logging.getLogger(__name__)

# Para PAYMENT: hablamos con ORDER dentro de la red de Docker
ORDER_SERVICE_URL = os.getenv("ORDER_SERVICE_URL", "http://order:5000")

def raise_and_log_error(my_logger, status_code: int, message: str):
    """Raises HTTPException and logs an error."""
    my_logger.error(message)
    # ambas formas valen; esta es más explícita:
    raise HTTPException(status_code=status_code, detail=message)