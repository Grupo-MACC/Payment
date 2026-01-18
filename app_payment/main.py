# -*- coding: utf-8 -*-
"""Main file to start FastAPI application."""
import logging.config
import os
from contextlib import asynccontextmanager
import uvicorn
from fastapi import FastAPI
import asyncio
from routers import payment_router
from sql import init_db
from sqlalchemy.ext.asyncio import async_sessionmaker
from microservice_chassis_grupo2.sql import database, models
from broker import payment_broker_service
from consul_client import get_consul_client

# Configure logging ################################################################################
# logging.config.fileConfig(os.path.join(os.path.dirname(__file__), "logging.ini"))
logging.config.fileConfig(os.path.join(os.path.dirname(__file__), "logging.ini"),disable_existing_loggers=False,)
logger = logging.getLogger(__name__)


# App Lifespan #####################################################################################
@asynccontextmanager
async def lifespan(__app: FastAPI):
    """Lifespan context manager."""
    consul = get_consul_client()

    # Evita errores en finally si el startup falla antes de crear tareas
    task_pay = task_auth = task_user = None
    task_money_return_saga_confirm = task_money_return_saga_cancel = None

    try:
        logger.info("Starting up")
        
        # Registro "auto" (usa SERVICE_* y CONSUL_* desde entorno)
        ok = await consul.register_self()
        logger.info("✅ Consul register_self: %s", ok)

        # Asegura que el engine del chassis existe
        await database.init_database()
        if database.engine is None:
            raise RuntimeError(
                "database.engine sigue siendo None tras init_database(). "
                "Revisa el chassis (microservice_chassis_grupo2/sql/database.py)."
            )

        try:
            logger.info("Creating database tables")
            async with database.engine.begin() as conn:
                await conn.run_sync(models.Base.metadata.create_all)
        except Exception:
            logger.error(
                "Could not create tables at startup",
            )
        async_session = async_sessionmaker(database.engine, expire_on_commit=False)
        async with async_session() as session:
            await init_db(session)

        try:
            task_pay = asyncio.create_task(payment_broker_service.consume_pay_command())
            task_auth = asyncio.create_task(payment_broker_service.consume_auth_events())
            task_user = asyncio.create_task(payment_broker_service.consume_user_events())
            task_money_return_saga_confirm = asyncio.create_task(payment_broker_service.consume_return_money())
            task_money_return_saga_cancel = asyncio.create_task(payment_broker_service.consume_refund_command())

        except Exception as e:
            logger.error(f"❌ Error lanzando payment broker service: {e}")
        
        
        yield

    except Exception:
        logger.exception("Application startup failed.")
        raise

    finally:
        logger.info("Shutting down database")
        await database.engine.dispose()
        logger.info("Shutting down rabbitmq")
        task_pay.cancel()
        task_auth.cancel()
        task_user.cancel()
        task_money_return_saga_confirm.cancel()
        task_money_return_saga_cancel.cancel()
        
        # Shutdown database (seguro)
        if hasattr(database, "dispose_database"):
            await database.dispose_database()
        elif getattr(database, "engine", None) is not None:
            await database.engine.dispose()

        # Deregistro (auto) + cierre del cliente HTTP
        try:
            ok = await consul.deregister_self()
            logger.info("✅ Consul deregister_self: %s", ok)
        except Exception:
            logger.exception("Error desregistrando en Consul")

        try:
            await consul.aclose()
        except Exception:
            logger.exception("Error cerrando cliente Consul")

# OpenAPI Documentation ############################################################################
APP_VERSION = os.getenv("APP_VERSION", "2.0.0")
logger.info("Running app version %s", APP_VERSION)
DESCRIPTION = """
Monolithic manufacturing order application.
"""

tag_metadata = [
    {
        "name": "Machine",
        "description": "Endpoints related to machines",
    },
    {
        "name": "Order",
        "description": "Endpoints to **CREATE**, **READ**, **UPDATE** or **DELETE** orders.",
    },
    {
        "name": "Piece",
        "description": "Endpoints **READ** piece information.",
    },
    {
        "name": "Payment",
        "description": "Endpoints para **crear**, **consultar** y **actualizar** pagos.",
    },
]

app = FastAPI(
    redoc_url=None,  # disable redoc documentation.
    title="FastAPI - Monolithic app",
    description=DESCRIPTION,
    version=APP_VERSION,
    servers=[{"url": "/", "description": "Development"}],
    license_info={
        "name": "MIT License",
        "url": "https://choosealicense.com/licenses/mit/",
    },
    openapi_tags=tag_metadata,
    lifespan=lifespan,
)

app.include_router(payment_router.router)

if __name__ == "__main__":
    """
    Application entry point. Starts the Uvicorn server with SSL configuration.
    Runs the FastAPI application on host.
    """
    cert_file = os.getenv("SERVICE_CERT_FILE", "/certs/payment/payment-cert.pem")
    key_file = os.getenv("SERVICE_KEY_FILE", "/certs/payment/payment-key.pem")

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("SERVICE_PORT", "5003")),
        reload=True,
        ssl_certfile=cert_file,
        ssl_keyfile=key_file,
    )