"""Native engine contracts and rendering regression checks."""

import gc
import pytest
from random import Random
from hashlib import sha256
from hilite import _oniguruma as native
from examples.basic_snippets import SNIPPETS
from concurrent.futures import ThreadPoolExecutor
from examples.demo_assets import dark_theme, demo_registry
from hilite import (
    Highlighter,
    LineOptions,
    LineSelection,
    ResourceLimits,
    GrammarRegistry,
    ResourceLimitError,
    UnsupportedPatternError,
)


def engine(patterns, **options):
    registry = GrammarRegistry()
    registry.register_dict({'scopeName': 'source.native', 'patterns': patterns}, language='native')
    return Highlighter(registry, **options)


@pytest.mark.parametrize(
    'heading,expected',
    [
        ('Python', 'fc6d16114af0257e5b0302ecff3b831132e028c0fa9685faf89df4f86a29e0b8'),
        ('JavaScript', '1a30305ae690b2767b730d8bcf187c4c17f41b69b58ed5b87cb2d03ca638106d'),
        (
            'HTML with embedded JavaScript',
            '51d4efc57b06b220306bc9d16aebd558b159871ed36f4f18e83b45661ac1ad3a',
        ),
        ('JSON', '1a863a2f4c4521b44fcfe0ad145a35acd25af657e302aa3e5e1281cfc178b6e0'),
        ('Shell', '659a6bf1e7b38315279180074959e9c32e6464b0323d81007e786b33850aa164'),
    ],
)
def test_demo_output_preserves_native_rendering(heading, expected):
    # Pinned demo output with line numbers and emphasis.
    language, source = SNIPPETS[heading]
    html = Highlighter(demo_registry()).highlight(
        source,
        language=language,
        theme=dark_theme(),
        lines=LineOptions(numbers=True, emphasize=LineSelection(lines={2})),
    )
    assert sha256(html.encode()).hexdigest() == expected


@pytest.mark.parametrize(
    'pattern,source,expected',
    [
        (r'\h+', ' 09aF xyz', '09aF'),
        (r'(?<word>\p{L}+)\s+\k<word>', 'éé éé', 'éé éé'),
        (r'(?<pair>\((?:[^()]|\g<pair>)*\))', '(a(b)c)', '(a(b)c)'),
        (r'[a-z&&[^aeiou]]+', 'aei bcdf ou', 'bcdf'),
    ],
)
def test_oniguruma_dialect(pattern, source, expected):
    highlighter = engine([{'match': pattern, 'name': 'matched'}])
    tokens = highlighter.tokenize(source, language='native')
    assert (
        ''.join(
            source[span.start : span.end] for span in tokens.spans if span.scopes[-1] == 'matched'
        )
        == expected
    )


def test_unicode_captures_named_groups_and_lifetimes():
    pattern = native.Pattern(r'(?<face>😀)(é)(z)?')
    scanner = native.Scanner([pattern])
    line = native.Line('前😀é後')
    _, match = scanner.find(line, 0, True, False, None)
    del scanner, line, pattern
    gc.collect()
    assert (match.start(), match.end(), match.group()) == (1, 3, '😀é')
    assert (match.start('face'), match.end('face')) == (1, 2)
    assert match.groups() == ('😀', 'é', None)
    assert match.group(3) is None
    assert match.start(3) == match.end(3) == -1
    for group in (-1, 99, 'missing'):
        with pytest.raises(IndexError):
            match.group(group)


def test_scanner_order_anchor_changes_and_backward_search():
    scanner = native.Scanner([native.Pattern(r'\Gx'), native.Pattern('x')])
    line = native.Line('xx')
    assert scanner.find(line, 0, True, False, None)[0] == 1
    assert scanner.find(line, 0, True, True, None)[0] == 0
    assert scanner.find(line, 1, False, False, None)[1].start() == 1
    assert scanner.find(line, 0, True, False, None)[1].start() == 0
    assert scanner.find(line, 2, False, False, None) is None
    with pytest.raises(IndexError):
        scanner.find(line, 3, False, False, None)


