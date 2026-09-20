"""Feature 152's law: trade, never withdraw.

app_spec.xml, "Trust Zone Isolation & Secrets", feature 152: *System
provisions exchange keys with trade permission but with withdrawal
permanently disabled, which returns a validation failure otherwise.*
docs/nullius-tech-architecture.md §17 carries the same clause nearly
verbatim — "Exchange API keys: **read + trade only, withdrawal permanently
disabled**, IP-allowlisted.  Stored in a secrets manager, never in env files
committed anywhere." — and the sentence decomposes into three claims, each
of which this module owns as a seam rather than a comment:

* **provisions exchange keys with trade permission** — the subject is the
  *permission set* the exchange stamped onto the key, not the key's
  material.  An operator asks the exchange for a key and states what it
  asked for; what this module holds is the set of permissions that came
  back, and the rule it applies is a **ceiling plus a floor**, not an
  equality:

  - *the ceiling* is §17's "read + trade only".  A key carrying anything
    beyond :data:`PROVISIONED_PERMISSIONS` is refused, because the
    surplus is by definition a capability the deployment did not ask for.
    This is what makes the rule a containment test rather than a trust
    exercise: extras are the risk, and extras are what get refused.
  - *the floor* is the sentence's own "with trade permission".  A key
    that cannot trade cannot place the orders the system exists to place,
    so it is refused too.
  - *between the two* — a key **tighter** than read + trade, such as a
    trade-only key — is admitted, and deliberately so.  Refusing it would
    be a false refusal of a *safer* key: the feature's requirement is
    that the key can trade and cannot withdraw, and a key holding less
    than read + trade satisfies that more strongly, not less.  §17's
    "only" forbids surplus; it does not oblige a deployment to grant read
    to a key that never needs it.

  Permissions are compared as the facts they are — case-folded, so the
  spelling an operator typed is not mistaken for a different permission —
  and a name that folds onto no known permission is refused, never
  dropped: silently discarding an unrecognised token would let a
  misspelled ``withdraw`` read as a compliant key, which is the one
  failure this feature exists to prevent.

* **but with withdrawal permanently disabled** — the *permanence* is the
  claim that orders the rest, and it is structural, not a setting.  Three
  things make it so.  The permission set excludes
  :data:`WITHDRAW_PERMISSION`, so a key that could withdraw cannot be
  built at all.  The account-side state is checked at issuance:
  :func:`provision_exchange_key` refuses a key whose exchange-side
  withdrawal switch is not off, because a key minted against an account
  that *can* withdraw would carry the capability no matter what its
  permission list says.  And the record this module hands out
  (:class:`ExchangeKey`) is immutable — ``__slots__``, read-only
  properties, no setter and no mutating method anywhere in the module —
  so there is no call, here or through the record, that returns a key with
  the switch re-enabled.  "Permanently disabled" is therefore not a
  promise about the exchange's console; it is the absence of any path in
  this module that could undo it, which is the only kind of permanence
  policy code can honestly offer.

* **which returns a validation failure otherwise** — the *consequence*,
  and the reason the law is a validator rather than a convention.
  :func:`validate_key` answers *every* described key with a
  :class:`KeyValidation`: an accepted key carries the verdict
  :attr:`KeyVerdict.PROVISIONED`, and every other shape — a withdrawal
  permission, an unknown permission, a set missing trade, an account whose
  withdrawal switch is still on — carries the verdict that names *which*
  rule it broke, so the failure is a finding an operator can act on rather
  than a bare "invalid".  The minting seam
  (:func:`provision_exchange_key`) judges through the same single
  function and raises the verdict's own exception class, so the failure
  the validator returns is the failure the caller that *provisions* gets;
  one rule, written once, expressed in the two shapes its two callers
  need.

The module is policy, like the rest of the zone's tooling: it names the
permissions a key may carry, reads the state the exchange stamped, and
states the consequence.  It holds no secret and names no key material —
§17's IP allowlist and §17's "stored in a secrets manager" belong to
feature 151 and its own module, and the environment a key belongs to is
feature 153's (:mod:`infra.security.credential_isolation`); what is here is
the permission shape and the withdrawal state, which is what feature 152's
sentence is about.

Stdlib-only, like the rest of the zone's tooling.  Nothing here dials an
exchange: the operator's request to the exchange happens out of band, and
this module is the validator that request's answer must pass.
"""

