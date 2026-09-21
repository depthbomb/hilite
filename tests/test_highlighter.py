import pytest
from html.parser import HTMLParser
from hilite import (
    Style,
    Theme,
    DEFAULT,
    Grammar,
    ThemeRule,
    TokenSpan,
    HtmlLayout,
    Highlighter,
    LineOptions,
    render_html,
    GrammarError,
    LineSelection,
    TokenizedCode,
    SelectionError,
    GrammarRegistry,
    LineHighlightStyle,
    UnsupportedPatternError,
)


class TextCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.code_depth = 0
        self.code_text = []
        self.gutter_text = []
        self.in_gutter = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == 'code' and 'data-hilite-code' in attributes:
            self.code_depth += 1
        if tag == 'pre' and 'data-hilite-gutter' in attributes:
            self.in_gutter = True

    def handle_endtag(self, tag: str) -> None:
        if tag == 'code' and self.code_depth:
            self.code_depth -= 1
        if tag == 'pre' and self.in_gutter:
            self.in_gutter = False

    def handle_data(self, data: str) -> None:
        if self.code_depth:
            self.code_text.append(data)
        if self.in_gutter:
            self.gutter_text.append(data)


@pytest.mark.parametrize('decorated', [False, True])
@pytest.mark.parametrize('gap', [False, True])
def test_rendering_crlf_across_style_boundaries(decorated, gap):
    tokenized = TokenizedCode(
        source='a\r\nb',
        language='test',
        root_scope='source.test',
        spans=(TokenSpan(0, 2, ('first',)), TokenSpan(3 if gap else 2, 4, ('second',))),
    )
    theme = Theme(rules=(ThemeRule('first', Style(foreground='#ff0000')),))
    options = LineOptions(emphasize=LineSelection(lines={1}) if decorated else LineSelection())
    collector = TextCollector()
    collector.feed(render_html(tokenized, theme=theme, lines=options))
    assert ''.join(collector.code_text) == 'a\nb'


@pytest.fixture
def registry() -> GrammarRegistry:
    result = GrammarRegistry()
    result.register_dict(
        {
            'scopeName': 'source.example',
            'patterns': [
                {'include': '#strings'},
                {'match': r'\b(if|else)\b', 'name': 'keyword.control.example'},
                {
                    'begin': r'(#)',
                    'end': r'$',
                    'name': 'comment.line.example',
                    'beginCaptures': {'1': {'name': 'punctuation.definition.comment'}},
                },
            ],
            'repository': {
                'strings': {
                    'begin': '"',
                    'end': '"',
                    'name': 'string.quoted.double.example',
                    'contentName': 'string.quoted.double.content.example',
                    'patterns': [{'match': r'\\.', 'name': 'constant.character.escape'}],
                }
            },
        },
        language='example',
        aliases=('ex',),
    )
    return result


def test_tokenizer_preserves_source_and_nested_scope_state(registry: GrammarRegistry) -> None:
    source = 'if "one\\n\ntwo" # note\nelse'
    tokenized = Highlighter(registry).tokenize(source, language='ex')

    assert ''.join(source[span.start : span.end] for span in tokenized.spans) == source
    assert any(span.scopes[-1] == 'keyword.control.example' for span in tokenized.spans)
    assert any('constant.character.escape' in span.scopes for span in tokenized.spans)
    second_line = source.index('two')
    assert any(
        span.start <= second_line < span.end
        and 'string.quoted.double.content.example' in span.scopes
        for span in tokenized.spans
    )


def test_capture_scopes_split_a_match(registry: GrammarRegistry) -> None:
    tokenized = Highlighter(registry).tokenize('# note', language='example')
    hash_span = next(span for span in tokenized.spans if span.start == 0 and span.end == 1)

    assert hash_span.scopes[-1] == 'punctuation.definition.comment'
    assert tokenized.spans[-1].scopes[-1] == 'comment.line.example'


def test_dynamic_end_backreference() -> None:
    registry = GrammarRegistry()
    registry.register_dict(
        {
            'scopeName': 'source.heredoc',
            'patterns': [
                {
                    'begin': r'<<(\w+)$',
                    'end': r'^\1$',
                    'name': 'string.heredoc',
                    'contentName': 'string.heredoc.content',
                }
            ],
        },
        language='heredoc',
    )

    tokenized = Highlighter(registry).tokenize('<<END\ninside\nEND\nafter', language='heredoc')
    inside = tokenized.source.index('inside')
    after = tokenized.source.index('after')

    assert any(
        span.start <= inside < span.end and 'string.heredoc.content' in span.scopes
        for span in tokenized.spans
    )
    assert all(
        not (span.start <= after < span.end and 'string.heredoc' in span.scopes)
        for span in tokenized.spans
    )


def test_ordered_patterns_win_same_position() -> None:
    registry = GrammarRegistry()
    registry.register_dict(
        {
            'scopeName': 'source.order',
            'patterns': [
                {'match': 'word', 'name': 'first'},
                {'match': r'\w+', 'name': 'second'},
            ],
        },
        language='order',
    )

    tokenized = Highlighter(registry).tokenize('word', language='order')

    assert tokenized.spans[0].scopes[-1] == 'first'


def test_zero_width_match_is_rejected() -> None:
    registry = GrammarRegistry()
    registry.register_dict(
        {'scopeName': 'source.zero', 'patterns': [{'match': r'(?=x)', 'name': 'zero'}]},
        language='zero',
    )

    with pytest.raises(GrammarError, match='zero-width'):
        Highlighter(registry).tokenize('x', language='zero')


