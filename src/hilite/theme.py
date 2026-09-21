import re
import plistlib
from os import PathLike
from pathlib import Path
from typing import Any, Optional
from hilite._json import loads_jsonc
from hilite.errors import ThemeError
from xml.parsers.expat import ExpatError
from collections.abc import Mapping, Sequence
from hilite._selectors import parse_selector, selector_score
from hilite.models import Style, Theme, UNSET, DEFAULT, ThemeRule, UnsetType

_COLOR = re.compile(r'^(?:#[0-9a-fA-F]{3,4}|#[0-9a-fA-F]{6}|#[0-9a-fA-F]{8}|transparent)$')


def validate_color(value: object, field: str = 'color') -> str:
    if not isinstance(value, str) or not _COLOR.fullmatch(value):
        raise ThemeError(
            f'{field} must be a hexadecimal RGB/RGBA color or transparent, got {value!r}'
        )
    return value


def _read_data(path: str | PathLike[str]) -> Mapping[str, object]:
    file_path = Path(path)
    try:
        if file_path.suffix.lower() in {'.plist', '.tmlanguage', '.tmtheme'}:
            with file_path.open('rb') as stream:
                data = plistlib.load(stream)
        else:
            with file_path.open(encoding='utf-8-sig') as stream:
                data = loads_jsonc(stream.read())
    except (OSError, ValueError, ExpatError, plistlib.InvalidFileException) as error:
        raise ThemeError(f'could not load theme {file_path}: {error}') from error
    if not isinstance(data, Mapping):
        raise ThemeError(f'theme {file_path} must contain an object at its root')
    return data


def _font_style(value: object) -> dict[str, bool | UnsetType]:
    if value is None:
        return {}
    if not isinstance(value, str):
        raise ThemeError('fontStyle must be a whitespace-separated string')
    words = set(value.split())
    supported = {'bold', 'italic', 'underline', 'strikethrough'}
    unsupported = sorted(words - supported)
    if unsupported:
        raise ThemeError(f'unsupported fontStyle values: {", ".join(unsupported)}')
    return {name: name in words for name in supported}


def _style_from_settings(settings: Mapping[str, object]) -> Style:
    unsupported = {'fontFamily', 'fontSize', 'lineHeight'} & settings.keys()
    if unsupported:
        raise ThemeError(f'unsupported per-token typography: {sorted(unsupported)}')
    foreground = settings.get('foreground', UNSET)
    background = settings.get('background', UNSET)
    if not isinstance(foreground, (str, UnsetType)):
        raise ThemeError('foreground must be a color string')
    if not isinstance(background, (str, UnsetType)):
        raise ThemeError('background must be a color string')
    if isinstance(foreground, str):
        validate_color(foreground, 'foreground')
    if isinstance(background, str):
        validate_color(background, 'background')
    return Style(
        foreground=foreground,
        background=background,
        **_font_style(settings.get('fontStyle')),
    )


