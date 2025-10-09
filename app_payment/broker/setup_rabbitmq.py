import pika

RABBITMQ_HOST = ""
EXCHANGE_NAME = "order_payment_exchange"

def setup_rabbitmq():
    connection = pika.BlockingConnection(pika.ConnectionParameters(RABBITMQ_HOST))
    channel = connection.channel()

    channel.exchange_declare(exchange=EXCHANGE_NAME, exchange_type='topic', durable=True)

    channel.queue_declare(queue='payment_queue', durable=True)

    channel.queue_bind(exchange=EXCHANGE_NAME, queue='payment_queue', routing_key='order.created')

    connection.close()