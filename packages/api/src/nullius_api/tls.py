"""HTTPS: the certificate and key a non-loopback bind requires.

additions_spec_journeys.xml feature 21 at its seam — *System refuses to
bind a non-loopback host unless NULLIUS_API_TLS_CERT and
NULLIUS_API_TLS_KEY name a certificate and key, which returns a startup
error message naming the missing file, and serves HTTPS through the
standard library's ssl module when they do, so a bearer token never
crosses a network in cleartext.*

Three laws, and each one is the sentence's own clause made decidable.

**A non-loopback bind requires a certificate and a key.**  The host the
address resolved to is classified by :func:`is_loopback_host`;
:data:`DEFAULT_HOST` is loopback and so is every spelling of the
interface only this machine can reach, so a server started with no
configuration at all — the deployment feature 4 was written for — needs
nothing here and serves cleartext over a socket nothing off-machine can
reach.  The moment a deployment names another address, the two
variables must name a PEM certificate and a PEM private key, or the
server refuses to start.  This is deliberately *not* a warning: the
credential every route but ``GET /healthz`` is asked to carry is a
bearer token, and feature 18's whole point is that it identifies the
caller — a token sent over an interface a network can read is that
credential disclosed, to anyone watching, for as long as it is valid.
Refusing to bind closes that window by never opening it.

**The refusal names the file, and never a traceback.**  Every way the
posture can fail is one plain sentence naming the variable that is
missing or the path it named and the one repair beside it: unset,
empty, whitespace-only, a path that does not exist, a path that cannot
be read, and a pair of files that is not a certificate and a key.  This
is a startup message on standard error for an operator — the same
stance :class:`~nullius_api.auth.ApiTokenConfigError` and
:class:`~nullius_api.server.ExecutionEngineResolutionError` take, and
the reason the file's path *is* named here (it is the operator's own
variable coming back, and a response body's no-filesystem-path law does
not reach a refusal printed before any socket exists).  Nothing in any
message carries the file's contents.

**HTTPS is the standard library's ssl module.**  When the pair is
there, the *listening* socket is wrapped server-side
(:meth:`TlsConfig.wrap`, called by
:class:`~nullius_api.server.ApiServer` immediately after the bind, so
the address is never left accepting a cleartext connection), and every
connection accepted off it is TLS.  There is no second listener, no
redirect from a cleartext port and no cleartext fallback: a deployment
that asked for another interface gets an HTTPS server or no server.

The classification is *fail-closed*, which is the one judgement call
worth stating.  A host is loopback only when it is provably so — one of
:data:`LOOPBACK_NAMES`, or an IP literal whose own ``is_loopback`` is
true — and every name that is not one of those, including a hostname
that happens to resolve to 127.0.0.1 today, counts as non-loopback.  No
name is resolved here: a classification that asked a resolver would
answer differently on a machine with different DNS, would block a
startup on a name server, and would make the safety of a bind depend on
a record somebody else controls.  The cost of the conservative answer
is that such a deployment is asked for a certificate it could have
done without; the cost of the other one is a token on the wire.
"""

from __future__ import annotations

import ipaddress
import os
import ssl
from collections.abc import Mapping
from dataclasses import dataclass

__all__ = [
    "LOOPBACK_NAMES",
    "TLS_CERT_ENV",
    "TLS_KEY_ENV",
    "TlsConfig",
    "TlsConfigError",
    "is_loopback_host",
]

#: The environment naming the PEM certificate a non-loopback bind serves
#: TLS with, as the feature sentence spells it.
TLS_CERT_ENV = "NULLIUS_API_TLS_CERT"

#: The environment naming the PEM private key for that certificate.
TLS_KEY_ENV = "NULLIUS_API_TLS_KEY"

#: The hostnames that are loopback by name rather than by address.  The
#: ``ip6-*`` pair are the aliases glibc's own ``/etc/hosts`` carries for
#: ``::1``, listed because a deployment that named one of them meant the
#: loopback interface and a classification that answered otherwise would
#: demand a certificate for a local-only bind.  Every *other* name — a
#: LAN hostname, a public name, a name whose zone file the deployment
#: does not control — is non-loopback: see this module's docstring for
#: why nothing here resolves a name.
LOOPBACK_NAMES = frozenset(
    {"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"}
)


class TlsConfigError(Exception):
    """The TLS posture cannot be established, so the server cannot start.

    Raised for every way a non-loopback deployment can fail to state its
    certificate and key — either variable unset, empty or
    whitespace-only, a path that does not exist, a path this process
    cannot read, and a pair that is not a loadable PEM certificate and
    key — and raised by :meth:`TlsConfig.resolve` *before* anything
    binds, so no ordering exists in which a socket is open on a
    non-loopback interface and the certificate question is still
    unanswered.

    The message names the variable or the path and the one repair, with
    the certifying file's own contents never echoed.  The entrypoint
    reports it as one plain sentence on standard error and exits (status
    2) — the same stance
    :class:`~nullius_api.auth.ApiTokenConfigError` takes for a missing
    token file and
    :class:`~nullius_api.server.ExecutionEngineResolutionError` for an
    engine path that does not resolve, and never a traceback.
    """


