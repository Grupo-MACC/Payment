# -*- coding: utf-8 -*-
"""Broker RabbitMQ del microservicio Payment.

Responsabilidades:
    - Consumir comandos (exchange_command):
        * cmd.check.payment
        * cmd.return.money
        * cmd.refund (SAGA cancelación)
    - Consumir eventos generales (exchange):
        * auth.running / auth.not_running
        * user.created
    - Publicar eventos SAGA (exchange_saga):
        * evt.payment.checked
        * evt.money.returned
        * evt.refund.result / evt.refunded / evt.refund_failed
    - Publicar logs (exchange_logs):
        * payment.info / payment.error / payment.debug
"""

from __future__ import annotations

import asyncio
import json
import logging

import httpx
from aio_pika import Message

from consul_client import get_consul_client
from microservice_chassis_grupo2.core.rabbitmq_core import (
    PUBLIC_KEY_PATH,
    declare_exchange,
    declare_exchange_command,
    declare_exchange_logs,
    declare_exchange_saga,
    get_channel,
)
from services import payment_service
from sql import schemas

logger = logging.getLogger(__name__)

# =============================================================================
# Constantes RabbitMQ (routing keys / colas / topics)
# =============================================================================

# --- Comandos (Order → Payment) en exchange_command ---
RK_CMD_PAY = "cmd.check.payment"
RK_CMD_RETURN_MONEY = "cmd.return.money"
RK_CMD_REFUND = "cmd.refund"  # SAGA cancelación

QUEUE_PAY = "pay_queue"
QUEUE_RETURN_MONEY = "return_money_queue"
QUEUE_REFUND = "refund_queue"

# --- Eventos generales (exchange) ---
RK_AUTH_RUNNING = "auth.running"
RK_AUTH_NOT_RUNNING = "auth.not_running"
QUEUE_AUTH_EVENTS = "payment_queue"  # se mantiene por compatibilidad (nombre histórico)

RK_USER_CREATED = "user.created"
QUEUE_USER_CREATED = "user_created_queue"

# --- Eventos SAGA (Payment → Order) en exchange_saga ---
RK_EVT_PAYMENT_RESULT = "evt.payment.checked"

RK_EVT_MONEY_RETURNED = "evt.money.returned"

RK_EVT_REFUND_RESULT = "evt.refund.result"
RK_EVT_REFUNDED = "evt.refunded"
RK_EVT_REFUND_FAILED = "evt.refund_failed"

# --- Topics para logger ---
TOPIC_INFO = "payment.info"
TOPIC_ERROR = "payment.error"
TOPIC_DEBUG = "payment.debug"

# --- Reglas de negocio usadas en el broker ---
PRICE_PER_PIECE_EUR = 120
EUR_TO_MINOR = 100


# =============================================================================
# Helpers internos (evitan duplicación)
# =============================================================================
#region 0. HELPERS
def _build_json_message(payload: dict) -> Message:
    """Construye un Message JSON persistente (delivery_mode=2)."""
    return Message(
        body=json.dumps(payload).encode(),
        content_type="application/json",
        delivery_mode=2,
    )


async def _publish_saga_event(routing_key: str, payload: dict) -> None:
    """Publica un evento en exchange_saga con payload JSON."""
    connection, channel = await get_channel()
    try:
        exchange = await declare_exchange_saga(channel)
        await exchange.publish(_build_json_message(payload), routing_key=routing_key)
    finally:
        await connection.close()


