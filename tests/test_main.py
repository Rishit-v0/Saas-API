import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy import text as sa_text
from sqlalchemy.orm import sessionmaker
from app.main import app
from app.database import Base, get_db
from urllib.parse import quote_plus
import os


# Use a separate test database — never run tests against your dev DB
# Tests create and destroy data rapidly — you don't want that in dev
# ── Build both URLs ────────────────────────────────────────────────────────────

ADMIN_URL = URL.create(
    drivername="postgresql",
    username=os.getenv("DATABASE_USER"),
    password=os.getenv("DATABASE_PASSWORD"),
    host=os.getenv("TEST_DATABASE_HOST", "localhost"),
    port=int(os.getenv("DATABASE_PORT", "5432")),
    database="postgres",  # the one CI created — always exists
)

# ✅ Fixed: use DATABASE_NAME from env so it matches what CI actually creates.
#    Also cast DATABASE_PORT to int — URL.create() requires it.
TEST_DATABASE_URL = URL.create(
    drivername="postgresql",
    username=os.getenv("DATABASE_USER"),
    password=os.getenv("DATABASE_PASSWORD"),
    host=os.getenv("TEST_DATABASE_HOST", "localhost"),
    port=int(os.getenv("DATABASE_PORT", "5432")),   # ✅ cast to int
    database="saas_test_db",             # ✅ was hardcoded "saas_test_db"
)

# ── Create saas_test_db if it doesn't exist ────────────────────────────────────
def ensure_test_database():
    admin_engine = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        # Create main app DB if missing
        main_db = os.getenv("DATABASE_NAME")
        exists = conn.execute(
            sa_text(f"SELECT 1 FROM pg_database WHERE datname = '{main_db}'")
        ).fetchone()
        if not exists:
            conn.execute(sa_text(f"CREATE DATABASE {main_db}"))

        # Create test DB if missing
        test_db = "saas_test_db"
        exists = conn.execute(
            sa_text(f"SELECT 1 FROM pg_database WHERE datname = '{test_db}'")
        ).fetchone()
        if not exists:
            conn.execute(sa_text(f"CREATE DATABASE {test_db}"))
    admin_engine.dispose()

ensure_test_database()  # ✅ runs before engine is built


# Set up the test database engine and session
engine = create_engine(TEST_DATABASE_URL)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Override the get_db dependency to use the test database
def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()

# Apply the override to the app's dependency
app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
def setup_database():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)

@pytest.fixture
def client():
    return TestClient(app)

@pytest.fixture
def registered_user(client):
    user_data = client.post("/api/v1/auth/register", json ={
        "email": "test@example.com",
        "username": "testuser",
        "password": "testpassword",
        "password2": "testpassword"
    })
    return user_data.json()

@pytest.fixture
def auth_token(client, registered_user):
    response = client.post("/api/v1/auth/token", data={
        "username": registered_user["email"],
        "password": "testpassword"
    })
    return response.json()["access_token"]


