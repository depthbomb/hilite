import json
import pytest
from random import Random
from hilite import Grammar, ThemeError
from hilite.theme import resolve_style
from concurrent.futures import ThreadPoolExecutor
from hilite.grammar import substitute_backreferences
from hilite import (
    Style,
    Theme,
    DEFAULT,
    ThemeRule,
    Highlighter,
    LineOptions,
    GrammarError,
    LineSelection,
    ResourceLimits,
    SelectionError,
    GrammarRegistry,
    ResourceLimitError,
    LineHighlightStyle,
)


def engine(patterns, **extra):
    registry = GrammarRegistry()
    registry.register_dict(
        {'scopeName': 'source.test', 'patterns': patterns, **extra}, language='test'
    )
    return Highlighter(registry)


@pytest.mark.parametrize('selector', [42, ['source.test'], {'scope': 'source.test'}])
def test_non_string_injection_selector_reports_grammar_error(selector):
    with pytest.raises(GrammarError, match='injection selector must be a string'):
        engine([], injectionSelector=selector).validate('test')


@pytest.mark.parametrize('background', [42, None, []])
def test_invalid_line_background_reports_theme_error(background):
    options = LineOptions(
        emphasize=LineSelection(lines={1}),
        highlight=LineHighlightStyle(background=background),
    )
    with pytest.raises(ThemeError, match='line highlight background'):
        Highlighter().highlight('text', language='plain', lines=options)


@pytest.mark.parametrize('field', ['aliases', 'injectTo'])
def test_extension_string_lists_reject_non_strings(tmp_path, field):
    language = {'id': 'test'}
    grammar = {'scopeName': 'source.test', 'path': 'test.json', 'language': 'test'}
    (language if field == 'aliases' else grammar)[field] = ['valid', 42]
    (tmp_path / 'package.json').write_text(
        json.dumps(
            {
                'contributes': {'languages': [language], 'grammars': [grammar]},
            }
        ),
        encoding='utf-8',
    )
    (tmp_path / 'test.json').write_text(
        json.dumps({'scopeName': 'source.test', 'patterns': []}),
        encoding='utf-8',
    )
    registry = GrammarRegistry()
    with pytest.raises(GrammarError, match=f'{field} .* must contain strings'):
        registry.import_extension(tmp_path)
    assert registry.languages == ()


def test_registry_replacement_invalidates_dependent_grammars():
    highlighter = engine([{'include': 'source.child'}])
    registry = highlighter.registry
    registry.register_dict(
        {'scopeName': 'source.child', 'patterns': [{'match': 'x', 'name': 'old'}]},
        language='child',
    )
    assert highlighter.tokenize('x', language='test').spans[0].scopes[-1] == 'old'
    registry.register_dict(
        {'scopeName': 'source.child', 'patterns': [{'match': 'x', 'name': 'new'}]},
        language='child',
        replace=True,
    )
    assert highlighter.tokenize('x', language='test').spans[0].scopes[-1] == 'new'


def test_capture_lookarounds_do_not_duplicate_source():
    highlighter = engine(
        [
            {
                'match': r'(?<=(a))(b)(?=(c))',
                'captures': {
                    '1': {'name': 'before'},
                    '2': {'name': 'inside'},
                    '3': {'name': 'after'},
                },
            },
        ]
    )
    tokens = highlighter.tokenize('abc', language='test')
    assert [(s.start, s.end) for s in tokens.spans] == [(0, 1), (1, 2), (2, 3)]
    assert tokens.spans[1].scopes[-1] == 'inside'


def test_repository_names_cannot_collide_with_nested_rule_paths():
    highlighter = engine(
        [{'include': '#box'}, {'include': '#box.patterns[0]'}],
        repository={
            'box': {
                'patterns': [
                    {
                        'begin': '<',
                        'end': '>',
                        'name': 'box',
                        'patterns': [{'match': 'x', 'name': 'first'}],
                    }
                ]
            },
            'box.patterns[0]': {
                'begin': r'\[',
                'end': r'\]',
                'name': 'box',
                'patterns': [{'match': 'x', 'name': 'second'}],
            },
        },
    )
    tokens = highlighter.tokenize('<x>[x]', language='test')
    assert [
        span.scopes[-1] for span in tokens.spans if tokens.source[span.start : span.end] == 'x'
    ] == ['first', 'second']


def test_lookahead_capture_alone_does_not_extend_consumption():
    highlighter = engine([{'match': 'b(?=(c))', 'captures': {'1': {'name': 'lookahead'}}}])
    tokens = highlighter.tokenize('abc', language='test')
    assert ''.join(tokens.source[s.start : s.end] for s in tokens.spans) == 'abc'


def test_child_scope_theme_properties_override_parent_scope_specificity():
    theme = Theme(
        rules=(
            ThemeRule('string.quoted.double', Style(foreground='#111111', italic=True)),
            ThemeRule('constant', Style(foreground='#222222')),
        )
    )
    style = resolve_style(('source.test', 'string.quoted.double', 'constant.escape'), theme)
    assert style.foreground == '#222222'
    assert style.italic is True


