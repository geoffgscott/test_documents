"""Rewriting a ToUnicode CMap's mapping body so it decodes to the wrong letters.

~keep This is the one part of the wrong-mapping pipeline that is worth unit-testing directly: it
takes plain CMap PostScript text and returns plain CMap PostScript text, with no qpdf, no PDF
object model, and no filesystem involved. `rewrite_mapping_body` is the function xberg issue #1696's
reproducer needs -- everything else in build_wrong_mapping_pdfs.py is plumbing to get real CMap
streams in and out of a real PDF.

The shift is ROT-3, applied per UTF-16BE code unit, and only to code units that fall in A-Z or a-z.
Digits, punctuation, and non-Latin code points pass through untouched. A `bfrange` whose destination
is a single code point expands one-for-one, incrementing the destination for each step; a `bfrange`
whose destination is an array (the PDF spec's third form) maps 1:1 with no increment. Everything
collected -- from both `bfchar` and `bfrange` blocks -- is re-emitted as one combined `bfchar` block.
"""

import re

SHIFT = 3
ALPHABET_SIZE = 26
UPPER_BASE = 0x41
LOWER_BASE = 0x61

_HEX = r"<([0-9A-Fa-f]+)>"
_BFCHAR_ENTRY = re.compile(rf"{_HEX}\s*{_HEX}")
_BFRANGE_SINGLE_ENTRY = re.compile(rf"{_HEX}\s*{_HEX}\s*{_HEX}")
_BFRANGE_ARRAY_ENTRY = re.compile(rf"{_HEX}\s*{_HEX}\s*\[\s*((?:{_HEX}\s*)+)\]")


def _shift_code_unit(unit: int) -> int:
    if UPPER_BASE <= unit <= UPPER_BASE + ALPHABET_SIZE - 1:
        return (unit - UPPER_BASE + SHIFT) % ALPHABET_SIZE + UPPER_BASE
    if LOWER_BASE <= unit <= LOWER_BASE + ALPHABET_SIZE - 1:
        return (unit - LOWER_BASE + SHIFT) % ALPHABET_SIZE + LOWER_BASE
    return unit


def shift_destination(destination_hex: str) -> str:
    """Apply the ROT-3 letter shift to every UTF-16BE code unit of one destination string."""
    raw = bytes.fromhex(destination_hex)
    shifted = bytearray()
    for offset in range(0, len(raw) - 1, 2):
        unit = (raw[offset] << 8) | raw[offset + 1]
        shifted += _shift_code_unit(unit).to_bytes(2, "big")
    return shifted.hex().upper()


def _increment_destination(destination_hex: str, step: int) -> str:
    width = len(destination_hex)
    value = int(destination_hex, 16) + step
    return format(value, f"0{width}X")


def _collect_bfchar_pairs(block_text: str) -> list[tuple[int, str]]:
    return [(int(code, 16), destination.upper()) for code, destination in _BFCHAR_ENTRY.findall(block_text)]


def _collect_bfrange_pairs(block_text: str) -> list[tuple[int, str]]:
    pairs: list[tuple[int, str]] = []
    consumed = block_text
    for match in _BFRANGE_ARRAY_ENTRY.finditer(block_text):
        start, end, destinations_text = match.group(1), match.group(2), match.group(3)
        destinations = [d.upper() for d in re.findall(_HEX, destinations_text)]
        for code, destination in zip(range(int(start, 16), int(end, 16) + 1), destinations, strict=True):
            pairs.append((code, destination))
        consumed = consumed.replace(match.group(0), "")
    for match in _BFRANGE_SINGLE_ENTRY.finditer(consumed):
        start, end, destination = match.group(1), match.group(2), match.group(3)
        first, last = int(start, 16), int(end, 16)
        for step, code in enumerate(range(first, last + 1)):
            pairs.append((code, _increment_destination(destination.upper(), step)))
    return pairs


def collect_mapping_pairs(mapping_text: str) -> list[tuple[int, str]]:
    """Collect every (source code, destination hex) pair from bfchar/bfrange blocks, in order."""
    pairs: list[tuple[int, str]] = []
    for match in re.finditer(r"beginbfchar\s*.*?endbfchar|beginbfrange\s*.*?endbfrange", mapping_text, re.DOTALL):
        block = match.group(0)
        if block.startswith("beginbfchar"):
            inner = block[len("beginbfchar") : -len("endbfchar")]
            pairs.extend(_collect_bfchar_pairs(inner))
        else:
            inner = block[len("beginbfrange") : -len("endbfrange")]
            pairs.extend(_collect_bfrange_pairs(inner))
    return pairs


def rewrite_mapping_body(mapping_text: str) -> str:
    """Expand bfrange/bfchar entries, ROT-3-shift every destination, and re-emit as one bfchar block.

    `mapping_text` is the text between a CMap's `begincmap`/`endcmap` boilerplate -- codespace
    ranges included, since they are ignored here and left for the caller to keep verbatim. The
    return value is a single `N beginbfchar ... endbfchar` block, newline-terminated per entry.
    """
    pairs = collect_mapping_pairs(mapping_text)
    lines = [f"{len(pairs)} beginbfchar"]
    for code, destination in pairs:
        lines.append(f"<{code:04X}> <{shift_destination(destination)}>")
    lines.append("endbfchar")
    return "\n".join(lines) + "\n"