from __future__ import annotations

import enum
from collections.abc import Iterable
from typing import Final

__all__ = [
    "PROVISIONED_PERMISSIONS",
    "READ_PERMISSION",
    "TRADE_PERMISSION",
    "WITHDRAW_PERMISSION",
    "ExchangeKey",
    "ExchangeKeyError",
    "KeyPermissionRejected",
    "KeyValidation",
    "KeyVerdict",
    "WithdrawalNotDisabled",
    "WithdrawalStateMalformed",
    "provision_exchange_key",
    "validate_key",
]

#: Reading the account: balances, orders, fills.  Half of §17's "read +
#: trade", and the half that costs nothing to grant — feature 153's audit
#: path and the execution path's reconciliation both need it.
READ_PERMISSION: Final[str] = "read"

#: Placing and cancelling orders.  The half the sentence insists on: a key
#: without it cannot do the one thing the system exists to do, so a key
#: missing it is not a provisioned key wearing a smaller hat — it is a
#: key that will fail at the first rebalance.
TRADE_PERMISSION: Final[str] = "trade"

#: Moving funds off the exchange.  Deliberately *named* here and
#: deliberately absent from :data:`PROVISIONED_PERMISSIONS`: the module has
#: to be able to recognise the permission in order to refuse a key that
#: carries it, and refusing it is the whole of the feature's middle clause.
WITHDRAW_PERMISSION: Final[str] = "withdraw"

#: The one permission set a provisioned key may carry — §17's "read +
#: trade only", as a closed set.  Exact, not a lower bound: a key carrying
#: anything beyond these two is refused, because the surplus is by
#: definition a capability the deployment did not ask for.
PROVISIONED_PERMISSIONS: Final[frozenset[str]] = frozenset(
    {READ_PERMISSION, TRADE_PERMISSION}
)

#: Every permission this module can place.  Three, and closed: a
#: permission outside it is not under-provisioning to be trimmed away but
#: an unrecognised capability, and the validator refuses it rather than
#: guessing what it might have been meant to say.
_KNOWN_PERMISSIONS: Final[frozenset[str]] = PROVISIONED_PERMISSIONS | {
    WITHDRAW_PERMISSION
}


class ExchangeKeyError(Exception):
    """Base of the provisioning taxonomy.

    One base class so a caller — the execution path's key loader, the
    operator script that mints the deployment's keys, a CI check that
    audits a key record against §17 — can catch every failure of the
    provisioning path with a single ``except``.  The subclasses split by
    *which contract* was violated, not by which line of code failed.
    """


class KeyPermissionRejected(ExchangeKeyError):
    """The permission set is not the one the deployment provisions.

    §17's "read + trade only": a set carrying the withdrawal permission, a
    set carrying a permission the deployment has no name for, or a set
    that does not carry trade at all.  All three are refusals rather than
    warnings, and the message names which of them fired, because the
    remedy differs — strip the excess permission at the exchange, fix the
    misspelling, or mint against an account with the right scopes — and a
    refusal that does not say which is a refusal an operator has to
    reverse-engineer out of the key itself.
    """


class WithdrawalStateMalformed(ExchangeKeyError):
    """The account-side withdrawal state is not a boolean.

    A third contract, and the one whose violation is silent.  The switch
    is read from a deployment's configuration, and configuration arrives
    as text: an operator's ``"false"``, an env var's ``"no"``, a
    hand-edited ``"true"``.  Every one of those is *truthy* in Python, so
    a truthiness test would accept ``"false"`` as "withdrawal is
    disabled" — minting a key that believes itself unable to withdraw
    while the account it was issued against can.  That is the feature's
    worst outcome, and it is invisible: the record reads
    ``withdrawal_disabled=True`` and every check downstream agrees.

    So the state has to be a real ``bool``, and anything else is refused
    as malformed rather than coerced — the same stance
    :func:`_permission_set` takes on a bare string, and for the same
    reason: a value the module cannot place is one it must not reason
    past.  Refused by *raising* rather than by returning the
    not-disabled verdict, because a value that is not a boolean does not
    describe an account state at all — reporting "the switch is on" for
    an input that may well have meant "off" would send an operator to
    the exchange's console to fix a setting that was never the problem.
    """


