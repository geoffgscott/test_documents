"""Finding and rewriting /ToUnicode CMap streams in a qpdf QDF (plain-text PDF) file.

~keep QDF mode (`qpdf --qdf --object-streams=disable --stream-data=uncompress`) is what makes this
tractable with regex instead of a real PDF object model: one object per readable block, streams
uncompressed, no object streams hiding indirection. `fix-qdf` is what makes writing it back safe --
it recomputes every cross-reference offset from the object boundaries, so this module only has to
get object *bodies* right, never byte offsets.
"""

import re
from dataclasses import dataclass

from corpus_tools.wrong_mapping.cmap import rewrite_mapping_body

_OBJECT = re.compile(rb"(?m)^(\d+) 0 obj\n(.*?)\nendobj", re.DOTALL)
_STREAM = re.compile(rb"\nstream\r?\n(.*?)\r?\nendstream", re.DOTALL)
_INDIRECT_REF = re.compile(rb"(\d+) 0 R")
_FONT_DICT_BLOCK = re.compile(rb"/Font\s*<<(.*?)>>", re.DOTALL)
_TO_UNICODE = re.compile(rb"/ToUnicode\s+(\d+) 0 R")
_BASE_FONT = re.compile(rb"/BaseFont\s*/(\S+)")
_LENGTH_DIRECT = re.compile(rb"/Length\s+(\d+)(?!\s+0\s+R)")
_LENGTH_INDIRECT = re.compile(rb"/Length\s+(\d+)\s+0\s+R")
_BF_SPAN = re.compile(rb"\d+\s+beginbf(?:char|range).*endbf(?:char|range)", re.DOTALL)


class UnsuitableSourceError(Exception):
    """Raised when some font on some page has no /ToUnicode -- this source cannot be used."""


@dataclass
class QdfDocument:
    """A qpdf QDF file's objects, keyed by object number, plus enough structure to walk pages."""

    raw: bytes
    objects: dict[int, tuple[int, int, bytes]]  # obj_num -> (body_start, body_end, body)

    @classmethod
    def parse(cls, raw: bytes) -> "QdfDocument":
        objects = {}
        for match in _OBJECT.finditer(raw):
            objects[int(match.group(1))] = (match.start(2), match.end(2), match.group(2))
        return cls(raw=raw, objects=objects)

    def body(self, obj_num: int) -> bytes:
        return self.objects[obj_num][2]

    def dict_part(self, obj_num: int) -> bytes:
        body = self.body(obj_num)
        stream_match = _STREAM.search(body)
        return body[: stream_match.start()] if stream_match else body


def _catalog_object_number(document: QdfDocument) -> int:
    for obj_num, (_, _, body) in document.objects.items():
        if b"/Type /Catalog" in body:
            return obj_num
    raise UnsuitableSourceError("no /Type /Catalog object found")


def _resolve_resources(document: QdfDocument, page_obj: int, inherited: int | None) -> int | None:
    body = document.dict_part(page_obj)
    match = re.search(rb"/Resources\s+(\d+) 0 R", body)
    if match:
        return int(match.group(1))
    if re.search(rb"/Resources\s*<<", body):
        return page_obj  # /Resources embedded inline in the page dict itself
    return inherited


def _walk_pages(document: QdfDocument, pages_obj: int, inherited_resources: int | None) -> list[int]:
    body = document.dict_part(pages_obj)
    resources = _resolve_resources(document, pages_obj, inherited_resources)
    kids_match = re.search(rb"/Kids\s*\[(.*?)\]", body, re.DOTALL)
    if not kids_match:
        return [pages_obj] if resources is not None else []
    resource_ids: list[int] = []
    for kid in _INDIRECT_REF.findall(kids_match.group(1)):
        kid_num = int(kid)
        kid_body = document.dict_part(kid_num)
        if b"/Type /Pages" in kid_body:
            resource_ids.extend(_walk_pages(document, kid_num, resources))
        else:
            page_resources = _resolve_resources(document, kid_num, resources)
            if page_resources is None:
                raise UnsuitableSourceError(f"page object {kid_num} has no /Resources, inherited or direct")
            resource_ids.append(page_resources)
    return resource_ids