def is_loopback_host(host: str) -> bool:
    """Whether ``host`` provably names the loopback interface only.

    ``127.0.0.1``, ``::1`` and the names in :data:`LOOPBACK_NAMES` are
    loopback; ``0.0.0.0``, ``::`` and ``192.0.2.10`` are not, and neither
    is any name that is not one of the aliases above.  Bracketed IPv6
    literals (``[::1]``, the spelling a URL uses), surrounding
    whitespace and a trailing DNS dot are all normalised first, because
    each is a spelling of the same address rather than a different one.

    Nothing is resolved, so this is a pure function of the string the
    deployment gave: the same host classifies the same way on every
    machine, and a startup never waits on a resolver.
    """
    name = (host or "").strip()
    if name.startswith("[") and name.endswith("]"):
        name = name[1:-1]
    name = name.rstrip(".").lower()
    if not name:
        return False
    if name in LOOPBACK_NAMES:
        return True
    try:
        address = ipaddress.ip_address(name)
    except ValueError:
        return False
    return address.is_loopback


def _require_readable_file(variable: str, path: str) -> None:
    """Refuse a path that is not a file this process can read.

    The existence check the sentence asks for, made by *opening* the
    file rather than by asking whether it is there: a path that exists
    and cannot be read is the same startup failure with a different
    repair, and ``open`` is the one call that answers both.  The failure
    is named — the variable, the path, and the repair — and the file's
    contents are not read, echoed or logged.
    """
    try:
        with open(path, "rb"):
            pass
    except FileNotFoundError as exc:
        raise TlsConfigError(
            f"{variable} names {path}, which does not exist. The repair is "
            f"{variable} naming the file at that path, or --host 127.0.0.1 "
            "to serve this machine only; a non-loopback bind without a "
            "certificate would put every bearer token on the wire in "
            "cleartext, so the server refuses to start"
        ) from exc
    except IsADirectoryError as exc:
        raise TlsConfigError(
            f"{variable} names {path}, which is a directory. The repair is "
            f"{variable} naming a PEM file, or --host 127.0.0.1 to serve "
            "this machine only"
        ) from exc
    except OSError as exc:
        raise TlsConfigError(
            f"{variable} names {path}, which could not be read "
            f"({type(exc).__name__}). The repair is a PEM file this process "
            "may read; the cause is in the server's log"
        ) from exc


def _load_context(cert: str, key: str) -> ssl.SSLContext:
    """The server context for ``cert`` and ``key``, or a refusal by name.

    Built on :data:`ssl.PROTOCOL_TLS_SERVER`, which brings the standard
    library's own defaults for the protocol floor and the cipher list:
    this module chooses no version and no suite of its own, because a
    hand-rolled policy here would be a second place the deployment's
    security is decided and would age worse than the one OpenSSL ships.
    """
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    try:
        context.load_cert_chain(certfile=cert, keyfile=key)
    except (OSError, ssl.SSLError) as exc:
        raise TlsConfigError(
            f"{TLS_CERT_ENV} names {cert} and {TLS_KEY_ENV} names {key}, "
            f"which could not be loaded as a certificate and private key "
            f"({type(exc).__name__}). The repair is a PEM certificate and "
            "its matching PEM private key; neither file's contents are "
            "reported here or written to a log"
        ) from exc
    return context