def test_default_foreground_restores_theme_foreground():
    theme = Theme(foreground='#abcdef', rules=(ThemeRule('keyword', Style(foreground='#123456')),))
    style = resolve_style(('keyword',), theme, (ThemeRule('keyword', Style(foreground=DEFAULT)),))
    assert style.foreground == '#abcdef'


@pytest.mark.parametrize('value', [True, 1.5, '1', 0, -1])
def test_line_number_start_requires_positive_integer(value):
    with pytest.raises((ValueError, SelectionError)):
        LineOptions(number_start=value)


@pytest.mark.parametrize('value', [True, 1.5, '1', 0, -1])
def test_resource_bounds_require_positive_integer(value):
    with pytest.raises(ValueError):
        ResourceLimits(max_spans=value)


@pytest.mark.parametrize('value', [float('inf'), float('nan'), True, '1'])
def test_deadline_requires_finite_seconds(value):
    with pytest.raises(ValueError):
        ResourceLimits(timeout_seconds=value)


def test_selection_checks_ranges_before_expanding_them():
    with pytest.raises(SelectionError, match='outside'):
        LineSelection(ranges=[(1, 10**12)]).resolve(3)


def test_selection_validates_before_deduplicating_bool_and_integer():
    with pytest.raises(SelectionError):
        LineSelection(lines=[1, True])


def test_dynamic_substitution_does_not_resubstitute_capture_text():
    assert substitute_backreferences(r'\2\1', ('a', r'\1')) == r'\\1a'


def test_escaped_dynamic_reference_is_literal():
    assert substitute_backreferences(r'\\1', ('x',)) == r'\\1'


def test_invalid_external_regex_keeps_its_diagnostic():
    highlighter = engine([{'include': 'source.bad'}])
    highlighter.registry.register_dict(
        {'scopeName': 'source.bad', 'patterns': [{'match': '['}]},
        language='bad',
    )
    with pytest.raises(GrammarError, match='oniguruma rejected'):
        highlighter.validate('test')


def test_capture_retokenization_adds_nested_scopes():
    highlighter = engine(
        [
            {
                'match': '(x)',
                'captures': {
                    '1': {'name': 'capture', 'patterns': [{'match': 'x', 'name': 'inner'}]}
                },
            }
        ]
    )
    assert highlighter.tokenize('x', language='test').spans[0].scopes == (
        'source.test',
        'capture',
        'inner',
    )


def test_nested_repository_resolves_local_rules():
    highlighter = engine(
        [
            {
                'patterns': [{'include': '#local'}],
                'repository': {'local': {'match': 'x', 'name': 'local'}},
            }
        ]
    )
    assert highlighter.tokenize('x', language='test').spans[0].scopes == ('source.test', 'local')


def test_input_limit_is_checked_before_grammar_compilation():
    highlighter = engine([{'match': '['}])
    highlighter = Highlighter(highlighter.registry, limits=ResourceLimits(max_input_chars=2))
    with pytest.raises(ResourceLimitError):
        highlighter.tokenize('long', language='test')


def test_dynamic_scope_name_and_multiple_scope_names():
    highlighter = engine([{'match': '(foo)', 'name': 'entity.$1 meta.label'}])
    assert highlighter.tokenize('foo', language='test').spans[0].scopes == (
        'source.test',
        'entity.foo',
        'meta.label',
    )


def test_plaintext_highlighter_does_not_mutate_supplied_empty_registry():
    registry = GrammarRegistry()
    Highlighter(registry)
    assert registry.languages == ()


def test_extension_import_failure_does_not_partially_register(tmp_path):
    (tmp_path / 'good.json').write_text(
        json.dumps({'scopeName': 'source.good', 'patterns': []}),
        encoding='utf-8',
    )
    (tmp_path / 'package.json').write_text(
        json.dumps(
            {
                'contributes': {
                    'grammars': [
                        {'path': './good.json', 'scopeName': 'source.good', 'language': 'good'},
                        {'path': './missing.json', 'scopeName': 'source.bad', 'language': 'bad'},
                    ]
                }
            }
        ),
        encoding='utf-8',
    )
    registry = GrammarRegistry()
    with pytest.raises(GrammarError):
        registry.import_extension(tmp_path)
    assert registry.languages == ()
    assert registry.revision == 0


def test_disabled_rules_are_not_executed():
    highlighter = engine([{'match': 'x', 'name': 'disabled', 'disabled': 1}])
    assert highlighter.tokenize('x', language='test').spans[0].scopes == ('source.test',)


def test_grammar_with_cyclic_python_data_is_rejected():
    data = {'scopeName': 'source.cycle', 'patterns': []}
    data['patterns'].append(data)
    with pytest.raises(GrammarError, match='nesting'):
        Grammar.from_dict(data)


def test_invalid_injection_selector_is_rejected_without_matching_input():
    highlighter = engine([], injections={'L:': {'match': 'x'}})
    with pytest.raises(GrammarError, match='selector'):
        highlighter.validate('test')


