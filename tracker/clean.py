"""Turn a race page's HTML into stable plain text for change detection.

Keeps all visible text, including headers and banners, because that is often
where race and ballot dates live. Drops scripts, styles, menus, footers and
forms, which change without the race details changing.
"""

from __future__ import annotations

import re

from lxml import html as lxml_html

DROP = (
    "//script|//style|//noscript|//template|//svg|//iframe|//nav|//footer|//form|//select"
    "|//*[@aria-hidden='true']|//*[@hidden]"
)
BLOCKS = {
    "address", "article", "aside", "blockquote", "dd", "div", "dl", "dt", "figcaption", "figure",
    "h1", "h2", "h3", "h4", "h5", "h6", "header", "li", "main", "ol", "p", "pre", "section",
    "table", "td", "th", "tr", "ul",
}


def clean_html(page: str) -> str:
    if not page.strip():
        return ""
    doc = lxml_html.fromstring(page)
    for el in doc.xpath(DROP):
        el.drop_tree()
    for el in doc.iter():
        if not isinstance(el.tag, str):
            continue  # comments and processing instructions
        if el.tag == "br":
            el.tail = "\n" + (el.tail or "")
        elif el.tag in BLOCKS:
            el.text = "\n" + (el.text or "")
            el.tail = "\n" + (el.tail or "")

    lines: list[str] = []
    for raw in doc.text_content().splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if line and (not lines or lines[-1] != line):
            lines.append(line)
    return "\n".join(lines)
