"""Tests for FastAPI endpoints."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

# Import after setting up test environment
from app.main import app


@pytest.fixture
def client():
    """Create a test client."""
    return TestClient(app)


@pytest.fixture
def auth_headers():
    """Create auth headers for testing."""
    from app.config import get_settings
    settings = get_settings()
    import base64
    credentials = base64.b64encode(
        f"{settings.AUTH_USERNAME}:{settings.AUTH_PASSWORD}".encode()
    ).decode()
    return {"Authorization": f"Basic {credentials}"}


class TestHealthEndpoints:
    """Test basic health/readiness endpoints."""

    def test_root_requires_auth(self, client):
        """Test root requires authentication."""
        response = client.get("/", follow_redirects=False)
        # Root requires auth (returns 401) or redirects to login
        assert response.status_code in (302, 307, 401)


class TestDeviceAPI:
    """Test device API endpoints."""

    def test_list_devices_unauthorized(self, client):
        """Test devices endpoint requires auth."""
        response = client.get("/devices/")
        assert response.status_code == 401

    def test_list_devices_with_auth(self, client, auth_headers):
        """Test devices endpoint with auth."""
        response = client.get("/devices/", headers=auth_headers)
        # Should return HTML page (200) or redirect
        assert response.status_code in (200, 307, 302)


class TestAPIv1:
    """Test REST API v1 endpoints."""

    def test_api_devices_unauthorized(self, client):
        """Test API requires authentication."""
        response = client.get("/api/v1/devices")
        assert response.status_code == 401

    def test_api_devices_with_auth(self, client, auth_headers):
        """Test API with authentication."""
        response = client.get("/api/v1/devices", headers=auth_headers)
        assert response.status_code == 200
        # Should return JSON list
        data = response.json()
        assert isinstance(data, list)


class TestEngines:
    """Test backup engines are registered."""

    def test_all_engines_registered(self):
        """Verify all expected engines are registered."""
        from app.modules.engines import ENGINES
        
        expected_engines = ["netmiko", "scp", "oxidized", "pfsense"]
        for engine in expected_engines:
            assert engine in ENGINES, f"Engine {engine} not registered"

    def test_pfsense_engine_instantiates(self):
        """Test pfsense engine can be instantiated."""
        from app.modules.engines import get_engine
        
        engine = get_engine("pfsense")
        assert engine is not None
        assert engine.__class__.__name__ == "PfSenseEngine"
