"""Exception types for the fetching layer."""


class FetchError(RuntimeError):
    """A target-page fetch could not be completed (bad scheme, DNS, network, size)."""


class SSRFError(FetchError):
    """The URL was rejected by the SSRF guard (non-public / disallowed address)."""


class TransientFetchError(FetchError):
    """A transient fetch failure (timeout / connection error) that may be retried."""


class RobotsDisallowedError(FetchError):
    """The site's robots.txt disallows fetching the URL for our user agent."""


class RateLimitedError(FetchError):
    """The per-host request rate limit was exceeded (non-transient — not retried)."""
