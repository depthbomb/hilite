import pytest
from concurrent.futures import ThreadPoolExecutor
from hilite import Highlighter, GrammarError, ResourceLimits, GrammarRegistry, ResourceLimitError


def engine(patterns, *, repository=None, limits=None):
    registry = GrammarRegistry()
    registry.register_dict(
        {
            'scopeName': 'source.test',
            'patterns': patterns,
            'repository': repository or {},
        },
        language='test',
    )
    return Highlighter(registry, limits=limits)


def test_local_repository_does_not_leak_to_siblings():
    highlighter = engine(
        [
            {'patterns': [], 'repository': {'local': {'match': 'x'}}},
            {'include': '#local'},
        ]
    )
    with pytest.raises(GrammarError, match='missing repository'):
        highlighter.validate('test')


def test_begin_rule_has_a_local_repository():
    highlighter = engine(
        [
            {
                'begin': '<',
                'end': '>',
                'patterns': [{'include': '#word'}],
                'repository': {'word': {'match': 'x', 'name': 'local'}},
            },
            {'include': '#word'},
        ],
        repository={'word': {'match': 'x', 'name': 'outer'}},
    )
    tokens = highlighter.tokenize('<x>x', language='test')
    assert tokens.spans[1].scopes[-1] == 'local'
    assert tokens.spans[-1].scopes[-1] == 'outer'


def test_include_cycles_still_allow_following_patterns():
    highlighter = engine(
        [{'include': '#outer'}],
        repository={
            'outer': {
                'repository': {'cycle': {'include': '#outer'}},
                'patterns': [{'include': '#cycle'}, {'match': 'x', 'name': 'letter'}],
            }
        },
    )
    assert highlighter.tokenize('x', language='test').spans[0].scopes[-1] == 'letter'


def test_capture_dependencies_are_validated_before_matching():
    highlighter = engine(
        [
            {
                'match': '(x)',
                'captures': {
                    '1': {
                        'patterns': [{'include': 'source.missing'}],
                    }
                },
            }
        ]
    )
    with pytest.raises(GrammarError, match='missing external grammar'):
        highlighter.validate('test')


def test_capture_recursion_without_progress_is_rejected():
    highlighter = engine(
        [{'include': '#recursive'}],
        repository={
            'recursive': {
                'match': '(x)',
                'captures': {'1': {'patterns': [{'include': '#recursive'}]}},
            }
        },
    )
    with pytest.raises(GrammarError, match='retokenization made no progress'):
        highlighter.tokenize('x', language='test')


def test_capture_recursion_shares_nesting_limit():
    highlighter = engine(
        [{'include': '#recursive'}],
        repository={
            'recursive': {
                'match': '(.+).',
                'captures': {'1': {'patterns': [{'include': '#recursive'}]}},
            }
        },
        limits=ResourceLimits(max_nesting=3),
    )
    with pytest.raises(ResourceLimitError, match='nesting'):
        highlighter.tokenize('abcdefgh', language='test')


def test_capture_tokens_share_span_limit():
    highlighter = engine(
        [
            {
                'match': '(.+)',
                'captures': {
                    '1': {
                        'patterns': [{'match': 'x', 'name': 'x'}, {'match': 'y', 'name': 'y'}],
                    }
                },
            }
        ],
        limits=ResourceLimits(max_spans=3),
    )
    with pytest.raises(ResourceLimitError, match='span'):
        highlighter.tokenize('xyxyxy', language='test')


def test_capture_pattern_compilation_shares_rule_limit():
    highlighter = engine(
        [
            {
                'match': '(x)',
                'captures': {
                    '1': {
                        'patterns': [{'match': 'x'}],
                    }
                },
            }
        ],
        limits=ResourceLimits(max_grammar_rules=2),
    )
    with pytest.raises(ResourceLimitError, match='rule count'):
        highlighter.validate('test')


def test_capture_retokenization_preserves_deadline(monkeypatch):
    highlighter = engine(
        [
            {
                'match': '(x)',
                'captures': {
                    '1': {
                        'patterns': [{'match': 'x', 'name': 'inner'}],
                    }
                },
            }
        ],
        limits=ResourceLimits(timeout_seconds=1),
    )
    highlighter.validate('test')
    monkeypatch.setattr('hilite.highlighter.monotonic', lambda: 0.0)
    ticks = iter((0.0, 0.0, 0.0, 2.0))
    monkeypatch.setattr('hilite.tokenizer.time.monotonic', lambda: next(ticks, 2.0))
    with pytest.raises(ResourceLimitError, match='deadline'):
        highlighter.tokenize('x', language='test')


def test_many_capture_tokens_preserve_source_and_thread_safety():
    highlighter = engine(
        [
            {
                'match': '(.+)',
                'captures': {
                    '1': {
                        'patterns': [{'match': 'x', 'name': 'x'}, {'match': 'y', 'name': 'y'}],
                    }
                },
            }
        ]
    )
    source = 'xy' * 1500
    expected = highlighter.tokenize(source, language='test')
    assert len(expected.spans) == len(source)
    assert ''.join(source[span.start : span.end] for span in expected.spans) == source
    with ThreadPoolExecutor(max_workers=4) as pool:
        actual = list(pool.map(lambda _: highlighter.tokenize(source, language='test'), range(8)))
    assert all(result == expected for result in actual)
