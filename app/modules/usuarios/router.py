"""
Router de FastAPI para el Módulo de Usuarios.
Expone los endpoints HTTP con documentación Swagger completa en español,
demostrando la interacción con PostgreSQL, la caché con Redis y el
almacenamiento de archivos con MinIO.
"""

from typing import List
from fastapi import (
    APIRouter,
    Depends,
    status,
    UploadFile,
    File,
    Path,
    Query,
)
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
import redis

from app.core.database import get_db
from app.core.redis import get_redis
from app.modules.usuarios.schemas import (
    UsuarioCreate,
    UsuarioUpdate,
    UsuarioResponse,
    UsuarioConCacheResponse,
    ImagenSubidaResponse,
    ArchivoUsuarioResponse,
    SubidaArchivoResponse,
)
from app.modules.usuarios import service

router = APIRouter(
    prefix="/usuarios",
    tags=["Usuarios (PostgreSQL + Redis + MinIO)"],
)


# ==============================================================================
# Endpoints CRUD (PostgreSQL)
# ==============================================================================
@router.post(
    "/",
    response_model=UsuarioResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear un nuevo usuario",
    description="""
    Registra un nuevo usuario en la base de datos **PostgreSQL**.
    
    - Valida que el email no se encuentre duplicado.
    - Asigna automáticamente una fecha de creación y un ID autoincremental.
    - Flujo: `Cliente -> FastAPI -> Router -> Service -> SQLAlchemy -> PostgreSQL`.
    """,
)
def crear_usuario(
    usuario_in: UsuarioCreate,
    db: Session = Depends(get_db),
):
    return service.crear_usuario(db=db, usuario_in=usuario_in)


@router.get(
    "/",
    response_model=List[UsuarioResponse],
    summary="Listar usuarios",
    description="""
    Retorna la lista de usuarios almacenados en **PostgreSQL** de forma paginada.
    """,
)
def listar_usuarios(
    skip: int = Query(0, ge=0, description="Número de registros a omitir (offset)"),
    limit: int = Query(50, ge=1, le=100, description="Límite máximo de registros a retornar"),
    db: Session = Depends(get_db),
):
    return service.listar_usuarios(db=db, skip=skip, limit=limit)


# ==============================================================================
# Endpoint con Demostración de Caché (Redis)
# ==============================================================================
@router.get(
    "/{id}",
    response_model=UsuarioConCacheResponse,
    summary="Consultar usuario por ID (Demostración CACHE HIT / CACHE MISS)",
    description="""
    Demuestra de forma interactiva el uso de **Redis** como sistema de caché rápida:

    1. **Primera petición (`CACHE MISS`)**:
       - Busca la clave `usuario:{id}` en Redis.
       - Al no encontrarla, consulta la base de datos **PostgreSQL**.
       - Guarda el usuario en Redis con un TTL (tiempo de vida) de 60 segundos.
       - Devuelve `origen: 'postgresql'`.

    2. **Peticiones posteriores dentro de los 60 segundos (`CACHE HIT`)**:
       - Encuentra el usuario directamente en la memoria RAM de **Redis**.
       - Responde de inmediato sin tocar PostgreSQL.
       - Devuelve `origen: 'redis'` junto con los segundos restantes de TTL.
    """,
)
def obtener_usuario(
    id: int = Path(..., ge=1, description="ID del usuario a consultar"),
    db: Session = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis),
):
    return service.obtener_usuario_por_id_con_cache(
        db=db, redis_client=redis_client, usuario_id=id
    )


@router.put(
    "/{id}",
    response_model=UsuarioResponse,
    summary="Actualizar un usuario (con invalidación de caché)",
    description="""
    Actualiza los datos de un usuario en **PostgreSQL**.
    
    **Comportamiento de Caché**:
    - Al modificar los datos, invalida (elimina) automáticamente la clave `usuario:{id}` en **Redis**.
    - La próxima llamada a `GET /usuarios/{id}` generará un nuevo `CACHE MISS` y refrescará la memoria con los datos actualizados.
    """,
)
def actualizar_usuario(
    id: int = Path(..., ge=1, description="ID del usuario a actualizar"),
    usuario_in: UsuarioUpdate = ...,
    db: Session = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis),
):
    return service.actualizar_usuario(
        db=db, redis_client=redis_client, usuario_id=id, usuario_in=usuario_in
    )


@router.delete(
    "/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar un usuario",
    description="""
    Elimina permanentemente un usuario:
    - Borra el registro en **PostgreSQL**.
    - Elimina la imagen asociada en el bucket de **MinIO** si existía.
    - Invalida la clave en **Redis**.
    """,
)
def eliminar_usuario(
    id: int = Path(..., ge=1, description="ID del usuario a eliminar"),
    db: Session = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis),
):
    service.eliminar_usuario(db=db, redis_client=redis_client, usuario_id=id)
    return None


# ==============================================================================
# Endpoints de Gestión de Imágenes (MinIO)
# ==============================================================================
@router.post(
    "/{id}/imagen",
    response_model=ImagenSubidaResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Subir imagen de perfil a MinIO",
    description="""
    Demuestra el almacenamiento desacoplado de archivos en **MinIO (S3)**:

    1. FastAPI recibe el archivo multimedia (JPG, PNG o WEBP).
    2. Valida tipo MIME y genera un nombre único (`usuarios/{id}/{uuid}.ext`).
    3. Sube el binario al bucket `img` en **MinIO**.
    4. Guarda **únicamente la clave/referencia** en la columna `imagen` de PostgreSQL.
       *(No se guarda el archivo binario pesado en la base de datos).*
    5. Invalida la caché del usuario en Redis.
    """,
)
async def subir_imagen_usuario(
    id: int = Path(..., ge=1, description="ID del usuario"),
    archivo: UploadFile = File(
        ...,
        description="Archivo de imagen (formatos permitidos: JPG, PNG, WEBP)",
    ),
    db: Session = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis),
):
    return await service.subir_imagen_usuario(
        db=db,
        redis_client=redis_client,
        usuario_id=id,
        archivo=archivo,
    )


