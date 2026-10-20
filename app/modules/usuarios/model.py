"""
Modelo SQLAlchemy 2.x para las tablas 'usuarios' y 'archivos_usuario'.
Demuestra el mapeo objeto-relacional (ORM) para PostgreSQL y relaciones 1 a N.
"""

from datetime import datetime
from typing import Optional, List
from sqlalchemy import String, Integer, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class Usuario(Base):
    """
    Representa a un usuario en la base de datos PostgreSQL.

    Campos:
    - id: Clave primaria autoincremental.
    - nombre: Nombre completo del usuario.
    - email: Correo electrónico único.
    - edad: Edad del usuario en años (opcional).
    - imagen: RUTA / REFERENCIA de la foto de perfil en MinIO (bucket 'img').
    - fecha_creacion: Marca de tiempo de registro (UTC).
    - archivos: Relación 1 a N con sus archivos de hoja de vida en MinIO (bucket 'archivos').
    """

    __tablename__ = "usuarios"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, index=True
    )
    nombre: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(
        String(150), unique=True, index=True, nullable=False
    )
    edad: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    imagen: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, default=None
    )
    fecha_creacion: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relación 1 a N con sus documentos y archivos de hoja de vida
    archivos: Mapped[List["ArchivoUsuario"]] = relationship(
        "ArchivoUsuario",
        back_populates="usuario",
        cascade="all, delete-orphan",
        order_by="ArchivoUsuario.fecha_subida.desc()",
    )

    def __repr__(self) -> str:
        return f"<Usuario(id={self.id}, nombre='{self.nombre}', email='{self.email}')>"


class ArchivoUsuario(Base):
    """
    Representa un archivo de hoja de vida o documento adjunto de un usuario.
    El archivo binario se almacena en MinIO (bucket 'archivos') y en PostgreSQL
    se almacenan únicamente los metadatos y la ruta de referencia.
    """

    __tablename__ = "archivos_usuario"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, index=True
    )
    usuario_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("usuarios.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    nombre_original: Mapped[str] = mapped_column(String(255), nullable=False)
    extension: Mapped[str] = mapped_column(String(10), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    tamano_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    archivo_key: Mapped[str] = mapped_column(String(255), nullable=False)
    bucket: Mapped[str] = mapped_column(String(50), nullable=False, default="archivos")
    fecha_subida: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relación inversa hacia Usuario
    usuario: Mapped["Usuario"] = relationship("Usuario", back_populates="archivos")

    def __repr__(self) -> str:
        return (
            f"<ArchivoUsuario(id={self.id}, usuario_id={self.usuario_id}, "
            f"nombre='{self.nombre_original}', bucket='{self.bucket}')>"
        )
