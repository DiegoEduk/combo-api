"""
Configuración del cliente de Caché Redis.
Gestiona el pool de conexiones y ofrece métodos utilitarios para
almacenar, consultar e invalidar datos en la caché en memoria.
"""

from typing import Optional, Generator
import logging
import redis
from app.core.config import settings

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------------------
# 1. Pool de conexiones Redis
# decode_responses=True para recibir strings (UTF-8) en lugar de bytes.
# ------------------------------------------------------------------------------
redis_pool = redis.ConnectionPool.from_url(
    settings.REDIS_URL,
    decode_responses=True,
    max_connections=20,
)

# Cliente global de Redis
redis_client: redis.Redis = redis.Redis(connection_pool=redis_pool)


def get_redis() -> Generator[redis.Redis, None, None]:
    """
    Dependencia de FastAPI para inyectar el cliente de Redis en routers o servicios.
    Uso: redis_db: redis.Redis = Depends(get_redis)
    """
    try:
        yield redis_client
    except Exception as e:
        logger.error(f"Error en la conexión a Redis: {e}")
        raise


def check_redis_health() -> bool:
    """
    Comprueba si el servidor Redis responde correctamente mediante ping().
    """
    try:
        return bool(redis_client.ping())
    except Exception as e:
        logger.warning(f"Fallo al contactar con Redis: {e}")
        return False
