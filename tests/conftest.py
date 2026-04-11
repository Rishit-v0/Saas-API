# from app import models, auth
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy import text as sa_text
from sqlalchemy.engine import URL
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app

# Create a test database URL (using SQLite for simplicity)
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
    port=int(os.getenv("DATABASE_PORT", "5432")),  # ✅ cast to int
    database="saas_test_db",  # ✅ was hardcoded "saas_test_db"
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


@pytest.fixture(scope="function", autouse=True)
def setup_database():
    # Create all tables in the test database
    Base.metadata.create_all(bind=engine)
    yield  # run the test
    # Drop all tables after the test to clean up
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client():
    return TestClient(app)


@pytest.fixture(scope="function")
def db_session():
    """Provide a transactional scope around a series of operations."""
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── User fixtures ──────────────────────────────────────────────────────────────
@pytest.fixture
def user_payload():
    return {
        "email": "rishit@test.com",
        "username": "rishit",
        "password": "StrongPass123!",
        "password2": "StrongPass123!",
    }


@pytest.fixture
def second_user_payload():
    return {
        "email": "second@test.com",
        "username": "seconduser",
        "password": "StrongPass123!",
        "password2": "StrongPass123!",
    }


@pytest.fixture
def registered_user(client, user_payload):
    response = client.post("/api/v1/auth/register", json=user_payload)
    assert response.status_code == 201, f"Registration failed: {response.json()}"
    return response.json()


@pytest.fixture
def second_registered_user(client, second_user_payload):
    response = client.post("/api/v1/auth/register", json=second_user_payload)
    assert response.status_code == 201, f"Registration failed: {response.json()}"
    return response.json()


@pytest.fixture
def auth_headers(client, registered_user):
    response = client.post(
        "/api/v1/auth/token",
        data={"username": registered_user["email"], "password": "StrongPass123!"},
    )
    assert response.status_code == 200, f"Authentication failed: {response.json()}"
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def second_auth_headers(client, second_registered_user):
    response = client.post(
        "/api/v1/auth/token",
        data={
            "username": second_registered_user["email"],
            "password": "StrongPass123!",
        },
    )
    assert response.status_code == 200, f"Authentication failed: {response.json()}"
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def tenant_payload():
    return {"name": "Acme Corp", "slug": "acme-corp"}


@pytest.fixture
def created_tenant(client, auth_headers, tenant_payload):
    response = client.post(
        "/api/v1/tenants/", json=tenant_payload, headers=auth_headers
    )
    assert response.status_code == 201, f"Tenant creation failed: {response.json()}"
    return response.json()
