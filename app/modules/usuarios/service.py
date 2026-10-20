"""
Capa de Servicio para el Módulo de Usuarios.
Implementa la lógica de negocio completa:
- Persistencia en PostgreSQL con SQLAlchemy 2.0.
- Caché en Redis con patrón Cache-Aside (Hit / Miss e invalidación).
- Almacenamiento de archivos binarios en MinIO y persistencia de referencias en DB.
"""

from typing import List, Optional, Tuple, Any
import json
import uuid
import logging
from sqlalchemy import select
from sqlalchemy.orm import Session
from fastapi import HTTPException, status, UploadFile
import redis

from app.core.config import settings
from app.core.minio_client import upload_to_minio, get_from_minio, delete_from_minio
from app.modules.usuarios.model import Usuario, ArchivoUsuario
from app.modules.usuarios.schemas import (
    UsuarioCreate,
    UsuarioUpdate,
    UsuarioResponse,
    UsuarioConCacheResponse,
    ImagenSubidaResponse,
    ArchivoUsuarioResponse,
    SubidaArchivoResponse,
)

logger = logging.getLogger(__name__)

# Extensiones y tipos MIME permitidos para la subida de imágenes (Bucket 'img')
TIPOS_MIME_PERMITIDOS_IMAGENES = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}

# Extensiones y tipos MIME para archivos de hojas de vida y anexos (Bucket 'archivos')
TIPOS_ARCHIVOS_PERMITIDOS = {
    "pdf": "application/pdf",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xls": "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


# ==============================================================================
# 1. Operaciones CRUD en PostgreSQL
# ==============================================================================
def crear_usuario(db: Session, usuario_in: UsuarioCreate) -> Usuario:
    """
    Crea un nuevo usuario en la base de datos PostgreSQL.
    Valida previamente que el email no esté en uso.
    """
    # Verificar si el email ya existe usando sintaxis moderna SQLAlchemy 2.0
    stmt = select(Usuario).where(Usuario.email == usuario_in.email)
    usuario_existente = db.scalar(stmt)
    if usuario_existente:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"El correo '{usuario_in.email}' ya está registrado por otro usuario.",
        )

    # Crear la instancia del modelo SQLAlchemy
    nuevo_usuario = Usuario(
        nombre=usuario_in.nombre,
        email=usuario_in.email,
        edad=usuario_in.edad,
    )
    db.add(nuevo_usuario)
    db.commit()
    db.refresh(nuevo_usuario)
    logger.info(f"Usuario creado con éxito en PostgreSQL: ID {nuevo_usuario.id}")
    return nuevo_usuario


def listar_usuarios(db: Session, skip: int = 0, limit: int = 50) -> List[Usuario]:
    """
    Obtiene la lista de usuarios paginada desde PostgreSQL.
    """
    stmt = select(Usuario).offset(skip).limit(limit).order_by(Usuario.id.asc())
    return list(db.scalars(stmt).all())


def obtener_usuario_por_id_bd(db: Session, usuario_id: int) -> Usuario:
    """
    Busca un usuario directamente en PostgreSQL por su ID.
    Lanza error 404 si no existe.
    """
    stmt = select(Usuario).where(Usuario.id == usuario_id)
    usuario = db.scalar(stmt)
    if not usuario:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Usuario con ID {usuario_id} no encontrado en la base de datos.",
        )
    return usuario


