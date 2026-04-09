# SaaS API

AI-powered multi-tenant SaaS backend built with FastAPI, PostgreSQL, Redis, and Docker.

## Tech Stack
- **Framework:** FastAPI + SQLAlchemy + Pydantic v2
- **Database:** PostgreSQL 15 with composite indexes
- **Cache:** Redis 7 via redis-py async client
- **Auth:** JWT (access + refresh tokens) via python-jose + bcrypt
- **Server:** Uvicorn (ASGI)
- **Containerization:** Docker + Docker Compose
- **Orchestration:** Kubernetes (minikube for local dev)
- **IaC:** Terraform with Docker provider
- **CI/CD:** GitHub Actions (lint + test + docker build)
- **Testing:** pytest with full integration test suite
- **Language:** Python 3.13

## Features
- Multi-tenant architecture with full tenant isolation
- JWT auth with access + refresh token pattern
- RBAC — Owner / Admin / Member role hierarchy
- Tenant CRUD with per-user data isolation
- Notes CRUD scoped to tenants with authorship rules
- Redis async caching layer
- GitHub Actions CI — flake8, black, isort, pytest, Docker build
- Kubernetes manifests for local deployment
- Terraform IaC config

## Project Structure
\`\`\`
saas-api/
├── app/
│   ├── main.py          # App entry point, router registration, lifespan
│   ├── database.py      # SQLAlchemy engine + session + dependency
│   ├── models.py        # User, Tenant, TenantUser, Note models
│   ├── schemas.py       # Pydantic request/response schemas
│   ├── auth.py          # JWT creation, verification, RBAC helpers
│   ├── cache.py         # Async Redis client wrapper
│   └── routers/
│       ├── auth.py      # Register, login, token refresh
│       ├── tenants.py   # Tenant CRUD + invite + members
│       └── notes.py     # Notes CRUD scoped to tenants
├── tests/
│   ├── conftest.py      # Shared fixtures, test DB setup
│   ├── test_main.py     # Auth + protected endpoint tests
│   ├── test_tenants.py  # Tenant isolation + RBAC tests
│   └── test_notes.py    # Notes CRUD + authorship tests
├── k8s/                 # Kubernetes manifests
├── terraform/           # Terraform IaC config
├── .github/workflows/   # GitHub Actions CI pipeline
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
\`\`\`

## Getting Started
\`\`\`bash
cp .env.example .env   # fill in your values
docker-compose up --build
\`\`\`
Visit **http://localhost:8002/docs** for interactive API documentation.

## API Endpoints

### Auth
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | /api/v1/auth/register | None | Register |
| POST | /api/v1/auth/token | None | Login |
| POST | /api/v1/auth/refresh | None | Refresh token |

### Tenants
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | /api/v1/tenants/ | JWT | Create tenant |
| GET | /api/v1/tenants/ | JWT | List my tenants |
| GET | /api/v1/tenants/{slug} | JWT + Member | Get tenant |
| POST | /api/v1/tenants/{slug}/invite | JWT + Admin | Invite user |
| GET | /api/v1/tenants/{slug}/members | JWT + Member | List members |

### Notes
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | /api/v1/tenants/{slug}/notes/ | JWT + Member | Create note |
| GET | /api/v1/tenants/{slug}/notes/ | JWT + Member | List notes |
| GET | /api/v1/tenants/{slug}/notes/{id} | JWT + Member | Get note |
| PUT | /api/v1/tenants/{slug}/notes/{id} | JWT + Author/Admin | Update note |
| DELETE | /api/v1/tenants/{slug}/notes/{id} | JWT + Author/Admin | Delete note |

## Running Tests
\`\`\`bash
pytest tests/ -v
\`\`\`

## Environment Variables
\`\`\`env
DATABASE_URL=postgresql://postgres:password@db:5432/saas_db
SECRET_KEY=your-secret-key
REDIS_URL=redis://redis:6379/0
\`\`\`