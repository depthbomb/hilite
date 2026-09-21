import pytest
import plistlib
from html.parser import HTMLParser
from hilite import (
    Theme,
    Grammar,
    Highlighter,
    LineOptions,
    render_html,
    GrammarError,
    ResourceLimits,
    GrammarRegistry,
    HtmlRenderingError,
    ResourceLimitError,
)


class CodeText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_code = False
        self.fragments = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == 'code' and 'data-hilite-code' in dict(attrs):
            self.in_code = True

    def handle_endtag(self, tag: str) -> None:
        if tag == 'code':
            self.in_code = False

    def handle_data(self, data: str) -> None:
        if self.in_code:
            self.fragments.append(data)


def test_begin_while_state_is_checked_on_each_line() -> None:
    registry = GrammarRegistry()
    registry.register_dict(
        {
            'scopeName': 'source.while',
            'patterns': [
                {
                    'begin': r'^list:$',
                    'while': r'^\s+',
                    'name': 'meta.list',
                    'contentName': 'meta.list.content',
                }
            ],
        },
        language='while',
    )

    tokenized = Highlighter(registry).tokenize('list:\n  one\n  two\noutside', language='while')
    one = tokenized.source.index('one')
    outside = tokenized.source.index('outside')

    assert any(
        span.start <= one < span.end and 'meta.list.content' in span.scopes
        for span in tokenized.spans
    )
    assert all(
        not (span.start <= outside < span.end and 'meta.list' in span.scopes)
        for span in tokenized.spans
    )


def test_local_left_injection_wins_same_position() -> None:
    registry = GrammarRegistry()
    registry.register_dict(
        {
            'scopeName': 'source.inject',
            'patterns': [{'match': 'word', 'name': 'ordinary'}],
            'injections': {
                'L:source.inject': {'patterns': [{'match': 'word', 'name': 'injected'}]}
            },
        },
        language='inject',
    )

    tokenized = Highlighter(registry).tokenize('word', language='inject')

    assert tokenized.spans[0].scopes[-1] == 'injected'


def test_external_injection_is_applied_to_target_scope() -> None:
    registry = GrammarRegistry()
    registry.register_dict(
        {'scopeName': 'source.host', 'patterns': []},
        language='host',
    )
    registry.register_dict(
        {
            'scopeName': 'source.host.todo',
            'patterns': [{'match': 'TODO', 'name': 'keyword.todo'}],
        },
        language='host-todo',
        inject_to=('source.host',),
        injection_selector='L:source.host',
    )

    tokenized = Highlighter(registry).tokenize('TODO', language='host')

    assert tokenized.spans[0].scopes[-1] == 'keyword.todo'


def test_oniguruma_executes_g_anchor() -> None:
    registry = GrammarRegistry()
    registry.register_dict(
        {
            'scopeName': 'source.extended',
            'patterns': [
                {
                    'begin': r'\[',
                    'end': r'\]',
                    'patterns': [{'match': r'\Gword', 'name': 'anchored'}],
                }
            ],
        },
        language='extended',
    )

    tokenized = Highlighter(registry).tokenize('[word]', language='extended')

    assert tokenized.spans[1].scopes[-1] == 'anchored'


def test_document_anchor_only_matches_first_physical_line() -> None:
    registry = GrammarRegistry()
    registry.register_dict(
        {
            'scopeName': 'source.anchor',
            'patterns': [{'match': r'\Aword', 'name': 'document.first'}],
        },
        language='anchor',
    )

    tokenized = Highlighter(registry).tokenize('word\nword', language='anchor')

    assert tokenized.spans[0].scopes[-1] == 'document.first'
    assert tokenized.spans[-1].scopes == ('source.anchor',)


