"""Feature 152: trade permission, withdrawal permanently disabled.

app_spec.xml, "Trust Zone Isolation & Secrets", feature 152: *System
provisions exchange keys with trade permission but with withdrawal
permanently disabled, which returns a validation failure otherwise.*
docs/nullius-tech-architecture.md §17 carries the clause nearly verbatim
("Exchange API keys: **read + trade only, withdrawal permanently
disabled**, IP-allowlisted."), and this suite is the whole feature in the
three claims the sentence decomposes into:

* **provisions exchange keys with trade permission** — the acceptable set
  is exactly read + trade, and the module publishes it as
  :data:`~infra.security.exchange_keys.PROVISIONED_PERMISSIONS`.
  ``TestTheProvisionedPermissionSet`` owns it.
* **but with withdrawal permanently disabled** — the permission that moves
  funds is refused at the key, and the account-side switch is refused at
  the account, so no path here mints a key that can withdraw.
  ``TestWithdrawalIsRefused`` owns both halves.
* **which returns a validation failure otherwise** — every described key
  is answered with a :class:`~infra.security.exchange_keys.KeyValidation`,
  and the minting seam raises the verdict's own exception.
  ``TestTheValidationFailure`` and ``TestProvisioning` own them.

The fixture "keys" are permission names and a boolean — the two facts the
control reads — never key material (§17 keeps that in a secrets manager,
feature 151).
"""

from __future__ import annotations

import pytest

from infra.security.exchange_keys import (
    PROVISIONED_PERMISSIONS,
    READ_PERMISSION,
    TRADE_PERMISSION,
    WITHDRAW_PERMISSION,
    ExchangeKey,
    ExchangeKeyError,
    KeyPermissionRejected,
    KeyValidation,
    KeyVerdict,
    WithdrawalNotDisabled,
    WithdrawalStateMalformed,
    provision_exchange_key,
    validate_key,
)

#: The set the exchange stamps onto a correctly provisioned key — the
#: fixture "key" of this suite.  It is a permission set and a switch, never
#: key material: feature 152 reads the permission *shape*, and §17 keeps
#: the bytes in a secrets manager (feature 151).
READ_AND_TRADE: tuple[str, ...] = (READ_PERMISSION, TRADE_PERMISSION)

#: The same set plus the permission §17 forbids — the key an operator
#: would get by asking the exchange for everything its console offers.
READ_TRADE_AND_WITHDRAW: tuple[str, ...] = (
    READ_PERMISSION,
    TRADE_PERMISSION,
    WITHDRAW_PERMISSION,
)

#: The account-side switch as the exchange stamps it: off (compliant, and
#: what the feature's middle clause requires) and on (its "otherwise").
WITHDRAWAL_OFF: bool = True
WITHDRAWAL_ON: bool = False

#: The label a provisioning script would give the execution path's key.
EXECUTION_KEY_LABEL: str = "live-execution"


def _validate(
    permissions: tuple[str, ...] = READ_AND_TRADE,
    *,
    withdrawal_disabled: bool = WITHDRAWAL_OFF,
    label: str = EXECUTION_KEY_LABEL,
) -> KeyValidation:
    """Judge one described key — the suite's single call into the law."""
    return validate_key(
        permissions=permissions,
        withdrawal_disabled=withdrawal_disabled,
        label=label,
    )


