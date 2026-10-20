"""
Configuración de la Base de Datos PostgreSQL utilizando SQLAlchemy 2.x.
Define el motor de conexión (Engine), la fábrica de sesiones (sessionmaker),
la clase base declarativa y la dependencia inyectable get_db().
"""

from typing import Generator
import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session
from app.core.config import settings

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------------------
# 1. Creación del motor de SQLAlchemy 2.x
# pool_pre_ping=True verifica la salud de la conexión antes de entregarla,
# evitando errores si la conexión se cierra por inactividad.
# ------------------------------------------------------------------------------
engine = create_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

# ------------------------------------------------------------------------------
# 2. Fábrica de sesiones (SessionLocal)
# Cada petición HTTP obtendrá una sesión independiente a través de get_db().
# ------------------------------------------------------------------------------
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


# ------------------------------------------------------------------------------
# 3. Clase Base para los modelos declarativos de SQLAlchemy 2.0
# Todos los modelos de la aplicación heredarán de esta clase Base.
# ------------------------------------------------------------------------------
class Base(DeclarativeBase):
    pass


# ------------------------------------------------------------------------------
# 4. Dependencia de FastAPI para obtener la sesión de base de datos
# Asegura que la sesión se cierre correctamente al finalizar cada petición.
# ------------------------------------------------------------------------------
def get_db() -> Generator[Session, None, None]:
    """
    Generador de dependencia para inyección de sesión de base de datos.
    Uso en routers: db: Session = Depends(get_db)
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """
    Crea las tablas definidas en los modelos si aún no existen.
    Se ejecuta al iniciar la aplicación FastAPI.
    """
    try:
        logger.info("Inicializando esquemas y tablas en PostgreSQL...")
        Base.metadata.create_all(bind=engine)
        logger.info("Tablas de PostgreSQL verificadas/creadas exitosamente.")
    except Exception as e:
        logger.error(f"Error al inicializar las tablas en PostgreSQL: {e}")
        raise
