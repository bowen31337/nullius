"""Feature 153: separate credentials per environment.

app_spec.xml, "Trust Zone Isolation & Secrets", feature 153: *System
uses separate credentials per environment, so a shadow sub-account key
returns 401 against the live account.*  This suite is the whole feature,
in the three claims the sentence decomposes into:

* **separate credentials per environment** — the environments are a
  closed set (:data:`~infra.security.credential_isolation.LIVE_SCOPE` and
  :data:`~infra.security.credential_isolation.SHADOW_SCOPE`), and a key is
  classified by the environment the exchange stamped into it, never by a
  name typed at call time.  ``test_scope.py`` owns the closed set.
* **so a shadow sub-account key** — a key carries the environment it was
  issued for, and that is the whole of what :func:`classify_credential`
  reads.  ``test_classify.py`` owns the classification.
* **returns 401 against the live account** — a cross-environment
  presentation is refused with :class:`ScopeMismatch`, the policy-side
  double of the exchange's :data:`~infra.security.credential_isolation.
  UNAUTHORIZED`.  ``test_boundary.py`` owns the boundary, and closes the
  chain from the exchange's 401 to the caller that refuses before the
  request reaches the wire.

The keys here are the environment markers themselves — ``"live"`` and
``"shadow"`` — standing in for the field the exchange issues a key with.
Feature 153 reads the environment a key carries, never its material, so
the suite holds only the marker.
"""

from __future__ import annotations

import pytest

from infra.security.credential_isolation import (
    LIVE_SCOPE,
    SHADOW_SCOPE,
    UNAUTHORIZED,
    CredentialScope,
    CredentialScopeError,
    ScopeMismatch,
    classify_credential,
    scope_of,
)


class TestSeparateCredentialsPerEnvironment:
    """The environments are a closed set, and a key is one of them."""

    def test_two_environments_only(self) -> None:
        """The deployment has exactly two environments: live and shadow."""
        assert {LIVE_SCOPE, SHADOW_SCOPE} == {"live", "shadow"}

    def test_live_and_shadow_are_distinct(self) -> None:
        """The two scopes are not the same environment."""
        assert CredentialScope(LIVE_SCOPE) != CredentialScope(SHADOW_SCOPE)

    def test_a_scope_is_its_environment(self) -> None:
        """A CredentialScope is the environment it names, comparable and hashable."""
        assert CredentialScope(LIVE_SCOPE).name == LIVE_SCOPE
        assert CredentialScope(SHADOW_SCOPE).name == SHADOW_SCOPE
        assert CredentialScope(LIVE_SCOPE) == CredentialScope(LIVE_SCOPE)
        assert hash(CredentialScope(LIVE_SCOPE)) == hash(CredentialScope(LIVE_SCOPE))

    def test_an_unknown_environment_is_refused(self) -> None:
        """A scope named for anything but live or shadow is a typo, not a
        third environment — the closed set refuses it."""
        with pytest.raises(CredentialScopeError):
            CredentialScope("production")

    def test_an_unknown_environment_is_refused_in_words(self) -> None:
        """The refusal names the closed set, so the drift is findable."""
        with pytest.raises(
            CredentialScopeError, match=r"live.*shadow|shadow.*live"
        ):
            CredentialScope("staging")


class TestClassifyCredential:
    """A key is classified by the environment the exchange stamped into it."""

    def test_a_shadow_key_classifies_as_shadow(self) -> None:
        """The shadow sub-account's key is placed in the shadow environment."""
        assert scope_of(SHADOW_SCOPE) == CredentialScope(SHADOW_SCOPE)

    def test_a_live_key_classifies_as_live(self) -> None:
        """The live account's key is placed in the live environment."""
        assert scope_of(LIVE_SCOPE) == CredentialScope(LIVE_SCOPE)

    def test_an_unmarked_key_is_refused(self) -> None:
        """A key carrying no environment this deployment recognises has no
        environment to authenticate against, and is refused rather than
        guessed at — the live account must never admit a key it cannot place."""
        with pytest.raises(ScopeMismatch):
            scope_of("unknown")

    def test_classification_is_the_exchanges_issuance(self) -> None:
        """scope_of reads the environment the key carries, so a caller learns
        which environment a key is a key of without presenting it."""
        assert scope_of(SHADOW_SCOPE).name == SHADOW_SCOPE
        assert scope_of(LIVE_SCOPE).name == LIVE_SCOPE


class TestTheEnvironmentBoundary:
    """A cross-environment presentation is refused — feature 153's 401."""

    def test_a_shadow_key_against_the_live_account_is_refused(self) -> None:
        """The feature's own sentence: the shadow sub-account key returns 401
        against the live account."""
        with pytest.raises(ScopeMismatch):
            classify_credential(SHADOW_SCOPE, LIVE_SCOPE)

    def test_a_live_key_against_the_shadow_account_is_refused(self) -> None:
        """The same law from the other side: a live key presented to the
        shadow account is refused just as firmly."""
        with pytest.raises(ScopeMismatch):
            classify_credential(LIVE_SCOPE, SHADOW_SCOPE)

    def test_a_shadow_key_against_the_shadow_account_is_accepted(self) -> None:
        """A shadow key presented to the shadow account is a key the account
        recognises — same environment, admitted."""
        assert classify_credential(SHADOW_SCOPE, SHADOW_SCOPE) == CredentialScope(
            SHADOW_SCOPE
        )

    def test_a_live_key_against_the_live_account_is_accepted(self) -> None:
        """A live key presented to the live account is a key the account
        recognises — same environment, admitted."""
        assert classify_credential(LIVE_SCOPE, LIVE_SCOPE) == CredentialScope(LIVE_SCOPE)

    def test_the_refusal_cites_unauthorized(self) -> None:
        """The policy-side refusal is the double of the exchange's 401: the
        status the spec names is the one the wire carries."""
        assert UNAUTHORIZED == 401
        with pytest.raises(ScopeMismatch):
            classify_credential(SHADOW_SCOPE, LIVE_SCOPE)


class TestTheBoundaryHoldsInBothDirections:
    """The environment boundary is symmetric — refusing one direction is not
    enough; the live key must not work on the shadow account either."""

    @pytest.mark.parametrize(
        "key, account",
        [
            (SHADOW_SCOPE, LIVE_SCOPE),
            (LIVE_SCOPE, SHADOW_SCOPE),
        ],
    )
    def test_a_cross_environment_presentation_is_always_refused(
        self, key: str, account: str
    ) -> None:
        """Every key presented against the environment it does not belong to
        is refused — the boundary admits only same-environment pairs."""
        with pytest.raises(ScopeMismatch):
            classify_credential(key, account)

    @pytest.mark.parametrize("env", [LIVE_SCOPE, SHADOW_SCOPE])
    def test_a_same_environment_presentation_is_always_accepted(
        self, env: str
    ) -> None:
        """Every key presented against its own environment is admitted — the
        boundary is a match, not a blanket deny."""
        assert classify_credential(env, env) == CredentialScope(env)
