from unittest.mock import Mock

import pytest

from app.modules.engines import ssh_auth


class DummyCredential:
    name = "jump"
    username = "oxidized"

    def __init__(self, password=None, ssh_key_path=None):
        self._password = password
        self.ssh_key_path = ssh_key_path

    def get_password(self):
        return self._password


def test_client_connect_kwargs_uses_ssh_key_without_password():
    cred = DummyCredential(ssh_key_path="/keys/proxy")

    kwargs = ssh_auth.client_connect_kwargs("10.2.1.10", 7006, cred, "SSH proxy jump")

    assert kwargs["hostname"] == "10.2.1.10"
    assert kwargs["port"] == 7006
    assert kwargs["username"] == "oxidized"
    assert kwargs["key_filename"] == "/keys/proxy"
    assert "password" not in kwargs
    assert kwargs["look_for_keys"] is False
    assert kwargs["allow_agent"] is False


def test_client_connect_kwargs_keeps_password_for_key_passphrase():
    cred = DummyCredential(password="passphrase", ssh_key_path="/keys/proxy")

    kwargs = ssh_auth.client_connect_kwargs("10.2.1.10", 7006, cred, "SSH proxy jump")

    assert kwargs["password"] == "passphrase"
    assert kwargs["key_filename"] == "/keys/proxy"


def test_client_connect_kwargs_rejects_missing_auth_method():
    cred = DummyCredential()

    with pytest.raises(ValueError, match="neither a password nor SSH key path"):
        ssh_auth.client_connect_kwargs("10.2.1.10", 7006, cred, "SSH proxy jump")


def test_connect_transport_uses_private_key(monkeypatch):
    cred = DummyCredential(ssh_key_path="/keys/device")
    pkey = object()
    transport = Mock()
    transport.is_authenticated.return_value = True

    monkeypatch.setattr(ssh_auth, "load_private_key", Mock(return_value=pkey))

    ssh_auth.connect_transport(transport, cred, "SSH/SCP")

    ssh_auth.load_private_key.assert_called_once_with("/keys/device", password=None)
    transport.start_client.assert_called_once_with(timeout=30)
    transport.auth_publickey.assert_called_once_with("oxidized", pkey)
    transport.auth_password.assert_not_called()


def test_connect_transport_falls_back_to_password_when_key_auth_fails(monkeypatch):
    cred = DummyCredential(password="secret", ssh_key_path="/keys/device")
    pkey = object()
    transport = Mock()
    transport.auth_publickey.side_effect = ssh_auth.paramiko.AuthenticationException()
    transport.is_authenticated.return_value = False

    monkeypatch.setattr(ssh_auth, "load_private_key", Mock(return_value=pkey))

    ssh_auth.connect_transport(transport, cred, "SSH/SCP")

    transport.auth_publickey.assert_called_once_with("oxidized", pkey)
    transport.auth_password.assert_called_once_with("oxidized", "secret")


def test_connect_transport_uses_password_without_key():
    cred = DummyCredential(password="secret")
    transport = Mock()

    ssh_auth.connect_transport(transport, cred, "SSH/SCP")

    transport.connect.assert_called_once_with(username="oxidized", password="secret")