def test_compile_error_contains_grammar_path_and_pattern():
    with pytest.raises(UnsupportedPatternError, match=r'source.native.*patterns\[0\].*oniguruma'):
        engine([{'match': '['}]).validate('native')


@pytest.mark.parametrize('source,pattern', [('ab', r'a\Kb'), ('😀é', r'😀\Ké')])
def test_cached_search_respects_consumed_start_before_keep(source, pattern):
    regex = native.Pattern(pattern)
    line = native.Line(source)
    assert line.search(regex, 0, False, False, None).start() == 1
    assert line.search(regex, 1, False, False, None) is None


def test_keep_does_not_reuse_match_after_another_rule_consumes_prefix():
    highlighter = engine(
        [
            {'match': r'a\Kb', 'name': 'kept'},
            {'match': 'a', 'name': 'prefix'},
            {'match': 'b', 'name': 'suffix'},
        ]
    )
    tokens = highlighter.tokenize('ab ab', language='native')
    assert [span.scopes[-1] for span in tokens.spans] == [
        'prefix',
        'suffix',
        'source.native',
        'prefix',
        'suffix',
    ]


@pytest.mark.parametrize('pattern', [r'a\Kb', r'.\K.', r'\G.', r'\A.', r'(?<=a)b', r'(é)?b'])
def test_cached_search_matches_fresh_search_at_changing_positions(pattern):
    regex = native.Pattern(pattern)
    source = 'ab aéb 😀ab'
    line = native.Line(source)
    positions = [*range(len(source) + 1), *range(len(source), -1, -1)]
    for first, anchored in [(False, False), (True, False), (False, True), (True, True)]:
        for position in positions:
            cached = line.search(regex, position, first, anchored, None)
            fresh = native.Line(source).search(regex, position, first, anchored, None)
            actual = None if cached is None else (cached.start(), cached.end(), cached.groups())
            expected = None if fresh is None else (fresh.start(), fresh.end(), fresh.groups())
            assert actual == expected


def test_retry_limit_and_deadline_are_reported_as_resource_errors():
    with pytest.raises(ResourceLimitError, match='resource limit'):
        engine([{'match': '(a+)+$'}], limits=ResourceLimits(timeout_seconds=None)).tokenize(
            'a' * 100 + '!', language='native'
        )
    with pytest.raises(TimeoutError, match='deadline'):
        native.Line('x').search(native.Pattern('x'), 0, True, False, 0.0)


def test_unicode_dynamic_end_and_crlf_offsets():
    highlighter = engine([{'begin': '<<(.+)$', 'end': r'^\1$', 'name': 'heredoc'}])
    source = '<<😀é\r\nbody\r\n😀é\r\nplain'
    tokens = highlighter.tokenize(source, language='native')
    assert ''.join(source[s.start : s.end] for s in tokens.spans) == source
    assert tokens.spans[-1].scopes == ('source.native',)
    assert source[tokens.spans[-1].start :] == '\r\nplain'


def test_shared_highlighter_random_inputs_are_deterministic():
    patterns = [
        {
            'begin': '"',
            'end': '"',
            'name': 'string',
            'patterns': [{'match': r'\\.', 'name': 'escape'}],
        },
        {'match': r'\w+', 'name': 'word'},
    ]
    highlighter = engine(patterns)
    reference = Highlighter(highlighter.registry)
    random = Random(1093)
    sources = [''.join(random.choices('abc 12"\\<>😀é\r\n\t', k=300)) for _ in range(80)]
    expected = [reference.tokenize(source, language='native') for source in sources]
    with ThreadPoolExecutor(max_workers=4) as executor:
        actual = list(
            executor.map(lambda source: highlighter.tokenize(source, language='native'), sources)
        )
    assert actual == expected
