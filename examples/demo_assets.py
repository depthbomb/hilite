from collections.abc import Mapping
from hilite import Style, Theme, ThemeRule, GrammarRegistry

PYTHON_GRAMMAR = {
    'scopeName': 'source.python.demo',
    'patterns': [
        {'include': '#comments'},
        {'include': '#strings'},
        {
            'match': r'\b(class|def)\s+([A-Za-z_]\w*)',
            'captures': {
                '1': {'name': 'storage.type.python'},
                '2': {'name': 'entity.name.function.python'},
            },
        },
        {
            'match': (
                r'\b(and|as|assert|async|await|break|case|class|continue|def|del|elif|else|'
                r'except|finally|for|from|global|if|import|in|is|lambda|match|nonlocal|not|or|'
                r'pass|raise|return|try|while|with|yield)\b'
            ),
            'name': 'keyword.control.python',
        },
        {'match': r'\b(True|False|None)\b', 'name': 'constant.language.python'},
        {'match': r'\b\d+(?:\.\d+)?\b', 'name': 'constant.numeric.python'},
        {
            'match': r'\b(print|len|range|str|int|list|dict|set|tuple)\b',
            'name': 'support.function.builtin.python',
        },
        {'match': r'@[A-Za-z_]\w*', 'name': 'entity.name.function.decorator.python'},
    ],
    'repository': {
        'comments': {
            'begin': '#',
            'end': '$',
            'name': 'comment.line.number-sign.python',
            'beginCaptures': {'0': {'name': 'punctuation.definition.comment.python'}},
        },
        'strings': {
            'patterns': [
                {
                    'begin': r'(?i)([rubf]{0,2})(""")',
                    'end': r'"""',
                    'name': 'string.quoted.multi.python',
                    'patterns': [{'match': r'\\.', 'name': 'constant.character.escape.python'}],
                },
                {
                    'begin': r'(?i)([rubf]{0,2})(\'\'\')',
                    'end': r'\'\'\'',
                    'name': 'string.quoted.multi.python',
                    'patterns': [{'match': r'\\.', 'name': 'constant.character.escape.python'}],
                },
                {
                    'begin': r'(?i)([rubf]{0,2})(")',
                    'end': '"',
                    'name': 'string.quoted.double.python',
                    'patterns': [{'match': r'\\.', 'name': 'constant.character.escape.python'}],
                },
                {
                    'begin': r"(?i)([rubf]{0,2})(')",
                    'end': "'",
                    'name': 'string.quoted.single.python',
                    'patterns': [{'match': r'\\.', 'name': 'constant.character.escape.python'}],
                },
            ]
        },
    },
}

JAVASCRIPT_GRAMMAR = {
    'scopeName': 'source.js.demo',
    'patterns': [
        {'begin': r'/\*', 'end': r'\*/', 'name': 'comment.block.js'},
        {'begin': r'//', 'end': '$', 'name': 'comment.line.double-slash.js'},
        {
            'begin': '`',
            'end': '`',
            'name': 'string.template.js',
            'patterns': [
                {'begin': r'\$\{', 'end': r'\}', 'name': 'meta.interpolation.js'},
                {'match': r'\\.', 'name': 'constant.character.escape.js'},
            ],
        },
        {
            'begin': '"',
            'end': '"',
            'name': 'string.quoted.double.js',
            'patterns': [{'match': r'\\.', 'name': 'constant.character.escape.js'}],
        },
        {
            'begin': "'",
            'end': "'",
            'name': 'string.quoted.single.js',
            'patterns': [{'match': r'\\.', 'name': 'constant.character.escape.js'}],
        },
        {
            'match': (
                r'\b(async|await|break|case|catch|class|const|continue|default|delete|do|else|'
                r'export|extends|finally|for|from|function|if|import|in|instanceof|let|new|of|'
                r'return|static|switch|throw|try|typeof|var|void|while|yield)\b'
            ),
            'name': 'keyword.control.js',
        },
        {'match': r'\b(true|false|null|undefined)\b', 'name': 'constant.language.js'},
        {'match': r'\b\d+(?:\.\d+)?\b', 'name': 'constant.numeric.js'},
        {'match': r'\b([A-Za-z_$][\w$]*)(?=\s*\()', 'name': 'entity.name.function.js'},
    ],
}

