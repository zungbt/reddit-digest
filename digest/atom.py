import html
from html.parser import HTMLParser
import re
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass

ATOM_NS = "http://www.w3.org/2005/Atom"


@dataclass
class Post:
    id: str
    sub: str
    title: str
    url: str
    link: str | None
    body: str
    published: str


def is_external(url: str | None) -> bool:
    if not url:
        return False
    try:
        parsed = urllib.parse.urlsplit(url)
    except Exception:
        return False
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    if host == "reddit.com" or host.endswith(".reddit.com"):
        return False
    if host == "redd.it" or host.endswith(".redd.it"):
        return False
    if "/gallery/" in parsed.path:
        return False
    return True


class LinkAnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._current_tag: str | None = None
        self._current_href: str | None = None
        self._anchor_text: list[str] = []
        self.link_href: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self._current_tag = tag
            self._current_href = dict(attrs).get("href")
            self._anchor_text = []

    def handle_data(self, data: str) -> None:
        if self._current_tag == "a":
            self._anchor_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._current_tag == "a":
            text = "".join(self._anchor_text).strip()
            if text == "[link]" and self._current_href:
                self.link_href = self._current_href.strip()
            self._current_tag = None
            self._current_href = None
            self._anchor_text = []


class MarkdownParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.text_parts: list[str] = []
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href.strip())
        elif tag in ("p", "br", "div", "li", "tr", "td", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6"):
            self.text_parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("p", "div", "li", "tr", "td", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6"):
            self.text_parts.append(" ")

    def handle_data(self, data: str) -> None:
        self.text_parts.append(data)


def _parse_entry(entry: ET.Element) -> Post:
    # id
    id_elem = entry.find(f"{{{ATOM_NS}}}id")
    raw_id = id_elem.text.strip() if id_elem is not None and id_elem.text else ""
    if raw_id.startswith("t3_"):
        post_id = raw_id
    elif "t3_" in raw_id:
        post_id = "t3_" + raw_id.split("t3_", 1)[1].split()[0]
    else:
        post_id = raw_id

    # sub
    category_elem = entry.find(f"{{{ATOM_NS}}}category")
    sub = category_elem.get("term", "") if category_elem is not None else ""

    # title
    title_elem = entry.find(f"{{{ATOM_NS}}}title")
    title = html.unescape(title_elem.text.strip()) if title_elem is not None and title_elem.text else ""

    # url (permalink)
    url = ""
    for link_elem in entry.findall(f"{{{ATOM_NS}}}link"):
        rel = link_elem.get("rel")
        href = link_elem.get("href", "")
        if rel == "alternate" or not rel:
            url = href
            break
    if not url:
        link_elem = entry.find(f"{{{ATOM_NS}}}link")
        if link_elem is not None:
            url = link_elem.get("href", "")

    # published
    published_elem = entry.find(f"{{{ATOM_NS}}}published")
    if published_elem is not None and published_elem.text:
        published = published_elem.text.strip()
    else:
        updated_elem = entry.find(f"{{{ATOM_NS}}}updated")
        published = updated_elem.text.strip() if updated_elem is not None and updated_elem.text else ""

    # content
    content_elem = entry.find(f"{{{ATOM_NS}}}content")
    raw_html = content_elem.text if content_elem is not None and content_elem.text else ""

    # Find [link] anchor href
    link_parser = LinkAnchorParser()
    link_parser.feed(raw_html)
    link_anchor_href = link_parser.link_href
    if not link_anchor_href:
        m = re.search(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>\s*\[link\]\s*</a>', raw_html, re.IGNORECASE)
        if m:
            link_anchor_href = m.group(1).strip()

    # Extract markdown section (between <!-- SC_OFF --> and <!-- SC_ON -->)
    md_html = ""
    if "<!-- SC_OFF -->" in raw_html and "<!-- SC_ON -->" in raw_html:
        md_html = raw_html.split("<!-- SC_OFF -->", 1)[1].split("<!-- SC_ON -->", 1)[0]
    elif '<div class="md">' in raw_html and "</div>" in raw_html:
        md_html = raw_html.split('<div class="md">', 1)[1].rsplit("</div>", 1)[0]

    md_parser = MarkdownParser()
    if md_html:
        md_parser.feed(md_html)
        raw_body_text = " ".join("".join(md_parser.text_parts).split())
        body = raw_body_text
    else:
        body = ""

    # Compute link
    if link_anchor_href and is_external(link_anchor_href):
        link = link_anchor_href
    else:
        link = None
        for h in md_parser.links:
            if is_external(h):
                link = h
                break

    return Post(
        id=post_id,
        sub=sub,
        title=title,
        url=url,
        link=link,
        body=body,
        published=published,
    )


def parse(xml: str) -> list[Post]:
    xml_bytes = xml.encode("utf-8") if isinstance(xml, str) else xml
    root = ET.fromstring(xml_bytes)
    posts = []
    for entry in root.findall(f"{{{ATOM_NS}}}entry"):
        posts.append(_parse_entry(entry))
    return posts
