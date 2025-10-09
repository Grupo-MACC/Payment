import pika
import json
import time
from broker.setup_rabbitmq import EXCHANGE_NAME, RABBITMQ_HOST
from services import payment_service
import threading

def handle_order_created(ch, method, properties, body):
    data = json.loads(body)
    #order = data['order_id']
    time.sleep(3)
    '''db_payment = payment_service.create_payment(payment=payment)

    routing_key = 'payment.failed'
    
    if db_payment is not None:
        time.sleep(3)
        db_payment = payment_service.pay_payment(payment_id=payment["payment_id"])
        if db_payment is not None:
            routing_key = 'payment.paid'''
    connection = pika.BlockingConnection(pika.ConnectionParameters(RABBITMQ_HOST))
    channel = connection.channel()

    channel.basic_publish(
        exchange=EXCHANGE_NAME,
        routing_key="payment.paid",
        body=json.dumps({"message": f"The order is paid."})
    )
    connection.close()


def consume_order_events():
    connection = pika.BlockingConnection(pika.ConnectionParameters(RABBITMQ_HOST))
    channel = connection.channel()

    channel.basic_consume(queue='payment_queue', on_message_callback=handle_order_created, auto_ack=True)

    channel.start_consuming()

def start_payment_broker_service():
    t = threading.Thread(target=consume_order_events, daemon=True)
    t.start()
    print("[PAYMENT BROKER] 🚀 Servicio de RabbitMQ lanzado en background")
