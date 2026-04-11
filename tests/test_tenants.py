import pytest


class TestTenantCreation:
    def test_create_tenant_returns_201(self, client, auth_headers, tenant_payload):
        response = client.post(
            "/api/v1/tenants/", json=tenant_payload, headers=auth_headers
        )
        assert response.status_code == 201

    def test_create_tenant_returns_correct_data(
        self, client, auth_headers, tenant_payload
    ):
        response = client.post(
            "/api/v1/tenants/", json=tenant_payload, headers=auth_headers
        )

        data = response.json()
        assert data["name"] == tenant_payload["name"]
        assert data["slug"] == tenant_payload["slug"]
        assert data["is_active"]
        assert "id" in data

    def test_create_tenant_requires_authentication(self, client, tenant_payload):
        response = client.post("/api/v1/tenants/", json=tenant_payload)
        assert response.status_code == 401

    def test_create_tenant_duplicate_slug_returns_400(
        self, client, auth_headers, tenant_payload
    ):
        # Create the first tenant
        client.post("/api/v1/tenants/", json=tenant_payload, headers=auth_headers)

        # Attempt to create a second tenant with the same slug
        response = client.post(
            "/api/v1/tenants/", json=tenant_payload, headers=auth_headers
        )
        assert response.status_code == 400
        assert "already taken" in response.json()["detail"].lower()

    def test_creator_becomes_owner(
        self, client, auth_headers, created_tenant, db_session
    ):
        from app import models

        membership_response = (
            db_session.query(models.TenantUser)
            .filter(models.TenantUser.user_id == created_tenant["id"])
            .first()
        )
        assert membership_response is not None
        assert membership_response.role == "owner"


class TestTenantListing:
    def test_list_tenants_returns_200(
        self,
        client,
        auth_headers,
    ):
        response = client.get("/api/v1/tenants/", headers=auth_headers)
        assert response.status_code == 200

    def test_list_tenants_returns_correct_data(
        self, client, auth_headers, created_tenant
    ):
        response = client.get("/api/v1/tenants/", headers=auth_headers)
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["name"] == created_tenant["name"]
        assert data[0]["slug"] == created_tenant["slug"]

    def test_list_tenants_only_shows_own_tenants(
        self, client, auth_headers, created_tenant, second_auth_headers
    ):
        response = client.get("/api/v1/tenants/", headers=second_auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 0

    def test_empty_tenants_list_for_new_user(self, client, auth_headers):
        response = client.get("/api/v1/tenants/", headers=auth_headers)
        assert response.status_code == 200
        assert response.json() == []


class TestTenantAccess:
    def test_get_tenant_by_slug_returns_200(self, client, auth_headers, created_tenant):
        response = client.get(
            f"/api/v1/tenants/{created_tenant['slug']}/", headers=auth_headers
        )
        assert response.status_code == 200

    def test_get_nonexistent_tenant_returns_404(self, client, auth_headers):
        response = client.get("/api/v1/tenants/nonexistent-slug/", headers=auth_headers)
        assert response.status_code == 404

    def test_non_member_cannot_access_tenant(
        self, client, created_tenant, second_auth_headers
    ):
        response = client.get(
            f"/api/v1/tenants/{created_tenant['slug']}/", headers=second_auth_headers
        )
        assert response.status_code == 403


class TestTenantInvite:
    def test_owner_can_invite_user(
        self, client, auth_headers, created_tenant, second_auth_headers
    ):
        response = client.post(
            f"/api/v1/tenants/{created_tenant['slug']}/invite/",
            json={"email": "second@test.com", "role": "member"},
            headers=auth_headers,
        )
        assert response.status_code == 200

    def test_invited_user_can_access_tenant(
        self, client, auth_headers, created_tenant, second_auth_headers
    ):
        # Invite the second user
        client.post(
            f"/api/v1/tenants/{created_tenant['slug']}/invite/",
            json={"email": "second@test.com", "role": "member"},
            headers=auth_headers,
        )
        # Attempt to access the tenant with the invited user's credentials
        response = client.get(
            f"/api/v1/tenants/{created_tenant['slug']}/", headers=second_auth_headers
        )
        assert response.status_code == 200

    def test_non_owner_cannot_invite_user(
        self, client, auth_headers, second_auth_headers, created_tenant
    ):
        # Attempt to invite a user with non-owner credentials
        response = client.post(
            f"/api/v1/tenants/{created_tenant['slug']}/invite/",
            json={"email": "second@test.com", "role": "member"},
            headers=auth_headers,
        )

        response = client.post(
            f"/api/v1/tenants/{created_tenant['slug']}/invite/",
            json={"email": "third@test.com", "role": "member"},
            headers=second_auth_headers,
        )
        assert response.status_code == 403

    def test_cannot_invite_duplicate_user(
        self, client, auth_headers, second_registered_user, created_tenant
    ):
        # Invite the second user
        client.post(
            f"/api/v1/tenants/{created_tenant['slug']}/invite/",
            json={"email": "second@test.com", "role": "member"},
            headers=auth_headers,
        )
        # Attempt to invite the same user again
        response = client.post(
            f"/api/v1/tenants/{created_tenant['slug']}/invite/",
            json={"email": "second@test.com", "role": "member"},
            headers=auth_headers,
        )
        assert response.status_code == 400
        assert "already a member" in response.json()["detail"].lower()

    def test_invite_nonexistent_user(self, client, auth_headers, created_tenant):
        response = client.post(
            f"/api/v1/tenants/{created_tenant['slug']}/invite/",
            json={"email": "nonexistent@test.com", "role": "member"},
            headers=auth_headers,
        )
        assert response.status_code == 404
