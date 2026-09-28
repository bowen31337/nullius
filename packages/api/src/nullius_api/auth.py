"""The bearer-token gate: who may ask, and what each asker may ask for.

additions_spec_journeys.xml feature 18 at its seam — *System requires a
bearer token on every route except GET /healthz, read from the token
file NULLIUS_API_TOKENS_FILE names with each token scoped to
metrics:read, research, evaluator or risk, which returns 401 for a
missing or unknown token, 403 for a token outside the route's scope,
and refuses to start when no token is configured* — split out of
:mod:`nullius_api.server` because the law is about *identity*, not
about transport: the dispatch decides what a request reaches, and this
module decides whether it is allowed to reach it at all.

Four laws shape it:

**One token, one scope.**  The sentence scopes each token to one of
four words, so the file maps *scope → the tokens that carry it* and a
token that appears under two of them is refused rather than resolved to
whichever the loader happened to see last.  That is the same rule
:mod:`nullius_api.json_encoding` states for two mapping keys that would
spell one text — an ambiguous mapping is refused, never silently
collapsed — and it is what makes :meth:`ApiTokens.scope_for` a function
rather than a guess.  A deployment wanting one credential to reach two
surfaces is asking for two tokens, which is also the answer that keeps
a leaked metrics credential from flattening the book.

**The file is a JSON object, and it is read strictly.**  ``{"metrics:read":
["…"], "research": ["…"], …}`` — the shape the workspace's config
documents already take, so an operator who has edited any other config
in this repository already knows how to edit this one.  Every departure
is refused by name with the one repair: a top level that is not an
object, a key that is not one of the four scope words (a typo like
``metric:read`` would otherwise be a scope that silently never
authenticates anybody), a value that is not a non-empty list of
non-empty strings, a token carrying whitespace (which could not survive
the ``Bearer`` scheme's own framing, so accepting it would store a
credential nobody can present).  Nothing is coerced, stripped or
defaulted: a token with a stray newline is refused so the operator
learns the file says something other than what they meant.

**Absence refuses; it does not open.**  *A missing token file is a
refusal to start, not an open server* — the constraint's own words.  So
an unset or empty :data:`TOKENS_FILE_ENV`, a path that does not exist, a
document that is not JSON and a file holding no tokens at all are all
:class:`ApiTokenConfigError`, raised before the socket binds.  A server
that started tokenless and answered 200 would be the one failure mode
this feature exists to prevent, so it cannot be reached by forgetting a
variable.

**The comparison is constant time, and the token is never echoed.**  A
presented token is checked against every configured one through
:func:`hmac.compare_digest` rather than a dictionary lookup, so the time
the answer takes does not report how much of a guess was correct.  And
nothing on the way out carries the secret: the refusals below name the
*scope* and the file, never the token that was presented or any token
that is configured, because a body an operator reads and a log an
operator keeps are both places a credential must never land (the
constraint's *tokens and request bodies are never written to a log*).
The value itself closes the last door on that: :meth:`ApiTokens.__repr__`
is written by hand to print the count and the scopes, since the repr
``@dataclass`` generates would print the credentials, and a value's repr
is exactly what a log line or a traceback reaches for.
"""

from __future__ import annotations

import hmac
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

__all__ = [
    "API_SCOPES",
    "EVALUATOR",
    "METRICS_READ",
    "RESEARCH",
    "RISK",
    "TOKENS_FILE_ENV",
    "ApiTokenConfigError",
    "ApiTokens",
    "bearer_token",
    "load_tokens",
]

#: The environment naming the token file, as the feature sentence spells
#: it.  Its absence is a refusal to start (:meth:`ApiTokens.from_env`).
TOKENS_FILE_ENV = "NULLIUS_API_TOKENS_FILE"