# ── TESTS ─────────────────────────────────────────────────────────────────────
class TestHealth:
    def test_health_check(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

class TestRegister:
    def test_register_success(self, client):
        response = client.post("/api/v1/auth/register", json={
            "email": "new@example.com",
            "username": "newuser",
            "password": "newpassword",
            "password2": "newpassword"
        })
        assert response.status_code == 201
        data = response.json()
        assert data["email"] == "new@example.com"
        assert data["username"] == "newuser"
        assert "password" not in data
        assert "hashed_password" not in data

    def test_register_duplicate_email(self, client, registered_user):
        response = client.post("/api/v1/auth/register", json={
            "email": registered_user["email"],
            "username": "anotheruser",
            "password": "anotherpassword",
            "password2": "anotherpassword"
        })
        assert response.status_code == 400
        assert response.json()["detail"] == "Email already registered"
    

    def test_register_password_mismatch(self, client):
        response = client.post("/api/v1/auth/register", json={
            "email": "test2@example.com",
            "username": "newuser",
            "password": "newpassword",
            "password2": "differentpassword"
        })
        assert response.status_code == 400
        assert response.json()["detail"] == "Passwords do not match"


class TestLogin:
    def test_login_success(self, client, registered_user):
        response = client.post("/api/v1/auth/token", data={
            "username": registered_user["email"],
            "password": "testpassword"
        })
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        
        assert data["token_type"] == "bearer"
        assert "refresh_token" in data

    def test_login_invalid_credentials(self, client):
        response = client.post("/api/v1/auth/token", data={
            "username": "test@example.com",
            "password": "wrongpassword"
        })
        assert response.status_code == 401
        
    def test_login_nonexistent_user(self, client):
        response = client.post("/api/v1/auth/token", data={
            "username": "nonexistent@example.com",
            "password": "testpassword"
        })
        assert response.status_code == 401

class TestRefreshToken:
    def test_refresh_token_success(self, client, auth_token):
        login_response = client.post("/api/v1/auth/token", data={
            "username": "test@example.com",
            "password": "testpassword"
        })
        refresh_token = login_response.json()["refresh_token"]

        response = client.post("/api/v1/auth/refresh", json={
            "refresh_token": refresh_token
        })
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    def test_refresh_token_invalid(self, client):
        response = client.post("/api/v1/auth/refresh", json={
            "refresh_token": "invalidtoken"
        })
        assert response.status_code == 401


class TestRegistrationEdgeCases:
    def test_register_never_returns_password(self, client):
        response = client.post("/api/v1/auth/register", json={
            "email": "secure@test.com",
            "username": "secureuser",
            "password": "securepassword",
            "password2": "securepassword"
        })
        assert response.status_code == 201
        data = response.json()
        assert "password" not in data
        assert "hashed_password" not in data
        assert "password2" not in data

    def test_register_invalid_email_returns_422(self, client):
        # 422 = Pydantic validation error.
        # Pydantic's EmailStr catches invalid emails before your code runs.

        response = client.post("/api/v1/auth/register", json={
            "email": "not-an-email",
            "username": "user",
            "password": "password",
            "password2": "password"
        })
        assert response.status_code == 422

    def test_register_missing_fields_returns_422(self, client):
        response = client.post("/api/v1/auth/register", json={
            "email": "test@example.com",
            # Missing username, password, password2
        })
        assert response.status_code == 422


class TestLoginEdgeCases:
    def test_login_returns_valid_jwt_format(self, client, registered_user):
        response = client.post("/api/v1/auth/token", data={
            "username": registered_user["email"],
            "password": "testpassword"
        })
        assert response.status_code == 200
        data = response.json()
        access_token = data["access_token"]
        # JWTs have three parts separated by dots
        assert len(access_token.split(".")) == 3

    def test_access_token_cannot_be_used_as_refresh_token(self, client, registered_user):
        response = client.post("/api/v1/auth/token", data={
            "username": registered_user["email"],
            "password": "testpassword"
        })
        assert response.status_code == 200
        data = response.json()
        access_token = data["access_token"]

        # Try to use the access token as a refresh token
        refresh_response = client.post("/api/v1/auth/refresh", json={
            "refresh_token": access_token
        })
        assert refresh_response.status_code == 401


class TestProtectedEndpoints:
    def test_protected_endpoint_without_token_returns_401(self, client):
        response = client.get("/api/v1/tenants/")
        assert response.status_code == 401

    def test_protected_endpoint_with_invalid_token_returns_401(self, client):
        response = client.get("/api/v1/tenants/", headers={
            "Authorization": "Bearer totally.invalidtoken.token"
        })
        assert response.status_code == 401

    def test_protected_endpoint_with_valid_token_returns_200(self, client, auth_token):
        response = client.get("/api/v1/tenants/", headers={
            "Authorization": f"Bearer {auth_token}"
        })
        assert response.status_code == 200