class WithdrawalNotDisabled(ExchangeKeyError):
    """The account-side withdrawal switch is not off.

    The other contract, and the one the feature's middle clause is written
    about.  A key can carry a perfect permission set and still be a key
    whose *account* will honour a withdrawal; the exchange issues the key
    against an account whose withdrawal state is its own, so the switch
    that matters is not the permission list but the one §17 requires to be
    permanently off.  Refused rather than provisioned with a note, because
    a key with withdrawal reachable is the exact artifact the feature
    exists to make impossible.
    """


class KeyVerdict(enum.StrEnum):
    """Which rule a described key satisfied or broke — the audit vocabulary.

    One enumeration carries both polarities, because a key's verdict is one
    fact and the audit line should read the same either way.  The refusal
    members are deliberately distinct rather than one ``INVALID``:
    ``withdrawal-permission-present`` and ``withdrawal-not-disabled`` are
    the two halves of §17's middle clause and are fixed in different
    places (the exchange's key scopes versus the account's withdrawal
    switch), so collapsing them would tell an operator to look in the
    wrong one.
    """

    #: Accepted: the set is exactly read + trade, and the account cannot
    #: withdraw.  The sentence's "provisions", satisfied.
    PROVISIONED = "provisioned"

    #: Refused: the set carries the withdrawal permission.  The feature's
    #: own clause, broken at the key.
    WITHDRAWAL_PERMISSION_PRESENT = "withdrawal-permission-present"

    #: Refused: the set carries a name outside the deployment's vocabulary.
    #: Refused rather than trimmed — a misspelled ``withdraw`` must not be
    #: able to read as a compliant key.
    UNKNOWN_PERMISSION = "unknown-permission"

    #: Refused: the set does not carry trade, so the key cannot place the
    #: orders the system exists to place.  The floor of the rule — the
    #: permission the feature's own sentence names — and deliberately not
    #: raised for a key that is merely *tighter* than read + trade.
    MISSING_TRADE_PERMISSION = "missing-trade-permission"

    #: Refused: the permission set is right but the account's withdrawal
    #: switch is on.  The "otherwise" of the feature's own sentence.
    WITHDRAWAL_NOT_DISABLED = "withdrawal-not-disabled"


class KeyValidation:
    """The validator's whole answer: verdict, the set it judged, and words.

    ``detail`` carries the operator-facing sentence — the one place the
    rule explains itself at refusal time, naming the permission set it was
    shown and where the offending capability lives — so "withdrawal
    permanently disabled" is a finding an operator can act on rather than
    a slogan.  ``accepted`` is derived from :attr:`code` rather than
    stored beside it, so a validation can never disagree with its own
    verdict.
    """

    __slots__ = ("code", "detail", "permissions")

    def __init__(
        self,
        *,
        code: KeyVerdict,
        detail: str,
        permissions: frozenset[str],
    ) -> None:
        self.code = code
        self.detail = detail
        self.permissions = permissions

    @property
    def accepted(self) -> bool:
        """Whether the described key may be provisioned."""
        return self.code is KeyVerdict.PROVISIONED

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"KeyValidation(accepted={self.accepted}, code={self.code!r})"


