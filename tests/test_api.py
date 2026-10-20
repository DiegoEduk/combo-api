"""
Pruebas automatizadas de los endpoints y lógica del proyecto.
Utiliza base de datos SQLite en memoria y un cliente simulado de Redis
para verificar las operaciones sin requerir Docker en ejecución durante los tests.
"""

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.core.database import Base, get_db
from app.core.redis import get_redis

# Base de datos SQLite en memoria para tests
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine_test = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine_test)


# Simulación simple de Redis en memoria
class FakeRedis:
    def __init__(self):
        self.store = {}
        self.ttls = {}

    def get(self, key):
        return self.store.get(key)

    def setex(self, name, time, value):
        self.store[name] = value
        self.ttls[name] = time
        return True

    def delete(self, key):
        if key in self.store:
            del self.store[key]
            if key in self.ttls:
                del self.ttls[key]
            return 1
        return 0

    def ttl(self, key):
        return self.ttls.get(key, 60)

    def ping(self):
        return True

    def incr(self, key):
        val = int(self.store.get(key, 0)) + 1
        self.store[key] = str(val)
        return val

    def expire(self, key, time):
        self.ttls[key] = time
        return True

    def keys(self, pattern="*"):
        return list(self.store.keys())


fake_redis_instance = FakeRedis()


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


def override_get_redis():
    yield fake_redis_instance


# Sobrescribir dependencias de FastAPI
app.dependency_overrides[get_db] = override_get_db
app.dependency_overrides[get_redis] = override_get_redis

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine_test)
    fake_redis_instance.store.clear()
    fake_redis_instance.ttls.clear()
    yield
    Base.metadata.drop_all(bind=engine_test)


