import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import sessionmaker
from app.main import app
from app.database import Base, get_db
from urllib.parse import quote_plus
import os


# Use a separate test database — never run tests against your dev DB
# Tests create and destroy data rapidly — you don't want that in dev

DATABASE_PASSWORD = quote_plus(os.getenv('DATABASE_PASSWORD', 'postgres'))
DATABASE_USER = os.getenv(
    'DATABASE_USER',
    'postgres'
) # Extract username if it contains '@'
TEST_DATABASE_URL = URL.create(
    drivername="postgresql",
    username=os.getenv("DATABASE_USER"),
    password=os.getenv("DATABASE_PASSWORD"),
    host="localhost",
    port=os.getenv("DATABASE_PORT"),
    database="saas_test_db",
)

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