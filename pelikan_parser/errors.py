class ParserError(RuntimeError):
    """Base error with a user-facing message."""


class ConfigurationError(ParserError):
    """Invalid or incomplete project configuration."""


class LocatorNotFoundError(ParserError):
    """None of the configured locator candidates matched the page."""
