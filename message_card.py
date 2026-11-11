"""Private, offline notification cards; render_card returns PNG bytes only."""
from io import BytesIO
from dataclasses import dataclass
from functools import lru_cache
import re

from PIL import Image, ImageDraw, ImageFont
from markdown_it import MarkdownIt

WIDTH = 1000
MAX_HEIGHT = 6000
FONT_SIZE = 30
MAX_TEXT_CHARS = 12000
MARGIN = 48
TRUNCATED = "…（内容过长，已截断）"
# YaHei covers Chinese but not notification emoji: keep text labels, omit icons.
_DECORATIVE_EMOJI = re.compile(
    '[\U0001f000-\U0001faff\u2600-\u27bf\u23f0-\u23ff\ufe0e\ufe0f\u200d]'
)


@dataclass(frozen=True)
class Span:
    text: str
    bold: bool = False


@dataclass(frozen=True)
class Block:
    kind: str
    spans: tuple[Span, ...]


def parse_blocks(text: str) -> list[Block]:
    """Convert local Markdown to visible spans; never resolve resource URLs."""
    clipped = len(text) > MAX_TEXT_CHARS
    # Bound before normalization and Markdown parsing, including unfinished fences.
    text = "".join(
        ch if (ord(ch) >= 32 or ch in "\n\t\r") and not 0xD800 <= ord(ch) <= 0xDFFF else " "
        for ch in text[:MAX_TEXT_CHARS]
    )
    text = _DECORATIVE_EMOJI.sub('', text)
    tokens = MarkdownIt("commonmark", {"html": False}).enable("table").parse(text)
    blocks = []
    lists = []
    quote = 0
    kind = "paragraph"
    row = None
    for token in tokens:
        t = token.type
        if t in ("bullet_list_open", "ordered_list_open"):
            lists.append(None if t == "bullet_list_open" else int(token.attrGet("start") or 1))
        elif t in ("bullet_list_close", "ordered_list_close"):
            lists.pop()
        elif t == "blockquote_open":
            quote += 1
        elif t == "blockquote_close":
            quote -= 1
        elif t == "heading_open":
            kind = "heading"
        elif t == "paragraph_open":
            kind = "list" if lists else "quote" if quote else "paragraph"
        elif t in ("fence", "code_block"):
            blocks.append(Block("omission", (Span("[代码块已省略]"),)))
        elif t == "tr_open":
            row = []
        elif t == "tr_close":
            blocks.append(Block("table", tuple(row)))
            row = None
        elif t == "inline":
            spans = []
            strong = 0
            for child in token.children or []:
                if child.type == "strong_open":
                    strong += 1
                elif child.type == "strong_close":
                    strong -= 1
                elif child.type in ("text", "code_inline"):
                    spans.append(Span(child.content, strong > 0))
                elif child.type in ("softbreak", "hardbreak"):
                    spans.append(Span("\n"))
                elif child.type == "image":
                    spans.append(Span("[图片已省略]"))
            if row is not None:
                if row:
                    row.append(Span("  ·  "))
                row.extend(spans)
            else:
                if kind == "list":
                    marker = "• " if lists[-1] is None else f"{lists[-1]}. "
                    if lists[-1] is not None:
                        lists[-1] += 1
                    spans.insert(0, Span("  " * (len(lists) - 1) + marker))
                blocks.append(Block(kind, tuple(spans)))
    if clipped:
        blocks.append(Block("truncation", (Span(TRUNCATED),)))
    return blocks


@lru_cache(maxsize=8)
def _font(size: int, bold: bool = False):
    candidates = (
        "C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "DejaVuSans.ttf",
    )
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


@dataclass(frozen=True)
class DrawLine:
    kind: str
    spans: tuple[Span, ...]
    size: int
    y: int


def _layout(blocks: list[Block]) -> tuple[list[DrawLine], int]:
    """Wrap Chinese/long tokens within a bounded one-image layout."""
    lines = []
    y = MARGIN
    # Local caches only: do not retain private text after returning.
    widths = {}
    stopped = False
    for block in blocks:
        size = 40 if block.kind == "heading" else FONT_SIZE
        step = int(size * 1.6)
        available = WIDTH - 2 * MARGIN - (24 if block.kind == "quote" else 0)
        spans = []
        used = 0.0

        def flush():
            nonlocal y, spans, used
            if y + step > MAX_HEIGHT - MARGIN - 80:
                return False
            lines.append(DrawLine(block.kind, tuple(spans), size, y))
            y += step
            spans, used = [], 0.0
            return True

        for span in block.spans:
            bold = span.bold or block.kind == "heading"
            for ch in span.text:
                if ch == "\n":
                    if not flush():
                        stopped = True
                        break
                    continue
                if ch == "\t":
                    ch = " "
                key = (ch, size, bold)
                if key not in widths:
                    widths[key] = _font(size, bold).getlength(ch)
                width = widths[key]
                if used + width > available and spans:
                    if not flush():
                        stopped = True
                        break
                if spans and spans[-1].bold == bold:
                    spans[-1] = Span(spans[-1].text + ch, bold)
                else:
                    spans.append(Span(ch, bold))
                used += width
            if stopped:
                break
        if stopped:
            break
        if spans and not flush():
            stopped = True
            break
        y += 16
    if stopped:
        lines.append(DrawLine("truncation", (Span(TRUNCATED),), FONT_SIZE, y))
        y += 48
    return lines, min(MAX_HEIGHT, max(200, y + MARGIN))


def render_card(text: str) -> bytes:
    """Return one private PNG; no files, logs, network, or notification sending.

    Source is capped at 12,000 code points before parsing; wrapped content is
    capped at 6,000 pixels high, with an explicit truncation notice for either
    limit. Fonts prefer Windows Microsoft YaHei, then local CJK/system fonts.
    """
    lines, height = _layout(parse_blocks(text))
    image = Image.new("RGB", (WIDTH, height), "#1e1e1e")
    draw = ImageDraw.Draw(image)
    for line in lines:
        x = MARGIN
        color = "#ce9178" if line.kind == "truncation" else "#d4d4d4"
        if line.kind == "quote":
            draw.rectangle((x, line.y, x + 4, line.y + 39), fill="#606060")
            x += 24
            color = "#9cdcfe"
        for span in line.spans:
            font = _font(line.size, span.bold)
            draw.text((x, line.y), span.text, font=font, fill=color, anchor="lt")
            x += font.getlength(span.text)
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()
