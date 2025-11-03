#!/bin/bash
echo "Service: ${SERVICE_NAME}"
IP=$(hostname -i)
export IP
echo "IP: ${IP}"

terminate() {
  echo "Termination signal received, shutting down..."
  kill -SIGTERM "$UVICORN_PID"
  wait "$UVICORN_PID"
  echo "Uvicorn has been terminated"
}

trap terminate SIGTERM SIGINT

echo "Starting Uvicorn with TLS (mTLS enforced)..."

uvicorn app_payment.main:app \
  --host 0.0.0.0 \
  --port 5003 \
  --ssl-keyfile /certs/payment/payment-key.pem \
  --ssl-certfile /certs/payment/payment-cert.pem \
  --ssl-ca-certs /certs/ca.pem \
  --ssl-cert-reqs 1 & 

UVICORN_PID=$!

wait "$UVICORN_PID"