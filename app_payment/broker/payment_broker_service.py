import json
import logging
import httpx
import asyncio
from aio_pika import Message
from services import payment_service
from sql import schemas
from microservice_chassis_grupo2.core.rabbitmq_core import get_channel, declare_exchange#, PUBLIC_KEY_PATH
from microservice_chassis_grupo2.core.router_utils import AUTH_SERVICE_URL

logger = logging.getLogger(__name__)

async def handle_order_created(message):
    async with message.process():
        data = json.loads(message.body)
        order_id = data['order_id']
        print(order_id)
        number_of_pieces = data['number_of_pieces']
        logger.info(f"[ORDER] 🟢 Procesando pedido {order_id}")

        # Simula retrasos de manera asíncrona si quieres

        # Crear pago (async)
        payment = schemas.PaymentPost(
            order_id=order_id,
            amount_minor=120 * number_of_pieces * 100,
            currency="EUR"
        )
        db_payment = await payment_service.create_payment(payment=payment)

        routing_key = 'payment.failed'
        print(db_payment)
        if db_payment is not None:
            # Pagar el pago (async)
            db_payment_result = await payment_service.pay_payment(payment_id=db_payment.id)
            if db_payment_result is not None:
                routing_key = 'payment.paid'

        # Publicar evento de resultado
        connection, _ = await get_channel()
        exchange = await declare_exchange()
        await exchange.publish(
            Message(
                body=json.dumps({
                    "message": "The order is paid." if routing_key == "payment.paid" else "Payment failed.",
                    "order_id": order_id
                }).encode()
            ),
            routing_key=routing_key
        )
        await connection.close()
        logger.info(f"[ORDER] 📤 Publicado evento {routing_key} → {order_id}")


async def consume_order_events():
    _, channel = await get_channel()
    exchange = await declare_exchange()

    # Declarar la cola por seguridad
    payment_queue = await channel.declare_queue("payment_queue", durable=True)

    # Declarar el binding por seguridad
    await payment_queue.bind(exchange, routing_key="order.created")

    # Suscribirse a los mensajes
    await payment_queue.consume(handle_order_created)

    logger.info("[ORDER] 🟢 Escuchando eventos de pedidos...")

    # Mantener el loop activo
    await asyncio.Future()

async def consume_auth_events():
    _, channel = await get_channel()
    
    exchange = await declare_exchange(channel)
    
    delivery_queue = await channel.declare_queue('delivery_queue', durable=True)
    await delivery_queue.bind(exchange, routing_key="auth.running")
    await delivery_queue.bind(exchange, routing_key="auth.not_running")
    
    await delivery_queue.consume(handle_auth_events)

async def handle_auth_events(message):
    async with message.process():
        data = json.loads(message.body)
        if data["status"] == "running":
            try:
                async with httpx.AsyncClient(
                    verify="/certs/ca.pem",
                    cert=("/certs/payment/order-cert.pem", "/certs/payment/order-key.pem"),
                ) as client:
                    response = await client.get(
                        f"{AUTH_SERVICE_URL}/auth/public-key"
                    )
                    response.raise_for_status()
                    public_key = response.text
                    
                    with open("PUBLIC_KEY_PATH", "w", encoding="utf-8") as f:
                        f.write(public_key)
                    
                    logger.info(f"✅ Clave pública de Auth guardada en {"PUBLIC_KEY_PATH"}")
            except Exception as exc:
                print(exc)