#: The four scope words the sentence closes the vocabulary to, spelled
#: here once so the token file's validation, the route table's rows and
#: the 403's message can never disagree about what may be asked for.
#: ``metrics:read`` carries a colon because it names a *capability over a
#: surface* while the other three name an actor; the asymmetry is the
#: spec's and is kept verbatim rather than tidied.
METRICS_READ = "metrics:read"
RESEARCH = "research"
EVALUATOR = "evaluator"
RISK = "risk"

#: The closed vocabulary, ordered as the sentence states it — a tuple so
#: every refusal that lists the alternatives reads the same way.
API_SCOPES: tuple[str, ...] = (METRICS_READ, RESEARCH, EVALUATOR, RISK)


class ApiTokenConfigError(Exception):
    """The token configuration cannot be loaded, so the server cannot start.

    Raised for every way the deployment can fail to state who may ask:
    :data:`TOKENS_FILE_ENV` unset or empty, a path that does not exist or
    cannot be read, a document that is not the JSON object of scopes, a
    scope word outside :data:`API_SCOPES`, a malformed token list, a
    token that appears twice, and a file that configures no token at
    all.  The entrypoint reports it as one plain sentence and exits
    (status 2), the same stance
    :class:`~nullius_api.server.ExecutionEngineResolutionError` takes for
    an engine path that does not resolve.

    Every message names the file it read and the one repair, and never
    the traceback of the cause: the reader is an operator starting a
    server, and the file's path is exactly what they must act on (it is
    a startup message on standard error, not a response body, so the
    envelope's no-filesystem-path law does not reach it).  No message
    ever carries a token.
    """


def bearer_token(header: str | None) -> str | None:
    """The token inside an ``Authorization`` header, or ``None``.

    ``Bearer <token>`` is the one scheme this transport accepts, and RFC
    7235 makes the scheme name case-insensitive, so ``bearer``, ``Bearer``
    and ``BEARER`` all parse — refusing the lower-case spelling would
    refuse a caller who read the grammar correctly.  Anything else
    answers ``None``: a bare token with no scheme, a different scheme
    (``Basic``), a scheme with no token after it, or no header at all.
    All of those are the same fact to the dispatch — *this request
    presented no usable token* — which is why they share a return value
    rather than becoming four refusals: the caller's repair is identical
    in each case, and telling them apart would report on the shape of a
    credential rather than on whether it was usable.

    The token is returned exactly as it arrived, never lower-cased or
    stripped of interior whitespace (only the framing spaces around it
    are the scheme's).  Configured tokens may not contain whitespace
    (:func:`load_tokens`), so a presented token carrying any is simply
    never a match — and it is still returned here rather than refused,
    so this function stays a parser and the *policy* stays in the
    dispatch that answers 401.
    """
    if not header:
        return None
    scheme, separator, value = header.partition(" ")
    if not separator or scheme.strip().lower() != "bearer":
        return None
    return value.strip() or None


