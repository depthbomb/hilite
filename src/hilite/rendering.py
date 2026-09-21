import re
import html
from typing import Optional
from bisect import bisect_right
from dataclasses import dataclass
from collections.abc import Sequence
from hilite.errors import ThemeError, HtmlRenderingError
from hilite.theme import style_to_css, resolve_style, validate_color, validate_selector
from hilite.models import (
    Style,
    Theme,
    UNSET,
    DEFAULT,
    ThemeRule,
    HtmlLayout,
    LineOptions,
    TokenizedCode,
)

_CSS_NAME = re.compile(r'^--?[a-zA-Z][a-zA-Z0-9-]*$|^[a-zA-Z][a-zA-Z0-9-]*$')
_UNSAFE_CSS_VALUE = re.compile(r'[;{}<>\r\n]')
_INVALID_HTML_TEXT = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff]')


@dataclass(frozen=True, slots=True)
class _Run:
    start: int
    end: int
    style: Style


@dataclass(frozen=True, slots=True)
class _Line:
    start: int
    content_end: int
    end: int


def _validate_css_value(value: str, field: str) -> str:
    if not value or _UNSAFE_CSS_VALUE.search(value):
        raise ThemeError(f'{field} contains an unsafe CSS value')
    return value


def _css(properties: Sequence[tuple[str, str]]) -> str:
    return ';'.join(f'{name}:{value}' for name, value in properties)


def _attribute(name: str, value: str) -> str:
    return f' {name}="{html.escape(value, quote=True)}"'


def _layout_css(layout: HtmlLayout, theme: Theme) -> tuple[tuple[str, str], ...]:
    if type(layout.tab_size) is not int or layout.tab_size < 1:
        raise ThemeError('tab_size must be a positive integer')
    properties = [
        ('box-sizing', 'border-box'),
        ('margin', _validate_css_value(layout.margin, 'margin')),
        ('max-width', _validate_css_value(layout.max_width, 'max_width')),
        ('background-color', validate_color(theme.background, 'theme background')),
        ('border', _validate_css_value(layout.border, 'border')),
        ('border-radius', _validate_css_value(layout.border_radius, 'border_radius')),
        ('overflow-x', _validate_css_value(layout.overflow_x, 'overflow_x')),
    ]
    for name, value in layout.trusted_css.items():
        if not _CSS_NAME.fullmatch(name):
            raise ThemeError(f'invalid CSS property name: {name!r}')
        properties.append((name, value))
    return tuple(properties)


def _code_css(layout: HtmlLayout, theme: Theme, numbered: bool) -> tuple[tuple[str, str], ...]:
    padding = layout.padding
    properties = [
        ('box-sizing', 'border-box'),
        ('margin', '0'),
        ('min-width', '0'),
        ('padding', _validate_css_value(padding, 'padding')),
        ('color', validate_color(theme.foreground, 'theme foreground')),
        ('font-family', _validate_css_value(layout.font_family, 'font_family')),
        ('font-size', _validate_css_value(layout.font_size, 'font_size')),
        ('line-height', _validate_css_value(layout.line_height, 'line_height')),
        ('tab-size', str(layout.tab_size)),
        ('white-space', 'pre'),
    ]
    if numbered:
        properties.extend((('flex', '1 1 auto'), ('overflow', 'visible')))
    else:
        properties.append(('overflow-x', 'auto'))
    return tuple(properties)


def _gutter_css(
    layout: HtmlLayout,
    options: LineOptions,
    theme: Theme,
) -> tuple[tuple[str, str], ...]:
    gutter = options.gutter
    background = theme.background
    if isinstance(theme.gutter_background, str):
        background = theme.gutter_background
    return (
        ('box-sizing', 'border-box'),
        ('flex', '0 0 auto'),
        ('margin', '0'),
        ('min-width', _validate_css_value(gutter.min_width, 'gutter min_width')),
        ('padding', _validate_css_value(gutter.padding or layout.padding, 'gutter padding')),
        ('color', validate_color(theme.gutter_foreground, 'gutter foreground')),
        ('background-color', validate_color(background, 'gutter background')),
        ('font-family', _validate_css_value(layout.font_family, 'font_family')),
        ('font-size', _validate_css_value(layout.font_size, 'font_size')),
        ('line-height', _validate_css_value(layout.line_height, 'line_height')),
        ('text-align', 'right'),
        ('user-select', _validate_css_value(gutter.user_select, 'gutter user_select')),
        ('white-space', 'pre'),
    )