# ==============================================================================
# 2. Operaciones con Caché en Redis (Patrón Cache-Aside)
# ==============================================================================
def obtener_usuario_por_id_con_cache(
    db: Session, redis_client: redis.Redis, usuario_id: int
) -> UsuarioConCacheResponse:
    """
    Consulta un usuario aplicando el patrón Cache-Aside:
    1. Busca en Redis:
       - Si existe -> CACHE HIT (devuelve dato de Redis inmediatamente).
    2. Si no existe -> CACHE MISS:
       - Consulta PostgreSQL.
       - Guarda el resultado en Redis con TTL (tiempo de expiración).
       - Devuelve el usuario indicando origen PostgreSQL.
    """
    clave_cache = f"usuario:{usuario_id}"

    # Paso 1: Intentar leer desde Redis
    try:
        dato_en_cache = redis_client.get(clave_cache)
    except Exception as e:
        logger.warning(f"Error al leer de Redis ({e}). Se consultará directamente la BD.")
        dato_en_cache = None

    if dato_en_cache:
        # ----------------------------------------------------------------------
        # CACHE HIT: El dato estaba en memoria RAM
        # ----------------------------------------------------------------------
        logger.info(f"[CACHE HIT] Usuario {usuario_id} encontrado en Redis.")
        try:
            ttl_restante = redis_client.ttl(clave_cache)
        except Exception:
            ttl_restante = None

        usuario_dict = json.loads(dato_en_cache)
        return UsuarioConCacheResponse(
            origen="redis",
            mensaje=(
                "⚡ CACHE HIT: Datos recuperados directamente desde la memoria RAM de Redis. "
                "No fue necesario consultar la base de datos PostgreSQL."
            ),
            tiempo_vida_cache_segundos=ttl_restante,
            usuario=UsuarioResponse.model_validate(usuario_dict),
        )

    # --------------------------------------------------------------------------
    # CACHE MISS: El dato no estaba en memoria, consultar PostgreSQL
    # --------------------------------------------------------------------------
    logger.info(f"[CACHE MISS] Usuario {usuario_id} no está en Redis. Consultando PostgreSQL...")
    usuario_bd = obtener_usuario_por_id_bd(db, usuario_id)

    # Serializar usuario a diccionario compatible con JSON
    usuario_respuesta = UsuarioResponse.model_validate(usuario_bd)
    usuario_dict = usuario_respuesta.model_dump(mode="json")

    # Paso 4: Guardar en Redis temporalmente con TTL configurado
    try:
        redis_client.setex(
            name=clave_cache,
            time=settings.REDIS_CACHE_TTL,
            value=json.dumps(usuario_dict),
        )
        logger.info(
            f"Usuario {usuario_id} guardado en Redis con TTL de {settings.REDIS_CACHE_TTL}s."
        )
    except Exception as e:
        logger.warning(f"No se pudo guardar en Redis: {e}")

    return UsuarioConCacheResponse(
        origen="postgresql",
        mensaje=(
            "🐘 CACHE MISS: El usuario no estaba en caché. Se consultó PostgreSQL y ahora "
            f"ha sido almacenado en Redis durante {settings.REDIS_CACHE_TTL} segundos. "
            "Las siguientes peticiones serán servidas por Redis."
        ),
        tiempo_vida_cache_segundos=settings.REDIS_CACHE_TTL,
        usuario=usuario_respuesta,
    )


def invalidar_cache_usuario(redis_client: redis.Redis, usuario_id: int) -> None:
    """
    Elimina la clave del usuario en Redis para evitar servir datos obsoletos
    cuando el registro es actualizado o eliminado.
    """
    clave_cache = f"usuario:{usuario_id}"
    try:
        eliminados = redis_client.delete(clave_cache)
        if eliminados:
            logger.info(f"Caché invalidada para {clave_cache} en Redis.")
    except Exception as e:
        logger.warning(f"No se pudo invalidar la caché en Redis para el usuario {usuario_id}: {e}")


def actualizar_usuario(
    db: Session,
    redis_client: redis.Redis,
    usuario_id: int,
    usuario_in: UsuarioUpdate,
) -> Usuario:
    """
    Actualiza la información de un usuario en PostgreSQL e invalida su caché en Redis.
    """
    usuario = obtener_usuario_por_id_bd(db, usuario_id)

    # Si se actualiza el email, verificar que no esté ocupado por otro usuario
    if usuario_in.email is not None and usuario_in.email != usuario.email:
        stmt = select(Usuario).where(Usuario.email == usuario_in.email)
        existente = db.scalar(stmt)
        if existente:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"El correo '{usuario_in.email}' ya pertenece a otro usuario.",
            )
        usuario.email = usuario_in.email

    if usuario_in.nombre is not None:
        usuario.nombre = usuario_in.nombre
    if usuario_in.edad is not None:
        usuario.edad = usuario_in.edad

    db.commit()
    db.refresh(usuario)

    # Invalidar inmediatamente la caché para asegurar consistencia
    invalidar_cache_usuario(redis_client, usuario_id)

    logger.info(f"Usuario {usuario_id} actualizado e invalidado de Redis.")
    return usuario


