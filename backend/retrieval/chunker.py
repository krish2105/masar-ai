"""Document chunking for the vector index.

Two rules from §6.1 shape this, and both exist because of how the corpus is
actually written:

1. **Never split across a markdown heading.** Every corpus document is
   heading-structured — "## Stations in this zone", "## Important limitation".
   A chunk spanning two headings mixes unrelated facts and produces citations
   that point at a passage only half of which supports the claim.

2. **Carry heading context into every chunk.** A chunk reading "AED 4.00 per
   gate crossing" is useless in isolation and actively dangerous as evidence.
   Prefixing the document title and heading path makes each chunk
   self-describing, which measurably improves both embedding quality and the
   reader's ability to judge a citation.

Token counts are approximated by whitespace words scaled by a constant. An exact
tokeniser would tie chunking to a specific model, and the boundary only needs to
be approximately right — chunk overlap absorbs the error.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CHUNK_TOKENS = 512
DEFAULT_OVERLAP_TOKENS = 64

# bge-m3 averages ~1.3 tokens per whitespace word on English prose and rather
# more on Arabic. Erring high keeps chunks inside the model's window.
TOKENS_PER_WORD = 1.4

_FRONT_MATTER = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
_HEADING = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


def estimate_tokens(text: str) -> int:
    return int(len(text.split()) * TOKENS_PER_WORD)


@dataclass(slots=True)
class Chunk:
    chunk_id: str
    doc_id: str
    text: str
    """The embedded text, including the heading-path prefix."""

    raw_text: str
    """The passage without the prefix — what a citation displays."""

    heading_path: str
    lang: str
    service_category: str
    title: str
    source_url: str
    retrieved_date: str
    position: int
    token_estimate: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ParsedDocument:
    doc_id: str
    front_matter: dict[str, Any]
    body: str
    path: Path

    @property
    def lang(self) -> str:
        return str(self.front_matter.get("lang", "en"))

    @property
    def title(self) -> str:
        return str(self.front_matter.get("title", self.doc_id))

    @property
    def category(self) -> str:
        return str(self.front_matter.get("service_category", "general"))

    @property
    def source_url(self) -> str:
        return str(self.front_matter.get("source_url", ""))

    @property
    def retrieved_date(self) -> str:
        return str(self.front_matter.get("retrieved_date", ""))


def parse_document(path: Path) -> ParsedDocument:
    """Split YAML front matter from the markdown body.

    A document without front matter is still usable — it simply carries no
    metadata — because failing the whole index over one malformed file would be
    a poor trade.
    """
    text = path.read_text(encoding="utf-8")
    front: dict[str, Any] = {}

    if match := _FRONT_MATTER.match(text):
        try:
            front = yaml.safe_load(match.group(1)) or {}
        except yaml.YAMLError:
            front = {}
        body = text[match.end() :]
    else:
        body = text

    return ParsedDocument(
        doc_id=str(front.get("doc_id", path.stem)),
        front_matter=front,
        body=body.strip(),
        path=path,
    )


@dataclass(slots=True)
class _Section:
    heading_path: str
    text: str


def _split_sections(body: str) -> list[_Section]:
    """Break a document at headings, tracking the full heading path.

    The path ("Fare zone 5 › Stations in this zone") is what makes an isolated
    chunk interpretable.
    """
    matches = list(_HEADING.finditer(body))
    if not matches:
        return [_Section(heading_path="", text=body.strip())] if body.strip() else []

    sections: list[_Section] = []

    if preamble := body[: matches[0].start()].strip():
        sections.append(_Section(heading_path="", text=preamble))

    stack: list[tuple[int, str]] = []
    for index, match in enumerate(matches):
        level = len(match.group(1))
        heading = match.group(2).strip()

        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, heading))

        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        content = body[match.end() : end].strip()
        if content:
            sections.append(_Section(heading_path=" › ".join(h for _, h in stack), text=content))

    return sections


def _split_long_text(text: str, max_tokens: int, overlap_tokens: int) -> list[str]:
    """Window an over-long section, preferring paragraph then sentence breaks."""
    if estimate_tokens(text) <= max_tokens:
        return [text]

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    units: list[str] = []
    for paragraph in paragraphs:
        if estimate_tokens(paragraph) <= max_tokens:
            units.append(paragraph)
            continue
        # A single oversized paragraph (a long markdown table, typically) is
        # split on line boundaries so table rows stay intact.
        buffer: list[str] = []
        for line in paragraph.splitlines():
            buffer.append(line)
            if estimate_tokens("\n".join(buffer)) >= max_tokens:
                units.append("\n".join(buffer))
                buffer = []
        if buffer:
            units.append("\n".join(buffer))

    chunks: list[str] = []
    current: list[str] = []
    for unit in units:
        candidate = [*current, unit]
        if current and estimate_tokens("\n\n".join(candidate)) > max_tokens:
            chunks.append("\n\n".join(current))
            # Overlap: carry the tail of the previous chunk into the next so a
            # fact spanning the boundary is retrievable from either side.
            tail: list[str] = []
            for previous in reversed(current):
                tail.insert(0, previous)
                if estimate_tokens("\n\n".join(tail)) >= overlap_tokens:
                    break
            current = [*tail, unit]
        else:
            current = candidate
    if current:
        chunks.append("\n\n".join(current))

    return chunks


def chunk_document(
    document: ParsedDocument,
    *,
    max_tokens: int = DEFAULT_CHUNK_TOKENS,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
) -> list[Chunk]:
    chunks: list[Chunk] = []
    position = 0

    for section in _split_sections(document.body):
        for piece in _split_long_text(section.text, max_tokens, overlap_tokens):
            prefix_parts = [document.title]
            if section.heading_path:
                prefix_parts.append(section.heading_path)
            prefix = " › ".join(prefix_parts)
            embedded = f"{prefix}\n\n{piece}"

            digest = hashlib.sha1(
                f"{document.doc_id}:{position}:{piece[:120]}".encode()
            ).hexdigest()[:16]

            chunks.append(
                Chunk(
                    chunk_id=f"{document.doc_id}#{position:03d}-{digest}",
                    doc_id=document.doc_id,
                    text=embedded,
                    raw_text=piece,
                    heading_path=section.heading_path,
                    lang=document.lang,
                    service_category=document.category,
                    title=document.title,
                    source_url=document.source_url,
                    retrieved_date=document.retrieved_date,
                    position=position,
                    token_estimate=estimate_tokens(embedded),
                    metadata={
                        k: v
                        for k, v in document.front_matter.items()
                        if k in {"dataset_id", "zone_id", "line_name", "mode", "domain"}
                    },
                )
            )
            position += 1

    return chunks


def chunk_corpus(
    corpus_dir: Path,
    *,
    max_tokens: int = DEFAULT_CHUNK_TOKENS,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
) -> list[Chunk]:
    chunks: list[Chunk] = []
    for path in sorted(corpus_dir.rglob("*.md")):
        document = parse_document(path)
        if not document.body:
            continue
        chunks.extend(
            chunk_document(document, max_tokens=max_tokens, overlap_tokens=overlap_tokens)
        )
    return chunks