def _styled_runs(
    tokenized: TokenizedCode,
    theme: Theme,
    overrides: Sequence[ThemeRule],
) -> tuple[_Run, ...]:
    style_cache: dict[tuple[str, ...], Style] = {}
    runs: list[_Run] = []
    previous_end = 0
    for span in tokenized.spans:
        if not 0 <= previous_end <= span.start < span.end <= len(tokenized.source):
            raise HtmlRenderingError('token spans must be ordered, nonoverlapping source ranges')
        previous_end = span.end
        try:
            style = style_cache[span.scopes]
        except KeyError:
            style = resolve_style(span.scopes, theme, overrides)
            style_cache[span.scopes] = style
        if runs and runs[-1].end == span.start and runs[-1].style == style:
            previous = runs[-1]
            runs[-1] = _Run(previous.start, span.end, style)
        else:
            runs.append(_Run(span.start, span.end, style))
    return tuple(runs)


def _escaped_source(source: str, start: int, end: int) -> str:
    # A CRLF pair can cross a token boundary. Emit its newline with the CR only.
    if start and source[start - 1 : start + 1] == '\r\n':
        start += 1
    value = source[start:end]
    return html.escape(value.replace('\r\n', '\n').replace('\r', '\n'), quote=False)


def _render_range(
    source: str,
    runs: tuple[_Run, ...],
    start: int,
    end: int,
    token_override: Style | None = None,
    *,
    run_ends: tuple[int, ...] = (),
    css_cache: Optional[dict[tuple[int, int], str]] = None,
    theme_foreground: str = '#000000',
) -> str:
    fragments = []
    cursor = start
    # Jump to this line's runs instead of rescanning the whole document for each line.
    first = bisect_right(run_ends, start) if run_ends else 0
    if css_cache is None:
        css_cache = {}
    for index in range(first, len(runs)):
        run = runs[index]
        if run.start >= end:
            break
        run_start = max(start, run.start)
        run_end = min(end, run.end)
        if cursor < run_start:
            fragments.append(_escaped_source(source, cursor, run_start))
        # Runs and the line override stay alive for this render, so their ids are safe keys.
        key = (id(run.style), id(token_override))
        attribute = css_cache.get(key)
        if attribute is None:
            style = run.style.overlay(token_override) if token_override is not None else run.style
            if style.foreground is DEFAULT:
                style = style.overlay(Style(foreground=theme_foreground))
            css = _css(style_to_css(style))
            attribute = _attribute('style', css) if css else ''
            css_cache[key] = attribute
        escaped = _escaped_source(source, run_start, run_end)
        if attribute:
            fragments.append(f'<span{attribute}>{escaped}</span>')
        else:
            fragments.append(escaped)
        cursor = run_end
    if cursor < end:
        fragments.append(_escaped_source(source, cursor, end))
    return ''.join(fragments)


def _lines(source: str) -> tuple[_Line, ...]:
    result = []
    start = 0
    for match in re.finditer(r'\r\n|\r|\n', source):
        result.append(_Line(start, match.start(), match.end()))
        start = match.end()
    result.append(_Line(start, len(source), len(source)))
    return tuple(result)


def _line_override(options: LineOptions) -> Style:
    highlight = options.highlight
    return Style(
        # Let the line's background show through any token backgrounds.
        background=DEFAULT,
        foreground=highlight.foreground,
        bold=highlight.bold,
        italic=highlight.italic,
    )


