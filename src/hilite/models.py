from math import isfinite
from types import MappingProxyType
from typing import Final, Optional
from dataclasses import field, dataclass
from hilite.errors import SelectionError
from collections.abc import Mapping, Iterable


class UnsetType:
    __slots__ = ()

    def __repr__(self) -> str:
        return 'UNSET'


class DefaultType:
    __slots__ = ()

    def __repr__(self) -> str:
        return 'DEFAULT'


UNSET: Final = UnsetType()
DEFAULT: Final = DefaultType()
type ColorValue = str | UnsetType | DefaultType
type FlagValue = bool | UnsetType


@dataclass(frozen=True, slots=True)
class Style:
    foreground: ColorValue = UNSET
    background: ColorValue = UNSET
    bold: FlagValue = UNSET
    italic: FlagValue = UNSET
    underline: FlagValue = UNSET
    strikethrough: FlagValue = UNSET

    def overlay(self, other: Style) -> Style:
        values = {}
        for name in ('foreground', 'background', 'bold', 'italic', 'underline', 'strikethrough'):
            value = getattr(other, name)
            values[name] = getattr(self, name) if value is UNSET else value
        return Style(**values)


@dataclass(frozen=True, slots=True)
class ThemeRule:
    selector: str
    style: Style


@dataclass(frozen=True, slots=True)
class Theme:
    foreground: str = '#000000'
    background: str = '#ffffff'
    rules: tuple[ThemeRule, ...] = ()
    gutter_foreground: str = '#6e7781'
    gutter_background: ColorValue = UNSET
    selection_background: str = '#fff3bf'
    default_style: Style = Style()

    def __post_init__(self) -> None:
        object.__setattr__(self, 'rules', tuple(self.rules))

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> Theme:
        from hilite.theme import theme_from_dict

        return theme_from_dict(data)

    @classmethod
    def from_file(cls, path: str) -> Theme:
        from hilite.theme import load_theme

        return load_theme(path)


@dataclass(frozen=True, slots=True)
class HtmlLayout:
    font_family: str = 'ui-monospace, SFMono-Regular, Consolas, monospace'
    font_size: str = '0.875rem'
    line_height: str = '1.5'
    padding: str = '1rem'
    margin: str = '0'
    border: str = '0'
    border_radius: str = '0.375rem'
    max_width: str = '100%'
    tab_size: int = 4
    overflow_x: str = 'auto'
    trusted_css: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, 'trusted_css', MappingProxyType(dict(self.trusted_css)))


@dataclass(frozen=True, slots=True)
class GutterStyle:
    min_width: str = '3ch'
    padding: Optional[str] = None
    separator: str = ''
    user_select: str = 'none'


@dataclass(frozen=True, slots=True)
class LineHighlightStyle:
    background: ColorValue = UNSET
    foreground: ColorValue = UNSET
    bold: FlagValue = UNSET
    italic: FlagValue = UNSET


@dataclass(frozen=True, slots=True)
class LineSelection:
    lines: frozenset[int] = frozenset()
    ranges: tuple[tuple[int, int], ...] = ()

    def __init__(
        self,
        lines: Iterable[int] = (),
        ranges: Iterable[tuple[int, int]] = (),
    ) -> None:
        line_values = tuple(lines)
        if any(type(line) is not int or line < 1 for line in line_values):
            raise SelectionError('selected line numbers must be positive integers')
        try:
            range_values = tuple(tuple(item) for item in ranges)
        except TypeError as error:
            raise SelectionError('line ranges must contain pairs of integers') from error
        object.__setattr__(self, 'lines', frozenset(line_values))
        object.__setattr__(self, 'ranges', range_values)
        self._validate_shape()

    def _validate_shape(self) -> None:
        for line in self.lines:
            if isinstance(line, bool) or not isinstance(line, int) or line < 1:
                raise SelectionError('selected line numbers must be positive integers')
        for item in self.ranges:
            if len(item) != 2:
                raise SelectionError('line ranges must contain exactly two endpoints')
            start, end = item
            if any(isinstance(value, bool) or not isinstance(value, int) for value in item):
                raise SelectionError('line range endpoints must be integers')
            if start < 1 or end < 1 or start > end:
                raise SelectionError('line ranges must be positive and inclusive')

    def resolve(self, line_count: int) -> frozenset[int]:
        if any(line > line_count for line in self.lines) or any(
            end > line_count for _, end in self.ranges
        ):
            raise SelectionError(f'selected lines are outside the source (1..{line_count})')
        resolved = set(self.lines)
        for start, end in self.ranges:
            resolved.update(range(start, end + 1))
        return frozenset(resolved)


@dataclass(frozen=True, slots=True)
class LineOptions:
    numbers: bool = False
    number_start: int = 1
    emphasize: LineSelection = LineSelection()
    gutter: GutterStyle = GutterStyle()
    highlight: LineHighlightStyle = LineHighlightStyle()
    hide_final_empty_line: bool = False

    def __post_init__(self) -> None:
        if type(self.number_start) is not int or self.number_start < 1:
            raise SelectionError('number_start must be a positive integer')


@dataclass(frozen=True, slots=True)
class TokenSpan:
    start: int
    end: int
    scopes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TokenizedCode:
    source: str
    language: str
    root_scope: str
    spans: tuple[TokenSpan, ...]


@dataclass(frozen=True, slots=True)
class ResourceLimits:
    max_input_chars: int = 1_000_000
    max_line_chars: int = 100_000
    max_nesting: int = 256
    max_spans: int = 1_000_000
    max_dynamic_patterns: int = 512
    timeout_seconds: float | None = 5.0
    max_grammar_rules: int = 100_000
    max_pattern_chars: int = 100_000

    def __post_init__(self) -> None:
        integer_fields = (
            self.max_input_chars,
            self.max_line_chars,
            self.max_nesting,
            self.max_spans,
            self.max_dynamic_patterns,
            self.max_grammar_rules,
            self.max_pattern_chars,
        )
        if any(type(value) is not int or value < 1 for value in integer_fields):
            raise ValueError('resource limit values must be positive integers')
        timeout = self.timeout_seconds
        if timeout is not None and (
            type(timeout) not in (int, float) or not isfinite(timeout) or timeout <= 0
        ):
            raise ValueError('timeout_seconds must be finite, positive, or None')
