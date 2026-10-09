"""Bandai card detail page (HTML) -> `RawDetail`.

`RawDetail` is the boundary structure: strings exactly as the page shows them (after whitespace/zero-width cleanup),
no interpretation. Interpretation into typed models happens in `build.py`.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from html.parser import HTMLParser

_ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍⁠﻿"))


class DetailPageError(Exception):
    """The page doesn't have the structure we expect."""


@dataclass(frozen=True)
class RawFaq:
    id: str
    updated: str
    question: str
    answer: str


@dataclass(frozen=True)
class RawDetail:
    card_no: str
    rarity: str  # as shown: "C", "C +", "LR", "P"
    block: str  # "1", "2", "β", "-"
    name: str
    fields: Mapping[str, str]  # label -> value, e.g. {"TYPE": "UNIT", "Lv.": "4", "Trait": "(A) (B)", ...}
    text: str  # effect text, line breaks kept, blank lines dropped
    image_src: str | None
    faq: tuple[RawFaq, ...]


def clean_inline(s: str) -> str:
    """Single-line text: drop zero-width characters, collapse whitespace."""
    return re.sub(r"\s+", " ", s.translate(_ZERO_WIDTH).replace("\xa0", " ")).strip()


def clean_block(s: str) -> str:
    """Multi-line text: drop zero-width characters and `\\r`, strip each line, drop blank lines."""
    s = s.translate(_ZERO_WIDTH).replace("\xa0", " ").replace("\r", "")
    lines = (re.sub(r"[ \t]+", " ", line).strip() for line in s.split("\n"))
    return "\n".join(line for line in lines if line)


@dataclass
class _Capture:
    key: str
    tag: str
    depth: int = 1
    parts: list[str] = field(default_factory=list)


class _DetailParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._cap: _Capture | None = None
        self._label: str | None = None
        self.card_no = ""
        self.rarity = ""
        self.block = ""
        self.name = ""
        self.fields: dict[str, str] = {}
        self.text = ""
        self.image_src: str | None = None
        self._in_card_image = 0
        self._faq: list[dict[str, str]] = []

    # -- helpers
    def _begin(self, key: str, tag: str) -> None:
        self._cap = _Capture(key, tag)

    def _finish(self, cap: _Capture) -> None:
        raw = "".join(cap.parts)
        match cap.key:
            case "card_no":
                self.card_no = clean_inline(raw)
            case "rarity":
                self.rarity = clean_inline(raw)
            case "block":
                self.block = clean_inline(raw)
            case "name":
                self.name = clean_inline(raw)
            case "label":
                self._label = clean_inline(raw)
            case "value":
                if self._label is None:
                    raise DetailPageError("data value without a preceding label")
                self.fields[self._label] = clean_inline(raw)
                self._label = None
            case "text":
                self.text = clean_block(raw)
            case "faq_num":
                self._faq.append({"id": clean_inline(raw)})
            case "faq_date":
                self._faq[-1]["updated"] = clean_inline(raw)
            case "faq_question":
                self._faq[-1]["question"] = clean_block(raw)
            case "faq_answer":
                self._faq[-1]["answer"] = clean_block(raw)

    # -- HTMLParser hooks
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = (attributes.get("class") or "").split()
        if self._cap is not None:
            if tag == self._cap.tag:
                self._cap.depth += 1
            if tag == "br":
                self._cap.parts.append("\n")
            elif tag == "p" and self._cap.key == "faq_answer":
                self._cap.parts.append("\n")
            return
        if tag == "div" and "cardImage" in classes:
            self._in_card_image = 1
        elif tag == "img" and self._in_card_image and self.image_src is None:
            self.image_src = attributes.get("src")
        elif tag == "div" and classes == ["cardNo"]:
            self._begin("card_no", tag)
        elif tag == "div" and classes == ["rarity"]:
            self._begin("rarity", tag)
        elif tag == "div" and classes == ["blockIcon"]:
            self._begin("block", tag)
        elif tag == "h1" and "cardName" in classes:
            self._begin("name", tag)
        elif tag == "dt" and "dataTit" in classes:
            self._begin("label", tag)
        elif tag == "dd" and "dataTxt" in classes:
            self._begin("value", tag)
        elif tag == "div" and "dataTxt" in classes and "isRegular" in classes:
            self._begin("text", tag)
        elif tag == "h3" and "qaColNum" in classes:
            self._begin("faq_num", tag)
        elif tag == "p" and "qaColDate" in classes:
            self._begin("faq_date_p", tag)
        elif tag == "dt" and "qaColQuestion" in classes:
            self._begin("faq_question", tag)
        elif tag == "dd" and "qaColAnswer" in classes:
            self._begin("faq_answer", tag)

    def handle_endtag(self, tag: str) -> None:
        cap = self._cap
        if cap is None or tag != cap.tag:
            return
        cap.depth -= 1
        if cap.depth > 0:
            return
        self._cap = None
        if cap.key == "faq_date_p":
            # "<span>July 04, 2025</span> Updated": keep only the span's text (the date).
            cap.key = "faq_date"
            cap.parts = [re.sub(r"\s*Updated\s*$", "", "".join(cap.parts).strip())]
        self._finish(cap)

    def handle_data(self, data: str) -> None:
        if self._cap is not None:
            self._cap.parts.append(data)

    def faq_entries(self) -> tuple[RawFaq, ...]:
        entries = []
        for item in self._faq:
            missing = {"id", "updated", "question", "answer"} - item.keys()
            if missing:
                raise DetailPageError(f"FAQ entry {item.get('id')} is missing {sorted(missing)}")
            entries.append(RawFaq(item["id"], item["updated"], item["question"], item["answer"]))
        return tuple(entries)


def parse_detail_html(html: str) -> RawDetail:
    """Parse one Bandai card detail page. Raises `DetailPageError` if the expected structure is missing."""
    parser = _DetailParser()
    parser.feed(html)
    parser.close()
    if not parser.card_no or not parser.name or not parser.rarity:
        raise DetailPageError(
            f"missing card number/name/rarity (got {parser.card_no!r}, {parser.name!r}, {parser.rarity!r})"
        )
    if "TYPE" not in parser.fields:
        raise DetailPageError(f"{parser.card_no}: no TYPE field (labels: {sorted(parser.fields)})")
    return RawDetail(
        card_no=parser.card_no,
        rarity=parser.rarity,
        block=parser.block,
        name=parser.name,
        fields=dict(parser.fields),
        text=parser.text,
        image_src=parser.image_src,
        faq=parser.faq_entries(),
    )