@dataclass(frozen=True)
class TlsConfig:
    """One deployment's TLS posture: the host, the pair, and whether.

    ``enabled`` is the whole answer a caller reads: *this server serves
    HTTPS*.  It is true exactly when the bind host is non-loopback and
    both variables named a readable certificate and key — so the three
    fields are never in a state where a caller has to re-derive the
    decision, and :attr:`scheme` and :attr:`url` read off it directly.

    A value rather than a live :class:`ssl.SSLContext`, deliberately.
    The context is built twice — once while resolving, so a certificate
    that is not one is refused *before* the bind, and once while
    wrapping — because a frozen value that held a mutable, thread-aware
    context would be a value that could not be compared, hashed or
    reasoned about, and because the two builds are the same three
    standard-library calls.  Nothing here is a secret: the paths are the
    operator's own variables and no message this module writes carries
    either file's contents.
    """

    #: The host this posture was resolved for — carried so a refusal and
    #: a startup log can name the bind the certificate was demanded for.
    host: str = ""

    #: The PEM certificate path, or ``None`` — set even when disabled,
    #: because a loopback bind that *was* given a pair must be reported
    #: as cleartext rather than silently upgraded.
    cert: str | None = None

    #: The PEM private key path, or ``None``.
    key: str | None = None

    #: Whether the server serves HTTPS.
    enabled: bool = False

    @classmethod
    def resolve(
        cls,
        host: str,
        *,
        env: Mapping[str, str] | None = None,
    ) -> TlsConfig:
        """Resolve the TLS posture for ``host``, or refuse to start.

        ``env`` defaults to the process environment, the same default
        :meth:`~nullius_api.server.ApiConfig.resolve` and
        :meth:`~nullius_api.auth.ApiTokens.from_env` take.  An unset,
        empty or whitespace-only value counts as absent — the members'
        own unset semantics — and a *loopback* host short-circuits to a
        disabled posture before either variable is read, so a local-only
        deployment is never refused for a certificate it does not need
        and never has one silently imposed on it either.

        A non-loopback host with no pair is the sentence's refusal, and
        it is raised here rather than remembered by a caller: the
        classification and the demand are one expression, so there is no
        path on which a non-loopback address reaches a bind without
        having been asked.  A pair that is named but unusable — absent,
        unreadable, not a PEM certificate and key — is the same refusal
        one step later, and both happen before the socket is taken.
        """
        source = os.environ if env is None else env
        if is_loopback_host(host):
            return cls(host=host)
        cert = (source.get(TLS_CERT_ENV) or "").strip()
        key = (source.get(TLS_KEY_ENV) or "").strip()
        missing = [
            variable
            for variable, value in ((TLS_CERT_ENV, cert), (TLS_KEY_ENV, key))
            if not value
        ]
        if missing:
            raise TlsConfigError(
                _missing_message(host, missing, cert=cert, key=key)
            )
        _require_readable_file(TLS_CERT_ENV, cert)
        _require_readable_file(TLS_KEY_ENV, key)
        _load_context(cert, key)  # refused here, before anything binds
        return cls(host=host, cert=cert, key=key, enabled=True)

    @property
    def scheme(self) -> str:
        """``https`` when this posture serves TLS, ``http`` when not."""
        return "https" if self.enabled else "http"

    def url(self, port: int) -> str:
        """The URL a deployment reaches this bind at — its own scheme."""
        return f"{self.scheme}://{self.host}:{port}"

    def wrap(self, sock: object) -> object:
        """Wrap the *listening* socket server-side, or return it unchanged.

        The whole of *serves HTTPS*: an :class:`ssl.SSLContext` built
        from the pair, wrapping a socket that has already been bound and
        is not yet accepted on — the wrap
        :class:`~nullius_api.server.ApiServer` performs in its own
        constructor, immediately after ``super().__init__`` bound the
        address and before ``serve_forever`` could accept anything.  A
        cleartext connection to that port therefore fails the handshake
        and is closed: there is no moment at which the address answers
        HTTP, which is what makes the sentence's *never crosses a
        network in cleartext* a property of the socket rather than of a
        redirect or a convention.

        A disabled posture returns the socket untouched, so the loopback
        case is exactly the server feature 4 built — same socket, same
        code path, nothing wrapped.
        """
        if not self.enabled:
            return sock
        assert self.cert is not None and self.key is not None  # by resolve
        return _load_context(self.cert, self.key).wrap_socket(sock, server_side=True)


def _missing_message(
    host: str, missing: list[str], *, cert: str, key: str
) -> str:
    """The refusal for a non-loopback bind with an incomplete pair.

    One sentence naming the address the deployment asked for, which of
    the variables named nothing, the value that *was* given where there
    was one — an operator who set a key and no certificate needs to see
    that the key was seen — and the one repair.

    The verb agrees with the subject and the noun agrees with how many
    variables are missing, because the operator reads this once, at
    startup, with no other clue: "NULLIUS_API_TLS_CERT and
    NULLIUS_API_TLS_KEY name no certificate and key" when neither was
    set, "NULLIUS_API_TLS_CERT names no certificate" when only that one
    was.  A half pair is not described as a missing pair — the variable
    that *was* set is reported beside it, so the sentence never sends an
    operator to look at a file they already configured.
    """
    given = [
        (variable, value)
        for variable, value in ((TLS_CERT_ENV, cert), (TLS_KEY_ENV, key))
        if value
    ]
    if missing:
        subject = " and ".join(missing)
        verb = "names" if len(missing) == 1 else "name"
        both = "certificate and key" if len(missing) == 2 else _wanted(missing[0])
        sentence = (
            f"{subject} {verb} no {both}, and this server was told to "
            f"bind {host}, which is not the loopback interface"
        )
    else:  # unreachable by resolve; a pair that named nothing at all
        sentence = (
            f"neither {TLS_CERT_ENV} nor {TLS_KEY_ENV} names a certificate "
            f"and key, and this server was told to bind {host}, which is not "
            "the loopback interface"
        )
    if given:
        seen = "; ".join(
            f"{variable} names {value}" for variable, value in given
        )
        sentence += f" ({seen})"
    return (
        f"{sentence}. The repair is {TLS_CERT_ENV} and {TLS_KEY_ENV} naming a "
        "PEM certificate and its private key, or --host 127.0.0.1 to serve "
        "this machine only; a bearer token must never cross a network in "
        "cleartext, so the server refuses to bind rather than serve an open "
        "cleartext socket"
    )


def _wanted(variable: str) -> str:
    """The noun a single missing variable names — its half of the pair."""
    return "certificate" if variable == TLS_CERT_ENV else "private key"