def test_malformed_dynamic_end_is_validated_before_matching():
    highlighter = engine([{'begin': '(x)', 'end': r'\1['}])
    with pytest.raises(GrammarError, match='rejected'):
        highlighter.validate('test')


def test_scope_less_imported_font_style_is_preserved():
    theme = Theme.from_dict({'settings': [{'settings': {'fontStyle': 'italic'}}]})
    assert resolve_style(('text',), theme).italic is True


def test_theme_include_is_not_silently_ignored():
    with pytest.raises(ThemeError, match='includes'):
        Theme.from_dict({'include': './base.json'})


def test_compilation_resource_bounds():
    highlighter = engine([{'match': 'abc'}])
    with pytest.raises(ResourceLimitError, match='pattern'):
        Highlighter(highlighter.registry, limits=ResourceLimits(max_pattern_chars=2)).validate(
            'test'
        )
    highlighter = engine([{'match': 'a'}, {'match': 'b'}])
    with pytest.raises(ResourceLimitError, match='rule count'):
        Highlighter(highlighter.registry, limits=ResourceLimits(max_grammar_rules=1)).validate(
            'test'
        )


def test_dynamic_pattern_expansion_respects_pattern_limit():
    highlighter = engine([{'begin': '(x+)', 'end': r'\1\1'}])
    highlighter = Highlighter(highlighter.registry, limits=ResourceLimits(max_pattern_chars=20))
    with pytest.raises(ResourceLimitError, match='expanded end/while'):
        highlighter.tokenize('x' * 15, language='test')


@pytest.mark.parametrize(
    'loader,error', [(Grammar.from_file, GrammarError), (Theme.from_file, ThemeError)]
)
def test_malformed_plist_reports_library_error(tmp_path, loader, error):
    path = tmp_path / 'broken.plist'
    path.write_text('<?xml version="1.0"?><plist><dict>', encoding='utf-8')
    with pytest.raises(error, match='could not load'):
        loader(path)


def test_expired_deadline_is_reported(monkeypatch):
    highlighter = engine([{'match': 'word'}])
    highlighter.validate('test')
    monkeypatch.setattr('hilite.highlighter.monotonic', lambda: 0.0)
    monkeypatch.setattr('hilite.tokenizer.time.monotonic', lambda: 10.0)
    with pytest.raises(ResourceLimitError, match='deadline'):
        highlighter.tokenize('word', language='test')


def test_small_cache_handles_recursive_external_grammars():
    highlighter = engine([{'begin': 'x', 'end': 'y', 'patterns': [{'include': 'source.other'}]}])
    highlighter.registry.register_dict(
        {
            'scopeName': 'source.other',
            'patterns': [{'begin': 'z', 'end': 'w', 'patterns': [{'include': 'source.test'}]}],
        },
        language='other',
    )
    highlighter = Highlighter(highlighter.registry, max_prepared_grammars=1)
    highlighter.validate('test')
    assert highlighter.cache_info().prepared_grammars <= 1


@pytest.mark.parametrize('cyclic', [False, True])
def test_long_include_chains_do_not_use_python_recursion(cyclic):
    repository = {f'r{i}': {'include': f'#r{i + 1}'} for i in range(1200)}
    repository['r1200'] = {'include': '#r0'} if cyclic else {'match': 'x', 'name': 'word'}
    highlighter = engine([{'include': '#r0'}], repository=repository)
    tokens = highlighter.tokenize('x', language='test')
    assert tokens.spans[0].scopes[-1] == ('source.test' if cyclic else 'word')


def test_long_external_begin_chains_validate_without_python_recursion():
    registry = GrammarRegistry()
    for index in range(1100):
        registry.register_dict(
            {
                'scopeName': f'source.chain{index}',
                'patterns': [
                    {
                        'begin': '<',
                        'end': '>',
                        'patterns': [{'include': f'source.chain{index + 1}'}]
                        if index < 1099
                        else [],
                    }
                ],
            }
        )
    highlighter = Highlighter(registry)
    highlighter.validate('source.chain0')
    assert highlighter.tokenize('<x>', language='source.chain0').source == '<x>'


def test_random_inputs_preserve_offsets_and_parallel_results():
    highlighter = engine(
        [
            {
                'begin': '"',
                'end': '"',
                'name': 'string',
                'patterns': [{'match': r'\\.', 'name': 'escape'}],
            },
            {'match': r'\w+', 'name': 'word'},
        ]
    )
    random = Random(731)
    sources = [''.join(random.choices('abc 12"\\<>😀\r\n\t', k=200)) for _ in range(40)]

    def tokenize(source):
        result = highlighter.tokenize(source, language='test')
        cursor = 0
        for span in result.spans:
            assert span.start == cursor
            assert span.end > span.start
            cursor = span.end
        assert cursor == len(source)
        return result

    expected = [tokenize(source) for source in sources]
    with ThreadPoolExecutor(max_workers=4) as executor:
        assert list(executor.map(tokenize, sources)) == expected
