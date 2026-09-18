from __future__ import annotations

import io
import re
from dataclasses import dataclass
from typing import Iterable

from pypdf import PdfReader


@dataclass(frozen=True)
class Clause:
    reference: str
    category: str
    text: str
    ordinal: int


CATEGORY_KEYWORDS = {
    "EXCLUSION": (
        "out of scope", "excluded", "excludes", "exclusion", "exclusions", "not included", "does not include"
    ),
    "ACCEPTANCE": ("acceptance", "accepted when", "definition of done"),
    "MILESTONE": ("milestone", "delivery date", "timeline", "schedule"),
    "INTEGRATION": ("integration", "integrate", "api", "webhook", "third-party", "provider"),
    "TECHNICAL": ("technical", "architecture", "database", "framework", "security", "authentication"),
    "COMMERCIAL": ("rate", "price", "fee", "payment terms", "change order"),
    "RESPONSIBILITY": ("client shall", "customer shall", "client responsibility", "provided by client"),
    "DELIVERABLE": ("deliverable", "shall build", "will provide", "will implement", "scope"),
}


def extract_pdf_text(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    pages = []
    for index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        pages.append(f"[Page {index}]\n{text.strip()}")
    return "\n\n".join(pages).strip()


def classify_clause(text: str) -> str:
    lowered = text.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(re.search(rf"\b{re.escape(keyword)}\b", lowered) for keyword in keywords):
            return category
    return "GENERAL"


def _clean_blocks(text: str) -> Iterable[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"[ \t]+", " ", normalized)
    blocks = re.split(r"\n\s*\n+", normalized)
    for block in blocks:
        cleaned = " ".join(line.strip() for line in block.splitlines() if line.strip())
        if cleaned:
            yield cleaned


def split_into_clauses(text: str) -> list[Clause]:
    """Split SOW text into auditable chunks while retaining section references."""
    clauses: list[Clause] = []
    section_pattern = re.compile(
        r"^(?:\[Page (?P<page>\d+)\]\s*)?(?:Section\s+)?"
        r"(?P<ref>\d+(?:\.\d+)*)(?:\s*[:.)-]\s*|\s+)(?P<body>.+)$",
        re.IGNORECASE,
    )

    for ordinal, block in enumerate(_clean_blocks(text), start=1):
        match = section_pattern.match(block)
        if match:
            reference = match.group("ref")
            body = match.group("body").strip()
        else:
            page = re.match(r"^\[Page (\d+)\]\s*(.+)$", block, re.DOTALL)
            reference = f"page-{page.group(1)}-{ordinal}" if page else f"chunk-{ordinal}"
            body = page.group(2).strip() if page else block

        # Avoid giant chunks when a PDF extractor removes paragraph breaks. Also
        # separate positive scope statements from negative/exclusion sentences;
        # indexing both as one clause causes valid work to inherit an exclusion.
        sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", body)
        groups: list[str] = []
        negative_markers = (
            "excluded", "excludes", "exclusions", "not included", "does not include", "out of scope"
        )
        has_negative = any(any(marker in sentence.lower() for marker in negative_markers) for sentence in sentences)
        has_positive = any(not any(marker in sentence.lower() for marker in negative_markers) for sentence in sentences)
        if len(sentences) > 1 and has_negative and has_positive:
            groups = [sentence.strip() for sentence in sentences if sentence.strip()]
        else:
            current = ""
            for sentence in sentences:
                if current and len(current) + len(sentence) > 900:
                    groups.append(current)
                    current = sentence
                else:
                    current = f"{current} {sentence}".strip()
            if current:
                groups.append(current)

        for part_index, group in enumerate(groups, start=1):
            part_ref = reference if len(groups) == 1 else f"{reference}.{part_index}"
            clauses.append(
                Clause(
                    reference=part_ref,
                    category=classify_clause(group),
                    text=group,
                    ordinal=len(clauses) + 1,
                )
            )

    return clauses
