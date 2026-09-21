"""Compare complete HTML calls using identical inputs and explicitly selected source trees."""

import sys
import json
import argparse
import platform
import tracemalloc
from pathlib import Path
from hashlib import sha256
from subprocess import run
from statistics import median
from time import perf_counter


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--samples', type=int, default=7)
    arguments = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(project))
    sys.path.insert(0, str(arguments.source.resolve()))

    from hilite import Highlighter, LineOptions, LineSelection
    from examples.demo_assets import DEMO_GRAMMARS, dark_theme, demo_registry
    from examples.basic_snippets import SNIPPETS

    theme = dark_theme()
    results = []
    for language, snippet in SNIPPETS.values():
        for size in (1_024, 10_240, 102_400):
            source = (snippet + '\n') * max(1, size // (len(snippet) + 1))
            for decorated in (False, True):
                options = LineOptions(
                    numbers=decorated,
                    emphasize=LineSelection(lines={2, 4}) if decorated else LineSelection(),
                )
                highlighter = Highlighter(demo_registry())

                def highlight(
                    iteration: int,
                    highlighter=highlighter,
                    source=source,
                    language=language,
                    options=options,
                ) -> str:
                    return highlighter.highlight(
                        source + ' ' * (iteration % 3),
                        language=language,
                        theme=theme,
                        lines=options,
                    )

                started = perf_counter()
                output = highlight(0)
                first = perf_counter() - started
                timings = []
                for iteration in range(arguments.samples):
                    started = perf_counter()
                    highlight(iteration)
                    timings.append(perf_counter() - started)
                tracemalloc.start()
                highlight(1)
                _, peak = tracemalloc.get_traced_memory()
                tracemalloc.stop()
                result = {
                    'language': language,
                    'size': size,
                    'decorated': decorated,
                    'source_sha256': sha256(source.encode()).hexdigest(),
                    'grammar_sha256': sha256(
                        json.dumps(DEMO_GRAMMARS[language], sort_keys=True).encode(),
                    ).hexdigest(),
                    'input_bytes': len(source.encode()),
                    'output_bytes': len(output.encode()),
                    'output_sha256': sha256(output.encode()).hexdigest(),
                    'first_seconds': first,
                    'median_seconds': median(timings),
                    'samples_seconds': timings,
                    'peak_python_bytes': peak,
                }
                results.append(result)
                print(language, size, decorated, round(median(timings) * 1000, 2), flush=True)

    cold = []
    probe = (
        'import sys; '
        f'sys.path[:0] = {[str(arguments.source.resolve()), str(project)]!r}; '
        'from hilite import Highlighter; '
        'from examples.demo_assets import demo_registry, dark_theme; '
        'Highlighter(demo_registry()).highlight('
        '"print(42)", language="python", theme=dark_theme())'
    )
    for _ in range(arguments.samples):
        started = perf_counter()
        run([sys.executable, '-c', probe], check=True, capture_output=True)
        cold.append(perf_counter() - started)
    arguments.output.write_text(
        json.dumps(
            {
                'python': sys.version,
                'platform': platform.platform(),
                'source': str(arguments.source.resolve()),
                'engine': 'oniguruma',
                'cold_process_seconds': cold,
                'results': results,
            },
            indent=2,
        ),
        encoding='utf-8',
    )


if __name__ == '__main__':
    main()
