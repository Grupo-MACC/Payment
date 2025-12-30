FROM python:3.12-slim-bookworm

# Configuration will be done as root
USER root

# Update pip, copy requirements file and install dependencies
RUN pip install --no-cache-dir --upgrade pip;
COPY requirements.txt /requirements.txt
RUN pip install -r /requirements.txt

# We will be working on this folder
WORKDIR /home/pyuser/code
ENV PYTHONPATH=/home/pyuser/code/app_payment
#ENV SQLALCHEMY_DATABASE_URL=sqlite+aiosqlite:///./payment.db

ENV DB_USER=admin
ENV DB_PASSWORD=maccadmin
ENV DB_NAME=payment_db

ENV RABBITMQ_USER=guest
ENV RABBITMQ_PASSWORD=guest
ENV RABBITMQ_HOST=10.0.11.30
ENV PUBLIC_KEY_PATH=/home/pyuser/code/auth_public.pem
# Consul Service Discovery
ENV CONSUL_HOST=10.0.11.40
ENV CONSUL_PORT=8500
ENV SERVICE_NAME=payment
ENV SERVICE_PORT=5003
ENV SERVICE_ID=payment

# Create a non root user
RUN useradd -u 1000 -d /home/pyuser -m pyuser && \
    chown -R pyuser:pyuser /home/pyuser

# Copy the entrypoint script (executed when the container starts) and add execution permissions
COPY entrypoint.sh /home/pyuser/code/entrypoint.sh
RUN chmod +x /home/pyuser/code/entrypoint.sh

# Switch user so container is run as non-root user
USER 1000

# Copy the app to the container
COPY app_payment /home/pyuser/code/app_payment

# Run the application
ENTRYPOINT ["./entrypoint.sh"]