HTML_GRAMMAR = {
    'scopeName': 'text.html.demo',
    'patterns': [
        {'begin': r'<!--', 'end': r'-->', 'name': 'comment.block.html'},
        {
            'begin': r'(?i)(<)(script)(?=[\s>])',
            'end': r'(?i)(</)(script)(\s*>)',
            'name': 'meta.tag.script.html',
            'contentName': 'source.js.embedded.html',
            'patterns': [{'include': 'source.js.demo'}],
        },
        {
            'begin': r'(?i)(</?)([A-Za-z][\w:-]*)',
            'end': r'(/?>)',
            'name': 'meta.tag.html',
            'beginCaptures': {
                '1': {'name': 'punctuation.definition.tag.begin.html'},
                '2': {'name': 'entity.name.tag.html'},
            },
            'endCaptures': {'1': {'name': 'punctuation.definition.tag.end.html'}},
            'patterns': [
                {
                    'match': r'[A-Za-z_:][\w:.-]*(?=\s*=)',
                    'name': 'entity.other.attribute-name.html',
                },
                {'begin': '"', 'end': '"', 'name': 'string.quoted.double.html'},
                {'begin': "'", 'end': "'", 'name': 'string.quoted.single.html'},
            ],
        },
        {'match': r'&(?:[A-Za-z]+|#\d+|#x[0-9A-Fa-f]+);', 'name': 'constant.character.entity.html'},
    ],
}

JSON_GRAMMAR = {
    'scopeName': 'source.json.demo',
    'patterns': [
        {
            'match': r'"(?:[^"\\]|\\.)*"(?=\s*:)',
            'name': 'support.type.property-name.json',
        },
        {
            'begin': '"',
            'end': '"',
            'name': 'string.quoted.double.json',
            'patterns': [
                {
                    'match': r'\\(?:["\\/bfnrt]|u[0-9A-Fa-f]{4})',
                    'name': 'constant.character.escape.json',
                }
            ],
        },
        {'match': r'\b(true|false|null)\b', 'name': 'constant.language.json'},
        {'match': r'-?\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b', 'name': 'constant.numeric.json'},
        {'match': r'[{}\[\],:]', 'name': 'punctuation.separator.json'},
    ],
}

SHELL_GRAMMAR = {
    'scopeName': 'source.shell.demo',
    'patterns': [
        {'begin': '#', 'end': '$', 'name': 'comment.line.number-sign.shell'},
        {
            'begin': '"',
            'end': '"',
            'name': 'string.quoted.double.shell',
            'patterns': [
                {'match': r'\$[A-Za-z_][A-Za-z0-9_]*|\$\{[^}]+\}', 'name': 'variable.other.shell'},
                {'match': r'\\.', 'name': 'constant.character.escape.shell'},
            ],
        },
        {'begin': "'", 'end': "'", 'name': 'string.quoted.single.shell'},
        {'match': r'\$[A-Za-z_][A-Za-z0-9_]*|\$\{[^}]+\}', 'name': 'variable.other.shell'},
        {
            'match': (
                r'\b(case|do|done|elif|else|esac|fi|for|function|if|in|select|then|'
                r'time|until|while)\b'
            ),
            'name': 'keyword.control.shell',
        },
        {
            'match': r'\b(cd|echo|exit|export|printf|read|set|shift|source|test|unset)\b',
            'name': 'support.function.builtin.shell',
        },
        {'match': r'--?[A-Za-z][A-Za-z0-9-]*', 'name': 'variable.parameter.option.shell'},
    ],
}

DEMO_GRAMMARS: Mapping[str, Mapping[str, object]] = {
    'python': PYTHON_GRAMMAR,
    'javascript': JAVASCRIPT_GRAMMAR,
    'html': HTML_GRAMMAR,
    'json': JSON_GRAMMAR,
    'shell': SHELL_GRAMMAR,
}

