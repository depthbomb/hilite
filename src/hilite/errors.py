class HighlighterError(Exception):
    """Base exception for the public API."""


class GrammarError(HighlighterError):
    """A grammar is malformed or cannot be executed safely."""


class UnsupportedPatternError(GrammarError):
    """Oniguruma cannot compile a grammar pattern."""


class MissingGrammarError(GrammarError):
    """No registered grammar matches the requested language or scope."""


class ThemeError(HighlighterError):
    """A theme or selector is malformed."""


class HtmlRenderingError(HighlighterError):
    """Source or styling cannot be represented by the HTML renderer."""


class SelectionError(HighlighterError, ValueError):
    """A line selection is invalid for the highlighted source."""


class ResourceLimitError(HighlighterError):
    """Highlighting exceeded a configured resource limit."""
