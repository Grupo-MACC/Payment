import json
import logging
import asyncio
from aio_pika import connect_robust, Message, ExchangeType
from services import payment_service
from sql import schemas
from broker.setup_rabbitmq import RABBITMQ_HOST, EXCHANGE_NAME


logger = logging.getLogger(__name__)

async def handle_order_created(message):
    async with message.process():
        data = json.loads(message.body)
        order_id = data['order_id']
        print(order_id)
        logger.info(f"[ORDER] 🟢 Procesando pedido {order_id}")

        # Simula retrasos de manera asíncrona si quieres

        # Crear pago (async)
        payment = schemas.PaymentPost(
            order_id=order_id,
            amount_minor=120,
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
        connection = await connect_robust(RABBITMQ_HOST)
        channel = await connection.channel()
        exchange = await channel.declare_exchange(EXCHANGE_NAME, ExchangeType.TOPIC, durable=True)
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
    connection = await connect_robust(RABBITMQ_HOST)
    channel = await connection.channel()

    # Declarar la cola por seguridad
    payment_queue = await channel.declare_queue("payment_queue", durable=True)

    # Declarar el binding por seguridad
    await payment_queue.bind(EXCHANGE_NAME, routing_key="order.created")

    # Suscribirse a los mensajes
    await payment_queue.consume(handle_order_created)

    logger.info("[ORDER] 🟢 Escuchando eventos de pedidos...")

    # Mantener el loop activo
    await asyncio.Future()