def _scope_selectors(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        selectors = (value.strip(),) if value.strip() else ()
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        if not all(isinstance(part, str) for part in value):
            raise ThemeError('theme rule scopes must contain strings')
        selectors = tuple(part.strip() for part in value if part.strip())
    elif value is None:
        selectors = ()
    else:
        raise ThemeError('theme rule scope must be a string or sequence of strings')
    for selector in selectors:
        validate_selector(selector)
    return selectors


def theme_from_dict(data: Mapping[str, object]) -> Theme:
    if 'include' in data:
        raise ThemeError('theme includes are unsupported; merge the included theme before loading')
    foreground = '#000000'
    background = '#ffffff'
    gutter_foreground = '#6e7781'
    gutter_background: str | UnsetType = UNSET
    selection_background = '#fff3bf'
    default_style = Style()
    rules: list[ThemeRule] = []

    colors = data.get('colors', {})
    if colors is not None and not isinstance(colors, Mapping):
        raise ThemeError('theme colors must be an object')
    if isinstance(colors, Mapping):
        color_values = {
            'editor.foreground': ('foreground', foreground),
            'editor.background': ('background', background),
            'editorLineNumber.foreground': ('gutter_foreground', gutter_foreground),
            'editorLineNumber.background': ('gutter_background', gutter_background),
            'editor.lineHighlightBackground': ('selection_background', selection_background),
        }
        resolved = {}
        for key, (name, fallback) in color_values.items():
            value = colors.get(key, fallback)
            if not isinstance(value, (str, UnsetType)):
                raise ThemeError(f'{key} must be a color string')
            if isinstance(value, str):
                validate_color(value, key)
            resolved[name] = value
        foreground = validate_color(resolved['foreground'], 'editor.foreground')
        background = validate_color(resolved['background'], 'editor.background')
        gutter_foreground = validate_color(
            resolved['gutter_foreground'], 'editorLineNumber.foreground'
        )
        gutter_background = resolved['gutter_background']
        selection_background = validate_color(
            resolved['selection_background'], 'editor.lineHighlightBackground'
        )

    source_rules = data.get('tokenColors', data.get('settings', ()))
    if not isinstance(source_rules, Sequence) or isinstance(source_rules, (str, bytes)):
        raise ThemeError('tokenColors/settings must be a sequence')
    for entry in source_rules:
        if not isinstance(entry, Mapping):
            raise ThemeError('each theme rule must be an object')
        settings = entry.get('settings', {})
        if not isinstance(settings, Mapping):
            raise ThemeError('theme rule settings must be an object')
        style = _style_from_settings(settings)
        selectors = _scope_selectors(entry.get('scope'))
        if not selectors:
            default_style = default_style.overlay(style)
            if isinstance(style.foreground, str):
                foreground = style.foreground
            if isinstance(style.background, str):
                background = style.background
            continue
        rules.extend(ThemeRule(selector, style) for selector in selectors)

    return Theme(
        foreground=foreground,
        background=background,
        rules=tuple(rules),
        gutter_foreground=gutter_foreground,
        gutter_background=gutter_background,
        selection_background=selection_background,
        default_style=default_style,
    )


def load_theme(path: str | PathLike[str]) -> Theme:
    return theme_from_dict(_read_data(path))


def validate_selector(selector: str) -> None:
    parse_selector(selector)


def selector_specificity(selector: str, scopes: tuple[str, ...]) -> Optional[tuple[int, ...]]:
    return selector_score(selector, scopes)


def _resolve_layer(scopes: tuple[str, ...], rules: Sequence[ThemeRule]) -> Style:
    matches = []
    for index, rule in enumerate(rules):
        validate_selector(rule.selector)
        specificity = selector_specificity(rule.selector, scopes)
        if specificity is not None:
            matches.append((specificity, index, rule.style))
    matches.sort(key=lambda item: (item[0], item[1]))
    style = Style()
    for _, _, matched_style in matches:
        style = style.overlay(matched_style)
    return style


def resolve_style(
    scopes: tuple[str, ...],
    theme: Theme,
    overrides: Sequence[ThemeRule] = (),
) -> Style:
    validate_color(theme.foreground, 'theme foreground')
    validate_color(theme.background, 'theme background')
    base = theme.default_style.overlay(Style(foreground=theme.foreground, background=DEFAULT))
    themed = base.overlay(_resolve_layer(scopes, theme.rules))
    # User overrides win even when a theme selector is more specific.
    result = themed.overlay(_resolve_layer(scopes, overrides))
    if result.foreground is DEFAULT:
        result = result.overlay(Style(foreground=theme.foreground))
    return result


def style_key(style: Style) -> tuple[Any, ...]:
    return (
        style.foreground,
        style.background,
        style.bold,
        style.italic,
        style.underline,
        style.strikethrough,
    )


def style_to_css(style: Style) -> tuple[tuple[str, str], ...]:
    properties = []
    if isinstance(style.foreground, str):
        properties.append(('color', validate_color(style.foreground, 'foreground')))
    if isinstance(style.background, str):
        properties.append(('background-color', validate_color(style.background, 'background')))
    if style.bold is True:
        properties.append(('font-weight', 'bold'))
    elif style.bold is False:
        properties.append(('font-weight', 'normal'))
    if style.italic is True:
        properties.append(('font-style', 'italic'))
    elif style.italic is False:
        properties.append(('font-style', 'normal'))
    decorations = []
    if style.underline is True:
        decorations.append('underline')
    if style.strikethrough is True:
        decorations.append('line-through')
    if decorations:
        properties.append(('text-decoration', ' '.join(decorations)))
    elif style.underline is False or style.strikethrough is False:
        properties.append(('text-decoration', 'none'))
    return tuple(properties)