# =============================================================================
# Handlers (consumidores)
# =============================================================================
#region 1. HANDLERS
async def handle_order_created(message) -> None:
    """Procesa el comando 'cmd.check.payment' (Order → Payment).

    Flujo:
        1) Crea un Payment (en BD).
        2) Intenta pagarlo descontando de la wallet.
        3) Publica evt.payment.checked a Order (SAGA existente).
        4) Loggea a exchange_logs.
    """
    async with message.process():
        data = json.loads(message.body)

        # Validación mínima del payload
        order_id = data.get("order_id")
        user_id = data.get("user_id")
        number_of_pieces = data.get("number_of_pieces")

        if order_id is None or user_id is None or number_of_pieces is None:
            logger.error("[PAYMENT] ❌ Payload inválido en 'cmd.check.payment': %s", data)
            await publish_to_logger(
                message={"message": "Payload inválido en cmd.check.payment", "payload": data},
                topic=TOPIC_ERROR,
            )
            return

        logger.info("[PAYMENT] 🟢 Procesando pago de order_id=%s (user_id=%s)", order_id, user_id)

        # Construcción del payment (misma lógica que tenías, solo ordenada)
        payment = schemas.PaymentPost(
            order_id=int(order_id),
            user_id=int(user_id),
            amount_minor=int(PRICE_PER_PIECE_EUR * int(number_of_pieces) * EUR_TO_MINOR),
            currency="EUR",
        )

        status = "paid"

        # 1) Crear pago
        db_payment = await payment_service.create_payment(payment=payment)
        if db_payment is None:
            status = "not_paid"
            logger.error("[PAYMENT] ❌ No se pudo crear Payment en BD (order_id=%s)", order_id)
        else:
            # 2) Intentar pagarlo
            db_payment_result = await payment_service.pay_payment(payment_id=db_payment.id)
            if db_payment_result is None:
                status = "not_paid"

        # 3) Log + 4) Publicación resultado SAGA
        if status == "paid":
            logger.info("[PAYMENT] ✅ Pago completado para order_id=%s", order_id)
            await publish_to_logger(
                message={"message": "Pago completado", "order_id": int(order_id)},
                topic=TOPIC_INFO,
            )
        else:
            logger.error("[PAYMENT] ❌ Pago fallido para order_id=%s", order_id)
            await publish_to_logger(
                message={"message": "Pago fallido", "order_id": int(order_id)},
                topic=TOPIC_ERROR,
            )

        await _publish_saga_event(
            routing_key=RK_EVT_PAYMENT_RESULT,
            payload={"status": status, "order_id": int(order_id)},
        )

        logger.info("[PAYMENT] 📤 Publicado evento %s → order_id=%s", RK_EVT_PAYMENT_RESULT, order_id)
        await publish_to_logger(
            message={
                "message": "Evento de pago publicado",
                "routing_key": RK_EVT_PAYMENT_RESULT,
                "order_id": int(order_id),
            },
            topic=TOPIC_DEBUG,
        )


async def handle_auth_events(message) -> None:
    """Gestiona eventos de auth.running / auth.not_running.

    Si auth está running:
        - Descubre auth via Consul
        - Descarga la public key
        - La guarda en PUBLIC_KEY_PATH
    """
    async with message.process():
        data = json.loads(message.body)
        status = data.get("status")

        # Solo actuamos ante "running" (como ya hacías)
        if status != "running":
            return

        try:
            auth_service_url = await get_consul_client().get_service_base_url("auth")
            logger.info("[PAYMENT] 🔍 Auth descubierto via Consul: %s", auth_service_url)

            async with httpx.AsyncClient() as client:
                response = await client.get(f"{auth_service_url}/auth/public-key")
                response.raise_for_status()
                public_key = response.text

            with open(PUBLIC_KEY_PATH, "w", encoding="utf-8") as f:
                f.write(public_key)

            logger.info("✅ Clave pública de Auth guardada en %s", PUBLIC_KEY_PATH)
            await publish_to_logger(
                message={"message": "Clave pública guardada", "path": PUBLIC_KEY_PATH},
                topic=TOPIC_INFO,
            )
        except Exception as exc:
            logger.error("[PAYMENT] ❌ Error obteniendo clave pública: %s", exc)
            await publish_to_logger(
                message={"message": "Error clave pública", "error": str(exc)},
                topic=TOPIC_ERROR,
            )


async def handle_user_events(message) -> None:
    """Crea la wallet al recibir user.created."""
    async with message.process():
        data = json.loads(message.body)
        user_id = data.get("user_id")

        if user_id is None:
            logger.error("[PAYMENT] ❌ Payload inválido en user.created: %s", data)
            await publish_to_logger(
                message={"message": "Payload inválido en user.created", "payload": data},
                topic=TOPIC_ERROR,
            )
            return

        await payment_service.create_wallet(user_id=int(user_id))
        logger.info("[PAYMENT] 👛 Wallet creada para user_id=%s", user_id)
        await publish_to_logger(
            message={"message": "Wallet creada", "user_id": int(user_id)},
            topic=TOPIC_INFO,
        )