def eliminar_usuario(
    db: Session,
    redis_client: redis.Redis,
    usuario_id: int,
) -> None:
    """
    Elimina un usuario de PostgreSQL, su imagen de MinIO (si tenía) y su clave de Redis.
    """
    usuario = obtener_usuario_por_id_bd(db, usuario_id)

    # Si el usuario tiene una imagen en MinIO, eliminar el archivo binario
    if usuario.imagen:
        delete_from_minio(usuario.imagen, bucket_name=settings.MINIO_BUCKET)
        logger.info(f"Imagen '{usuario.imagen}' eliminada de MinIO al borrar usuario {usuario_id}.")

    # Si el usuario tiene archivos de hoja de vida en MinIO, eliminarlos del bucket 'archivos'
    for archivo_adjunto in usuario.archivos:
        delete_from_minio(archivo_adjunto.archivo_key, bucket_name=settings.MINIO_BUCKET_ARCHIVOS)
        logger.info(f"Archivo '{archivo_adjunto.archivo_key}' eliminado de MinIO al borrar usuario {usuario_id}.")

    # Eliminar registro de PostgreSQL (los registros en archivos_usuario se borran en cascada)
    db.delete(usuario)
    db.commit()

    # Invalidar caché en Redis
    invalidar_cache_usuario(redis_client, usuario_id)
    logger.info(f"Usuario {usuario_id} eliminado completamente del sistema.")


# ==============================================================================
# 3. Operaciones de Archivos Multimedia con MinIO
# ==============================================================================
async def subir_imagen_usuario(
    db: Session,
    redis_client: redis.Redis,
    usuario_id: int,
    archivo: UploadFile,
) -> ImagenSubidaResponse:
    """
    Sube un archivo de imagen a MinIO y guarda la referencia en PostgreSQL:
    1. Valida que el usuario exista.
    2. Valida tipo MIME permitido (JPG, PNG, WEBP).
    3. Genera una ruta única: 'usuarios/{usuario_id}/{uuid}.{ext}'.
    4. Sube los bytes binarios a MinIO (bucket 'img').
    5. Guarda la referencia en la columna 'imagen' de la tabla 'usuarios' en PostgreSQL.
    6. Invalida la caché del usuario en Redis.
    """
    usuario = obtener_usuario_por_id_bd(db, usuario_id)

    # 1. Validar formato MIME
    content_type = archivo.content_type or ""
    if content_type not in TIPOS_MIME_PERMITIDOS_IMAGENES:
        formatos_validos = ", ".join(TIPOS_MIME_PERMITIDOS_IMAGENES.keys())
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Formato no permitido ({content_type}). Tipos aceptados: {formatos_validos}",
        )

    # 2. Leer contenido en memoria
    contenido = await archivo.read()
    tamano = len(contenido)
    if tamano == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El archivo enviado está vacío.",
        )

    # 3. Si el usuario ya tenía una imagen previa, eliminarla de MinIO para no dejar huérfanos
    if usuario.imagen:
        delete_from_minio(usuario.imagen)

    # 4. Generar clave única del objeto en MinIO
    extension = TIPOS_MIME_PERMITIDOS_IMAGENES[content_type]
    identificador_unico = uuid.uuid4().hex
    clave_objeto = f"usuarios/{usuario_id}/{identificador_unico}.{extension}"

    # 5. Guardar en MinIO
    import io
    stream_datos = io.BytesIO(contenido)
    upload_to_minio(
        object_name=clave_objeto,
        data=stream_datos,
        length=tamano,
        content_type=content_type,
    )

    # 6. Guardar únicamente la referencia en PostgreSQL
    usuario.imagen = clave_objeto
    db.commit()
    db.refresh(usuario)

    # 7. Invalidar la caché en Redis
    invalidar_cache_usuario(redis_client, usuario_id)

    logger.info(
        f"Imagen para usuario {usuario_id} guardada en MinIO como '{clave_objeto}' "
        "y referenciada en PostgreSQL."
    )

    return ImagenSubidaResponse(
        mensaje="Imagen subida exitosamente a MinIO y referencia actualizada en PostgreSQL.",
        usuario_id=usuario_id,
        imagen_key=clave_objeto,
        bucket=settings.MINIO_BUCKET,
        tamano_bytes=tamano,
        content_type=content_type,
    )


