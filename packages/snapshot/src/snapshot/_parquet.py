"""Parquet row counts, read from the file's own footer metadata.

The manifest (feature 31) records a row count per file, and the lake's
data files are Parquet (§4.2: ``bars/``, ``trades/``, ``bookfeat/``,
``borrow/``). A Parquet file already knows its row count — it is written
into the footer's Thrift-encoded ``FileMetaData`` by whoever wrote the
file — so the honest way to count rows is to read that number, not to
approximate it from bytes. This module does exactly that, in the stdlib,
because this package has no dependencies by design and row counting must
not quietly grow one.

**Why a Thrift reader is here.** Parquet's footer is a Thrift *compact
protocol* struct. Reading one field out of it — ``num_rows``, field id 3
of ``FileMetaData`` — still requires walking the whole struct, because
variable-width integers mean nothing after a mis-parsed field is aligned.
The reader below therefore implements the compact protocol's value types
generically (skip what you do not want, so what you do want is aligned),
which is a bounded, well-specified ~100 lines rather than a dependency.

Two deliberate limits, stated so nobody has to rediscover them:

* Only complete Parquet frames are parsed: the file must carry the
  ``PAR1`` magic at *both* ends. A file with a leading magic but no
  trailing one is mid-append (staging is append-only, and a seal may run
  while a worker is writing); it is not treated as Parquet and its rows
  are reported unknown, rather than failing a seal over a file that was
  perfectly fine a second later.
* A file that *is* a complete frame but whose footer does not parse —
  truncated metadata, a length that runs past the file, a ``num_rows``
  that is negative — is refused with :class:`SnapshotContentError`. That
  file claims to be Parquet and is not readable as one: loud is the
  package's policy for content it cannot address.

The encoding itself follows the Thrift compact protocol specification:
ULEB128 varints, zigzag-compacted signed integers, field headers whose
high nibble is the field-id delta, list/set/map headers carrying their
element types inline. Only enough of the protocol to *read forward* is
implemented; nothing here writes.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

from ._errors import SnapshotContentError

__all__ = ["PARQUET_MAGIC", "parquet_num_rows"]

#: The magic a Parquet file begins and ends with (parquet-format spec §1).
PARQUET_MAGIC = b"PAR1"

# Thrift compact protocol type ids (spec table 1). Field headers and
# collection headers carry these ids; the reader dispatches on them.
_STOP = 0x00
_BOOLEAN_TRUE = 0x01
_BOOLEAN_FALSE = 0x02
_BYTE = 0x03
_I16 = 0x04
_I32 = 0x05
_I64 = 0x06
_DOUBLE = 0x07
_BINARY = 0x08
_LIST = 0x09
_SET = 0x0A
_MAP = 0x0B
_STRUCT = 0x0C

_KNOWN_TYPES = frozenset(range(0x0D))

# FileMetaData field ids (parquet.thrift). Only field 3 is read; the rest
# are skipped. Kept as named constants so the intent survives review.
_FILE_METADATA_NUM_ROWS = 3

# A footer length is a u32; a footer larger than 2 GiB is not a footer.
_MAX_FOOTER_BYTES = 1 << 31


def parquet_num_rows(path: Path) -> int:
    """Return the row count a Parquet file records in its own footer.

    Reads only the trailing frame: the last 8 bytes are the little-endian
    footer length and the ``PAR1`` magic, so the seek cost is the footer's
    size, never the data's. The footer's ``FileMetaData`` struct is walked
    and its ``num_rows`` field (id 3, an i64) returned.

    Raises :class:`SnapshotContentError` when the file is not a complete
    ``PAR1`` frame or when the footer does not parse as Thrift — see the
    module docstring for where each refusal draws its line.
    """
    if not isinstance(path, Path):
        path = Path(path)
    size = path.stat().st_size
    if size < 4 + 4 + len(PARQUET_MAGIC):  # magic + footer length + magic
        raise SnapshotContentError(
            f"{path} is too short to be a Parquet file; a manifest cannot "
            "count rows it cannot read"
        )
    with path.open("rb") as handle:
        head = handle.read(len(PARQUET_MAGIC))
        handle.seek(-8, os.SEEK_END)
        tail = handle.read(8)
    if head != PARQUET_MAGIC or tail[4:] != PARQUET_MAGIC:
        raise SnapshotContentError(
            f"{path} does not carry the Parquet magic at both ends; it is "
            "not a complete Parquet file"
        )
    footer_length = int.from_bytes(tail[:4], "little")
    if not 0 < footer_length <= min(size - 8, _MAX_FOOTER_BYTES):
        raise SnapshotContentError(
            f"{path} declares a Parquet footer of {footer_length} bytes, "
            f"which does not fit the {size}-byte file; the footer is corrupt"
        )
    with path.open("rb") as handle:
        handle.seek(size - 8 - footer_length)
        footer = handle.read(footer_length)
    num_rows = _FileMetaData(footer, path).num_rows
    if num_rows < 0:
        raise SnapshotContentError(
            f"{path} records a negative Parquet row count ({num_rows}); "
            "the footer metadata is corrupt"
        )
    return num_rows


def is_complete_parquet(path: Path) -> bool:
    """Whether ``path`` carries the full ``PAR1`` frame, cheaply.

    The frame check a row counter performs before committing to the
    footer parser (see the module docstring for why a half-frame is
    allowed to pass as "not Parquet yet" rather than failing).
    """
    size = path.stat().st_size
    if size < 4 + 4 + len(PARQUET_MAGIC):
        return False
    with path.open("rb") as handle:
        head = handle.read(len(PARQUET_MAGIC))
        handle.seek(-4, os.SEEK_END)
        tail = handle.read(4)
    return head == PARQUET_MAGIC and tail == PARQUET_MAGIC


class _Cursor:
    """A read-only position over the footer bytes.

    Every method advances exactly one compact-protocol value; a misaligned
    read surfaces as :class:`SnapshotContentError` naming the file, so a
    corrupt footer reads as corruption rather than as a wrong row count.
    """

    __slots__ = ("_data", "_pos", "_path")

    def __init__(self, data: bytes, path: Path) -> None:
        self._data = data
        self._pos = 0
        self._path = path

    def byte(self) -> int:
        if self._pos >= len(self._data):
            self._truncated("byte")
        value = self._data[self._pos]
        self._pos += 1
        return value

    def varint(self) -> int:
        """Read a ULEB128 unsigned integer."""
        result = 0
        shift = 0
        while True:
            encoded = self.byte()
            result |= (encoded & 0x7F) << shift
            if not encoded & 0x80:
                return result
            shift += 7
            if shift > 63:
                self.malformed("a varint longer than 64 bits")

    def zigzag(self) -> int:
        """Read a zigzag-compacted signed integer (i16/i32/i64)."""
        unsigned = self.varint()
        return (unsigned >> 1) ^ -(unsigned & 1)

    def skip(self, value_type: int) -> None:
        """Advance past one value of ``value_type`` without decoding it."""
        if value_type in (_BOOLEAN_TRUE, _BOOLEAN_FALSE):
            return  # booleans live in the field header, not the stream
        if value_type == _BYTE:
            self.byte()
        elif value_type in (_I16, _I32, _I64):
            self.varint()
        elif value_type == _DOUBLE:
            self._advance(8)
        elif value_type == _BINARY:
            self._advance(self.varint())
        elif value_type in (_LIST, _SET):
            self._skip_collection()
        elif value_type == _MAP:
            self._skip_map()
        elif value_type == _STRUCT:
            self._skip_struct()
        else:  # pragma: no cover - _KNOWN_TYPES gates the header parse
            self.malformed(f"unknown value type {value_type}")

    def struct_fields(self) -> "Iterator[tuple[int, int]]":
        """Yield each ``(field id, value type)`` header of a struct.

        A generator, and necessarily one: on the wire a field's header is
        immediately followed by its *value*, so the caller must consume or
        :meth:`skip` the value between iterations — a struct cannot be
        header-scanned first and value-read second. The compact protocol's
        field-id delta (or its long form: the id as a following zigzag
        i16, when the delta would exceed 15) is decoded here so callers
        see absolute ids.
        """
        field_id = 0
        while True:
            header = self.byte()
            if header == _STOP:
                return
            value_type = header & 0x0F
            if value_type not in _KNOWN_TYPES or value_type == _STOP:
                self.malformed(f"field header type {value_type:#x}")
            delta = (header >> 4) & 0x0F
            if delta:
                field_id += delta
            else:  # long form: the id follows the header as a zigzag i16
                field_id = self.zigzag()
            yield field_id, value_type

    def _skip_collection(self) -> None:
        header = self.byte()
        size = (header >> 4) & 0x0F
        element_type = header & 0x0F
        if element_type not in _KNOWN_TYPES or element_type == _STOP:
            self.malformed(f"collection element type {element_type:#x}")
        if size == 0x0F:
            size = self.varint()
        for _ in range(size):
            if element_type in (_BOOLEAN_TRUE, _BOOLEAN_FALSE):
                # Booleans inside a collection are full bytes, not folded
                # into the header the way struct fields are.
                self.byte()
            else:
                self.skip(element_type)

    def _skip_map(self) -> None:
        size = self.varint()
        if size == 0:
            return  # an empty map is the size alone — no key/value byte
        key_value = self.byte()
        key_type = (key_value >> 4) & 0x0F
        value_type = key_value & 0x0F
        for candidate in (key_type, value_type):
            if candidate not in _KNOWN_TYPES or candidate == _STOP:
                self.malformed(f"map type {candidate:#x}")
        for _ in range(size):
            for member_type in (key_type, value_type):
                if member_type in (_BOOLEAN_TRUE, _BOOLEAN_FALSE):
                    self.byte()
                else:
                    self.skip(member_type)

    def _skip_struct(self) -> None:
        for _field_id, value_type in self.struct_fields():
            self.skip(value_type)

    def _advance(self, count: int) -> None:
        if count < 0 or self._pos + count > len(self._data):
            self._truncated(f"{count} bytes")
        self._pos += count

    def _truncated(self, what: str) -> None:
        self.malformed(f"the footer ends mid-value while reading {what}")

    def malformed(self, detail: str) -> None:
        """Refuse the footer: it does not parse as compact-protocol Thrift."""
        raise SnapshotContentError(
            f"{self._path} has a malformed Parquet footer: {detail}; the "
            "row count cannot be read from metadata that does not parse"
        )


class _FileMetaData:
    """The one field the manifest needs from a Parquet footer: ``num_rows``."""

    __slots__ = ("num_rows",)

    def __init__(self, footer: bytes, path: Path) -> None:
        cursor = _Cursor(footer, path)
        num_rows: int | None = None
        for field_id, value_type in cursor.struct_fields():
            if field_id == _FILE_METADATA_NUM_ROWS:
                if value_type != _I64:
                    cursor.malformed(
                        f"num_rows is encoded as type {value_type:#x}, "
                        "not i64"
                    )
                num_rows = cursor.zigzag()
            else:
                cursor.skip(value_type)
        if num_rows is None:
            raise SnapshotContentError(
                f"{path} has a Parquet footer that carries no num_rows; "
                "the metadata is not a FileMetaData struct"
            )
        self.num_rows = num_rows
