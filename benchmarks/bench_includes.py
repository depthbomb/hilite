"""Measure highlighting grammars with shared repository include graphs."""

import sys
import json
import argparse
import platform
from pathlib import Path
from hashlib import sha256
from statistics import median
from time import perf_counter


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--samples', type=int, default=9)
    arguments = parser.parse_args()
    if arguments.samples < 1:
        parser.error('--samples must be positive')
    sys.path.insert(0, str(arguments.source.resolve()))

    from hilite import Highlighter, GrammarRegistry

    results = []
    for depth in (10, 14, 17):
        repository = {
            f'r{index}': {
                'patterns': [{'include': f'#r{index + 1}'}, {'include': f'#r{index + 1}'}],
            }
            for index in range(depth)
        }
        repository[f'r{depth}'] = {'match': 'x', 'name': 'letter'}
        registry = GrammarRegistry()
        registry.register_dict(
            {
                'scopeName': 'source.test',
                'patterns': [{'include': '#r0'}],
                'repository': repository,
            },
            language='test',
        )
        cold = []
        warm = []
        hashes = set()
        for _ in range(arguments.samples):
            highlighter = Highlighter(registry)
            for timings in (cold, warm):
                started = perf_counter()
                output = highlighter.highlight('x', language='test')
                timings.append(perf_counter() - started)
                hashes.add(sha256(output.encode()).hexdigest())
        assert len(hashes) == 1
        result = {
            'depth': depth,
            'grammar_sha256': sha256(json.dumps(repository, sort_keys=True).encode()).hexdigest(),
            'output_sha256': hashes.pop(),
            'cold_median_seconds': median(cold),
            'warm_median_seconds': median(warm),
            'cold_samples_seconds': cold,
            'warm_samples_seconds': warm,
        }
        results.append(result)
        print(depth, median(cold), median(warm), flush=True)

    arguments.output.write_text(
        json.dumps(
            {
                'python': sys.version,
                'platform': platform.platform(),
                'source': str(arguments.source.resolve()),
                'results': results,
            },
            indent=2,
        ),
        encoding='utf-8',
    )


if __name__ == '__main__':
    main()
