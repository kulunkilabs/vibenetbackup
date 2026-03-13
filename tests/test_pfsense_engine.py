"""Tests for the pfSense/OPNsense backup engine."""

import pytest
import pytest_asyncio
from unittest.mock import Mock, patch, AsyncMock
import httpx

from app.modules.engines.pfsense_engine import PfSenseEngine
from app.models.device import Device
from app.models.credential import Credential


class TestPfSenseEngine:
    """Test cases for PfSenseEngine."""

    @pytest.fixture
    def engine(self):
        return PfSenseEngine()

    @pytest.fixture
    def pfsense_device(self):
        return Device(
            id=1,
            hostname="pfsense-test",
            ip_address="192.168.1.1",
            device_type="pfsense",
            port=443,
        )

    @pytest.fixture
    def opnsense_device(self):
        return Device(
            id=2,
            hostname="opnsense-test",
            ip_address="192.168.1.2",
            device_type="opnsense",
            port=443,
        )

    @pytest.fixture
    def credential(self):
        cred = Credential(
            id=1,
            name="test-cred",
            username="admin",
        )
        cred.set_password("secret123")
        return cred

    def test_detect_api_type_pfsense(self, engine, pfsense_device):
        """Test auto-detection of pfSense."""
        result = engine._detect_api_type(pfsense_device)
        assert result == "pfsense"

    def test_detect_api_type_opnsense(self, engine, opnsense_device):
        """Test auto-detection of OPNsense."""
        result = engine._detect_api_type(opnsense_device)
        assert result == "opnsense"

    def test_extract_csrf_token(self, engine):
        """Test CSRF token extraction from HTML."""
        html = '<input name="__csrf_magic" value="test-token-123" />'
        result = engine._extract_csrf_token(html)
        assert result == "test-token-123"

    def test_extract_csrf_token_alternative_format(self, engine):
        """Test CSRF token extraction with single quotes."""
        html = "<input __csrf_magic value='token-456'>"
        result = engine._extract_csrf_token(html)
        assert result == "token-456"

    def test_extract_csrf_token_not_found(self, engine):
        """Test CSRF token extraction when not present."""
        html = "<html><body>No token here</body></html>"
        result = engine._extract_csrf_token(html)
        assert result == ""

    @pytest.mark.asyncio
    async def test_fetch_opnsense_config_success(self, engine, opnsense_device, credential):
        """Test successful OPNsense config fetch."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "<opnsense-config>test</opnsense-config>"
        
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        
        result = await engine._fetch_opnsense_config(
            opnsense_device, credential, mock_client
        )
        
        assert result == "<opnsense-config>test</opnsense-config>"
        mock_client.get.assert_called_once_with(
            "https://192.168.1.2/api/core/backup/download/this",
            auth=("admin", "secret123"),
            timeout=60
        )

    @pytest.mark.asyncio
    async def test_fetch_opnsense_config_auth_failed(self, engine, opnsense_device, credential):
        """Test OPNsense config fetch with auth failure."""
        mock_response = Mock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"
        
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        
        with pytest.raises(PermissionError, match="authentication failed"):
            await engine._fetch_opnsense_config(
                opnsense_device, credential, mock_client
            )

    @pytest.mark.asyncio
    async def test_test_connection_opnsense_success(self, engine, opnsense_device, credential):
        """Test successful connection test for OPNsense."""
        mock_response = Mock()
        mock_response.status_code = 200
        
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        
        result = await engine.test_connection(opnsense_device, credential)
        # Note: This would need proper async mocking of httpx.AsyncClient
        # This is a simplified test structure


class TestPfSenseEngineIntegration:
    """Integration tests - requires actual pfSense/OPNsense instance."""
    
    @pytest.mark.skip(reason="Requires actual firewall instance")
    @pytest.mark.asyncio
    async def test_real_pfsense_connection(self):
        """Test against real pfSense - skipped by default."""
        engine = PfSenseEngine()
        device = Device(
            hostname="real-pfsense",
            ip_address="10.0.0.1",
            device_type="pfsense",
            port=443,
        )
        cred = Credential(username="admin", password_type="password")
        cred._password = cred.encrypt_password("admin")
        
        result = await engine.test_connection(device, cred)
        assert result is True