@router.get(
    "/{id}/imagen",
    summary="Descargar o visualizar la imagen de un usuario desde MinIO",
    description="""
    Recupera y transmite la imagen directamente al cliente:
    
    1. Consulta en **PostgreSQL** la referencia `imagen` del usuario.
    2. Conecta internamente con **MinIO** usando el nombre del servicio Docker (`minio:9000`).
    3. Descarga el stream del bucket `img` y lo transmite al cliente mediante `StreamingResponse`.
    """,
    responses={
        200: {
            "content": {
                "image/jpeg": {},
                "image/png": {},
                "image/webp": {},
            },
            "description": "Flujo binario de la imagen solicitada",
        }
    },
)
def obtener_imagen_usuario(
    id: int = Path(..., ge=1, description="ID del usuario"),
    db: Session = Depends(get_db),
):
    stream_minio, content_type = service.obtener_imagen_usuario(
        db=db, usuario_id=id
    )
    return StreamingResponse(
        stream_minio.stream(32 * 1024),
        media_type=content_type,
    )


@router.delete(
    "/{id}/imagen",
    status_code=status.HTTP_200_OK,
    summary="Eliminar la imagen de un usuario",
    description="""
    Elimina el archivo binario del bucket en **MinIO**, actualiza la columna `imagen` a `NULL`
    en **PostgreSQL** e invalida la caché en **Redis**.
    """,
)
def eliminar_imagen_usuario(
    id: int = Path(..., ge=1, description="ID del usuario"),
    db: Session = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis),
):
    service.eliminar_imagen_usuario(db=db, redis_client=redis_client, usuario_id=id)
    return {
        "mensaje": f"Imagen del usuario {id} eliminada correctamente de MinIO y base de datos."
    }


# ==============================================================================
# Endpoints de Gestión de Hojas de Vida y Documentos (Bucket 'archivos')
# ==============================================================================
@router.post(
    "/{id}/archivos",
    response_model=SubidaArchivoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Subir archivo de hoja de vida o documento al bucket 'archivos'",
    description="""
    Permite a un usuario subir múltiples documentos adjuntos para su expediente u hoja de vida:
    - **Formatos permitidos**: PDF (`.pdf`), Word (`.doc`, `.docx`), Excel (`.xls`, `.xlsx`).
    - **Almacenamiento**:
      - El archivo binario físico se guarda en **MinIO** en el bucket dedicado `archivos` con ruta `hojas_de_vida/{id}/{uuid}.ext`.
      - En **PostgreSQL** se registran los metadatos: nombre original, tipo MIME, tamaño en bytes y fecha en la tabla `archivos_usuario`.
    """,
)
async def subir_archivo_usuario(
    id: int = Path(..., ge=1, description="ID del usuario"),
    archivo: UploadFile = File(
        ...,
        description="Archivo de hoja de vida (PDF, DOC, DOCX, XLS, XLSX)",
    ),
    db: Session = Depends(get_db),
):
    return await service.subir_archivo_hoja_vida(
        db=db, usuario_id=id, archivo=archivo
    )


@router.get(
    "/{id}/archivos",
    response_model=List[ArchivoUsuarioResponse],
    summary="Listar todos los archivos de hoja de vida del usuario",
    description="""
    Retorna la lista de todos los documentos y archivos subidos por el usuario,
    ordenados del más reciente al más antiguo.
    """,
)
def listar_archivos_usuario(
    id: int = Path(..., ge=1, description="ID del usuario"),
    db: Session = Depends(get_db),
):
    return service.listar_archivos_usuario(db=db, usuario_id=id)


@router.get(
    "/{id}/archivos/{archivo_id}",
    summary="Descargar un archivo de hoja de vida desde MinIO",
    description="""
    Descarga el archivo físico en streaming desde el bucket `archivos` de MinIO,
    estableciendo el encabezado `Content-Disposition` para que el navegador lo guarde
    con su nombre original.
    """,
)
def descargar_archivo_usuario(
    id: int = Path(..., ge=1, description="ID del usuario"),
    archivo_id: int = Path(..., ge=1, description="ID del archivo a descargar"),
    db: Session = Depends(get_db),
):
    stream_minio, content_type, nombre_original = service.obtener_stream_archivo_usuario(
        db=db, usuario_id=id, archivo_id=archivo_id
    )
    headers = {
        "Content-Disposition": f'attachment; filename="{nombre_original}"'
    }
    return StreamingResponse(
        stream_minio.stream(32 * 1024),
        media_type=content_type,
        headers=headers,
    )


@router.delete(
    "/{id}/archivos/{archivo_id}",
    status_code=status.HTTP_200_OK,
    summary="Eliminar un archivo de hoja de vida",
    description="""
    Elimina el archivo binario del bucket `archivos` en MinIO y elimina
    el registro de metadatos en la tabla `archivos_usuario` de PostgreSQL.
    """,
)
def eliminar_archivo_usuario(
    id: int = Path(..., ge=1, description="ID del usuario"),
    archivo_id: int = Path(..., ge=1, description="ID del archivo a eliminar"),
    db: Session = Depends(get_db),
):
    service.eliminar_archivo_usuario(db=db, usuario_id=id, archivo_id=archivo_id)
    return {
        "mensaje": f"Archivo {archivo_id} eliminado exitosamente de MinIO y PostgreSQL."
    }
