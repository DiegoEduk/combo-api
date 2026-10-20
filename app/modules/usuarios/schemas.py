"""
Esquemas Pydantic v2 para validación, serialización y documentación Swagger
del módulo de usuarios.
"""

from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel, ConfigDict, EmailStr, Field


# ------------------------------------------------------------------------------
# Esquemas Base y CRUD
# ------------------------------------------------------------------------------
class UsuarioBase(BaseModel):
    nombre: str = Field(
        ...,
        min_length=2,
        max_length=100,
        description="Nombre completo del usuario",
        examples=["Carlos Ramírez"],
    )
    email: EmailStr = Field(
        ...,
        description="Dirección de correo electrónico única",
        examples=["carlos@ejemplo.com"],
    )
    edad: Optional[int] = Field(
        None,
        ge=0,
        le=120,
        description="Edad del usuario en años",
        examples=[28],
    )


class UsuarioCreate(UsuarioBase):
    """Esquema para la creación de un nuevo usuario (POST /usuarios/)."""
    pass


class UsuarioUpdate(BaseModel):
    """
    Esquema para la actualización de un usuario existente (PUT /usuarios/{id}).
    Todos los campos son opcionales para permitir actualizaciones parciales.
    """
    nombre: Optional[str] = Field(
        None, min_length=2, max_length=100, examples=["Carlos A. Ramírez"]
    )
    email: Optional[EmailStr] = Field(
        None, examples=["carlos.nuevo@ejemplo.com"]
    )
    edad: Optional[int] = Field(None, ge=0, le=120, examples=[29])


class UsuarioResponse(UsuarioBase):
    """
    Esquema de respuesta estándar que incluye los campos generados por el servidor.
    """
    id: int = Field(..., description="Identificador único del usuario", examples=[1])
    imagen: Optional[str] = Field(
        None,
        description="Ruta/referencia de la imagen en MinIO (ej. 'usuarios/1/uuid.jpg')",
        examples=["usuarios/1/8f4d9f532ab34c6394d8.jpg"],
    )
    fecha_creacion: datetime = Field(
        ...,
        description="Fecha y hora de registro del usuario (UTC)",
    )

    model_config = ConfigDict(from_attributes=True)


# ------------------------------------------------------------------------------
# Esquemas Pedagógicos Especiales (Demostración de Redis y MinIO)
# ------------------------------------------------------------------------------
class UsuarioConCacheResponse(BaseModel):
    """
    Respuesta pedagógica que muestra explícitamente si el resultado
    provino de la caché en memoria (Redis) o de la base de datos (PostgreSQL).
    """
    origen: Literal["redis", "postgresql"] = Field(
        ...,
        description="Indica de dónde se obtuvo el dato ('redis' para CACHE HIT, 'postgresql' para CACHE MISS)",
        examples=["redis"],
    )
    mensaje: str = Field(
        ...,
        description="Explicación didáctica del estado de la caché",
        examples=["CACHE HIT: Datos recuperados directamente desde la memoria RAM de Redis en ~1ms"],
    )
    tiempo_vida_cache_segundos: Optional[int] = Field(
        None,
        description="Segundos restantes antes de que la clave expire en Redis (TTL)",
        examples=[58],
    )
    usuario: UsuarioResponse = Field(
        ...,
        description="Información completa del usuario",
    )


class ImagenSubidaResponse(BaseModel):
    """
    Respuesta al subir una imagen a MinIO y actualizar la referencia en PostgreSQL.
    """
    mensaje: str = Field(
        ...,
        examples=["Imagen subida a MinIO y referencia guardada en PostgreSQL exitosamente."],
    )
    usuario_id: int = Field(..., examples=[1])
    imagen_key: str = Field(
        ...,
        description="Referencia guardada en PostgreSQL que apunta al objeto en MinIO",
        examples=["usuarios/1/8f4d9f532ab34c6394d8.jpg"],
    )
    bucket: str = Field(..., examples=["img"])
    tamano_bytes: int = Field(..., examples=[1048576])
    content_type: str = Field(..., examples=["image/jpeg"])


class ArchivoUsuarioResponse(BaseModel):
    """
    Metadatos de un archivo de hoja de vida o anexo almacenado en MinIO (bucket 'archivos').
    """
    id: int = Field(..., description="ID único del archivo en la base de datos", examples=[1])
    usuario_id: int = Field(..., description="ID del usuario propietario", examples=[1])
    nombre_original: str = Field(
        ...,
        description="Nombre original con el que se subió el archivo",
        examples=["Curriculum_Carlos_2026.pdf"],
    )
    extension: str = Field(..., description="Extensión del archivo", examples=["pdf"])
    content_type: str = Field(..., description="Tipo MIME del documento", examples=["application/pdf"])
    tamano_bytes: int = Field(..., description="Tamaño del archivo en bytes", examples=[204850])
    archivo_key: str = Field(
        ...,
        description="Ruta/referencia del archivo binario dentro de MinIO",
        examples=["hojas_de_vida/1/a1b2c3d4e5.pdf"],
    )
    bucket: str = Field(..., description="Bucket de MinIO donde reside", examples=["archivos"])
    fecha_subida: datetime = Field(..., description="Fecha y hora de subida (UTC)")

    model_config = ConfigDict(from_attributes=True)


class SubidaArchivoResponse(BaseModel):
    """
    Respuesta detallada al subir un archivo de hoja de vida o documento.
    """
    mensaje: str = Field(
        ...,
        examples=["Archivo de hoja de vida almacenado exitosamente en MinIO."],
    )
    archivo: ArchivoUsuarioResponse