def test_invalid_oniguruma_pattern_is_rejected() -> None:
    registry = GrammarRegistry()
    registry.register_dict(
        {'scopeName': 'source.extended', 'patterns': [{'match': '['}]},
        language='extended',
    )

    with pytest.raises(UnsupportedPatternError, match='oniguruma rejected'):
        Highlighter(registry).tokenize('word', language='extended')


def test_external_scope_include() -> None:
    registry = GrammarRegistry()
    registry.register_dict(
        {
            'scopeName': 'source.words',
            'patterns': [{'match': 'shared', 'name': 'constant.shared'}],
        },
        language='words',
    )
    registry.register_dict(
        {'scopeName': 'source.host', 'patterns': [{'include': 'source.words'}]},
        language='host',
    )

    tokenized = Highlighter(registry).tokenize('shared', language='host')

    assert tokenized.spans[0].scopes == ('source.host', 'constant.shared')


def test_html_escapes_source_and_keeps_gutter_outside_code(registry: GrammarRegistry) -> None:
    source = 'if <tag>\r\nelse'
    tokenized = Highlighter(registry).tokenize(source, language='example')
    rendered = render_html(
        tokenized,
        lines=LineOptions(numbers=True, number_start=10),
    )
    collector = TextCollector()
    collector.feed(rendered)

    assert '&lt;tag&gt;' in rendered
    assert ''.join(collector.code_text) == 'if <tag>\nelse'
    assert ''.join(collector.gutter_text) == '10\n11'
    assert '10' not in ''.join(collector.code_text)


def test_selected_lines_are_inclusive_and_preserve_token_styles(registry: GrammarRegistry) -> None:
    tokenized = Highlighter(registry).tokenize('if\nplain\nelse', language='example')
    rendered = render_html(
        tokenized,
        theme=Theme(selection_background='#112233'),
        lines=LineOptions(
            emphasize=LineSelection(lines={1}, ranges=[(2, 3)]),
            highlight=LineHighlightStyle(foreground='#abcdef'),
        ),
    )

    assert rendered.count('background-color:#112233') == 3
    assert 'color:#abcdef' in rendered
    assert rendered.count('data-line=') == 3


def test_out_of_range_line_selection_fails(registry: GrammarRegistry) -> None:
    tokenized = Highlighter(registry).tokenize('one line', language='example')

    with pytest.raises(SelectionError, match='outside the source'):
        render_html(tokenized, lines=LineOptions(emphasize=LineSelection(lines={2})))


def test_theme_specificity_then_forced_overrides(registry: GrammarRegistry) -> None:
    tokenized = Highlighter(registry).tokenize('if', language='example')
    theme = Theme(
        rules=(
            ThemeRule('keyword', Style(foreground='#111111', italic=True)),
            ThemeRule('keyword.control', Style(foreground='#222222', bold=True)),
        )
    )
    rendered = render_html(
        tokenized,
        theme=theme,
        overrides=(ThemeRule('keyword', Style(foreground='#abcdef', italic=False)),),
    )

    assert 'color:#abcdef' in rendered
    assert 'font-weight:bold' in rendered
    assert 'font-style:normal' in rendered


def test_theme_import_distinguishes_missing_and_empty_font_style() -> None:
    theme = Theme.from_dict(
        {
            'colors': {'editor.background': '#101010'},
            'tokenColors': [
                {'scope': 'keyword', 'settings': {'fontStyle': 'bold italic'}},
                {'scope': 'keyword.control', 'settings': {'fontStyle': ''}},
            ],
        }
    )
    registry = GrammarRegistry()
    registry.register_dict(
        {'scopeName': 'source.theme', 'patterns': [{'match': 'if', 'name': 'keyword.control'}]},
        language='theme',
    )
    rendered = Highlighter(registry).highlight('if', language='theme', theme=theme)

    assert 'background-color:#101010' in rendered
    assert 'font-weight:normal' in rendered
    assert 'font-style:normal' in rendered


def test_layout_rejects_untrusted_css_in_typed_fields(registry: GrammarRegistry) -> None:
    tokenized = Highlighter(registry).tokenize('if', language='example')

    with pytest.raises(Exception, match='unsafe CSS'):
        render_html(tokenized, layout=HtmlLayout(padding='1rem;color:red'))


def test_default_resets_a_token_background(registry: GrammarRegistry) -> None:
    tokenized = Highlighter(registry).tokenize('if', language='example')
    theme = Theme(rules=(ThemeRule('keyword', Style(background='#112233')),))
    rendered = render_html(
        tokenized,
        theme=theme,
        overrides=(ThemeRule('keyword.control', Style(background=DEFAULT)),),
    )

    assert rendered.count('background-color:#112233') == 0


def test_extension_import_reads_manifest_and_grammar(tmp_path) -> None:
    grammar_path = tmp_path / 'syntaxes' / 'sample.tmLanguage.json'
    grammar_path.parent.mkdir()
    grammar_path.write_text(
        '{"scopeName":"source.sample","patterns":[{"match":"x","name":"letter.x"}]}',
        encoding='utf-8',
    )
    (tmp_path / 'package.json').write_text(
        '{"contributes":{"languages":[{"id":"sample","aliases":["Sample"]}],'
        '"grammars":[{"language":"sample","scopeName":"source.sample",'
        '"path":"./syntaxes/sample.tmLanguage.json"}]}}',
        encoding='utf-8',
    )
    registry = GrammarRegistry()

    imported = registry.import_extension(tmp_path)

    assert imported[0].source_path == grammar_path.resolve()
    assert registry.get('Sample').scope_name == 'source.sample'


def test_grammar_object_can_be_registered(registry: GrammarRegistry) -> None:
    grammar = Grammar.from_dict(
        {'scopeName': 'source.direct', 'patterns': []},
        language='direct',
    )

    registry.register(grammar)

    assert registry.get('direct') is grammar