class TestTheProvisionedPermissionSet:
    """§17's "read + trade only" is a closed, published set."""

    def test_the_set_is_exactly_read_and_trade(self) -> None:
        """The one set the deployment provisions — no more, no less."""
        assert PROVISIONED_PERMISSIONS == {READ_PERMISSION, TRADE_PERMISSION}

    def test_the_permission_names_are_the_specs_own_words(self) -> None:
        """The vocabulary is the spec's own words, so a refusal citing
        ``withdraw`` cites the permission an operator sees in the
        exchange's console."""
        assert (READ_PERMISSION, TRADE_PERMISSION, WITHDRAW_PERMISSION) == (
            "read",
            "trade",
            "withdraw",
        )

    def test_the_forbidden_permission_is_not_in_the_set(self) -> None:
        """The set is exact: withdrawal is refused elsewhere, and absent
        here — a lower bound would let it back in unnoticed."""
        assert WITHDRAW_PERMISSION not in PROVISIONED_PERMISSIONS

    def test_a_read_and_trade_key_is_provisioned(self) -> None:
        """The feature's own clause: a key with trade permission, and a
        permission set that is the provisioned one, is accepted."""
        validation = _validate()
        assert validation.accepted
        assert validation.code is KeyVerdict.PROVISIONED
        assert validation.permissions == PROVISIONED_PERMISSIONS

    def test_the_permission_order_does_not_matter(self) -> None:
        """The law is a set comparison, so the order an operator listed
        the scopes in is not a fact about the key."""
        assert _validate((TRADE_PERMISSION, READ_PERMISSION)).accepted

    def test_the_spelling_does_not_matter(self) -> None:
        """Case and surrounding space are folded — the spelling an
        operator typed is not the permission."""
        assert _validate((" READ ", "Trade")).accepted

    def test_a_key_missing_trade_is_refused(self) -> None:
        """A read-only key cannot place the orders the system exists to
        place, so it is not the key the sentence provisions."""
        validation = _validate((READ_PERMISSION,), label="readonly-audit")
        assert not validation.accepted
        assert validation.code is KeyVerdict.MISSING_TRADE_PERMISSION

    def test_a_key_with_no_permissions_at_all_is_refused(self) -> None:
        """The empty set is the missing-trade case, not a special one."""
        assert _validate(()).code is KeyVerdict.MISSING_TRADE_PERMISSION

    def test_the_refusal_says_which_permission_is_missing(self) -> None:
        """A refusal that does not name the missing half of "read +
        trade" is one an operator has to reverse-engineer."""
        assert TRADE_PERMISSION in _validate((READ_PERMISSION,)).detail

    def test_a_tighter_key_than_read_plus_trade_is_admitted(self) -> None:
        """The rule is a ceiling plus a floor, not an equality: §17's
        "read + trade only" forbids *surplus*, and the sentence requires
        trade. A trade-only key holds less than read + trade and so
        satisfies the requirement more strongly — refusing it would be a
        false refusal of a safer key."""
        validation = _validate((TRADE_PERMISSION,), label="execution-orders-only")
        assert validation.accepted
        assert validation.code is KeyVerdict.PROVISIONED


class TestTheRuleIsACeilingAndAFloor:
    """Both edges, and the band between them."""

    def test_the_ceiling_refuses_surplus(self) -> None:
        """Anything beyond read + trade is a capability the deployment did
        not ask for."""
        assert _validate(
            (READ_PERMISSION, TRADE_PERMISSION, "transfer")
        ).code is KeyVerdict.UNKNOWN_PERMISSION

    def test_the_floor_refuses_a_key_that_cannot_trade(self) -> None:
        """The sentence's own "with trade permission"."""
        assert _validate(
            (READ_PERMISSION,)
        ).code is KeyVerdict.MISSING_TRADE_PERMISSION

    @pytest.mark.parametrize(
        "permissions",
        [
            (READ_PERMISSION, TRADE_PERMISSION),
            (TRADE_PERMISSION,),  # tighter than the ceiling: admitted
        ],
    )
    def test_everything_in_the_band_is_admitted(
        self, permissions: tuple[str, ...]
    ) -> None:
        """No input inside the band is falsely refused, and every one of
        them is a key that trades and cannot withdraw."""
        validation = _validate(permissions)
        assert validation.accepted
        assert TRADE_PERMISSION in validation.permissions
        assert WITHDRAW_PERMISSION not in validation.permissions


