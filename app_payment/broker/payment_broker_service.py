import json
import logging
import httpx
import asyncio
from aio_pika import Message
from services import payment_service
from sql import schemas
from microservice_chassis_grupo2.core.rabbitmq_core import get_channel, declare_exchange,declare_exchange_command,declare_exchange_saga, declare_exchange_logs, PUBLIC_KEY_PATH
from consul_client import get_service_url

logger = logging.getLogger(__name__)

async def handle_order_created(message):
    async with message.process():
        data = json.loads(message.body)
        order_id = data['order_id']
        user_id = data["user_id"]
        print(order_id)
        number_of_pieces = data['number_of_pieces']
        logger.info(f"[ORDER] 🟢 Procesando pedido {order_id}")

        # Simula retrasos de manera asíncrona si quieres

        # Crear pago (async)
        payment = schemas.PaymentPost(
            order_id=order_id,
            user_id=user_id,
            amount_minor=120 * number_of_pieces * 100,
            currency="EUR"
        )
        db_payment = await payment_service.create_payment(payment=payment)

        message = 'paid'
        routing_key = "payment.result"
        print(db_payment)
        if db_payment is not None:
            # Pagar el pago (async)
            db_payment_result = await payment_service.pay_payment(payment_id=db_payment.id)
            if db_payment_result is None:
                message = 'not_paid'
        # Publicar evento de resultado
        if message == 'paid':
            logger.info(f"[PAYMENT] ✅ Pago completado para order_id={order_id}")
            await publish_to_logger(
                message={"message": "Pago completado", "order_id": order_id},
                topic="payment.info"
            )
        else:
            logger.error(f"[PAYMENT] ❌ Pago fallido para order_id={order_id}")
            await publish_to_logger(
                message={"message": "Pago fallido", "order_id": order_id},
                topic="payment.error"
            )
        connection, channel = await get_channel()
        exchange = await declare_exchange_saga(channel)
        await exchange.publish(
            Message(
                body=json.dumps({
                    "status": message,
                    "order_id": order_id
                }).encode()
            ),
            routing_key=routing_key
        )
        await connection.close()
        logger.info(f"[ORDER] 📤 Publicado evento {routing_key} → {order_id}")
        await publish_to_logger(
            message={"message": "Evento de pago publicado", "routing_key": routing_key, "order_id": order_id},
            topic="payment.debug"
        )

async def consume_pay_command():
    _, channel = await get_channel()
    exchange = await declare_exchange_command(channel)

    # Declarar la cola por seguridad
    pay_queue = await channel.declare_queue("pay_queue", durable=True)

    # Declarar el binding por seguridad
    await pay_queue.bind(exchange, routing_key="pay")

    # Suscribirse a los mensajes
    await pay_queue.consume(handle_order_created)

    logger.info("[ORDER] 🟢 Escuchando eventos de pedidos...")

    # Mantener el loop activo
    await asyncio.Future()

async def consume_auth_events():
    _, channel = await get_channel()
    
    exchange = await declare_exchange(channel)
    
    payment_queue = await channel.declare_queue('payment_queue', durable=True)
    await payment_queue.bind(exchange, routing_key="auth.running")
    await payment_queue.bind(exchange, routing_key="auth.not_running")
    
    await payment_queue.consume(handle_auth_events)
    logger.info("[PAYMENT] 🟢 Escuchando eventos de auth...")
    await publish_to_logger(
        message={"message": "Escuchando eventos de auth"},
        topic="payment.info"
    )

async def handle_auth_events(message):
    async with message.process():
        data = json.loads(message.body)
        if data["status"] == "running":
            try:
                # Use Consul to discover auth service (no fallback)
                auth_service_url = await get_service_url("auth")
                logger.info(f"[PAYMENT] 🔍 Auth descubierto via Consul: {auth_service_url}")
                
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        f"{auth_service_url}/auth/public-key"
                    )
                    response.raise_for_status()
                    public_key = response.text
                    
                    with open(PUBLIC_KEY_PATH, "w", encoding="utf-8") as f:
                        f.write(public_key)
                    
                    logger.info(f"✅ Clave pública de Auth guardada en {PUBLIC_KEY_PATH}")
                    await publish_to_logger(
                        message={"message": "Clave pública guardada", "path": PUBLIC_KEY_PATH},
                        topic="payment.info"
                    )
            except Exception as exc:
                logger.error(f"[PAYMENT] ❌ Error obteniendo clave pública: {exc}")
                await publish_to_logger(
                    message={"message": "Error clave pública", "error": str(exc)},
                    topic="payment.error"
                )

async def consume_user_events():
    _, channel = await get_channel()
    
    exchange = await declare_exchange(channel)
    
    user_created_queue = await channel.declare_queue('user_created_queue', durable=True)
    await user_created_queue.bind(exchange, routing_key="user.created")
    
    await user_created_queue.consume(handle_user_events)
    logger.info("[PAYMENT] 🟢 Escuchando eventos user.created...")
    await publish_to_logger(
        message={"message": "Escuchando eventos user.created"},
        topic="payment.info"
    )

async def handle_user_events(messsage):
    async with messsage.process():
        data = json.loads(messsage.body)
        user_id = data["user_id"]
        db_wallet = await payment_service.create_wallet(user_id=user_id)
        logger.info(f"[PAYMENT] 👛 Wallet creada para user_id={user_id}")
        await publish_to_logger(
            message={"message": "Wallet creada", "user_id": user_id},
            topic="payment.info"
        )