class ExchangeKey:
    """A provisioned key's record: what the exchange stamped, held still.

    The record is the *issuance*, not the secret: a label for the audit
    trail, the permission set stamped onto the key, and the account-side
    withdrawal state at minting time.  No key material is held or
    nameable here — §17 stores that in a secrets manager (feature 151),
    and this module's subject is the shape of the key, never its bytes.

    **The record is immutable, and that is the feature's "permanently".**
    ``__slots__`` plus read-only properties mean the withdrawal state
    cannot be reassigned by the process holding the key, and the module
    publishes no method that returns a key with it re-enabled, so the
    state :func:`provision_exchange_key` checked at issuance is the state
    the key carries for its whole life.  A mutable flag would make
    "permanently disabled" a claim about the deployment's habits; an
    immutable record makes it a claim about the code, which is the kind
    that can be checked.
    """

    __slots__ = ("_label", "_permissions", "_withdrawal_disabled")

    def __init__(
        self,
        *,
        label: str,
        permissions: frozenset[str],
        withdrawal_disabled: bool,
    ) -> None:
        # Deliberately not validating here: this constructor is the record
        # of an issuance that has already been judged, and
        # :func:`provision_exchange_key` is the only caller — the one seam
        # where the law is applied, so the law is written once.
        self._label = label
        self._permissions = permissions
        self._withdrawal_disabled = withdrawal_disabled

    @property
    def label(self) -> str:
        """The key's name in the deployment's own vocabulary.

        For the audit trail and the refusal messages — "live-execution",
        "shadow-research" — never for classification: feature 153 places a
        key by the environment the exchange stamped into it, and a name an
        operator typed is not a marker an exchange issued.
        """
        return self._label

    @property
    def permissions(self) -> frozenset[str]:
        """The permission set the exchange stamped onto the key.

        Exactly :data:`PROVISIONED_PERMISSIONS` for any key this module
        hands out, and exposed so a caller can check that claim against
        the record rather than take it from the constructor's word.
        """
        return self._permissions

    @property
    def withdrawal_disabled(self) -> bool:
        """Whether the account this key was issued against cannot withdraw.

        Always ``True`` for a provisioned key — the validator refuses any
        issuance whose switch is on — and read-only, so the guarantee is
        the record's, not a caller's discipline.
        """
        return self._withdrawal_disabled

    def allows(self, permission: str) -> bool:
        """Whether this key carries ``permission``.

        The seam the order path asks before a call: ``allows(TRADE)`` is
        ``True`` for every provisioned key and ``allows(WITHDRAW)`` is
        ``False`` for every one of them, by construction rather than by
        the caller's restraint.
        """
        return _fold(permission) in self._permissions

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, ExchangeKey)
            and other.label == self.label
            and other.permissions == self.permissions
            and other.withdrawal_disabled == self.withdrawal_disabled
        )

    def __hash__(self) -> int:
        return hash((self.label, self.permissions, self.withdrawal_disabled))

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"ExchangeKey(label={self.label!r}, "
            f"permissions={sorted(self.permissions)!r}, "
            f"withdrawal_disabled={self.withdrawal_disabled})"
        )


def _fold(permission: str) -> str:
    """A permission name as the module compares it.

    The spelling an operator typed is not the fact, so ``"TRADE"`` and
    ``" trade "`` are the permission ``"trade"``.  Folding is confined to
    case and surrounding space: a name that still matches no known
    permission stays unknown and is refused by the caller, because
    normalising a misspelling into a permission is how a key that can
    withdraw would pass a check written to stop it.
    """
    return permission.strip().lower()


def _permission_set(permissions: Iterable[str]) -> frozenset[str]:
    """The described permissions as a set of folded names.

    A bare string is refused rather than iterated: ``"read,trade"``
    iterates to characters, and a validator that answered a comma-joined
    string with ``unknown-permission`` would be reporting a real refusal
    for an unreal reason.  Anything else iterable is read member by
    member, and a member that is not a string is refused for the same
    reason — a permission the module cannot even name is not one it can
    certify as absent.
    """
    if isinstance(permissions, str):
        raise KeyPermissionRejected(
            f"permissions was given the bare string {permissions!r}; feature "
            f"152 validates the permission *set* an exchange stamped onto a "
            f"key, so pass the permission names as a collection "
            f"(e.g. ({READ_PERMISSION!r}, {TRADE_PERMISSION!r})), not a "
            f"single joined string — iterating a string would judge one "
            f"character at a time and report the wrong refusal."
        )
    folded: set[str] = set()
    for permission in permissions:
        if not isinstance(permission, str):
            raise KeyPermissionRejected(
                f"permission {permission!r} of type "
                f"{type(permission).__name__} is not a permission name; "
                f"feature 152 places each permission in a closed vocabulary "
                f"({READ_PERMISSION!r}, {TRADE_PERMISSION!r}, "
                f"{WITHDRAW_PERMISSION!r}) and cannot judge a member it "
                f"cannot name, so the key is refused rather than guessed at."
            )
        folded.add(_fold(permission))
    return frozenset(folded)