class TestWithdrawalIsRefused:
    """The middle clause, at both places withdrawal can be reachable."""

    def test_the_withdrawal_permission_is_refused(self) -> None:
        """A key the exchange stamped with withdrawal reach is refused —
        the feature's own clause, broken at the key."""
        validation = _validate(READ_TRADE_AND_WITHDRAW)
        assert not validation.accepted
        assert validation.code is KeyVerdict.WITHDRAWAL_PERMISSION_PRESENT

    def test_the_withdrawal_refusal_is_refused_alone(self) -> None:
        """A key carrying *only* the forbidden permission is refused for
        the forbidden permission, not for the missing trade — the
        sentence's clause outranks the missing half."""
        validation = _validate((WITHDRAW_PERMISSION,))
        assert validation.code is KeyVerdict.WITHDRAWAL_PERMISSION_PRESENT

    def test_every_extra_permission_is_refused(self) -> None:
        """The set is exact: anything beyond read + trade is a capability
        the deployment did not ask for."""
        validation = _validate((READ_PERMISSION, TRADE_PERMISSION, "transfer"))
        assert validation.code is KeyVerdict.UNKNOWN_PERMISSION

    def test_a_misspelled_withdrawal_is_refused_rather_than_trimmed(self) -> None:
        """The reason the vocabulary is closed: a ``withdrawl`` silently
        discarded would leave a key that can withdraw looking exactly
        like one that cannot."""
        validation = _validate((READ_PERMISSION, TRADE_PERMISSION, "withdrawl"))
        assert not validation.accepted
        assert validation.code is KeyVerdict.UNKNOWN_PERMISSION

    def test_an_unknown_permission_is_named_in_the_refusal(self) -> None:
        """The operator has to be able to find the surplus scope."""
        assert "transfer" in _validate(
            (READ_PERMISSION, TRADE_PERMISSION, "transfer")
        ).detail

    def test_an_account_that_can_still_withdraw_is_refused(self) -> None:
        """The account-side half: a perfect permission set buys nothing
        if the account itself will honour a withdrawal."""
        validation = _validate(withdrawal_disabled=WITHDRAWAL_ON)
        assert not validation.accepted
        assert validation.code is KeyVerdict.WITHDRAWAL_NOT_DISABLED

    def test_the_account_side_refusal_is_distinct_from_the_key_side_one(self) -> None:
        """The two halves of the clause are fixed in different places —
        the exchange's key scopes versus the account's switch — so
        merging their verdicts would send an operator to the wrong one."""
        assert (
            KeyVerdict.WITHDRAWAL_NOT_DISABLED
            is not KeyVerdict.WITHDRAWAL_PERMISSION_PRESENT
        )

    def test_the_account_side_refusal_names_the_switch(self) -> None:
        """The message says which of the two places to look."""
        detail = _validate(withdrawal_disabled=WITHDRAWAL_ON).detail
        assert "switch" in detail
        assert WITHDRAW_PERMISSION in detail


class TestTheValidationFailure:
    """The feature's "returns a validation failure otherwise", as an answer."""

    def test_every_described_key_is_answered(self) -> None:
        """The validator returns for every input — a refusal is a normal
        answer, not an exception, so a caller can branch on the code the
        way feature 156's gate branches on its decision's reason."""
        for permissions in (
            READ_AND_TRADE,
            READ_TRADE_AND_WITHDRAW,
            (READ_PERMISSION,),
            (),
            (READ_PERMISSION, TRADE_PERMISSION, "transfer"),
        ):
            assert isinstance(_validate(permissions), KeyValidation)

    def test_accepted_agrees_with_the_verdict(self) -> None:
        """``accepted`` is derived from the code rather than stored beside
        it, so a validation cannot disagree with its own verdict."""
        for code in KeyVerdict:
            validation = KeyValidation(
                code=code, detail="", permissions=PROVISIONED_PERMISSIONS
            )
            assert validation.accepted is (code is KeyVerdict.PROVISIONED)

    def test_the_verdict_is_the_audit_vocabulary(self) -> None:
        """The refusal codes are the four ways the sentence can fail, each
        spelled for the audit line."""
        assert {code.value for code in KeyVerdict} == {
            "provisioned",
            "withdrawal-permission-present",
            "unknown-permission",
            "missing-trade-permission",
            "withdrawal-not-disabled",
        }

    def test_the_validation_carries_the_set_it_judged(self) -> None:
        """The answer is checkable against the input, not just asserted."""
        described = _validate(READ_TRADE_AND_WITHDRAW)
        assert described.permissions == {
            READ_PERMISSION,
            TRADE_PERMISSION,
            WITHDRAW_PERMISSION,
        }

    @pytest.mark.parametrize(
        "permissions",
        [READ_TRADE_AND_WITHDRAW, (READ_PERMISSION,), (), ("transfer",)],
    )
    def test_every_bad_key_is_refused(self, permissions: tuple[str, ...]) -> None:
        """No bad shape slips through as accepted."""
        assert not _validate(permissions).accepted

    def test_a_bare_string_is_refused_rather_than_iterated(self) -> None:
        """A comma-joined string would judge one character at a time and
        report a real refusal for an unreal reason."""
        with pytest.raises(ExchangeKeyError):
            validate_key(
                permissions="read,trade",  # type: ignore[arg-type]
                withdrawal_disabled=WITHDRAWAL_OFF,
            )

    def test_a_non_string_permission_is_refused(self) -> None:
        """A member the module cannot name is not one it can certify."""
        with pytest.raises(ExchangeKeyError):
            validate_key(
                permissions=[READ_PERMISSION, 7],  # type: ignore[list-item]
                withdrawal_disabled=WITHDRAWAL_OFF,
            )