async def consume_return_money():
    _, channel = await get_channel()
    
    exchange = await declare_exchange_command(channel)

    return_money_queue = await channel.declare_queue('return_money_queue', durable=True)
    await return_money_queue.bind(exchange, routing_key="return.money")

    await return_money_queue.consume(handle_return_money)

async def handle_return_money(messsage):
    async with messsage.process():
        data = json.loads(messsage.body)
        user_id = data["user_id"]
        order_id = data["order_id"]
        db_wallet = await payment_service.add_money_to_wallet(user_id=user_id, order_id=order_id, amount=None)
        await publish_money_returned(user_id=user_id, order_id=order_id)

async def publish_money_returned(user_id: int, order_id: int):
    connection, channel = await get_channel()
    exchange = await declare_exchange_saga(channel)
    await exchange.publish(
        Message(
            body=json.dumps({
                "message": "money_returned",
                "user_id": user_id,
                "order_id": order_id
            }).encode()
        ),
        routing_key="money.returned"
    )
    await connection.close()
    logger.info(f"[WALLET] 📤 Publicado evento money.returned → {user_id}")


#region SAGA CANCEL
# Order → Payment (command)
RK_CMD_REFUND = "cmd.refund"

# Payment → Order (events)
RK_EVT_REFUND_RESULT = "evt.refund.result"
RK_EVT_REFUNDED = "evt.refunded"
RK_EVT_REFUND_FAILED = "evt.refund_failed"

#region refund cmd
async def consume_refund_command():
    """Escucha el comando de refund emitido por Order (SAGA de cancelación).

    Garantía práctica:
        - En tu proyecto hay ambigüedad sobre en qué exchange se publican comandos.
          Para que funcione "sí o sí", esta cola se bindea a:
              * exchange_command
              * exchange (general)
              * exchange_saga
        - Y escucha tanto 'cmd.refund' como 'cmd_refund'.

    Esto evita el bug típico: "lo publico, pero nadie lo consume".
    """
    _, channel = await get_channel()

    exchange_cmd = await declare_exchange_command(channel)
    refund_queue = await channel.declare_queue("refund_queue", durable=True)
    await refund_queue.bind(exchange_cmd, routing_key=RK_CMD_REFUND)

    await refund_queue.consume(handle_refund_command)

    logger.info("[PAYMENT] 🟢 Escuchando cmd.refund (SAGA cancelación) en rks=%s", RK_CMD_REFUND)

    # Mantener el loop activo
    await asyncio.Future()


async def handle_refund_command(message):
    """Handler del comando cmd.refund.

    Payload esperado (mínimo):
        {
          "order_id": 123,
          "saga_id": "uuid-..."
        }

    Resultado:
        - Ejecuta refund en la wallet usando lógica existente (Payment + Wallet).
        - Publica el resultado en exchange_saga con:
            * refund.result (siempre)
            * evt_refunded o evt_refund_failed (según outcome)
    """
    async with message.process():
        data = json.loads(message.body)

        order_id = data.get("order_id")
        saga_id = data.get("saga_id") or data.get("sagaId")

        if order_id is None or saga_id is None:
            logger.error("[PAYMENT] ❌ cmd.refund inválido: %s", data)
            # Sin saga_id no tiene sentido responder al SAGA (no hay correlación)
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

#region refund evt
async def publish_refund_events(
    saga_id: str,
    order_id: int,
    status: str,
    reason: str | None = None,
    user_id: int | None = None,
    amount_minor: int | None = None,
    already_refunded: bool = False,
):
    """Publica el resultado del refund para el SAGA de Order.

    Publica SIEMPRE:
        - routing_key = refund.result

    Además:
        - si status == refunded       → evt_refunded
        - si status == refund_failed  → evt_refund_failed

    Esto cumple el informe SAGA y además mantiene compatibilidad con listeners antiguos.
    """
    connection, channel = await get_channel()
    try:
        exchange = await declare_exchange_saga(channel)

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

        def _msg():
            return Message(
                body=json.dumps(payload).encode(),
                content_type="application/json",
                delivery_mode=2,
            )

        # Siempre publicamos refund.result
        await exchange.publish(_msg(), routing_key=RK_EVT_REFUND_RESULT)

        # Y el evento específico de éxito/fracaso
        specific_rk = RK_EVT_REFUNDED if status == "refunded" else RK_EVT_REFUND_FAILED
        await exchange.publish(_msg(), routing_key=specific_rk)

        logger.info(
            "[PAYMENT] 📤 Refund events publicados: %s -> order_id=%s saga_id=%s",
            specific_rk, order_id, saga_id
        )

        await publish_to_logger(
            message={
                "message": "Refund event published",
                "order_id": order_id,
                "saga_id": saga_id,
                "status": status,
            },
            topic="payment.info" if status == "refunded" else "payment.error",
        )
    finally:
        await connection.close()


#region LOGGER
async def publish_to_logger(message: dict, topic: str):
    connection = None
    try:
        connection, channel = await get_channel()
        exchange = await declare_exchange_logs(channel)

        log_data = {
            "measurement": "logs",
            "service": topic.split(".")[0],
            "severity": topic.split(".")[1],
            **message,
        }

        msg = Message(
            body=json.dumps(log_data).encode(),
            content_type="application/json",
            delivery_mode=2
        )

        await exchange.publish(message=msg, routing_key=topic)
    except Exception as e:
        print(f"[PAYMENT] Error publishing to logger: {e}")
    finally:
        if connection:
            await connection.close()