@dataclass(frozen=True)
class ApiTokens:
    """Every configured token and the one scope it carries.

    Stored as an ordered tuple of ``(token, scope)`` pairs rather than a
    mapping, because the lookup that matters is not *is this token a key*
    but *does this token equal any configured one, in constant time* —
    see :meth:`scope_for`.  The tuple keeps that scan's order
    deterministic (the file's own), and being hashable and immutable it
    lets the whole value be compared and shared safely, which a mutable
    mapping would not.

    ``source`` is the file the tokens were read from, carried for the
    startup log and for refusals composed after loading.  It is a
    filesystem path, and it is safe here for the reason
    :class:`ApiTokenConfigError` states: it reaches standard error and
    the server's own log, never a response body.
    """

    entries: tuple[tuple[str, str], ...] = ()
    source: str = "<in-process>"

    def __post_init__(self) -> None:
        """Refuse a set built by hand that the constructors would refuse.

        ``from_scope_tokens`` and :func:`load_tokens` both validate, but
        they are not the only way to build this value — it is a plain
        frozen dataclass, so ``ApiTokens(entries=(("", "risk"),))``
        bypasses every check above.  Since the whole point of the type
        is that a server holding one cannot be open, the invariants are
        re-asserted here rather than trusted to the callers: the scopes
        are the four words, no token is empty or whitespace-bearing, and
        no token appears twice.  Construction is not a hot path, so the
        cost of checking is nothing next to the cost of being wrong.
        """
        seen: dict[str, str] = {}
        for token, scope in self.entries:
            if scope not in API_SCOPES:
                raise ApiTokenConfigError(
                    f"{scope!r} is not one of the four scope words "
                    f"({' , '.join(API_SCOPES)}); the repair is one of "
                    "those words"
                )
            if not isinstance(token, str) or not token:
                raise ApiTokenConfigError(
                    f"the token for scope {scope!r} is empty; every caller "
                    "would already hold it, so the repair is a non-empty "
                    "token"
                )
            if any(character.isspace() for character in token):
                raise ApiTokenConfigError(
                    f"the token for scope {scope!r} contains whitespace, "
                    "which the Authorization header's framing cannot carry; "
                    "the repair is a token with none"
                )
            if token in seen:
                raise ApiTokenConfigError(
                    f"the token carrying scope {scope!r} is configured "
                    f"under scope {seen[token]!r} as well; the repair is "
                    "one scope per token"
                )
            seen[token] = scope
        if not self.entries:
            raise ApiTokenConfigError(
                "no token is configured at all; the repair is at least one "
                "scope naming at least one token, and a server refuses to "
                "start rather than serve an open API"
            )

    def __len__(self) -> int:
        """How many tokens are configured — the count, never the tokens."""
        return len(self.entries)

    def __repr__(self) -> str:
        """The count and the scopes — never the tokens.

        ``@dataclass`` would otherwise generate a repr printing every
        field, and this type's fields *are* the credentials: one
        ``log.info("tokens: %s", tokens)``, or a traceback rendering a
        frame's locals, would put the whole set in a log file, which the
        constraint forbids outright.  Writing the repr by hand makes
        that unreachable rather than a rule somebody has to remember —
        the same way :meth:`scope_for` makes a variable-time comparison
        unreachable rather than a discipline.  What it prints is what
        the startup log already prints: how many tokens, over which
        scopes, from which file.
        """
        return (
            f"ApiTokens({len(self.entries)} tokens over "
            f"{list(self.scopes)!r} from {self.source!r})"
        )

    @property
    def scopes(self) -> tuple[str, ...]:
        """The scopes that carry at least one token, in the file's order.

        A scope the deployment configured no token for is absent rather
        than empty — *no token reaches this surface* is a different fact
        from *the surface has no scope*, and the 403's message says
        which (its repair is a token for the scope, which is exactly
        what this list is missing).
        """
        return tuple(dict.fromkeys(scope for _token, scope in self.entries))

    def scope_for(self, token: str) -> str | None:
        """The scope ``token`` carries, or ``None`` when it is unknown.

        Every configured token is compared, and none of them returns
        early: the loop scans the whole set through
        :func:`hmac.compare_digest` so the time this takes is a fact
        about how many tokens the deployment configured and not about
        how many leading characters a guess got right.  A dictionary
        lookup would answer the same question faster and would leak
        precisely that — for a credential check, the fast answer is the
        wrong one.

        The comparison is over UTF-8 bytes rather than text because
        ``compare_digest`` accepts only ASCII strings, and a configured
        token is free to be any text the file spells; comparing bytes
        makes a non-ASCII token a supported credential instead of a
        ``TypeError`` at authentication time.  A miss (``None``) is the
        dispatch's 401, never an exception.
        """
        presented = token.encode("utf-8")
        found: str | None = None
        for configured, scope in self.entries:
            if hmac.compare_digest(configured.encode("utf-8"), presented):
                found = scope
        return found

    @classmethod
    def from_scope_tokens(
        cls,
        mapping: Mapping[str, str],
        *,
        source: str = "<in-process>",
    ) -> ApiTokens:
        """Build a token set one-token-per-scope, in memory.

        :func:`load_tokens`'s inverse for callers that are not reading a
        file: a test wanting a known credential, or a deployment binding
        its tokens from a source other than the environment.  It applies
        *the same* validation as the file door — the four scope words,
        non-empty whitespace-free tokens, no token twice — because a set
        built here is checked by :meth:`scope_for` exactly like a loaded
        one, and a second, laxer constructor would be a way to configure
        a credential the file format refuses.  That is also what makes
        it useful as a test double: :data:`TEST_TOKENS` in the suite is
        built through this, so a test token is shaped by the same rules
        a real one is.

        A token appearing under two scopes is refused here for the same
        reason the file refuses it, so the ambiguity cannot be laundered
        by building in memory instead of reading a file.
        """
        bad_scopes = sorted(set(mapping) - set(API_SCOPES))
        if bad_scopes:
            raise ApiTokenConfigError(
                f"{', '.join(repr(scope) for scope in bad_scopes)} is not "
                f"one of the four scope words "
                f"({' , '.join(API_SCOPES)}). The repair is one of those "
                "words — a scope the transport does not know would be a "
                "token that silently authenticates nobody"
            )
        entries: list[tuple[str, str]] = []
        seen: dict[str, str] = {}
        for scope, token in mapping.items():
            _check_token(source, scope, token)
            if token in seen:
                raise ApiTokenConfigError(
                    f"the token carrying scope {scope!r} is configured "
                    f"under scope {seen[token]!r} as well. The repair is "
                    "one scope per token — a token with two scopes is not "
                    "a credential with two rights but an ambiguity about "
                    "which one applies"
                )
            seen[token] = scope
            entries.append((token, scope))
        if not entries:
            raise ApiTokenConfigError(
                "no token is configured at all. The repair is at least one "
                "scope naming at least one token; a server refuses to "
                "start rather than serve an open API"
            )
        return cls(entries=tuple(entries), source=source)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> ApiTokens:
        """Load the tokens :data:`TOKENS_FILE_ENV` names, or refuse to start.

        ``env`` defaults to the process environment, the same default
        :meth:`~nullius_api.server.ApiConfig.resolve` takes for the bind
        address.  An unset, empty or whitespace-only value is a refusal
        rather than an open server — the constraint's own law — and it is
        raised here, *before* anything binds, so the window in which a
        tokenless server could answer a request does not exist.
        """
        source = os.environ if env is None else env
        path = (source.get(TOKENS_FILE_ENV) or "").strip()
        if not path:
            raise ApiTokenConfigError(
                f"{TOKENS_FILE_ENV} is unset, so this server has no tokens "
                "and no way to tell a caller who may ask. The repair is "
                f"{TOKENS_FILE_ENV} naming a JSON file that maps each of "
                f"{' , '.join(API_SCOPES)} to the tokens carrying it; the "
                "server refuses to start rather than serve an open API, "
                "and GET /healthz is the one route that never needed a "
                "token"
            )
        return load_tokens(path)