class TestTheWithdrawalStateMustBeABoolean:
    """The one input whose wrongness would otherwise pass silently.

    The switch arrives from configuration, and configuration is text.  Every
    non-empty string is truthy in Python, so a truthiness test would read
    the string ``"false"`` as "withdrawal is disabled" — minting a key that
    believes it cannot withdraw while its account can, with the record
    reading ``withdrawal_disabled=True`` and every check downstream
    agreeing.  That is the feature's worst outcome and its quietest, so the
    state must be a real ``bool``.
    """

    @pytest.mark.parametrize(
        "value",
        ["false", "no", "0", "true", "yes", 1, 0, None, [], {}, 1.0],
    )
    def test_a_non_boolean_withdrawal_state_is_refused(self, value: object) -> None:
        """No text, number or container stands in for the boolean."""
        with pytest.raises(WithdrawalStateMalformed):
            validate_key(
                permissions=READ_AND_TRADE,
                withdrawal_disabled=value,  # type: ignore[arg-type]
            )

    def test_the_falsy_string_false_is_refused_not_read_as_disabled(self) -> None:
        """The bite: ``"false"`` is truthy, so a truthiness test would
        accept it as "withdrawal is disabled" — the exact silent failure
        this rule exists to prevent."""
        assert bool("false") is True  # the reason the guard has to exist
        with pytest.raises(WithdrawalStateMalformed):
            validate_key(
                permissions=READ_AND_TRADE,
                withdrawal_disabled="false",  # type: ignore[arg-type]
            )

    def test_the_malformed_state_is_refused_rather_than_called_not_disabled(self) -> None:
        """A value that is not a boolean does not describe an account
        state, so reporting "the switch is on" would send an operator to
        the exchange to fix a setting that was never the problem."""
        with pytest.raises(WithdrawalStateMalformed) as raised:
            validate_key(
                permissions=READ_AND_TRADE,
                withdrawal_disabled="false",  # type: ignore[arg-type]
            )
        assert not isinstance(raised.value, WithdrawalNotDisabled)

    def test_the_malformed_state_names_the_value_and_its_type(self) -> None:
        """The refusal has to say what it was handed."""
        with pytest.raises(WithdrawalStateMalformed) as raised:
            validate_key(
                permissions=READ_AND_TRADE,
                withdrawal_disabled="no",  # type: ignore[arg-type]
            )
        message = str(raised.value)
        assert "'no'" in message
        assert "str" in message

    def test_both_real_booleans_are_still_judged(self) -> None:
        """The guard refuses everything that is *not* a bool, and nothing
        that is — ``True`` and ``False`` reach their verdicts."""
        assert _validate(withdrawal_disabled=True).accepted
        assert _validate(withdrawal_disabled=False).code is (
            KeyVerdict.WITHDRAWAL_NOT_DISABLED
        )

    def test_a_malformed_state_refuses_the_mint(self) -> None:
        """And the minting seam refuses it too, rather than provisioning a
        key on a value it could not read."""
        with pytest.raises(WithdrawalStateMalformed):
            provision_exchange_key(
                label=EXECUTION_KEY_LABEL,
                permissions=READ_AND_TRADE,
                withdrawal_disabled="false",  # type: ignore[arg-type]
            )

    def test_the_malformed_state_is_checked_before_the_permissions(self) -> None:
        """Order matters for the message: when *both* the switch and the
        permission set are malformed, the silent-wrongness input is the one
        reported — a caller fixing the permissions first would still mint a
        key on an unreadable switch."""
        with pytest.raises(WithdrawalStateMalformed):
            validate_key(
                permissions=READ_TRADE_AND_WITHDRAW,
                withdrawal_disabled="false",  # type: ignore[arg-type]
            )


