"""
Configuración centralizada de la aplicación utilizando Pydantic Settings.
Lee las variables de entorno definidas en el sistema o en el archivo .env.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Clase de configuración principal de la aplicación.
    Todos los valores pueden ser sobrescritos por variables de entorno.
    """

    # Identificación del Proyecto
    PROJECT_NAME: str = "ComboAPI - FastAPI Modular"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    API_V1_STR: str = "/api/v1"

    # Base de datos PostgreSQL (SQLAlchemy 2.x con psycopg3)
    # Ejemplo dentro de red Docker: postgresql+psycopg://combo_user:combo_super_password@postgres:5432/combo_db
    DATABASE_URL: str = (
        "postgresql+psycopg://combo_user:combo_super_password@localhost:5432/combo_db"
    )

    # Redis (Caché en memoria)
    # Ejemplo dentro de red Docker: redis://redis:6379/0
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_CACHE_TTL: int = 60  # Tiempo de vida de la caché en segundos (1 minuto)

    # MinIO (Almacenamiento de objetos S3 compatible)
    # Ejemplo dentro de red Docker: minio:9000
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minio_admin"
    MINIO_SECRET_KEY: str = "minio_super_secret_password"
    MINIO_BUCKET: str = "img"
    MINIO_BUCKET_ARCHIVOS: str = "archivos"  # Bucket para hojas de vida y documentos
    MINIO_SECURE: bool = False  # False para HTTP interno en Docker, True para HTTPS con SSL

    # Configuración de Pydantic Settings
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


# Instancia singleton accesible en toda la aplicación
settings = Settings()
