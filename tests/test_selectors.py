import pytest
from hilite.grammar import injection_selector_matches
from hilite import Style, Theme, ThemeRule, ThemeError, GrammarError
from hilite.theme import resolve_style, validate_selector, selector_specificity


@pytest.mark.parametrize(
    'selector,scopes,matched',
    [
        ('source.python string', ('source.python', 'meta.function', 'string.quoted'), True),
        ('source.python > string', ('source.python', 'meta.function', 'string.quoted'), False),
        ('source.python > string', ('source.python', 'string.quoted'), True),
        ('source > meta string', ('source', 'meta', 'other', 'meta', 'string'), True),
        ('string - string.regexp', ('source.js', 'string.quoted'), True),
        ('string - string.regexp', ('source.js', 'string.regexp'), False),
        ('(string | comment) - (comment.block | string.regexp)', ('comment.line',), True),
        ('(string | comment) - (comment.block | string.regexp)', ('comment.block',), False),
        ('(string, comment) & source.python', ('source.python', 'comment.line'), True),
        ('(string, comment) & source.python', ('source.js', 'comment.line'), False),
        ('-comment', ('source.python', 'string'), True),
        ('-comment', ('source.python', 'comment.line'), False),
        ('--comment', ('comment.line',), True),
        ('source.* string', ('source.python', 'string.quoted'), True),
        ('source.* string', ('source', 'string.quoted'), False),
        ('*', ('source.python', 'string.quoted'), True),
        ('source.python | source.js', ('source.js',), True),
        ('source.python, source.js', ('source.js',), True),
        ('source.python > meta > string', ('source.python', 'meta.function', 'string'), True),
        ('source.python > meta > string', ('source.python', 'meta', 'other', 'string'), False),
        ('entity.other.attribute-name', ('entity.other.attribute-name.html',), True),
    ],
)
def test_selector_expressions(selector, scopes, matched):
    assert (selector_specificity(selector, scopes) is not None) is matched


@pytest.mark.parametrize(
    'selector',
    [
        '',
        ' source',
        'source ',
        '()',
        '(source',
        'source)',
        'source |',
        '| source',
        'source,',
        ',source',
        'source,,string',
        'source -',
        'source >',
        '> source',
        'source &',
        'source && string',
        'source @ string',
        'source..python',
        'source.*word',
        'L:source',
        'source - ()',
        'source > (string | comment)',
    ],
)
def test_malformed_selectors_are_rejected(selector):
    with pytest.raises(ThemeError):
        validate_selector(selector)


def test_selector_resource_bounds():
    for selector in ('(' * 65 + 'source' + ')' * 65, 'a' * 8193, 'a ' * 1024 + 'b'):
        with pytest.raises(ThemeError):
            validate_selector(selector)


def test_imported_grouped_comma_is_not_split():
    theme = Theme.from_dict(
        {
            'tokenColors': [
                {
                    'scope': '(string, comment) - comment.block',
                    'settings': {'foreground': '#123456'},
                },
            ]
        }
    )
    assert resolve_style(('comment.line',), theme).foreground == '#123456'
    assert resolve_style(('comment.block',), theme).foreground == '#000000'


def test_theme_specificity_uses_the_matching_alternative():
    theme = Theme(
        rules=(
            ThemeRule('string.quoted | comment', Style(foreground='#111111')),
            ThemeRule('string', Style(foreground='#222222')),
            ThemeRule('comment.line', Style(foreground='#333333')),
        )
    )
    assert resolve_style(('source', 'string.quoted'), theme).foreground == '#111111'
    assert resolve_style(('source', 'comment.line'), theme).foreground == '#333333'


def test_exclusions_do_not_increase_specificity():
    theme = Theme(
        rules=(
            ThemeRule('string.quoted', Style(foreground='#111111')),
            ThemeRule('string - comment.very.deep', Style(foreground='#222222')),
        )
    )
    assert resolve_style(('source', 'string.quoted'), theme).foreground == '#111111'


def test_parent_specificity_and_declaration_order():
    theme = Theme(
        rules=(
            ThemeRule('source.python string', Style(foreground='#111111')),
            ThemeRule('source string', Style(foreground='#222222')),
            ThemeRule('source.python string', Style(italic=True)),
        )
    )
    style = resolve_style(('source.python', 'string.quoted'), theme)
    assert style.foreground == '#111111'
    assert style.italic is True


def test_override_layer_accepts_selector_expressions():
    theme = Theme(rules=(ThemeRule('string.quoted', Style(foreground='#111111')),))
    override = ThemeRule('(string | comment) - string.regexp', Style(foreground='#222222'))
    assert resolve_style(('string.quoted',), theme, (override,)).foreground == '#222222'


def test_injection_priorities_apply_to_top_level_branches():
    selector = 'R:source.python, L:(source.js | text.html) - comment'
    assert injection_selector_matches(selector, ('source.python',)) == (True, False)
    assert injection_selector_matches(selector, ('source.js',)) == (True, True)
    assert injection_selector_matches(selector, ('source.js', 'comment')) == (False, False)


@pytest.mark.parametrize('selector', ['L:', 'R:()', 'L:(source |)', 'R:source, L:'])
def test_invalid_injection_expression_is_a_grammar_error(selector):
    with pytest.raises(GrammarError, match='selector'):
        injection_selector_matches(selector, ('source',))