class TestProvisioning:
    """The minting seam: the same law, expressed as a raised refusal."""

    def test_a_compliant_key_is_minted(self) -> None:
        """The feature's "provisions": a read + trade key against an
        account that cannot withdraw becomes a record."""
        key = provision_exchange_key(
            label=EXECUTION_KEY_LABEL,
            permissions=READ_AND_TRADE,
            withdrawal_disabled=WITHDRAWAL_OFF,
        )
        assert isinstance(key, ExchangeKey)
        assert key.permissions == PROVISIONED_PERMISSIONS
        assert key.withdrawal_disabled is True

    def test_a_withdrawal_permission_refuses_the_mint(self) -> None:
        """The minting seam raises, because there is no half-valid key
        record to hand back."""
        with pytest.raises(KeyPermissionRejected):
            provision_exchange_key(
                label=EXECUTION_KEY_LABEL,
                permissions=READ_TRADE_AND_WITHDRAW,
                withdrawal_disabled=WITHDRAWAL_OFF,
            )

    def test_an_enabled_withdrawal_switch_refuses_the_mint(self) -> None:
        """And the account-side fault is its own exception class, so a
        caller that can only remedy one of them can say so in a bare
        ``except``."""
        with pytest.raises(WithdrawalNotDisabled):
            provision_exchange_key(
                label=EXECUTION_KEY_LABEL,
                permissions=READ_AND_TRADE,
                withdrawal_disabled=WITHDRAWAL_ON,
            )

    def test_a_missing_trade_permission_refuses_the_mint(self) -> None:
        """A read-only key is refused at the mint, not discovered at the
        first rebalance."""
        with pytest.raises(KeyPermissionRejected):
            provision_exchange_key(
                label="readonly-audit",
                permissions=(READ_PERMISSION,),
                withdrawal_disabled=WITHDRAWAL_OFF,
            )

    def test_the_mint_failure_is_the_validators_own_words(self) -> None:
        """One rule written once: the raised refusal and the returned
        validation carry the same sentence, so the words an operator
        reads do not depend on which seam they reached it through."""
        validation = _validate(READ_TRADE_AND_WITHDRAW)
        with pytest.raises(KeyPermissionRejected) as raised:
            provision_exchange_key(
                label=EXECUTION_KEY_LABEL,
                permissions=READ_TRADE_AND_WITHDRAW,
                withdrawal_disabled=WITHDRAWAL_OFF,
            )
        assert str(raised.value) == validation.detail

    def test_the_account_side_failure_is_the_validators_own_words(self) -> None:
        """Same for the other contract."""
        validation = _validate(withdrawal_disabled=WITHDRAWAL_ON)
        with pytest.raises(WithdrawalNotDisabled) as raised:
            provision_exchange_key(
                label=EXECUTION_KEY_LABEL,
                permissions=READ_AND_TRADE,
                withdrawal_disabled=WITHDRAWAL_ON,
            )
        assert str(raised.value) == validation.detail

    def test_both_refusals_share_a_base_class(self) -> None:
        """So a caller that treats every provisioning failure alike can
        catch the taxonomy with one ``except``."""
        for permissions, switch in (
            (READ_TRADE_AND_WITHDRAW, WITHDRAWAL_OFF),
            (READ_AND_TRADE, WITHDRAWAL_ON),
        ):
            with pytest.raises(ExchangeKeyError):
                provision_exchange_key(
                    label=EXECUTION_KEY_LABEL,
                    permissions=permissions,
                    withdrawal_disabled=switch,
                )


