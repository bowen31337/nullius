"""Feature 153's law: separate credentials per environment.

app_spec.xml, "Trust Zone Isolation & Secrets", feature 153: *System
uses separate credentials per environment, so a shadow sub-account key
returns 401 against the live account.*  docs/nullius-tech-architecture.md
§17 states the control in two lines — "Separate keys per environment. The
shadow sub-account key must not work on the live account." — and the
deployment note drives it home: "Separate keys per environment. The shadow
sub-account key must not work on the live account."  This module is that
line made structural.  The sentence decomposes into three claims, and this
module owns all three:

* **separate credentials per environment** — the subject is a *binding*,
  not a secret.  A deployment has two environments here — the shadow
  account it trades against while developing and validating, and the live
  account that moves real capital — and each carries its own exchange key.
  The module's job is to hold that binding (:class:`CredentialScope`) and
  to be asked, of any presented key, *which environment it belongs to*.
  That classification is the whole of the control: a key is not "valid" or
  "invalid" in the abstract, it is valid *for an environment*, and the
  environment it is valid for is a property of the key itself, fixed when
  the exchange issues it.  The binding keys on :data:`LIVE_SCOPE` and
  :data:`SHADOW_SCOPE` so it holds for every key the deployment ever mints
  — a key inherits its environment by the marker the exchange stamps into
  it, not by someone remembering which account it was issued against.

* **so a shadow sub-account key** — the *shape* of the shadow credential.
  Exchanges issue the shadow key against a *sub-account*, a child account
  the broker provisions for testing: the same market, the same API, a
  separate balance and a separate key.  That sub-account marker is what
  this module reads to classify a key — the field an exchange puts in the
  key or its attached metadata that says "this key was issued for the
  shadow sub-account, not the live one."  The classifier does not invent
  the marker: it reads the environment the deployment declares the key
  belongs to (:meth:`CredentialScope.scope_of`), because the exchange's
  issuance is the source of truth and a guessed marker would be a second,
  divergent source.

* **returns 401 against the live account** — the *consequence*, and the
  claim that orders everything else.  When the live execution path
  authenticates with a key that the binding says is a shadow key, the
  exchange refuses it — the sub-account's key is not a key the live
  account recognises, so the request is answered ``401 Unauthorized``
  (:data:`UNAUTHORIZED`, the HTTP status the exchange returns, not a
  home-grown sentinel).  The refusal is not a warning and not a fallback:
  it is the environment boundary asserting itself.  The reverse is the
  same law seen from the other side — a live key presented to the shadow
  account is refused just as firmly — and the module refuses to *mint* a
  key whose declared environment does not match the environment it would
  authenticate against, because a key that claims to be shadow but carries
  a live marker (or vice versa) is exactly the cross-environment
  credential the feature exists to make impossible.

The module is a *policy*, not a client: it names the environments, reads
the binding an exchange stamped, and states the consequence, so the claim
"a shadow sub-account key returns 401 against the live account" can be
checked against the binding rather than taken from the prose.  It does not
dial an exchange — that is the execution path's step, which starts from
the binding this module holds — and it owns no secret: the keys are
deployment secrets managed out of band (feature 151, the secrets manager),
and what this module classifies is the environment a key belongs to, never
the key's material.

Stdlib-only, like the rest of the zone's tooling.  Nothing here
authenticates over a network; this module is the binding a caller consults
before it does.
"""

from __future__ import annotations

from typing import Final

__all__ = [
    "LIVE_SCOPE",
    "SHADOW_SCOPE",
    "UNAUTHORIZED",
    "CredentialScope",
    "CredentialScopeError",
    "ScopeMismatch",
    "classify_credential",
    "scope_of",
]

#: The HTTP status an exchange returns when a presented key is not a key
#: the account recognises.  Feature 153's "401" is this status verbatim:
#: the shadow sub-account key, presented to the live account, is answered
#: with this, not with a home-grown sentinel, so the consequence the spec
#: names is the one the wire carries.
UNAUTHORIZED: Final[int] = 401

#: The environment that moves real capital.  A key belongs here iff the
#: exchange issued it against the live account; the binding keys on this
#: scope so every live key is classified by the environment it was minted
#: for, not by a name someone typed at call time.
LIVE_SCOPE: Final[str] = "live"

#: The environment that trades paper.  A key belongs here iff the exchange
#: issued it against the shadow sub-account — the child account the broker
#: provisions for development and validation, separate balance, separate
#: key.  The sub-account marker is what :meth:`CredentialScope.scope_of`
#: reads to place a key here.
SHADOW_SCOPE: Final[str] = "shadow"


class CredentialScopeError(Exception):
    """Base of the credential-scope taxonomy.

    One base class so a caller — the live execution path that must refuse
    a shadow key before it places an order, the shadow path that must
    refuse a live key, an operator script that audits which environment a
    key belongs to — can catch every failure of the classification path
    with a single ``except``.  The subclasses split by *which contract*
    was violated, not by which line of code failed.
    """


