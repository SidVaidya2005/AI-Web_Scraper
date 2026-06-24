"""Strip boilerplate and trim page HTML to a character budget before the LLM."""

from dataclasses import dataclass

from selectolax.parser import HTMLParser

from app.config import Settings

# Non-content nodes removed before extracting text. A coarse, lossy strip: drop the
# chrome (nav/header/footer) and the non-prose machinery (script/style/svg/iframe) so
# only the page's meaningful text reaches the model.
_DROP_SELECTOR = "script, style, nav, footer, header, noscript, svg, iframe"


@dataclass(frozen=True)
class CleanResult:
    """Cleaned page text plus whether the character cap dropped any of it.

    `truncated` lets callers signal lossy reduction (record it on the job, warn in
    logs) — the truncation itself is still the documented v1 behavior.
    """

    text: str
    truncated: bool


def clean(html: str, *, settings: Settings) -> CleanResult:
    """Return boilerplate-free plain text for `html`, capped at max_content_chars.

    Pure function — no network, no job state, no LLM. The cap is a coarse cost
    ceiling (characters, not tokens); truncation is naive `text[:cap]` and is
    documented as lossy (token-aware chunking is a Phase-5 follow-up). `truncated`
    reports whether the cap actually dropped content.
    """
    tree = HTMLParser(html)
    for node in tree.css(_DROP_SELECTOR):
        node.decompose()
    text = tree.body.text(separator=" ", strip=True) if tree.body else tree.text()
    cap = settings.max_content_chars
    return CleanResult(text=text[:cap], truncated=len(text) > cap)