DARK_THEME_DATA = {
    'colors': {
        'editor.foreground': '#d8dee9',
        'editor.background': '#242933',
        'editorLineNumber.foreground': '#667085',
        'editorLineNumber.background': '#1f232b',
        'editor.lineHighlightBackground': '#343b49',
    },
    'tokenColors': [
        {'scope': 'comment', 'settings': {'foreground': '#738091', 'fontStyle': 'italic'}},
        {'scope': 'string', 'settings': {'foreground': '#a3be8c'}},
        {'scope': 'constant.character.escape', 'settings': {'foreground': '#ebcb8b'}},
        {'scope': 'keyword', 'settings': {'foreground': '#b48ead', 'fontStyle': 'bold'}},
        {'scope': 'storage.type', 'settings': {'foreground': '#81a1c1', 'fontStyle': 'bold'}},
        {'scope': 'constant', 'settings': {'foreground': '#d08770'}},
        {'scope': 'entity.name.function', 'settings': {'foreground': '#88c0d0'}},
        {'scope': 'entity.name.tag', 'settings': {'foreground': '#bf616a'}},
        {'scope': 'entity.other.attribute-name', 'settings': {'foreground': '#d08770'}},
        {'scope': 'support', 'settings': {'foreground': '#8fbcbb'}},
        {'scope': 'variable', 'settings': {'foreground': '#ebcb8b'}},
        {'scope': 'punctuation', 'settings': {'foreground': '#7f8c9f'}},
    ],
}

LIGHT_THEME = Theme(
    foreground='#24292f',
    background='#f6f8fa',
    gutter_foreground='#8c959f',
    gutter_background='#eef1f4',
    selection_background='#fff1a8',
    rules=(
        ThemeRule('comment', Style(foreground='#6e7781', italic=True)),
        ThemeRule('string', Style(foreground='#0a7f3f')),
        ThemeRule('constant.character.escape', Style(foreground='#9a6700')),
        ThemeRule('keyword', Style(foreground='#cf222e', bold=True)),
        ThemeRule('storage.type', Style(foreground='#8250df', bold=True)),
        ThemeRule('constant', Style(foreground='#0550ae')),
        ThemeRule('entity.name.function', Style(foreground='#8250df')),
        ThemeRule('entity.name.tag', Style(foreground='#116329')),
        ThemeRule('entity.other.attribute-name', Style(foreground='#953800')),
        ThemeRule('support', Style(foreground='#0550ae')),
        ThemeRule('variable', Style(foreground='#953800')),
        ThemeRule('punctuation', Style(foreground='#57606a')),
    ),
)

CUSTOM_THEME = Theme(
    foreground='#f8f4e3',
    background='#17131f',
    gutter_foreground='#746985',
    gutter_background='#211a2c',
    selection_background='#3d3151',
    rules=(
        ThemeRule('comment', Style(foreground='#8d809f', italic=True)),
        ThemeRule('string', Style(foreground='#b8e994')),
        ThemeRule('constant.character.escape', Style(foreground='#ffd166', bold=True)),
        ThemeRule('keyword', Style(foreground='#ff6b9d', bold=True)),
        ThemeRule('storage.type', Style(foreground='#c792ea')),
        ThemeRule('constant', Style(foreground='#ffbf69')),
        ThemeRule('entity.name.function', Style(foreground='#73d2de')),
        ThemeRule('entity.name.tag', Style(foreground='#ff758f')),
        ThemeRule('entity.other.attribute-name', Style(foreground='#ffd166')),
        ThemeRule('support', Style(foreground='#62d6e8')),
        ThemeRule('variable', Style(foreground='#ffd166')),
        ThemeRule('punctuation', Style(foreground='#9f93b1')),
    ),
)


def demo_registry() -> GrammarRegistry:
    registry = GrammarRegistry()
    for language, grammar in DEMO_GRAMMARS.items():
        aliases = ('js',) if language == 'javascript' else ()
        registry.register_dict(grammar, language=language, aliases=aliases)
    return registry


def dark_theme() -> Theme:
    return Theme.from_dict(DARK_THEME_DATA)


def html_page(title: str, sections: list[tuple[str, str]]) -> str:
    rendered_sections = ''.join(
        f'<section><h2>{heading}</h2>{fragment}</section>' for heading, fragment in sections
    )
    return (
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        f'<title>{title}</title>'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<body style="max-width:72rem;margin:2rem auto;padding:0 1rem;'
        'font-family:system-ui,sans-serif;background:#11151c;color:#edf2f7">'
        f'<h1>{title}</h1>{rendered_sections}</body></html>'
    )