def test_jsonc_grammar_and_theme_files_are_supported(tmp_path) -> None:
    grammar_path = tmp_path / 'sample.tmLanguage.json'
    grammar_path.write_text(
        """{
          // grammar comment
          "scopeName": "source.sample",
          "patterns": [{"match": "x", "name": "letter-x"}],
        }""",
        encoding='utf-8',
    )
    theme_path = tmp_path / 'sample-color-theme.json'
    theme_path.write_text(
        """{
          /* theme comment */
          "tokenColors": [
            {"scope": ["letter-x, letter-y"], "settings": {"foreground": "#123456"}},
          ],
        }""",
        encoding='utf-8',
    )
    registry = GrammarRegistry()
    registry.register_file(grammar_path, language='sample')

    rendered = Highlighter(registry).highlight(
        'x',
        language='sample',
        theme=Theme.from_file(theme_path),
    )

    assert 'color:#123456' in rendered


def test_xml_plist_grammar_is_supported(tmp_path) -> None:
    grammar_path = tmp_path / 'sample.tmLanguage'
    with grammar_path.open('wb') as stream:
        plistlib.dump(
            {
                'scopeName': 'source.plist',
                'patterns': [{'match': 'x', 'name': 'letter.x'}],
            },
            stream,
        )
    registry = GrammarRegistry()
    registry.register_file(grammar_path, language='plist')

    tokenized = Highlighter(registry).tokenize('x', language='plist')

    assert tokenized.spans[0].scopes[-1] == 'letter.x'


def test_replacing_grammar_removes_old_aliases() -> None:
    registry = GrammarRegistry()
    registry.register(
        Grammar.from_dict(
            {'scopeName': 'source.replace', 'patterns': []},
            language='old',
            aliases=('old-alias',),
        )
    )
    registry.register(
        Grammar.from_dict(
            {'scopeName': 'source.replace', 'patterns': []},
            language='new',
        ),
        replace=True,
    )

    assert registry.languages == ('new',)
    with pytest.raises(Exception, match='no grammar registered'):
        registry.get('old-alias')


def test_validation_resolves_nested_external_dependencies() -> None:
    registry = GrammarRegistry()
    registry.register_dict(
        {
            'scopeName': 'source.dependencies',
            'patterns': [
                {
                    'begin': 'x',
                    'end': 'x',
                    'patterns': [{'include': 'source.missing'}],
                }
            ],
        },
        language='dependencies',
    )

    with pytest.raises(GrammarError, match='missing external grammar'):
        Highlighter(registry).validate('dependencies')


def test_grammar_data_is_frozen_at_registration_boundary() -> None:
    data = {'scopeName': 'source.frozen', 'patterns': []}
    grammar = Grammar.from_dict(data, language='frozen')
    data['scopeName'] = 'source.changed'

    assert grammar.scope_name == 'source.frozen'
    assert grammar.raw['scopeName'] == 'source.frozen'
    with pytest.raises(TypeError):
        grammar.raw['scopeName'] = 'source.changed'


def test_hidden_final_empty_line_removes_trailing_display_newline() -> None:
    tokenized = Highlighter().tokenize('line\n', language='plain')
    rendered = render_html(
        tokenized,
        lines=LineOptions(hide_final_empty_line=True),
    )
    parser = CodeText()
    parser.feed(rendered)

    assert ''.join(parser.fragments) == 'line'


def test_html_renderer_rejects_invalid_control_characters() -> None:
    tokenized = Highlighter().tokenize('safe\x00unsafe', language='plain')

    with pytest.raises(HtmlRenderingError, match='offset 4'):
        render_html(tokenized)


def test_input_and_line_resource_limits() -> None:
    input_limited = Highlighter(limits=ResourceLimits(max_input_chars=3))
    line_limited = Highlighter(limits=ResourceLimits(max_line_chars=3))

    with pytest.raises(ResourceLimitError, match='input contains'):
        input_limited.tokenize('four', language='plain')
    with pytest.raises(ResourceLimitError, match='line 1'):
        line_limited.tokenize('four\nok', language='plain')