def load_tokens(path: str) -> ApiTokens:
    """Read and validate the token file at ``path``.

    The whole of the file's contract, refused by name and never
    coerced: see this module's docstring for the shape and for why each
    departure is an error rather than a default.  Every refusal names
    ``path`` — which is the operator's own variable coming back, not a
    leaked deployment path — and the one repair.

    A document that configures *no* token is refused here as well as at
    the environment door: an empty object, or a file where every scope
    maps to an empty list, is the same open server by a longer route.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            document = json.load(handle)
    except FileNotFoundError as exc:
        raise ApiTokenConfigError(
            f"{TOKENS_FILE_ENV} names {path}, which does not exist. The "
            "repair is a token file at that path — a JSON object mapping "
            f"each of {' , '.join(API_SCOPES)} to the tokens carrying it "
            "— and the server refuses to start rather than serve an open "
            "API"
        ) from exc
    except OSError as exc:
        raise ApiTokenConfigError(
            f"{TOKENS_FILE_ENV} names {path}, which could not be read "
            f"({type(exc).__name__}). The repair is a token file this "
            "process may read; the cause is in the server's log"
        ) from exc
    except (UnicodeDecodeError, ValueError) as exc:
        raise ApiTokenConfigError(
            f"{TOKENS_FILE_ENV} names {path}, which is not JSON. The "
            "repair is one JSON object mapping each of "
            f"{' , '.join(API_SCOPES)} to the tokens carrying it; the "
            "file's contents are not echoed here and are not written to "
            "a log"
        ) from exc

    if not isinstance(document, dict):
        raise ApiTokenConfigError(
            f"{TOKENS_FILE_ENV} names {path}, whose top level is a JSON "
            f"{type(document).__name__}, not an object. The repair is one "
            "JSON object keyed by scope, each value the list of tokens "
            "carrying it"
        )

    entries: list[tuple[str, str]] = []
    seen: dict[str, str] = {}
    for scope, tokens in document.items():
        if scope not in API_SCOPES:
            raise ApiTokenConfigError(
                f"{TOKENS_FILE_ENV} names {path}, which keys a scope "
                f"{scope!r}; the four scope words are "
                f"{' , '.join(API_SCOPES)}. The repair is one of those "
                "words — a scope the transport does not know would be a "
                "token that silently authenticates nobody"
            )
        if not isinstance(tokens, list) or not tokens:
            raise ApiTokenConfigError(
                f"{TOKENS_FILE_ENV} names {path}, where scope {scope!r} "
                f"holds {tokens!r}; each scope holds a non-empty list of "
                "tokens. The repair is the list of tokens carrying that "
                "scope, or the key removed entirely — a scope with no "
                "tokens is a surface no credential reaches, which is a "
                "deployment fact worth stating rather than an empty list"
            )
        for token in tokens:
            _check_token(path, scope, token)
            if token in seen:
                raise ApiTokenConfigError(
                    f"{TOKENS_FILE_ENV} names {path}, which configures the "
                    f"token carrying scope {scope!r} under scope "
                    f"{seen[token]!r} as well. The repair is one scope per "
                    "token — a token with two scopes is not a credential "
                    "with two rights but an ambiguity about which one "
                    "applies, and the transport refuses it rather than "
                    "resolving it to whichever the loader saw last"
                )
            seen[token] = scope
            entries.append((token, scope))

    if not entries:
        raise ApiTokenConfigError(
            f"{TOKENS_FILE_ENV} names {path}, which configures no token at "
            "all. The repair is at least one scope naming at least one "
            "token; the server refuses to start rather than serve an open "
            "API"
        )
    return ApiTokens(entries=tuple(entries), source=path)


def _check_token(path: str, scope: str, token: Any) -> None:
    """Refuse a token that is not a non-empty, whitespace-free string.

    Three departures, one repair each, and all three are the same
    question — *could this string ever come back through the ``Bearer``
    scheme?*  A non-string cannot be compared to a credential at all; an
    empty string is a credential every caller already holds; and a token
    containing whitespace could not survive the scheme's own framing, so
    storing it would be storing a secret nobody can present.
    """
    if not isinstance(token, str):
        raise ApiTokenConfigError(
            f"{TOKENS_FILE_ENV} names {path}, where scope {scope!r} holds "
            f"a token of type {type(token).__name__}; every token is a "
            "string. The repair is the token written as JSON text"
        )
    if not token:
        raise ApiTokenConfigError(
            f"{TOKENS_FILE_ENV} names {path}, where scope {scope!r} holds "
            "an empty token, which every caller would already hold. The "
            "repair is a non-empty token, or the entry removed"
        )
    if any(character.isspace() for character in token):
        raise ApiTokenConfigError(
            f"{TOKENS_FILE_ENV} names {path}, where the token for scope "
            f"{scope!r} contains whitespace. The repair is a token with "
            "none: an Authorization header carries the credential after "
            "a single space, so a token containing whitespace could "
            "never be presented, and it is refused here rather than "
            "stored as a credential nobody can use"
        )