def obtener_stream_imagen_usuario(
    db: Session,
    usuario_id: int,
) -> Tuple[Any, str]:
    """
    Recupera el stream de la imagen desde MinIO consultando la referencia en PostgreSQL.
    Retorna (stream_objeto, content_type) para usar con StreamingResponse.
    """
    usuario = obtener_usuario_por_id_bd(db, usuario_id)

    if not usuario.imagen:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"El usuario con ID {usuario_id} no tiene ninguna imagen de perfil asignada.",
        )

    try:
        respuesta_minio = get_from_minio(usuario.imagen)
        # Inferir content-type de los headers de MinIO o de la extensión
        content_type = (
            respuesta_minio.headers.get("content-type")
            or "application/octet-stream"
        )
        return respuesta_minio, content_type
    except Exception as e:
        logger.error(f"Error al descargar imagen '{usuario.imagen}' desde MinIO: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No fue posible recuperar la imagen desde el servidor de almacenamiento MinIO.",
        )


def eliminar_imagen_usuario(
    db: Session,
    redis_client: redis.Redis,
    usuario_id: int,
) -> None:
    """
    Elimina la imagen de un usuario en MinIO, pone en NULL el campo 'imagen' en PostgreSQL
    e invalida la caché en Redis.
    """
    usuario = obtener_usuario_por_id_bd(db, usuario_id)

    if not usuario.imagen:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"El usuario con ID {usuario_id} no tiene una imagen para eliminar.",
        )

    # Eliminar de MinIO
    delete_from_minio(usuario.imagen)

    # Limpiar campo en PostgreSQL
    usuario.imagen = None
    db.commit()
    db.refresh(usuario)

    # Invalidar caché en Redis
    invalidar_cache_usuario(redis_client, usuario_id)
    logger.info(f"Imagen del usuario {usuario_id} eliminada de MinIO y PostgreSQL.")


