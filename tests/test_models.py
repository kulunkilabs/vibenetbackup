"""Tests for database models."""

import pytest
from app.models.device import (
    DEVICE_TYPES, 
    DEVICE_COMMANDS,
    get_config_commands,
    oxidized_model_to_device_type
)
from app.models.credential import Credential


class TestDeviceTypes:
    """Test device type definitions."""

    def test_pfsense_in_device_types(self):
        """Verify pfSense is registered as a device type."""
        assert "pfsense" in DEVICE_TYPES
        assert "pfSense" in DEVICE_TYPES["pfsense"]

    def test_opnsense_in_device_types(self):
        """Verify OPNsense is registered as a device type."""
        assert "opnsense" in DEVICE_TYPES
        assert "OPNsense" in DEVICE_TYPES["opnsense"]

    def test_pfsense_commands(self):
        """Verify pfSense has correct config commands."""
        commands = get_config_commands("pfsense")
        assert commands == ["cat /cf/conf/config.xml"]

    def test_opnsense_commands(self):
        """Verify OPNsense has correct config commands."""
        commands = get_config_commands("opnsense")
        assert commands == ["cat /conf/config.xml"]

    def test_unknown_device_type_fallback(self):
        """Test fallback for unknown device types."""
        commands = get_config_commands("unknown_vendor")
        assert commands == ["show running-config"]


class TestOxidizedModelMap:
    """Test Oxidized model mapping."""

    def test_ios_to_cisco_ios(self):
        """Test ios maps to cisco_ios."""
        result = oxidized_model_to_device_type("ios")
        assert result == "cisco_ios"

    def test_junos_mapping(self):
        """Test junos maps correctly."""
        result = oxidized_model_to_device_type("junos")
        assert result == "juniper_junos"

    def test_unknown_model_passes_through(self):
        """Test unknown models pass through as-is."""
        result = oxidized_model_to_device_type("custom_vendor")
        assert result == "custom_vendor"


class TestCredentialEncryption:
    """Test credential encryption/decryption."""

    def test_password_encryption(self, db_session):
        """Test passwords are encrypted and can be decrypted."""
        cred = Credential(
            name="test-enc",
            username="admin",
        )
        db_session.add(cred)
        db_session.commit()
        
        cred.set_password("mysecretpassword")
        db_session.commit()
        
        # Password should be encrypted (not plaintext)
        assert cred.password_encrypted != "mysecretpassword"
        
        # Should be able to decrypt
        decrypted = cred.get_password()
        assert decrypted == "mysecretpassword"

    def test_password_none(self, db_session):
        """Test handling of None password."""
        cred = Credential(
            name="test-none",
            username="admin",
        )
        db_session.add(cred)
        db_session.commit()
        
        assert cred.get_password() is None
