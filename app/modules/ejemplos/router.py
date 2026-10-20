"""
Router pedagógico y de salud del sistema.
Proporciona endpoints para validar el estado de todos los servicios conectados
y guías explicativas de cada componente arquitectónico.
"""

from typing import Dict, Any
from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy import text, func, select
from sqlalchemy.orm import Session
import redis

from app.core.config import settings
from app.core.database import get_db
from app.core.redis import get_redis, check_redis_health
from app.core.minio_client import minio_client, check_minio_health
from app.modules.usuarios.model import Usuario

router = APIRouter(tags=["Salud y Ejemplos Pedagógicos"])


# ==============================================================================
# Endpoint Global de Salud (/health)
# ==============================================================================
@router.get(
    "/health",
    summary="Verificar el estado de salud de todos los servicios",
    description="""
    Comprueba en tiempo real la conectividad de los 4 componentes:
    - **FastAPI**: El servidor web responde.
    - **PostgreSQL**: Se ejecuta con éxito una consulta `SELECT 1`.
    - **Redis**: El servidor responde al comando `PING`.
    - **MinIO**: El cliente S3 verifica la existencia del bucket configurado.
    
    Ideal para configurar el Healthcheck en **Coolify** o Docker Compose.
    """,
)
def verificar_salud(
    db: Session = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis),
):
    estado: Dict[str, str] = {
        "fastapi": "ok",
        "postgresql": "error",
        "redis": "error",
        "minio": "error",
    }

    # 1. Comprobar PostgreSQL
    try:
        db.execute(text("SELECT 1"))
        estado["postgresql"] = "ok"
    except Exception as e:
        estado["postgresql"] = f"error: {str(e)}"

    # 2. Comprobar Redis
    try:
        if redis_client.ping():
            estado["redis"] = "ok"
    except Exception as e:
        estado["redis"] = f"error: {str(e)}"

    # 3. Comprobar MinIO (ambos buckets)
    try:
        bucket_img = minio_client.bucket_exists(settings.MINIO_BUCKET)
        bucket_archivos = minio_client.bucket_exists(settings.MINIO_BUCKET_ARCHIVOS)
        if bucket_img and bucket_archivos:
            estado["minio"] = "ok"
        else:
            estado["minio"] = f"error: buckets no disponibles (img: {bucket_img}, archivos: {bucket_archivos})"
    except Exception as e:
        estado["minio"] = f"error: {str(e)}"

    todos_ok = all(v == "ok" for v in estado.values())
    codigo_http = status.HTTP_200_OK if todos_ok else status.HTTP_503_SERVICE_UNAVAILABLE

    return JSONResponse(status_code=codigo_http, content=estado)


# ==============================================================================
# Endpoint Pedagógico: PostgreSQL
# ==============================================================================
@router.get(
    "/ejemplos/postgresql",
    summary="Explicación y demostración de PostgreSQL con SQLAlchemy 2.x",
    description="Explica cómo funciona la persistencia y consulta estadísticas en vivo de la tabla de usuarios.",
)
def ejemplo_postgresql(db: Session = Depends(get_db)) -> Dict[str, Any]:
    conteo_usuarios = db.scalar(select(func.count(Usuario.id))) or 0
    return {
        "servicio": "PostgreSQL 16",
        "orm": "SQLAlchemy 2.x con psycopg3",
        "concepto": (
            "PostgreSQL es la base de datos relacional principal. En este proyecto se utiliza "
            "el patrón ORM (Object-Relational Mapping) moderno de SQLAlchemy 2.0 (DeclarativeBase, "
            "select(), Mapped y mapped_column)."
        ),
        "flujo_de_datos": [
            "1. El cliente envía un JSON al router de FastAPI.",
            "2. Pydantic valida los tipos de datos y restricciones.",
            "3. La capa Service crea la entidad SQLAlchemy.",
            "4. SQLAlchemy genera las sentencias SQL parametrizadas.",
            "5. PostgreSQL ejecuta y persiste la fila en disco.",
        ],
        "tabla_ejemplo": "usuarios",
        "total_usuarios_registrados": conteo_usuarios,
        "conexion_interna": settings.DATABASE_URL.split("@")[-1] if "@" in settings.DATABASE_URL else "configurada",
    }