# ==============================================================================
# 4. Operaciones con Múltiples Archivos de Hoja de Vida (Bucket 'archivos')
# ==============================================================================
async def subir_archivo_hoja_vida(
    db: Session,
    usuario_id: int,
    archivo: UploadFile,
) -> SubidaArchivoResponse:
    """
    Sube un documento de hoja de vida o anexo (PDF, DOC, DOCX, XLS, XLSX)
    al bucket 'archivos' de MinIO y registra sus metadatos en PostgreSQL.
    """
    obtener_usuario_por_id_bd(db, usuario_id)

    nombre_original = archivo.filename or "documento"
    partes = nombre_original.rsplit(".", 1)
    extension = partes[1].lower() if len(partes) > 1 else ""

    content_type = archivo.content_type or ""

    # Validar formato permitido
    if extension not in TIPOS_ARCHIVOS_PERMITIDOS and content_type not in TIPOS_ARCHIVOS_PERMITIDOS.values():
        extensiones_validas = ", ".join(f".{ext}" for ext in TIPOS_ARCHIVOS_PERMITIDOS.keys())
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Formato no permitido para hoja de vida. Extensiones permitidas: {extensiones_validas}",
        )

    if not extension and content_type in TIPOS_ARCHIVOS_PERMITIDOS.values():
        for ext, mime in TIPOS_ARCHIVOS_PERMITIDOS.items():
            if mime == content_type:
                extension = ext
                break

    if content_type not in TIPOS_ARCHIVOS_PERMITIDOS.values() and extension in TIPOS_ARCHIVOS_PERMITIDOS:
        content_type = TIPOS_ARCHIVOS_PERMITIDOS[extension]

    contenido = await archivo.read()
    tamano = len(contenido)
    if tamano == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El archivo enviado está vacío.",
        )

    # Generar ruta única en el bucket de archivos
    uuid_archivo = uuid.uuid4().hex
    clave_objeto = f"hojas_de_vida/{usuario_id}/{uuid_archivo}.{extension}"

    import io
    stream_datos = io.BytesIO(contenido)
    upload_to_minio(
        object_name=clave_objeto,
        data=stream_datos,
        length=tamano,
        content_type=content_type,
        bucket_name=settings.MINIO_BUCKET_ARCHIVOS,
    )

    # Registrar metadatos en la tabla archivos_usuario de PostgreSQL
    nuevo_archivo = ArchivoUsuario(
        usuario_id=usuario_id,
        nombre_original=nombre_original,
        extension=extension,
        content_type=content_type,
        tamano_bytes=tamano,
        archivo_key=clave_objeto,
        bucket=settings.MINIO_BUCKET_ARCHIVOS,
    )
    db.add(nuevo_archivo)
    db.commit()
    db.refresh(nuevo_archivo)

    logger.info(
        f"Archivo '{nombre_original}' subido para el usuario {usuario_id} "
        f"en bucket '{settings.MINIO_BUCKET_ARCHIVOS}' con ID {nuevo_archivo.id}."
    )

    return SubidaArchivoResponse(
        mensaje=f"Archivo '{nombre_original}' guardado correctamente en el bucket '{settings.MINIO_BUCKET_ARCHIVOS}'.",
        archivo=ArchivoUsuarioResponse.model_validate(nuevo_archivo),
    )


def listar_archivos_usuario(db: Session, usuario_id: int) -> List[ArchivoUsuario]:
    """
    Retorna la lista de archivos de hoja de vida y anexos registrados para un usuario.
    """
    obtener_usuario_por_id_bd(db, usuario_id)

    stmt = (
        select(ArchivoUsuario)
        .where(ArchivoUsuario.usuario_id == usuario_id)
        .order_by(ArchivoUsuario.fecha_subida.desc())
    )
    return list(db.scalars(stmt).all())


def obtener_stream_archivo_usuario(
    db: Session,
    usuario_id: int,
    archivo_id: int,
) -> Tuple[Any, str, str]:
    """
    Recupera el stream de un archivo desde MinIO, su content-type y su nombre original.
    """
    obtener_usuario_por_id_bd(db, usuario_id)

    stmt = select(ArchivoUsuario).where(
        ArchivoUsuario.id == archivo_id,
        ArchivoUsuario.usuario_id == usuario_id,
    )
    archivo_db = db.scalar(stmt)
    if not archivo_db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Archivo con ID {archivo_id} no encontrado para el usuario {usuario_id}.",
        )

    try:
        respuesta_minio = get_from_minio(
            object_name=archivo_db.archivo_key,
            bucket_name=archivo_db.bucket,
        )
        return respuesta_minio, archivo_db.content_type, archivo_db.nombre_original
    except Exception as e:
        logger.error(f"Error al descargar archivo '{archivo_db.archivo_key}' desde MinIO: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al recuperar el archivo desde el bucket de MinIO.",
        )


def eliminar_archivo_usuario(
    db: Session,
    usuario_id: int,
    archivo_id: int,
) -> None:
    """
    Elimina un archivo físico de MinIO y su registro en PostgreSQL.
    """
    obtener_usuario_por_id_bd(db, usuario_id)

    stmt = select(ArchivoUsuario).where(
        ArchivoUsuario.id == archivo_id,
        ArchivoUsuario.usuario_id == usuario_id,
    )
    archivo_db = db.scalar(stmt)
    if not archivo_db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Archivo con ID {archivo_id} no encontrado para el usuario {usuario_id}.",
        )

    delete_from_minio(archivo_db.archivo_key, bucket_name=archivo_db.bucket)

    db.delete(archivo_db)
    db.commit()

    logger.info(f"Archivo {archivo_id} ('{archivo_db.nombre_original}') eliminado exitosamente.")
