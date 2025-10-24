from microservice_chassis_grupo2.core.rabbitmq_core import get_channel, declare_exchange

async def setup_rabbitmq():
    connection, channel = await get_channel()
    
    exchange = await declare_exchange()

    payment_queue = await channel.declare_queue('payment_queue', durable=True)

    await payment_queue.bind(exchange, routing_key='order.created')

    print("✅ RabbitMQ configurado correctamente (exchange + colas creadas).")

    connection.close()