async def handle_return_money(message) -> None:
    """Procesa cmd.return.money (comando legacy): devuelve dinero a la wallet por order_id."""
    async with message.process():
        data = json.loads(message.body)
        user_id = data.get("user_id")
        order_id = data.get("order_id")

        if user_id is None or order_id is None:
            logger.error("[PAYMENT] ❌ Payload inválido en cmd.return.money: %s", data)
            await publish_to_logger(
                message={"message": "Payload inválido en cmd.return.money", "payload": data},
                topic=TOPIC_ERROR,
            )
            return

        # add_money_to_wallet ya gestiona amount=None buscando el Payment por order_id
        await payment_service.add_money_to_wallet(
            user_id=int(user_id),
            order_id=int(order_id),
            amount=None,
        )

        await publish_money_returned(user_id=int(user_id), order_id=int(order_id))


# -------------------------
# SAGA CANCEL: refund command
# -------------------------
#region 2. SAGA CANCEL
async def handle_refund_command(message) -> None:
    """Procesa cmd.refund (Order → Payment) para la SAGA de cancelación.

    Payload mínimo esperado:
        {
          "order_id": 123,
          "saga_id": "uuid-..."
        }

    Resultado:
        - Ejecuta refund (wallet + estado Payment).
        - Publica SIEMPRE:
            * evt.refund.result
          y además:
            * evt.refunded o evt.refund_failed
    """
    async with message.process():
        data = json.loads(message.body)

        order_id = data.get("order_id")
        saga_id = data.get("saga_id") or data.get("sagaId")

        if order_id is None or saga_id is None:
            logger.error("[PAYMENT] ❌ cmd.refund inválido: %s", data)
            return

        ok, info = await payment_service.refund_payment_by_order_id(int(order_id))

        if ok:
            await publish_refund_events(
                saga_id=str(saga_id),
                order_id=int(order_id),
                status="refunded",
                user_id=info.get("user_id"),
                amount_minor=info.get("amount_minor"),
                already_refunded=bool(info.get("already_refunded")),
            )
        else:
            await publish_refund_events(
                saga_id=str(saga_id),
                order_id=int(order_id),
                status="refund_failed",
                reason=info.get("reason", "unknown"),
            )


# =============================================================================
# Consumers (setup colas + bindings)
# =============================================================================
#region 3. CONSUMERS
async def consume_pay_command() -> None:
    """Consumer del comando 'cmd.check.payment'."""
    connection, channel = await get_channel()
    exchange = await declare_exchange_command(channel)

    queue = await channel.declare_queue(QUEUE_PAY, durable=True)
    await queue.bind(exchange, routing_key=RK_CMD_PAY)
    await queue.consume(handle_order_created)

    logger.info("[PAYMENT] 🟢 Escuchando comando %s en cola %s", RK_CMD_PAY, QUEUE_PAY)
    await asyncio.Future()  # mantener viva la conexión


async def consume_auth_events() -> None:
    """Consumer de eventos de auth (exchange general)."""
    connection, channel = await get_channel()
    exchange = await declare_exchange(channel)

    queue = await channel.declare_queue(QUEUE_AUTH_EVENTS, durable=True)
    await queue.bind(exchange, routing_key=RK_AUTH_RUNNING)
    await queue.bind(exchange, routing_key=RK_AUTH_NOT_RUNNING)
    await queue.consume(handle_auth_events)

    logger.info("[PAYMENT] 🟢 Escuchando eventos auth.* en cola %s", QUEUE_AUTH_EVENTS)
    await publish_to_logger(message={"message": "Escuchando eventos de auth"}, topic=TOPIC_INFO)
    await asyncio.Future()


async def consume_user_events() -> None:
    """Consumer de user.created (exchange general)."""
    connection, channel = await get_channel()
    exchange = await declare_exchange(channel)

    queue = await channel.declare_queue(QUEUE_USER_CREATED, durable=True)
    await queue.bind(exchange, routing_key=RK_USER_CREATED)
    await queue.consume(handle_user_events)

    logger.info("[PAYMENT] 🟢 Escuchando %s en cola %s", RK_USER_CREATED, QUEUE_USER_CREATED)
    await publish_to_logger(message={"message": "Escuchando eventos user.created"}, topic=TOPIC_INFO)
    await asyncio.Future()


