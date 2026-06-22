"""Strip boilerplate and trim page HTML to a character budget before the LLM."""

from selectolax.parser import HTMLParser

from app.config import Settings

# Non-content nodes removed before extracting text. A coarse, lossy strip: drop the
# chrome (nav/header/footer) and the non-prose machinery (script/style/svg/iframe) so
# only the page's meaningful text reaches the model.
_DROP_SELECTOR = "script, style, nav, footer, header, noscript, svg, iframe"


def clean(html: str, *, settings: Settings) -> str:
    """Return boilerplate-free plain text for `html`, capped at max_content_chars.

    Pure function — no network, no job state, no LLM. The cap is a coarse cost
    ceiling (characters, not tokens); truncation is naive `text[:cap]` and is
    documented as lossy (token-aware chunking is a Phase-5 follow-up).
    """
    tree = HTMLParser(html)
    for node in tree.css(_DROP_SELECTOR):
        node.decompose()
    text = tree.body.text(separator=" ", strip=True) if tree.body else tree.text()
    return text[: settings.max_content_chars]