class ScopeMismatch(CredentialScopeError):
    """A key's declared environment does not match the environment it was
    presented against.

    Feature 153's "separate credentials per environment" is the whole of
    this: a key classified as shadow, presented to the live account (or a
    live key presented to the shadow account), is refused rather than
    accepted.  The exchange answers such a presentation with
    :data:`UNAUTHORIZED` — the sub-account's key is not a key the live
    account recognises — and this is the policy-side double of that
    answer: the binding says the key belongs to the other environment, so
    the caller refuses it here, before the request ever reaches the wire.
    Refused rather than coerced, because a cross-environment credential
    that silently succeeded would be discovered only when it traded
    against the wrong account, which is the exact failure the feature
    exists to prevent.
    """


class CredentialScope:
    """The environment a credential belongs to, as the exchange stamped it.

    Deliberately a small value object rather than a bare string: the two
    environments are a closed set, and carrying the environment as a typed
    member — not a ``str`` that any typo could widen — is what keeps a
    caller from classifying a key against an environment the deployment
    does not have.  ``name`` is the environment this scope *is*;
    :meth:`scope_of` is how a presented key is placed into one.
    """

    __slots__ = ("name",)

    def __init__(self, name: str) -> None:
        if name not in (LIVE_SCOPE, SHADOW_SCOPE):
            raise CredentialScopeError(
                f"credential scope {name!r} is not one of the deployment's "
                f"environments ({LIVE_SCOPE!r}, {SHADOW_SCOPE!r}); feature "
                f"153's environments are a closed set, and a scope named for "
                f"anything else is a typo, not a third environment."
            )
        self.name = name

    @staticmethod
    def scope_of(presented: str) -> CredentialScope:
        """The environment a presented key belongs to.

        The exchange's issuance is the source of truth: the key carries,
        in the field the deployment declares holds it, the environment it
        was minted for, and this reads that field.  A key presented with
        no environment marker — or one that is not a known environment —
        is refused (:class:`ScopeMismatch`) rather than guessed at,
        because an unclassified key has no environment to authenticate
        against, and the live account must never admit a key it cannot
        place.
        """
        if presented not in (LIVE_SCOPE, SHADOW_SCOPE):
            raise ScopeMismatch(
                f"presented credential {presented!r} carries no environment "
                f"this deployment recognises ({LIVE_SCOPE!r}, {SHADOW_SCOPE!r}); "
                f"feature 153 classifies every key by the environment the "
                f"exchange stamped into it, and a key with no such marker has "
                f"no environment to authenticate against, so it is refused "
                f"rather than admitted against an account it cannot be placed "
                f"to."
            )
        return CredentialScope(presented)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, CredentialScope) and other.name == self.name

    def __hash__(self) -> int:
        return hash(self.name)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"CredentialScope({self.name!r})"


def classify_credential(presented: str, against: str) -> CredentialScope:
    """Classify a presented key against the account it was presented to.

    The whole feature in one consultation: a key carries the environment
    it was issued for (``presented``), and it is being presented against
    an account (``against``).  When the two agree the key is returned in
    its scope — it is a key the account recognises.  When they disagree —
    a shadow sub-account key presented to the live account, or a live key
    presented to the shadow account — the presentation is refused with
    :class:`ScopeMismatch`, the policy-side double of the exchange's
    :data:`UNAUTHORIZED`: the sub-account's key is not a key the live
    account recognises, so the request would be answered 401, and this
    refuses it before it reaches the wire.
    """
    key_scope = CredentialScope.scope_of(presented)
    target_scope = CredentialScope(against)
    if key_scope != target_scope:
        raise ScopeMismatch(
            f"credential for the {key_scope.name!r} environment was presented "
            f"against the {target_scope.name!r} account; feature 153's separate "
            f"credentials per environment means the exchange answers this with "
            f"{UNAUTHORIZED} Unauthorized — the {key_scope.name} sub-account key "
            f"is not a key the {target_scope.name} account recognises — so the "
            f"presentation is refused here, before the request reaches the wire."
        )
    return key_scope


def scope_of(presented: str) -> CredentialScope:
    """The environment a presented key belongs to — the classifier alone.

    The seam a caller reaches for when it needs only to *know* which
    environment a key is a key of, without yet presenting it against an
    account: the live path asks "is this key live?" before it submits an
    order, the audit path asks "which environment does this key belong
    to?" of a stored credential.  Delegates to
    :meth:`CredentialScope.scope_of`, so the closed-set rule and the
    refusal of an unmarked key hold here exactly as they do there — one
    classification rule, at the one place it is written.
    """
    return CredentialScope.scope_of(presented)