def test_inicio():
    """Verifica que el endpoint raíz responda correctamente."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["estado"] == "operativo"
    assert "/docs" in data["documentacion_swagger"]


def test_crud_usuarios_y_cache_redis():
    """
    Verifica el flujo completo:
    1. Crear usuario en BD (POST)
    2. Primera consulta -> CACHE MISS (PostgreSQL)
    3. Segunda consulta -> CACHE HIT (Redis)
    4. Actualizar usuario -> invalida caché (PUT)
    5. Tercera consulta -> CACHE MISS con nuevos datos
    6. Eliminar usuario (DELETE)
    """
    # 1. Crear usuario
    payload = {
        "nombre": "Carlos Ramírez",
        "email": "carlos@ejemplo.com",
        "edad": 28,
    }
    response_post = client.post("/usuarios/", json=payload)
    assert response_post.status_code == 201
    usuario_creado = response_post.json()
    user_id = usuario_creado["id"]
    assert usuario_creado["nombre"] == "Carlos Ramírez"
    assert usuario_creado["email"] == "carlos@ejemplo.com"

    # 2. Primera consulta GET -> CACHE MISS (PostgreSQL)
    response_miss = client.get(f"/usuarios/{user_id}")
    assert response_miss.status_code == 200
    data_miss = response_miss.json()
    assert data_miss["origen"] == "postgresql"
    assert "CACHE MISS" in data_miss["mensaje"]
    assert data_miss["usuario"]["id"] == user_id

    # 3. Segunda consulta GET -> CACHE HIT (Redis)
    response_hit = client.get(f"/usuarios/{user_id}")
    assert response_hit.status_code == 200
    data_hit = response_hit.json()
    assert data_hit["origen"] == "redis"
    assert "CACHE HIT" in data_hit["mensaje"]
    assert data_hit["usuario"]["id"] == user_id

    # 4. Actualizar usuario (PUT) -> invalida la clave en Redis
    update_payload = {"nombre": "Carlos A. Ramírez", "edad": 29}
    response_put = client.put(f"/usuarios/{user_id}", json=update_payload)
    assert response_put.status_code == 200
    assert response_put.json()["nombre"] == "Carlos A. Ramírez"
    assert response_put.json()["edad"] == 29

    # Verificar que la caché fue invalidada
    assert f"usuario:{user_id}" not in fake_redis_instance.store

    # 5. Tercera consulta GET -> CACHE MISS nuevamente con datos actualizados
    response_miss2 = client.get(f"/usuarios/{user_id}")
    assert response_miss2.status_code == 200
    data_miss2 = response_miss2.json()
    assert data_miss2["origen"] == "postgresql"
    assert data_miss2["usuario"]["nombre"] == "Carlos A. Ramírez"

    # 6. Eliminar usuario (DELETE)
    response_del = client.delete(f"/usuarios/{user_id}")
    assert response_del.status_code == 204

    # Verificar que ya no existe (404)
    response_404 = client.get(f"/usuarios/{user_id}")
    assert response_404.status_code == 404


def test_email_duplicado():
    """Verifica que no se permita registrar el mismo email dos veces."""
    payload = {"nombre": "Ana", "email": "ana@test.com", "edad": 30}
    r1 = client.post("/usuarios/", json=payload)
    assert r1.status_code == 201

    r2 = client.post("/usuarios/", json=payload)
    assert r2.status_code == 400
    assert "ya está registrado" in r2.json()["detail"]


def test_endpoints_pedagogicos():
    """Verifica los endpoints de ejemplos y explicación técnica."""
    # PostgreSQL
    r_pg = client.get("/ejemplos/postgresql")
    assert r_pg.status_code == 200
    assert "PostgreSQL" in r_pg.json()["servicio"]

    # Redis
    r_redis = client.get("/ejemplos/redis")
    assert r_redis.status_code == 200
    assert "CACHE HIT" in r_redis.json()["conceptos_clave"]

    # MinIO
    with patch("app.modules.ejemplos.router.minio_client.list_objects", return_value=[]):
        r_minio = client.get("/ejemplos/minio")
        assert r_minio.status_code == 200
        assert "buckets_activos" in r_minio.json()
        assert "archivos" in r_minio.json()["buckets_activos"]


def test_verificar_salud():
    """Verifica el endpoint de salud /health con mocks."""
    with patch("app.modules.ejemplos.router.minio_client.bucket_exists", return_value=True):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["fastapi"] == "ok"
        assert data["postgresql"] == "ok"
        assert data["redis"] == "ok"
        assert data["minio"] == "ok"


def test_subir_y_gestionar_archivos_hoja_vida():
    """
    Verifica el flujo completo de múltiples archivos de hoja de vida:
    1. Subir archivo PDF y DOCX al bucket 'archivos'
    2. Validar rechazo de extensiones no permitidas (.exe)
    3. Listar archivos del usuario
    4. Descargar archivo en streaming comprobando Content-Disposition
    5. Eliminar un archivo
    """
    # 1. Crear usuario previo
    res_user = client.post(
        "/usuarios/",
        json={"nombre": "Laura Gómez", "email": "laura@ejemplo.com", "edad": 26},
    )
    user_id = res_user.json()["id"]

    # Mock de upload_to_minio y get_from_minio para no requerir conexión real en test
    with patch("app.modules.usuarios.service.upload_to_minio") as mock_upload, \
         patch("app.modules.usuarios.service.delete_from_minio") as mock_delete:

        # 2. Subir PDF válido
        pdf_content = b"%PDF-1.4 Mock CV Content"
        files_pdf = {"archivo": ("mi_curriculum.pdf", pdf_content, "application/pdf")}
        res_pdf = client.post(f"/usuarios/{user_id}/archivos", files=files_pdf)
        assert res_pdf.status_code == 201
        data_pdf = res_pdf.json()["archivo"]
        pdf_id = data_pdf["id"]
        assert data_pdf["nombre_original"] == "mi_curriculum.pdf"
        assert data_pdf["extension"] == "pdf"
        assert data_pdf["bucket"] == "archivos"

        # 3. Subir archivo Word (.docx) válido
        docx_content = b"Mock Word document content"
        files_docx = {
            "archivo": (
                "certificados.docx",
                docx_content,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        }
        res_docx = client.post(f"/usuarios/{user_id}/archivos", files=files_docx)
        assert res_docx.status_code == 201
        data_docx = res_docx.json()["archivo"]
        docx_id = data_docx["id"]
        assert data_docx["nombre_original"] == "certificados.docx"
        assert data_docx["extension"] == "docx"

        # 4. Rechazar formato no permitido (.exe)
        exe_content = b"MZ executable"
        files_exe = {"archivo": ("malware.exe", exe_content, "application/octet-stream")}
        res_exe = client.post(f"/usuarios/{user_id}/archivos", files=files_exe)
        assert res_exe.status_code == 400
        assert "Formato no permitido" in res_exe.json()["detail"]

        # 5. Listar archivos del usuario
        res_list = client.get(f"/usuarios/{user_id}/archivos")
        assert res_list.status_code == 200
        archivos = res_list.json()
        assert len(archivos) == 2
        nombres = [a["nombre_original"] for a in archivos]
        assert "mi_curriculum.pdf" in nombres
        assert "certificados.docx" in nombres

        # 6. Descargar archivo en streaming
        class MockMinioStream:
            def stream(self, chunk_size):
                yield b"Fake streaming data"

        with patch("app.modules.usuarios.service.get_from_minio", return_value=MockMinioStream()):
            res_down = client.get(f"/usuarios/{user_id}/archivos/{pdf_id}")
            assert res_down.status_code == 200
            assert 'attachment; filename="mi_curriculum.pdf"' in res_down.headers["content-disposition"]
            assert res_down.content == b"Fake streaming data"

        # 7. Eliminar archivo individual
        res_del = client.delete(f"/usuarios/{user_id}/archivos/{pdf_id}")
        assert res_del.status_code == 200
        assert mock_delete.called

        # 8. Comprobar que queda 1 archivo
        res_list2 = client.get(f"/usuarios/{user_id}/archivos")
        assert len(res_list2.json()) == 1