async def consume_return_money() -> None:
    """Consumer del comando cmd.return.money (legacy)."""
    connection, channel = await get_channel()
    exchange = await declare_exchange_command(channel)

    queue = await channel.declare_queue(QUEUE_RETURN_MONEY, durable=True)
    await queue.bind(exchange, routing_key=RK_CMD_RETURN_MONEY)
    await queue.consume(handle_return_money)

    logger.info("[PAYMENT] 🟢 Escuchando comando %s en cola %s", RK_CMD_RETURN_MONEY, QUEUE_RETURN_MONEY)
    await asyncio.Future()


async def consume_refund_command() -> None:
    """Consumer del comando cmd.refund (SAGA cancelación)."""
    connection, channel = await get_channel()
    exchange = await declare_exchange_command(channel)

    queue = await channel.declare_queue(QUEUE_REFUND, durable=True)
    await queue.bind(exchange, routing_key=RK_CMD_REFUND)
    await queue.consume(handle_refund_command)

    logger.info("[PAYMENT] 🟢 Escuchando comando %s en cola %s", RK_CMD_REFUND, QUEUE_REFUND)
    await asyncio.Future()


# =============================================================================
# Publishers específicos (SAGA / wallet)
# =============================================================================
#region 4. PUBLISHERS
async def publish_money_returned(user_id: int, order_id: int) -> None:
    """Publica evt.money.returned (evento saga/legacy) tras devolver dinero a wallet."""
    await _publish_saga_event(
        routing_key=RK_EVT_MONEY_RETURNED,
        payload={
            "message": "money_returned",
            "user_id": int(user_id),
            "order_id": int(order_id),
        },
    )
    logger.info("[PAYMENT] 📤 Publicado evento %s → user_id=%s order_id=%s", RK_EVT_MONEY_RETURNED, user_id, order_id)


async def publish_refund_events(
    saga_id: str,
    order_id: int,
    status: str,
    reason: str | None = None,
    user_id: int | None = None,
    amount_minor: int | None = None,
    already_refunded: bool = False,
) -> None:
    """Publica el resultado del refund para el SAGA de Order.

    Publica SIEMPRE:
        - evt.refund.result

    Además:
        - status == 'refunded'      → evt.refunded
        - status != 'refunded'      → evt.refund_failed
    """
    payload = {
        "saga_id": str(saga_id),
        "order_id": int(order_id),
        "status": str(status),
    }

    if user_id is not None:
        payload["user_id"] = int(user_id)
    if amount_minor is not None:
        payload["amount_minor"] = int(amount_minor)
    if already_refunded:
        payload["already_refunded"] = True
    if status != "refunded":
        payload["reason"] = reason or "unknown"

    # Publicación doble: result + evento específico
    connection, channel = await get_channel()
    try:
        exchange = await declare_exchange_saga(channel)

        await exchange.publish(_build_json_message(payload), routing_key=RK_EVT_REFUND_RESULT)

        specific_rk = RK_EVT_REFUNDED if status == "refunded" else RK_EVT_REFUND_FAILED
        await exchange.publish(_build_json_message(payload), routing_key=specific_rk)

        logger.info("[PAYMENT] 📤 Refund events publicados: %s -> order_id=%s saga_id=%s", specific_rk, order_id, saga_id)

        await publish_to_logger(
            message={"message": "Refund event published", "order_id": order_id, "saga_id": saga_id, "status": status},
            topic=TOPIC_INFO if status == "refunded" else TOPIC_ERROR,
        )
    finally:
        await connection.close()


# =============================================================================
# Logger publisher
# =============================================================================
#region 5. LOGGER
async def publish_to_logger(message: dict, topic: str) -> None:
    """Publica un log estructurado a exchange_logs.

    topic esperado:
        - payment.info / payment.error / payment.debug
    """
    connection = None
    try:
        connection, channel = await get_channel()
        exchange = await declare_exchange_logs(channel)

        parts = topic.split(".", 1)
        service = parts[0] if parts else "payment"
        severity = parts[1] if len(parts) == 2 else "info"

        log_data = {
            "measurement": "logs",
            "service": service,
            "severity": severity,
            **message,
        }

        await exchange.publish(_build_json_message(log_data), routing_key=topic)
    except Exception:
        logger.exception("[PAYMENT] Error publishing to logger")
    finally:
        if connection:
            await connection.close()
