"""Exception types for the fetching layer."""


class FetchError(RuntimeError):
    """A target-page fetch could not be completed (bad scheme, DNS, network, size)."""


class SSRFError(FetchError):
    """The URL was rejected by the SSRF guard (non-public / disallowed address)."""