def validate_key(
    *,
    permissions: Iterable[str],
    withdrawal_disabled: bool,
    label: str = "",
) -> KeyValidation:
    """Judge a described key against §17 — the validation failure's home.

    Takes what an operator asked the exchange for and what came back: the
    permission set stamped onto the key, and the account-side withdrawal
    state.  Returns a :class:`KeyValidation` for *every* input, because
    the feature's "returns a validation failure otherwise" is an answer,
    not an exception — the validating caller branches on
    :attr:`KeyValidation.code`, the same way feature 156's gate branches
    on its decision's reason.

    The verdicts are the three clauses in order.  A permission outside the
    vocabulary is refused first (:attr:`KeyVerdict.UNKNOWN_PERMISSION`),
    because it is the one member whose *meaning* the module cannot see and
    so the one it must not reason past.  The withdrawal permission is
    refused next
    (:attr:`KeyVerdict.WITHDRAWAL_PERMISSION_PRESENT`) — the feature's own
    clause, and it outranks a missing trade permission so that a key
    carrying both faults is reported for the one §17 is written about.  A
    set missing trade is refused as
    :attr:`KeyVerdict.MISSING_TRADE_PERMISSION`: it cannot place an order,
    so it is not the key the sentence provisions.  Only then does the
    account-side switch get read — a perfect set against an account that
    can still withdraw is refused as
    :attr:`KeyVerdict.WITHDRAWAL_NOT_DISABLED`, the "otherwise" of the
    sentence's own middle clause.

    Accepted is therefore the band between the rule's two edges: no
    permission beyond :data:`PROVISIONED_PERMISSIONS` and the trade
    permission present.  A trade-only key sits inside the band and is
    admitted — it is *safer* than read + trade, and refusing it would
    refuse a key the feature's requirement is satisfied by.  See the
    module docstring for why the rule is a ceiling and a floor rather
    than an equality.

    The withdrawal state is checked for *being a boolean* before any of
    that, and raises :class:`WithdrawalStateMalformed` rather than
    returning a verdict: it is not a property of the key being judged, it
    is the caller having handed this function something that is not the
    fact it asked for.  The check comes first because it is the only
    input whose wrongness would otherwise pass *silently* — see that
    exception's docstring.
    """
    if not isinstance(withdrawal_disabled, bool):
        raise WithdrawalStateMalformed(
            f"withdrawal_disabled was given {withdrawal_disabled!r} of type "
            f"{type(withdrawal_disabled).__name__}, not a bool. The "
            f"account-side withdrawal state arrives from configuration, "
            f"which is text: every non-empty string — 'false', 'no', "
            f"'0' — is truthy in Python, so a truthiness test here would "
            f"read 'false' as 'withdrawal is disabled' and mint a key that "
            f"believes it cannot withdraw while its account can. Feature "
            f"152's 'permanently disabled' is the one claim this module "
            f"cannot afford to take on faith, so the state must be a real "
            f"bool and anything else is refused rather than coerced."
        )

    described = _permission_set(permissions)
    what = f"key {label!r}" if label else "the described key"

    unknown = sorted(described - _KNOWN_PERMISSIONS)
    if unknown:
        return KeyValidation(
            code=KeyVerdict.UNKNOWN_PERMISSION,
            permissions=described,
            detail=(
                f"{what} carries permission(s) {', '.join(unknown)} that this "
                f"deployment has no name for; the vocabulary is closed "
                f"({READ_PERMISSION!r}, {TRADE_PERMISSION!r}, "
                f"{WITHDRAW_PERMISSION!r}) and feature 152 refuses the key "
                f"rather than trimming the surplus — a misspelled "
                f"{WITHDRAW_PERMISSION!r} silently dropped here would leave a "
                f"key that can withdraw looking exactly like one that cannot, "
                f"which is the failure §17's 'withdrawal permanently "
                f"disabled' exists to prevent."
            ),
        )

    if WITHDRAW_PERMISSION in described:
        return KeyValidation(
            code=KeyVerdict.WITHDRAWAL_PERMISSION_PRESENT,
            permissions=described,
            detail=(
                f"{what} carries the {WITHDRAW_PERMISSION!r} permission, so it "
                f"can move funds off the exchange. §17 requires exchange keys "
                f"to be 'read + trade only, withdrawal permanently disabled' "
                f"and feature 152 refuses this key: re-issue it at the "
                f"exchange without the withdrawal scope — this is a refusal of "
                f"the key, not of a setting this module could turn off, "
                f"because the permission is the exchange's to grant and only "
                f"the exchange's to remove."
            ),
        )

    if TRADE_PERMISSION not in described:
        return KeyValidation(
            code=KeyVerdict.MISSING_TRADE_PERMISSION,
            permissions=described,
            detail=(
                f"{what} does not carry the {TRADE_PERMISSION!r} permission "
                f"(it carries {sorted(described) or 'nothing'}); feature 152 "
                f"provisions keys *with trade permission*, and a key that "
                f"cannot place an order is not that key — it would fail at the "
                f"first rebalance, after the deployment had already spent the "
                f"issuance on it. Re-issue with {READ_PERMISSION!r} and "
                f"{TRADE_PERMISSION!r}."
            ),
        )

    if not withdrawal_disabled:
        return KeyValidation(
            code=KeyVerdict.WITHDRAWAL_NOT_DISABLED,
            permissions=described,
            detail=(
                f"{what} carries the right permission set "
                f"({sorted(described)}) but was issued against an account "
                f"whose withdrawal switch is still on. §17 requires exchange "
                f"keys to have withdrawal 'permanently disabled' and feature "
                f"152 refuses this key: a permission list excluding "
                f"{WITHDRAW_PERMISSION!r} buys nothing if the account itself "
                f"will honour a withdrawal. Disable withdrawal on the account "
                f"at the exchange — it cannot be done from here, and it "
                f"cannot be undone from here either, which is the point."
            ),
        )

    return KeyValidation(
        code=KeyVerdict.PROVISIONED,
        permissions=described,
        detail=(
            f"{what} carries exactly "
            f"{sorted(PROVISIONED_PERMISSIONS)} and was issued against an "
            f"account whose withdrawal switch is permanently off — §17's "
            f"'read + trade only, withdrawal permanently disabled', satisfied "
            f"(feature 152)."
        ),
    )