# ==============================================================================
# Endpoint Pedagógico: Redis
# ==============================================================================
@router.get(
    "/ejemplos/redis",
    summary="Explicación y demostración del sistema de caché Redis",
    description="Demuestra cómo se utiliza Redis para acelerar lecturas y evitar sobrecarga en la base de datos.",
)
def ejemplo_redis(redis_client: redis.Redis = Depends(get_redis)) -> Dict[str, Any]:
    # Guardar una clave de prueba pedagógica
    clave_demo = "ejemplo:visitas"
    visitas = redis_client.incr(clave_demo)
    redis_client.expire(clave_demo, 300)

    # Contar claves actuales en Redis
    total_claves = len(redis_client.keys("*"))

    return {
        "servicio": "Redis 7 (In-Memory Data Store)",
        "concepto": (
            "Redis almacena pares clave-valor directamente en la memoria RAM del servidor. "
            "Permite lecturas con latencias menores a 1 milisegundo."
        ),
        "conceptos_clave": {
            "CACHE HIT": (
                "Ocurre cuando el dato solicitado ya existe en Redis. Se responde de inmediato "
                "sin consultar la base de datos PostgreSQL."
            ),
            "CACHE MISS": (
                "Ocurre cuando el dato no está en Redis (primera consulta o clave expirada). "
                "Se consulta PostgreSQL, se guarda el resultado en Redis y se devuelve al cliente."
            ),
            "TTL (Time-To-Live)": (
                f"Tiempo de vida configurado ({settings.REDIS_CACHE_TTL}s en este proyecto). "
                "Al expirar este tiempo, la clave se borra automáticamente de la memoria."
            ),
            "INVALIDACION": (
                "Cuando un registro es modificado (PUT) o eliminado (DELETE), se borra inmediatamente "
                "su clave en Redis para garantizar que no se sirvan datos obsoletos."
            ),
        },
        "contador_demo_visitas": visitas,
        "total_claves_actuales_en_redis": total_claves,
    }


# ==============================================================================
# Endpoint Pedagógico: MinIO
# ==============================================================================
@router.get(
    "/ejemplos/minio",
    summary="Explicación y demostración de MinIO (Almacenamiento de Objetos S3)",
    description="Explica la separación entre datos estructurados (PostgreSQL) y binarios (MinIO S3).",
)
def ejemplo_minio() -> Dict[str, Any]:
    buckets_info = {}
    for bucket in [settings.MINIO_BUCKET, settings.MINIO_BUCKET_ARCHIVOS]:
        objetos = []
        try:
            for obj in minio_client.list_objects(bucket, recursive=True):
                objetos.append({
                    "clave": obj.object_name,
                    "tamano_bytes": obj.size,
                    "ultima_modificacion": str(obj.last_modified),
                })
            buckets_info[bucket] = {
                "total_objetos": len(objetos),
                "objetos_recientes": objetos[:5],
            }
        except Exception as e:
            buckets_info[bucket] = {"error": str(e)}

    return {
        "servicio": "MinIO S3 Compatible Storage",
        "buckets_activos": {
            "img": f"Bucket '{settings.MINIO_BUCKET}' destinado a avatares e imágenes de perfil (JPG, PNG, WEBP)",
            "archivos": f"Bucket '{settings.MINIO_BUCKET_ARCHIVOS}' destinado a hojas de vida y documentos (PDF, DOC, DOCX, XLS, XLSX)",
        },
        "concepto": (
            "MinIO es un servidor de almacenamiento de objetos compatible con la API de Amazon S3. "
            "Está diseñado para almacenar grandes volúmenes de datos no estructurados como imágenes, videos y documentos."
        ),
        "buenas_practicas_implementadas": [
            "NO guardar binarios pesados (BLOBs) dentro de PostgreSQL, ya que saturan la memoria y degradan respaldos.",
            "Separar tipos de recursos en distintos buckets ('img' para avatares y 'archivos' para hojas de vida/anexos).",
            "Guardar el archivo físico en MinIO con nombres únicos (UUID) estructurados por usuario.",
            "Guardar únicamente los metadatos y la ruta de referencia en PostgreSQL.",
            "Servir los archivos desde FastAPI hacia el cliente usando StreamingResponse.",
        ],
        "estado_buckets": buckets_info,
    }
