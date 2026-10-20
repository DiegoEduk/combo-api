"""
Punto de Entrada Principal de la Aplicación FastAPI.
Configura el ciclo de vida (lifespan), inicialización de servicios,
registro de routers modulares y documentación Swagger.
"""

from contextlib import asynccontextmanager
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from app.core.config import settings
from app.core.database import init_db
from app.core.minio_client import init_minio
from app.modules.usuarios import usuarios_router
from app.modules.ejemplos import ejemplos_router

# Configuración básica de logs
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(name)s - %(message)s",
)
logger = logging.getLogger("combo_api")


# ------------------------------------------------------------------------------
# Manejador de ciclo de vida (Lifespan): Startup & Shutdown
# ------------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Gestiona el ciclo de vida de la aplicación.
    Se ejecuta al iniciar el servidor antes de recibir peticiones,
    y al detenerse para liberar recursos.
    """
    logger.info("==================================================")
    logger.info(f"Iniciando {settings.PROJECT_NAME} en modo {settings.ENVIRONMENT}...")
    logger.info("==================================================")

    # 1. Inicializar tablas en PostgreSQL
    try:
        init_db()
    except Exception as e:
        logger.error(f"Fallo al inicializar base de datos: {e}")

    # 2. Inicializar bucket en MinIO
    try:
        init_minio()
    except Exception as e:
        logger.error(f"Fallo al inicializar bucket de MinIO: {e}")

    logger.info("Sistema listo para recibir peticiones HTTP.")
    yield

    logger.info("Deteniendo la aplicación y cerrando recursos...")


# ------------------------------------------------------------------------------
# Instancia de FastAPI
# ------------------------------------------------------------------------------
app = FastAPI(
    title=settings.PROJECT_NAME,
    description="""
    ## 🚀 Proyecto Modular: FastAPI + PostgreSQL + Redis + MinIO
    
    Plantilla de arquitectura lista para desplegar en **Coolify** mediante Docker Compose.

    ### Servicios Integrados:
    * **FastAPI**: Backend REST moderno de alto rendimiento con validación mediante Pydantic v2.
    * **PostgreSQL (16)**: Persistencia relacional gestionada con **SQLAlchemy 2.x**.
    * **Redis (7)**: Caché ultrarrápida en memoria con demostración didáctica de **CACHE HIT** y **CACHE MISS**.
    * **MinIO (S3)**: Almacenamiento seguro de objetos e imágenes desacoplado de la base de datos.
    
    ### Red interna:
    Los servicios `postgres`, `redis` y `minio` no se encuentran expuestos a Internet. 
    FastAPI es el punto único de entrada y se comunica de manera privada con ellos.
    """,
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# Middleware de CORS (Permite conexiones desde clientes frontend / dashboard)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------------------------------------------------------------
# Registro de Routers Modulares
# ------------------------------------------------------------------------------
# Se registran directamente en la raíz para cumplir con las rutas solicitadas (/usuarios/ y /ejemplos/)
# y también con el prefijo /api/v1 para compatibilidad con APIs versionadas.
app.include_router(usuarios_router)
app.include_router(ejemplos_router)

# Soporte adicional para rutas versionadas /api/v1/usuarios
app.include_router(usuarios_router, prefix=settings.API_V1_STR, include_in_schema=False)


@app.get(
    "/",
    tags=["General"],
    summary="Página de inicio y estado general",
    description="Devuelve información de bienvenida y enlaces útiles a la documentación interactiva.",
)
def inicio():
    return {
        "proyecto": settings.PROJECT_NAME,
        "estado": "operativo",
        "documentacion_swagger": "/docs",
        "documentacion_redoc": "/redoc",
        "salud_servicios": "/health",
        "servicios": {
            "fastapi": "En ejecución (Puerto 8000)",
            "postgresql": "PostgreSQL 16 (Red interna: postgres:5432)",
            "redis": "Redis 7 (Red interna: redis:6379)",
            "minio": "MinIO S3 (Red interna: minio:9000)",
        },
    }
