import pytest
import pytest_asyncio
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.models.device import Device
from app.models.credential import Credential


# Use in-memory SQLite for tests
TEST_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture(scope="session")
def db_engine():
    """Create a test database engine."""
    engine = create_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session(db_engine):
    """Create a fresh database session for each test."""
    SessionLocal = sessionmaker(bind=db_engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def sample_device():
    """Create a sample device for testing."""
    return Device(
        id=1,
        hostname="test-firewall",
        ip_address="192.168.1.1",
        device_type="pfsense",
        port=443,
        enabled=True,
    )


@pytest.fixture
def sample_credential():
    """Create a sample credential for testing."""
    cred = Credential(
        id=1,
        name="test-cred",
        username="admin",
        password_type="password",
    )
    # Set encrypted password (plaintext is "testpass")
    cred._password = cred.encrypt_password("testpass")
    return cred
