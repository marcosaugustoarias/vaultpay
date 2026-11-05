import os
import tempfile

# Must be set BEFORE the app is imported (settings are read at import time).
_tmp = tempfile.mkdtemp(prefix="vaultpay-test-")
os.environ["VAULTPAY_ENV"] = "test"
os.environ["VAULTPAY_DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.database import Base, SessionLocal, engine, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import User  # noqa: E402
from app.security import totp  # noqa: E402
from app.security.rate_limit import limiter  # noqa: E402
from app.services import ledger  # noqa: E402

PASSWORD = "correct-horse-battery-9"
CSRF = {"X-Requested-With": "vaultpay"}


@pytest.fixture(autouse=True)
def fresh_state():
    Base.metadata.drop_all(engine)
    init_db()
    with SessionLocal() as db:
        ledger.ensure_treasury(db)
    limiter.reset()
    yield


@pytest.fixture
def settings():
    return get_settings()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session


class Customer:
    """A registered + logged-in customer for tests."""

    def __init__(self, client: TestClient, email: str, access_token: str):
        self.client = client
        self.email = email
        self.token = access_token
        self.password = PASSWORD

    @property
    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}

    def accounts(self) -> list[dict]:
        return self.client.get("/api/accounts", headers=self.headers).json()

    @property
    def account(self) -> dict:
        return self.accounts()[0]

    def fund(self, cents: int) -> None:
        r = self.client.post(
            f"/api/accounts/{self.account['id']}/fund", json={"amount_cents": cents}, headers=self.headers
        )
        assert r.status_code == 201, r.text

    def enable_mfa(self) -> str:
        secret = self.client.post("/api/mfa/setup", headers=self.headers).json()["secret"]
        r = self.client.post("/api/mfa/enable", json={"code": totp.current_code(secret)}, headers=self.headers)
        assert r.status_code == 200, r.text
        return secret


def make_customer(client: TestClient, email: str = "alice@example.com", password: str = PASSWORD) -> Customer:
    r = client.post("/api/auth/register", json={"email": email, "password": password, "full_name": "Test User"})
    assert r.status_code == 202, r.text
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return Customer(client, email, r.json()["access_token"])


@pytest.fixture
def alice(client):
    return make_customer(client, "alice@example.com")


@pytest.fixture
def bob(client):
    # Separate cookie jar so Alice's session cookie does not leak into Bob's.
    with TestClient(app) as c2:
        yield make_customer(c2, "bob@example.com")


def make_admin(client: TestClient, email: str = "root@example.com") -> Customer:
    cust = make_customer(client, email)
    with SessionLocal() as db:
        db.query(User).filter(User.email == email).update({"role": "admin"})
        db.commit()
    return cust
