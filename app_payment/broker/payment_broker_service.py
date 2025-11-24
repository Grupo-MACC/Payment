import json
import logging
import httpx
import asyncio
from aio_pika import Message
from services import payment_service
from sql import schemas
from microservice_chassis_grupo2.core.rabbitmq_core import get_channel, declare_exchange,declare_exchange_command,declare_exchange_saga, declare_exchange_logs, PUBLIC_KEY_PATH
from microservice_chassis_grupo2.core.router_utils import AUTH_SERVICE_URL

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
                async with httpx.AsyncClient(
                    verify="/certs/ca.pem",
                    cert=("/certs/payment/payment-cert.pem", "/certs/payment/payment-key.pem"),
                ) as client:
                    response = await client.get(
                        f"{AUTH_SERVICE_URL}/auth/public-key"
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