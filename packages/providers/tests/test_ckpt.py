"""Feature 204's weights: the checkpoint hash, and the null that means hosted.

app_spec.xml feature 204: *System persists ``agent_ckpt_hash`` for self-hosted
weights plus ``agent_sampling`` recording temperature, top_p, thinking and
seed.*  This file holds the half of that sentence that is about the *value* —
what a checkpoint hash is, and what it refuses — and leaves the row to
``test_weights_store.py``.  ``test_sampling.py`` takes the other value type.

**The asymmetry with the sampling is the thing to hold on to here.**  Both
columns are nullable, and the two nulls are not the same kind of thing: 0115's
comment on this one is ``non-null for self-hosted weights``, so a NULL is a
*recorded fact* — the weights came from a provider and there was no local
checkpoint to hash — while a NULL sampling is a record that has not been
written yet.  That is why :func:`~providers.require_agent_ckpt_hash` refuses
``None`` rather than folding it: a function handed a bare value has no row to
read the fact from, and answering "hosted" for something that might be a
truncated digest would put a node in a weight stratum on no evidence.  The
store is where the null gets its meaning, because the store has the row.

The digest's shape is not invented here.  A 64-character lowercase hex string is
the sha256 rendering, and the case-folding rule and the refusal of the
``sha256:``-prefixed spelling are
``artifacts._dedup.canonical_code_hash``'s — the same rule this codebase already
applies to the other content digest it records, so a reader who knows one knows
both.
"""

from __future__ import annotations

import pytest
from providers import (
    CKPT_HASH_LENGTH,
    HOSTED_API_CKPT_HASH,
    CkptHashMalformedError,
    ModelPinError,
    hosted_api_weights,
    require_agent_ckpt_hash,
)

#: A real-shaped digest: 64 lowercase hex characters.  Spelled out rather than
#: built from a substring of the alphabet so that a reader can count it.
DIGEST = "3f2a1c0d" * 8

#: §14.1's self-hosted checkpoint, in the spelling a deployment would record it
#: for a local model — the two values together are what the "same weights"
#: claim in a report is made of.
SELF_HOSTED_DIGEST = "ab" * 32


def test_the_hosted_case_is_the_null_and_the_null_is_not_an_absence():
    # §9.1's column comment is ``non-null for self-hosted weights``, which makes
    # the null the *other* case rather than a missing value; the constant is
    # spelled as a named None so that a caller passing it is stating the hosted
    # fact rather than leaving a field out.
    assert HOSTED_API_CKPT_HASH is None
    assert hosted_api_weights() is HOSTED_API_CKPT_HASH


def test_a_digest_is_the_sixty_four_hex_characters_the_column_holds():
    # CHAR(64) in 0115: the length is the schema's, not a convenience here.
    assert CKPT_HASH_LENGTH == 64
    assert len(DIGEST) == CKPT_HASH_LENGTH
    assert require_agent_ckpt_hash(DIGEST) == DIGEST


def test_a_digest_that_is_a_uuid_is_refused_even_though_it_is_hex():
    # The failure this guards against is a value of the right *alphabet* but the
    # wrong *kind* — a node id or a campaign id pasted into the column, which
    # every reader would then treat as a weight identity.  The length check is
    # what catches it; the alphabet alone would not.
    with pytest.raises(CkptHashMalformedError):
        require_agent_ckpt_hash("f47ac10b-58cc-4372-a567-0e02b2c3d479")


def test_an_uppercase_digest_is_folded_rather_than_refused():
    # Case is not part of a digest's identity — sha256 hex has one canonical
    # rendering and the tools that print it disagree about case — so the parser
    # folds rather than refusing.  Refusing would make one checkpoint look like
    # two weight strata depending on which tool recorded it.
    assert require_agent_ckpt_hash(DIGEST.upper()) == DIGEST


def test_the_prefixed_spelling_is_refused_by_name():
    # ``sha256:...`` is how several tools render a digest, and it is a *string
    # about* a digest rather than one.  It is refused explicitly so the message
    # can say so: the alternative is a caller who strips the prefix at the call
    # site and a column that then holds two spellings of one checkpoint.
    with pytest.raises(CkptHashMalformedError) as refusal:
        require_agent_ckpt_hash(f"sha256:{DIGEST}")
    assert "sha256:" in str(refusal.value)


@pytest.mark.parametrize(
    "value",
    [
        DIGEST[:63],           # one character short
        DIGEST + "0",          # one long
        "z" * 64,              # right length, not hex
        DIGEST[:32] + "-" + DIGEST[:31],  # a dash where a hex digit belongs
        "",
        "   ",                 # whitespace only: empty once the padding is folded
    ],
)
def test_a_value_that_is_not_a_sha256_digest_is_refused(value):
    # The empty string is the one worth naming: a lenient reader might fold it
    # to None and it would then read as *hosted-API weights* — a claim about
    # where the weights came from, made from a value that says nothing at all.
    with pytest.raises(CkptHashMalformedError):
        require_agent_ckpt_hash(value)


def test_surrounding_whitespace_is_folded_with_the_case():
    # Deliberate, and the same rule this codebase already applies to its other
    # content digest (``artifacts._dedup.canonical_code_hash``, which is also
    # ``value.strip().casefold()``): padding is a copy-paste artefact rather
    # than part of a digest's identity, and a column holding a padded value
    # would compare unequal to every other node's hash while looking identical
    # to a reader.  The whitespace-only case above still refuses, because there
    # is nothing left of it once the padding goes.
    padded = f"  {DIGEST}\n"
    assert require_agent_ckpt_hash(padded) == DIGEST


@pytest.mark.parametrize("value", [None, 42, 1.0, True, b"ab" * 32, [DIGEST], {"h": DIGEST}])
def test_a_non_string_is_refused(value):
    # ``None`` in particular: the parser is handed a bare value and has no row
    # to read, so it cannot know whether the caller meant hosted weights or
    # forgot to pass anything — the store is where the null becomes a fact, and
    # this function refusing it is what keeps the two from being the same thing.
    with pytest.raises(CkptHashMalformedError):
        require_agent_ckpt_hash(value)


def test_a_refusal_is_a_model_pin_error_and_not_only_this_class():
    # Feature 204's errors join feature 203's base rather than minting a second
    # one — see test_pin_errors.py for the whole error-surface assertion.
    assert issubclass(CkptHashMalformedError, ModelPinError)


def test_a_refusal_names_the_value_it_would_not_read():
    with pytest.raises(CkptHashMalformedError) as refusal:
        require_agent_ckpt_hash("nope")
    assert "nope" in str(refusal.value)