def page_resource_objects(document: QdfDocument) -> list[int]:
    """Every /Resources object number reachable from a page, one entry per page."""
    catalog = _catalog_object_number(document)
    pages_match = re.search(rb"/Pages\s+(\d+) 0 R", document.dict_part(catalog))
    if not pages_match:
        raise UnsuitableSourceError("catalog has no /Pages entry")
    return _walk_pages(document, int(pages_match.group(1)), None)


def font_object_numbers(document: QdfDocument, resources_obj: int) -> list[int]:
    """The direct-child font refs of one /Resources object's /Font subdictionary."""
    match = _FONT_DICT_BLOCK.search(document.dict_part(resources_obj))
    if not match:
        return []
    return [int(ref) for ref in _INDIRECT_REF.findall(match.group(1))]


def to_unicode_object_numbers(document: QdfDocument) -> set[int]:
    """Every ToUnicode CMap stream reachable from any page's fonts.

    Raises UnsuitableSourceError naming the offending font if any font on any page lacks one.
    """
    stream_objects: set[int] = set()
    for resources_obj in set(page_resource_objects(document)):
        for font_obj in font_object_numbers(document, resources_obj):
            font_dict = document.dict_part(font_obj)
            match = _TO_UNICODE.search(font_dict)
            if not match:
                base_font_match = _BASE_FONT.search(font_dict)
                name = base_font_match.group(1).decode("latin-1") if base_font_match else f"object {font_obj}"
                raise UnsuitableSourceError(f"font without /ToUnicode: {name} (object {font_obj})")
            stream_objects.add(int(match.group(1)))
    return stream_objects


def _new_length_bytes(dict_part: bytes, new_length: int) -> tuple[bytes, int | None]:
    """Return the dict text with /Length updated, and an indirect Length object number if any."""
    indirect = _LENGTH_INDIRECT.search(dict_part)
    if indirect:
        return dict_part, int(indirect.group(1))
    direct = _LENGTH_DIRECT.search(dict_part)
    if not direct:
        raise UnsuitableSourceError("ToUnicode stream object has no /Length entry")
    updated = dict_part[: direct.start(1)] + str(new_length).encode("ascii") + dict_part[direct.end(1) :]
    return updated, None


def rewrite_to_unicode_streams(document: QdfDocument, stream_objects: set[int]) -> bytes:
    """Return new raw QDF bytes with every named ToUnicode stream's mapping body ROT-3-shifted."""
    edits: list[tuple[int, int, bytes]] = []
    for obj_num in stream_objects:
        body_start, body_end, body = document.objects[obj_num]
        stream_match = _STREAM.search(body)
        if not stream_match:
            raise UnsuitableSourceError(f"ToUnicode object {obj_num} has no stream")
        stream_text = stream_match.group(1)
        bf_span = _BF_SPAN.search(stream_text)
        if not bf_span:
            raise UnsuitableSourceError(f"ToUnicode object {obj_num} has no bfchar/bfrange mapping")
        new_mapping = rewrite_mapping_body(bf_span.group(0).decode("ascii")).encode("ascii").rstrip(b"\n")
        new_stream_text = stream_text[: bf_span.start()] + new_mapping + stream_text[bf_span.end() :]
        new_body = body[: stream_match.start(1)] + new_stream_text + body[stream_match.end(1) :]
        dict_part = new_body[: new_body.find(b"\nstream\n")]
        new_dict_part, indirect_length_obj = _new_length_bytes(dict_part, len(new_stream_text))
        new_body = new_dict_part + new_body[len(dict_part) :]
        edits.append((body_start, body_end, new_body))
        if indirect_length_obj is not None:
            length_start, length_end, _ = document.objects[indirect_length_obj]
            edits.append((length_start, length_end, str(len(new_stream_text)).encode("ascii")))

    edits.sort(key=lambda edit: edit[0], reverse=True)
    raw = document.raw
    for start, end, replacement in edits:
        raw = raw[:start] + replacement + raw[end:]
    return raw
