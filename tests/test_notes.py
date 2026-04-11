import pytest


@pytest.fixture
def note_payload():
    return {"title": "Test Note", "content": "This is a test note."}


@pytest.fixture
def created_note(client, auth_headers, created_tenant, note_payload):
    response = client.post(
        f"/api/v1/tenants/{created_tenant['slug']}/notes/",
        json=note_payload,
        headers=auth_headers,
    )
    assert response.status_code == 201, f"Note creation failed: {response.json()}"
    return response.json()


class TestNoteCreation:
    def test_create_note_returns_201(
        self, client, auth_headers, created_tenant, note_payload
    ):
        response = client.post(
            f"/api/v1/tenants/{created_tenant['slug']}/notes/",
            json=note_payload,
            headers=auth_headers,
        )
        assert response.status_code == 201

    def test_create_note_returns_correct_data(
        self, client, auth_headers, created_tenant, note_payload
    ):
        response = client.post(
            f"/api/v1/tenants/{created_tenant['slug']}/notes/",
            json=note_payload,
            headers=auth_headers,
        )
        data = response.json()
        assert data["title"] == note_payload["title"]
        assert data["content"] == note_payload["content"]
        assert "id" in data
        assert "created_at" in data
        assert data["is_archived"] == False

    def test_create_note_requires_authentication(
        self, client, created_tenant, note_payload
    ):
        response = client.post(
            f"/api/v1/tenants/{created_tenant['slug']}/notes/", json=note_payload
        )
        assert response.status_code == 401

    def test_non_member_cannot_create_note(
        self, client, second_auth_headers, created_tenant, note_payload
    ):
        response = client.post(
            f"/api/v1/tenants/{created_tenant['slug']}/notes/",
            json=note_payload,
            headers=second_auth_headers,
        )
        assert response.status_code == 403


class TestNoteListing:
    def test_list_notes_returns_200(self, client, auth_headers, created_tenant):
        response = client.get(
            f"/api/v1/tenants/{created_tenant['slug']}/notes/", headers=auth_headers
        )
        assert response.status_code == 200

    def test_list_notes_returns_correct_data(
        self, client, auth_headers, created_tenant, created_note
    ):
        response = client.get(
            f"/api/v1/tenants/{created_tenant['slug']}/notes/", headers=auth_headers
        )
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["title"] == created_note["title"]
        assert data[0]["content"] == created_note["content"]

    def test_archived_notes_are_not_listed(
        self, client, auth_headers, created_tenant, created_note
    ):
        client.put(
            f"/api/v1/tenants/{created_tenant['slug']}/notes/{created_note['id']}/",
            json={"is_archived": True},
            headers=auth_headers,
        )
        response = client.get(
            f"/api/v1/tenants/{created_tenant['slug']}/notes/", headers=auth_headers
        )
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 0
        assert data == []


class TestNoteUpdate:
    def test_update_note_returns_200(
        self, client, auth_headers, created_tenant, created_note
    ):
        update_data = {"title": "Updated Title", "content": "Updated content."}
        response = client.put(
            f"/api/v1/tenants/{created_tenant['slug']}/notes/{created_note['id']}/",
            json=update_data,
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["title"] == update_data["title"]
        assert data["content"] == update_data["content"]

    def test_non_author_cannot_update_note(
        self, client, second_auth_headers, created_tenant, created_note
    ):
        update_data = {
            "title": "Malicious Update",
            "content": "Trying to update someone else's note.",
        }
        response = client.put(
            f"/api/v1/tenants/{created_tenant['slug']}/notes/{created_note['id']}/",
            json=update_data,
            headers=second_auth_headers,
        )
        assert response.status_code == 403

    def test_update_note_not_found(self, client, auth_headers, created_tenant):
        update_data = {
            "title": "Nonexistent Note",
            "content": "Trying to update a note that doesn't exist.",
        }
        response = client.put(
            f"/api/v1/tenants/{created_tenant['slug']}/notes/9999/",
            json=update_data,
            headers=auth_headers,
        )
        assert response.status_code == 404


class TestNoteDelete:
    def test_delete_note_returns_204(
        self, client, auth_headers, created_tenant, created_note
    ):
        response = client.delete(
            f"/api/v1/tenants/{created_tenant['slug']}/notes/{created_note['id']}/",
            headers=auth_headers,
        )
        assert response.status_code == 204

    def test_non_author_cannot_delete_note(
        self, client, second_auth_headers, created_tenant, created_note
    ):
        response = client.delete(
            f"/api/v1/tenants/{created_tenant['slug']}/notes/{created_note['id']}/",
            headers=second_auth_headers,
        )
        assert response.status_code == 403

    def test_delete_note_not_found(
        self, client, auth_headers, created_tenant, created_note
    ):
        client.delete(
            f"/api/v1/tenants/{created_tenant['slug']}/notes/{created_note['id']}/",
            headers=auth_headers,
        )
        response = client.get(
            f"/api/v1/tenants/{created_tenant['slug']}/notes/", headers=auth_headers
        )
        assert response.json() == []


class TestNoteAtoB:
    def test_tenant_a_notes_are_not_visible_to_tenant_b(
        self, client, created_tenant, created_note, second_auth_headers
    ):
        client.post(
            f"/api/v1/tenants/",
            json={"name": "User 2 Corp", "slug": "user2-corp"},
            headers=second_auth_headers,
        )
        response = client.get(
            f"/api/v1/tenants/{created_tenant['slug']}/notes/",
            headers=second_auth_headers,
        )
        assert response.status_code == 403