class TestTheKeyCannotWithdraw:
    """The "permanently" of the sentence, asserted against the record."""

    def test_a_provisioned_key_has_withdrawal_disabled(self) -> None:
        """Every key this module hands out carries the switch off."""
        key = provision_exchange_key(
            label=EXECUTION_KEY_LABEL,
            permissions=READ_AND_TRADE,
            withdrawal_disabled=WITHDRAWAL_OFF,
        )
        assert key.withdrawal_disabled is True

    def test_a_provisioned_key_allows_trade(self) -> None:
        """The permission the sentence insists on is on the record."""
        key = provision_exchange_key(
            label=EXECUTION_KEY_LABEL,
            permissions=READ_AND_TRADE,
            withdrawal_disabled=WITHDRAWAL_OFF,
        )
        assert key.allows(TRADE_PERMISSION)
        assert key.allows(READ_PERMISSION)

    def test_a_provisioned_key_does_not_allow_withdrawal(self) -> None:
        """And the permission §17 forbids is absent — by construction,
        not by the caller's restraint."""
        key = provision_exchange_key(
            label=EXECUTION_KEY_LABEL,
            permissions=READ_AND_TRADE,
            withdrawal_disabled=WITHDRAWAL_OFF,
        )
        assert not key.allows(WITHDRAW_PERMISSION)

    @pytest.mark.parametrize(
        "attribute",
        ["label", "permissions", "withdrawal_disabled"],
    )
    def test_the_record_cannot_be_reassigned(self, attribute: str) -> None:
        """The permanence is structural: the switch cannot be flipped by
        the process holding the key."""
        key = provision_exchange_key(
            label=EXECUTION_KEY_LABEL,
            permissions=READ_AND_TRADE,
            withdrawal_disabled=WITHDRAWAL_OFF,
        )
        with pytest.raises(AttributeError):
            setattr(key, attribute, False)

    def test_the_module_publishes_no_way_to_undo_the_switch(self) -> None:
        """The honest form of "permanently": no call here takes a key and
        returns one with withdrawal reachable, so the state checked at
        issuance is the state the key carries for good."""
        import infra.security.exchange_keys as module

        # Every public name the module exports is a permission constant, an
        # exception/verdict type, the immutable record, or one of the two
        # seams — and none of the callables takes an ExchangeKey as its
        # subject, so none can hand back a re-enabled one.
        callables = {
            name: value
            for name, value in vars(module).items()
            if not name.startswith("_")
            and callable(value)
            and getattr(value, "__module__", None) == module.__name__
        }
        assert set(callables) == {
            "validate_key",
            "provision_exchange_key",
            "ExchangeKey",
            "KeyValidation",
            "KeyVerdict",
            "ExchangeKeyError",
            "KeyPermissionRejected",
            "WithdrawalNotDisabled",
            "WithdrawalStateMalformed",
        }
        for name, function in callables.items():
            # The *parameters*, not the return: provision_exchange_key
            # returns an ExchangeKey, which is the point — the question is
            # whether anything takes one as its subject.
            parameters = getattr(function, "__annotations__", {})
            subject_types = {
                value
                for key, value in parameters.items()
                if key != "return"
            }
            assert "ExchangeKey" not in subject_types, (
                f"{name} takes an ExchangeKey and could be a path back to "
                f"an enabled withdrawal switch"
            )

    def test_two_identically_provisioned_keys_are_equal(self) -> None:
        """The record is a value: same label, same set, same switch."""
        first = provision_exchange_key(
            label=EXECUTION_KEY_LABEL,
            permissions=READ_AND_TRADE,
            withdrawal_disabled=WITHDRAWAL_OFF,
        )
        second = provision_exchange_key(
            label=EXECUTION_KEY_LABEL,
            permissions=(TRADE_PERMISSION, READ_PERMISSION),
            withdrawal_disabled=WITHDRAWAL_OFF,
        )
        assert first == second
        assert hash(first) == hash(second)

    def test_the_record_holds_no_key_material(self) -> None:
        """§17 stores the secret in a secrets manager (feature 151); this
        record's field set cannot express one, which is a stronger
        guarantee than a redaction rule someone can forget to apply."""
        key = provision_exchange_key(
            label=EXECUTION_KEY_LABEL,
            permissions=READ_AND_TRADE,
            withdrawal_disabled=WITHDRAWAL_OFF,
        )
        assert set(key.__slots__) == {
            "_label",
            "_permissions",
            "_withdrawal_disabled",
        }
