#!/bin/bash

# Nombre y ID del servicio
SERVICE_NAME="payment"
SERVICE_ID="payment"
SERVICE_PORT=5003
CONSUL_HOST="10.1.11.40"  # IP del Consul agent
CONSULT_PORT=8501
TAGS='["payment","microservice"]'
META='{"version":"1.0"}'

# Detectar automáticamente la IP privada de la máquina actual
SERVICE_ADDRESS=$(hostname -I | awk '{print $1}')

# Hacer el registro en Consul
curl -s -X PUT "http://${CONSUL_HOST}:${CONSULT_PORT}/v1/agent/service/register" \
     -H "Content-Type: application/json" \
     -d "{
           \"ID\": \"${SERVICE_ID}\",
           \"Name\": \"${SERVICE_NAME}\",
           \"Address\": \"${SERVICE_ADDRESS}\",
           \"Port\": ${SERVICE_PORT},
           \"Tags\": ${TAGS},
           \"Meta\": ${META},
           \"Check\": {
             \"HTTP\": \"http://${SERVICE_ADDRESS}:${SERVICE_PORT}/docs\",
             \"Interval\": \"10s\",
             \"Timeout\": \"5s\"
           }
         }"

echo "Servicio ${SERVICE_NAME} registrado en Consul con IP ${SERVICE_ADDRESS}"