def _refusal(validation: KeyValidation, label: str) -> ExchangeKeyError:
    """The exception a refused verdict raises at the minting seam.

    The subclass is chosen by *which contract* broke, so a caller that
    can only remedy one of them can say so in a bare ``except``: a
    permission fault is :class:`KeyPermissionRejected` (the key must be
    re-issued at the exchange), and an account-side fault is
    :class:`WithdrawalNotDisabled` (the account must be changed).  The
    message is the validator's own, so the words an operator reads do not
    depend on which of the two seams they reached the refusal through.
    """
    if validation.code is KeyVerdict.WITHDRAWAL_NOT_DISABLED:
        return WithdrawalNotDisabled(validation.detail)
    return KeyPermissionRejected(validation.detail)


def provision_exchange_key(
    *,
    label: str,
    permissions: Iterable[str],
    withdrawal_disabled: bool,
) -> ExchangeKey:
    """Mint the deployment's key record, or refuse it with the reason.

    The seam an operator's provisioning script calls with what the
    exchange issued: a label, the permission set stamped onto the key, and
    whether the account's withdrawal switch is off.  The judgement is
    :func:`validate_key`'s — the same single function, so the failure this
    raises is exactly the failure that validator returns — and it is
    raised here rather than returned because a provisioning call has no
    sensible continuation: there is no half-valid key record to hand back,
    and a caller that wanted to *inspect* a failure instead of aborting
    calls the validator directly.

    On acceptance the returned :class:`ExchangeKey` is immutable and there
    is no second seam: nothing in this module takes a key and returns one
    with withdrawal re-enabled, so the state checked here is the state the
    key carries for good.
    """
    validation = validate_key(
        permissions=permissions,
        withdrawal_disabled=withdrawal_disabled,
        label=label,
    )
    if not validation.accepted:
        raise _refusal(validation, label)
    return ExchangeKey(
        label=label,
        permissions=validation.permissions,
        withdrawal_disabled=True,
    )
