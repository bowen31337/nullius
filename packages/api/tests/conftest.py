"""Fixtures for the api member's own suite.

This suite lives inside the package (``packages/api/tests``) rather
than under the repository-level ``tests/`` tree, because the member —
including its tests — is this feature's file-claim scope, the same
placement the ops, router and cost-model members' suites take for the
same reason: same-basename files collide under one pytest run, so each
member's suite is collected under its own conftest.

The path bootstrap puts every declared workspace member's scan root on
``sys.path`` — not just this member's own ``src/`` — because the
transport serves the *composed* application: the route table resolves
components the ops, ledger, promotion, forward, nulloracle and risk
members register, and the store-wrap tests construct those members'
own endpoint classes over fake stores, so all of them must be
importable regardless of how pytest was invoked.  Resolved from the
root ``pyproject.toml``'s own ``[tool.uv.workspace]`` through
:func:`app.module_loader.workspace_scan_roots` rather than hard-coded,
the same convention ``packages/ops/tests/conftest.py`` follows and for
the same reason: a hard-coded path here could quietly disagree with
the declaration that decides whether a member is importable at all.

Every test gets a ``DATABASE_URL`` pointing at a test-only database
(``TEST_DATABASE_URL`` when provided, else a throwaway per-test SQLite
file), mirroring the repository-level conftest and the ops member's
own: the routes this transport serves write charges, registrations and
kills, exactly the rows a stray inherited ``DATABASE_URL`` would land
somewhere an operator reads.

Feature 21's certificate pair is built here too
(:func:`write_self_signed_certificate`), with the ``cryptography``
package the *nulloracle* member already brings into the workspace —
never a new dependency of this member's, and never a container on the
tests' ``sys.path``: a certificate generated at test time is a real
X.509 pair the standard library's ``ssl`` accepts and rejects for the
right reasons, where a checked-in PEM would be a fixture that could go
stale, expire, or be mistaken for a deployment's secret.
"""

from __future__ import annotations

import ipaddress
import json
import os
import ssl
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

# conftest.py -> packages/api/tests -> packages/api -> packages -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
APP_SRC = REPO_ROOT / "src"

if str(APP_SRC) not in sys.path:
    sys.path.insert(0, str(APP_SRC))

from app.module_loader import workspace_scan_roots

for _root in workspace_scan_roots():
    _entry = str(_root)
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from nullius_api.auth import API_SCOPES, ApiTokens
from nullius_api.tls import TLS_CERT_ENV, TLS_KEY_ENV

DATABASE_URL_ENV = "DATABASE_URL"
TEST_DATABASE_URL_ENV = "TEST_DATABASE_URL"


@pytest.fixture(autouse=True)
def _database_url_isolation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> str:
    """Point ``DATABASE_URL`` at a test-only database for every test.

    Mirrors the repository-level conftest and the ops member's own:
    ``TEST_DATABASE_URL`` wins when set and non-empty, else a per-test
    SQLite file under pytest's temporary directory.  An empty
    ``TEST_DATABASE_URL`` counts as unset.
    """
    url = os.environ.get(TEST_DATABASE_URL_ENV) or (
        f"sqlite:///{tmp_path / 'api-test.db'}"
    )
    monkeypatch.setenv(DATABASE_URL_ENV, url)
    return url


@pytest.fixture
def test_database_url(_database_url_isolation: str) -> str:
    """The isolated database URL for this test, as the code sees it."""
    return _database_url_isolation


# -- The token every request now needs (feature 18) -------------------------------
#
# Feature 18 puts a bearer token in front of every route but ``GET
# /healthz``, which means the suites written before it — every one of
# which asked without a header and asserted on the *route's* answer —
# now need a credential to reach the behaviour they are actually about.
# The helpers below are that credential, in one place, so the suites
# share one spelling of a test token rather than ten.
#
# ``TEST_TOKENS`` carries a token for each of the four scopes and is
# built with :meth:`ApiTokens.from_scope_tokens` rather than by hand, so
# the thing the suites authenticate with is the thing the loader
# produces — a fixture that spelled the entries itself could pass while
# the loader's own shape was wrong.

#: The token this suite presents for a given scope, when nothing more
#: specific is wanted.  Deliberately obvious strings: a test token that
#: looked like a real credential would be one more thing to grep for.
TEST_TOKENS = ApiTokens.from_scope_tokens(
    {
        "metrics:read": "test-metrics-token",
        "research": "test-research-token",
        "evaluator": "test-evaluator-token",
        "risk": "test-risk-token",
    },
    source="<the test suite's own token set>",
)


def token_for(scope: str) -> str:
    """The test token carrying ``scope`` — the credential a route needs."""
    for token, carried in TEST_TOKENS.entries:
        if carried == scope:
            return token
    raise AssertionError(f"no test token carries {scope!r}")  # pragma: no cover


#: :data:`TEST_TOKENS` written as the *file* feature 18 reads — scope →
#: list of tokens.  Derived from the token set rather than spelled a
#: second time, so the document a subprocess reads configures exactly
#: the credentials the in-process fixtures present; a second literal
#: could drift from the first and turn a boot test green for the wrong
#: reason.
TOKEN_FILE_DOCUMENT: dict[str, list[str]] = {
    scope: [token_for(scope)] for scope in API_SCOPES
}