def _line_background(options: LineOptions, theme: Theme) -> str | None:
    background = options.highlight.background
    if background is UNSET:
        return validate_color(theme.selection_background, 'selection background')
    if background is DEFAULT:
        return None
    if not isinstance(background, str):
        raise ThemeError('line highlight background must be a color, DEFAULT, or UNSET')
    return validate_color(background, 'line highlight background')


def _render_code(
    tokenized: TokenizedCode,
    runs: tuple[_Run, ...],
    options: LineOptions,
    theme: Theme,
) -> tuple[str, int]:
    source_lines = _lines(tokenized.source)
    selected = options.emphasize.resolve(len(source_lines))
    displayed = source_lines
    if (
        options.hide_final_empty_line
        and len(source_lines) > 1
        and source_lines[-1].start == len(tokenized.source)
    ):
        displayed = source_lines[:-1]
    if not selected:
        hidden_final_line = len(displayed) != len(source_lines)
        if displayed:
            end = displayed[-1].content_end if hidden_final_line else displayed[-1].end
        else:
            end = 0
        return _render_range(tokenized.source, runs, 0, end), len(displayed)
    fragments = []
    token_override = _line_override(options)
    background = _line_background(options, theme)
    run_ends = tuple(run.end for run in runs)
    css_cache: dict[tuple[int, int], str] = {}
    for index, line in enumerate(displayed, start=1):
        emphasized = index in selected
        css_properties = [
            ('display', 'inline-block'),
            ('min-width', '100%'),
            ('min-height', '1lh'),
            ('vertical-align', 'top'),
        ]
        if emphasized and background is not None:
            css_properties.append(('background-color', background))
        content = _render_range(
            tokenized.source,
            runs,
            line.start,
            line.content_end,
            token_override if emphasized else None,
            run_ends=run_ends,
            css_cache=css_cache,
            theme_foreground=theme.foreground,
        )
        fragments.append(
            f'<span data-line="{index}"{_attribute("style", _css(css_properties))}>{content}</span>'
        )
        if index < len(displayed):
            fragments.append('\n')
    return ''.join(fragments), len(displayed)


def render_html(
    tokenized: TokenizedCode,
    *,
    theme: Theme | None = None,
    overrides: Sequence[ThemeRule] = (),
    layout: HtmlLayout | None = None,
    lines: LineOptions | None = None,
) -> str:
    invalid_character = _INVALID_HTML_TEXT.search(tokenized.source)
    if invalid_character is not None:
        raise HtmlRenderingError(
            f'source contains an HTML-incompatible control character at offset '
            f'{invalid_character.start()}'
        )
    selected_theme = theme or Theme()
    for rule in (*selected_theme.rules, *overrides):
        validate_selector(rule.selector)
    selected_layout = layout or HtmlLayout()
    line_options = lines or LineOptions()
    runs = _styled_runs(tokenized, selected_theme, tuple(overrides))
    code, displayed_line_count = _render_code(tokenized, runs, line_options, selected_theme)
    container_css = list(_layout_css(selected_layout, selected_theme))
    if line_options.numbers:
        container_css.extend((('display', 'flex'), ('align-items', 'stretch')))
    code_css = _css(_code_css(selected_layout, selected_theme, line_options.numbers))
    code_element = (
        f'<pre data-hilite-code-container{_attribute("style", code_css)}>'
        f'<code data-hilite-code style="font:inherit;display:block;'
        f'min-height:{displayed_line_count}lh">{code}</code></pre>'
    )
    children = code_element
    if line_options.numbers:
        gutter_lines = []
        for offset in range(displayed_line_count):
            number = line_options.number_start + offset
            gutter_lines.append(f'{number}{line_options.gutter.separator}')
        gutter_text = html.escape('\n'.join(gutter_lines), quote=False)
        gutter_css = _css(_gutter_css(selected_layout, line_options, selected_theme))
        gutter = (
            f'<pre data-hilite-gutter aria-hidden="true"'
            f'{_attribute("style", gutter_css)}>{gutter_text}</pre>'
        )
        children = f'{gutter}{code_element}'
    return f'<div data-hilite{_attribute("style", _css(container_css))}>{children}</div>'
