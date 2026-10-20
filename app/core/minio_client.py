"""
Configuración del cliente MinIO para almacenamiento de archivos S3 compatible.
Gestiona la inicialización automática del bucket y las operaciones de
subida, descarga y eliminación de objetos multimedia.
"""

from typing import Generator, BinaryIO, Optional
import logging
from minio import Minio
from minio.error import S3Error
from app.core.config import settings

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------------------
# 1. Instanciación del cliente MinIO
# En Docker se conecta a 'minio:9000' sin SSL (secure=False).
# ------------------------------------------------------------------------------
minio_client = Minio(
    endpoint=settings.MINIO_ENDPOINT,
    access_key=settings.MINIO_ACCESS_KEY,
    secret_key=settings.MINIO_SECRET_KEY,
    secure=settings.MINIO_SECURE,
)


def init_minio() -> None:
    """
    Verifica si el bucket configurado (ej. 'img') existe.
    Si no existe, lo crea automáticamente al iniciar la aplicación.
    """
    buckets_a_verificar = [settings.MINIO_BUCKET, settings.MINIO_BUCKET_ARCHIVOS]
    try:
        for bucket in buckets_a_verificar:
            logger.info(f"Comprobando existencia del bucket MinIO: '{bucket}'...")
            if not minio_client.bucket_exists(bucket):
                minio_client.make_bucket(bucket)
                logger.info(f"Bucket '{bucket}' creado exitosamente en MinIO.")
            else:
                logger.info(f"Bucket '{bucket}' ya existe y está listo para usarse.")
    except Exception as e:
        logger.error(f"Error al inicializar los buckets de MinIO: {e}")
        logger.warning("No se pudo conectar a MinIO durante el inicio. Se reintentará en cada petición.")


def get_minio() -> Generator[Minio, None, None]:
    """
    Dependencia de FastAPI para inyectar el cliente MinIO.
    Uso: minio_storage: Minio = Depends(get_minio)
    """
    yield minio_client


def upload_to_minio(
    object_name: str,
    data: BinaryIO,
    length: int,
    content_type: str,
    bucket_name: Optional[str] = None,
) -> str:
    """
    Sube un flujo binario al bucket de MinIO.
    Retorna el nombre o ruta del objeto guardado.
    """
    bucket = bucket_name or settings.MINIO_BUCKET
    minio_client.put_object(
        bucket_name=bucket,
        object_name=object_name,
        data=data,
        length=length,
        content_type=content_type,
    )
    return object_name


def get_from_minio(object_name: str, bucket_name: Optional[str] = None):
    """
    Recupera un objeto desde MinIO. Retorna la respuesta HTTP en streaming.
    El llamador es responsable de cerrar la respuesta después de leerla.
    """
    bucket = bucket_name or settings.MINIO_BUCKET
    return minio_client.get_object(bucket_name=bucket, object_name=object_name)


def delete_from_minio(object_name: str, bucket_name: Optional[str] = None) -> None:
    """
    Elimina un objeto del bucket de MinIO si existe.
    """
    bucket = bucket_name or settings.MINIO_BUCKET
    try:
        minio_client.remove_object(bucket_name=bucket, object_name=object_name)
    except S3Error as e:
        logger.warning(f"No se pudo eliminar el objeto '{object_name}' en MinIO: {e}")


def check_minio_health() -> bool:
    """
    Verifica si MinIO está operativo comprobando la existencia de los buckets configurados.
    """
    try:
        minio_client.bucket_exists(settings.MINIO_BUCKET)
        minio_client.bucket_exists(settings.MINIO_BUCKET_ARCHIVOS)
        return True
    except Exception as e:
        logger.warning(f"MinIO no responde en healthcheck: {e}")
        return False