def write_token_file(path: Path) -> str:
    """Write :data:`TOKEN_FILE_DOCUMENT` to ``path``; return it as text.

    The file's contents are the suite's own obvious fixture tokens, so
    writing them is safe — the constraint's *tokens are never written to
    a log* is a rule about the server, and a test fixture's credentials
    in a test's temporary directory are not a deployment's secret.
    """
    path.write_text(json.dumps(TOKEN_FILE_DOCUMENT), encoding="utf-8")
    return str(path)


@pytest.fixture
def tokens() -> ApiTokens:
    """The suite's token set, for a server built by hand."""
    return TEST_TOKENS


@pytest.fixture
def token_file(tmp_path: Path) -> str:
    """A token file on disk, as :data:`TOKENS_FILE_ENV` would name it."""
    return write_token_file(tmp_path / "api-tokens.json")


@pytest.fixture
def authorized() -> dict[str, str]:
    """An ``Authorization`` header for every scope, keyed by scope.

    ``authorized["risk"]`` is the header ``POST /risk/halt`` needs, and
    so on — so a test states *which* credential it means rather than
    repeating the ``Bearer`` framing, and a test that wants the wrong
    scope for a route writes ``authorized[OTHER_SCOPE]`` and reads as
    what it is.
    """
    return {
        scope: {"Authorization": f"Bearer {token_for(scope)}"} for scope in API_SCOPES
    }


# -- The certificate and key a non-loopback bind requires (feature 21) -------------
#
# The pair is *generated* rather than checked in.  A real self-signed
# X.509 certificate is what makes these tests worth having — the server
# loads it with ``ssl.SSLContext.load_cert_chain``, so a fixture that
# was not a real pair would prove nothing about the branch that serves
# HTTPS — and generating one per session keeps a private key out of the
# repository rather than committing a file that looks like a secret.
#
# ``cryptography`` is imported inside the helper, not at this module's
# top level: it is a dependency of the *nulloracle* member (``uv.lock``
# carries it for that member), not of this one, and an import at module
# scope would make every test in this suite depend on a package this
# member never declares.  A collection error on a machine where the
# workspace was not installed would then look like a transport fault.

#: The subject the fixture certificate carries.  A ``localhost`` common
#: name rather than a deployment-shaped one: nothing here is pretending
#: to be a real host's certificate, which is why no test verifies the
#: peer's identity (the client trusts this exact file).
CERTIFICATE_COMMON_NAME = "localhost"

#: How far *before* the issuing moment the fixture certificate becomes
#: valid.  X.509 times are absolute instants, and a clock in a timezone
#: ahead of UTC is easily ahead of a certificate generated from UTC — so
#: the window is opened a day in the past rather than at the instant of
#: generation, which is what keeps *valid on every machine that runs
#: this suite* a property of the fixture rather than of the machine's
#: clock.
CERTIFICATE_BACKDATE = timedelta(days=1)

#: How long the fixture certificate is valid for.  Long enough that a
#: slow suite never outlives it, short enough to read as a test fixture.
CERTIFICATE_DAYS = 365


def write_self_signed_certificate(
    directory: Path, name: str = "api-tls"
) -> tuple[str, str]:
    """Write a self-signed certificate and key; return both paths.

    ``(certificate, key)``, as PEM files under ``directory`` — the two
    paths ``NULLIUS_API_TLS_CERT`` and ``NULLIUS_API_TLS_KEY`` name, in
    that order, which is the order the feature sentence states them in.
    """
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, CERTIFICATE_COMMON_NAME)]
    )
    issued_at = datetime.now(UTC) - CERTIFICATE_BACKDATE
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(issued_at)
        .not_valid_after(issued_at + timedelta(days=CERTIFICATE_DAYS))
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName(CERTIFICATE_COMMON_NAME),
                    # The tests reach the server over loopback, so the
                    # certificate must name that *address* too: a client
                    # with ``check_hostname`` on matches an IP against
                    # the SAN's IP entries, never against a DNS name.
                    x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                ]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    cert_path = directory / f"{name}.pem"
    key_path = directory / f"{name}-key.pem"
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    return str(cert_path), str(key_path)


@pytest.fixture(scope="session")
def certificate_pair(tmp_path_factory: pytest.TempPathFactory) -> tuple[str, str]:
    """One self-signed pair for the whole session, and its two paths.

    Session-scoped because generating an RSA key is the slow part and
    nothing in this suite mutates the files; every test that needs a
    *different* pair (a mismatched key, a file that is not a
    certificate) writes its own on top of these.
    """
    return write_self_signed_certificate(tmp_path_factory.mktemp("api-tls"))


@pytest.fixture
def tls_env(
    certificate_pair: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> tuple[str, str]:
    """Put the fixture pair in the two variables feature 21 reads.

    Set through ``monkeypatch`` so a test that *wants* the unconfigured
    case only has to delete one of them, and so no test leaks a
    certificate path into the next one's environment.
    """
    certificate, key = certificate_pair
    monkeypatch.setenv(TLS_CERT_ENV, certificate)
    monkeypatch.setenv(TLS_KEY_ENV, key)
    return certificate, key


def ssl_client_context(certificate: str) -> ssl.SSLContext:
    """A client context that trusts exactly the fixture certificate.

    ``CERT_REQUIRED`` against the fixture's own CA, rather than the
    default context: the point of the HTTPS tests is that the *server*
    completed a real TLS handshake with the certificate it was
    configured with, and a client that had switched verification off
    would pass against a server serving the wrong key just as happily.
    """
    context = ssl.create_default_context(cafile=certificate)
    context.check_hostname = True
    return context
