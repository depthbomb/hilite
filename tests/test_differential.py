import re
import json
import pytest
from pathlib import Path
from hilite import Highlighter, GrammarRegistry

FIXTURES = json.loads(
    (Path(__file__).parent / 'fixtures/textmate_reference.json').read_text('utf-8')
)


ADDITIONAL_FIXTURES = json.loads(
    (Path(__file__).parent / 'fixtures/compatibility_reference.json').read_text('utf-8')
)


@pytest.mark.parametrize(
    'fixture', [*FIXTURES['cases'], *ADDITIONAL_FIXTURES['cases']], ids=lambda case: case['name']
)
def test_reference_scopes(fixture):
    registry = GrammarRegistry()
    for external in fixture.get('external', ()):
        registry.register_dict(external)
    registry.register_dict(fixture['grammar'], language='test')
    tokens = Highlighter(registry).tokenize(fixture['source'], language='test')
    actual = []
    offset = 0
    for line in re.split(r'\r\n|\r|\n', fixture['source']):
        actual_line = []
        for index, character in enumerate(line, offset):
            span = next(span for span in tokens.spans if span.start <= index < span.end)
            actual_line.append([character, list(span.scopes)])
        actual.append(actual_line)
        offset += len(line)
        if fixture['source'][offset : offset + 2] == '\r\n':
            offset += 2
        elif fixture['source'][offset : offset + 1] in ('\r', '\n'):
            offset += 1
    if fixture['name'] == 'capture-outside':
        # Intentional boundary: capture styling is clipped to the consuming match.
        # The reference lets the lookahead style the next character as well.
        assert actual == [
            [
                ['a', ['source.test']],
                ['b', ['source.test', 'inside']],
                ['c', ['source.test']],
            ]
        ]
    else:
        assert actual == fixture['expected']
