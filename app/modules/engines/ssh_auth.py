import paramiko

from app.models.credential import Credential


def require_ssh_auth(credential: Credential, purpose: str) -> None:
    if not credential.username:
        raise ValueError(f"Credential '{credential.name}' has no username - {purpose} requires a username")
    if not credential.get_password() and not credential.ssh_key_path:
        raise ValueError(
            f"Credential '{credential.name}' has neither a password nor SSH key path - "
            f"{purpose} requires at least one authentication method"
        )


def client_connect_kwargs(hostname: str, port: int, credential: Credential, purpose: str) -> dict:
    require_ssh_auth(credential, purpose)
    kwargs = {
        "hostname": hostname,
        "port": port,
        "username": credential.username,
        "timeout": 30,
        "look_for_keys": False,
        "allow_agent": False,
    }
    password = credential.get_password()
    if password:
        kwargs["password"] = password
    if credential.ssh_key_path:
        kwargs["key_filename"] = credential.ssh_key_path
    return kwargs


def load_private_key(key_path: str, password: str | None = None) -> paramiko.PKey:
    errors: list[str] = []
    for key_cls in (paramiko.Ed25519Key, paramiko.RSAKey, paramiko.ECDSAKey, paramiko.DSSKey):
        try:
            return key_cls.from_private_key_file(key_path, password=password)
        except Exception as exc:
            errors.append(f"{key_cls.__name__}: {exc}")
    raise paramiko.SSHException(f"Unable to load private key {key_path}: {'; '.join(errors)}")


def connect_transport(transport: paramiko.Transport, credential: Credential, purpose: str) -> None:
    require_ssh_auth(credential, purpose)
    password = credential.get_password()
    if credential.ssh_key_path:
        pkey = load_private_key(credential.ssh_key_path, password=password)
        transport.start_client(timeout=30)
        try:
            transport.auth_publickey(credential.username, pkey)
        except paramiko.AuthenticationException:
            if not password:
                raise
        if not transport.is_authenticated():
            transport.auth_password(credential.username, password)
    else:
        transport.connect(username=credential.username, password=password)
