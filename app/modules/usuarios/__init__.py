"""
Módulo de Usuarios: gestión completa de usuarios, persistencia en PostgreSQL,
caché en Redis y almacenamiento de imágenes en MinIO.
"""

from app.modules.usuarios.router import router as usuarios_router

__all__ = ["usuarios_router"]
