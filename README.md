# hilite

A Python syntax highlighting library powered by Oniguruma.

## Getting started

Source installs build a native extension, so you'll need Rust and a C compiler.
On Windows, install Visual Studio Build Tools with the C++ tools. Then install
from a local checkout using a virtual environment:

```console
python -m pip install .
```

Bring your own grammar and theme files. JSON and XML plist formats are supported;
full language grammars and themes aren't bundled with the package.

```python
from hilite import Theme, Highlighter, GrammarRegistry

registry = GrammarRegistry()
registry.register_file('grammars/python.tmLanguage.json', language='python', aliases=('py',))

theme = Theme.from_file('themes/dark-plus.json')
highlighter = Highlighter(registry)

html = highlighter.highlight(
    'def greet(name):\n    return f"Hello, {name}!"',
    language='python',
    theme=theme,
)
```

Reuse your `Highlighter` instance to keep parsed grammars and compiled patterns
cached. The native extension bundles Oniguruma. Prebuilt wheels install without
Rust or a C compiler.

You can also import grammars from an installed VS Code extension:

```python
registry.import_extension(r'C:\Users\me\.vscode\extensions\publisher.language-version')
```

Pass the directory containing the extension's `package.json`. The importer reads
its grammar files without running extension code. Register any external grammars
it depends on, and keep the original licenses when copying grammar or theme files.
Highlighting doesn't download anything.

## Make it your own

Add line numbers and emphasize a line:

```python
from hilite import HtmlLayout, LineOptions, LineSelection

html = highlighter.highlight(
    'def greet(name):\n    return f"Hello, {name}!"',
    language='python',
    theme=theme,
    layout=HtmlLayout(font_size='14px', padding='1.25rem'),
    lines=LineOptions(numbers=True, emphasize=LineSelection(lines={2})),
)
```

Line selections start at 1. Use `ranges=[(2, 5)]` for an inclusive range or
`number_start=100` to change the displayed numbering. The gutter stays separate
from the code, so copying code doesn't include line numbers.

Load a theme with `Theme.from_file()`, build one with `Theme` and `ThemeRule`, or
pass `overrides` to force a style over the theme:

```python
from hilite import Style, ThemeRule

html = highlighter.highlight(
    '# a comment',
    language='python',
    theme=theme,
    overrides=(ThemeRule('comment', Style(foreground='#8a9199', italic=False)),),
)
```

If you want to render the same code with several themes, call
`highlighter.tokenize(source, language='python')` once and pass the result to
`render_html(tokens, theme=theme)`. Tokens retain their scope stacks and Python
string offsets.

## Try the examples

From a checkout, these commands create HTML pages you can open in a browser:

```console
python -m examples.basic_snippets -o language-gallery.html
python -m examples.themes_and_overrides -o theme-gallery.html
python -m examples.lines_and_layout -o line-layout.html
```

The examples include small demo grammars for Python, JavaScript, HTML, JSON, and
shell, so they work without extra downloads. They cover the snippets shown, rather
than every feature of those languages. See
[`import_extension.py`](examples/import_extension.py) for highlighting a file with
an installed VS Code extension.

## Native builds

Wheels include the native extension and Oniguruma 6.9.10. Source installs compile
the extension automatically and require a successful native build. Cargo may
download its locked dependencies during compilation.

Native builds are verified on Windows x64 with CPython 3.14. The build scripts
support Linux and macOS, but those platforms are untested.

Invalid patterns raise an error with the grammar and rule location. Call
`highlighter.validate('python')` to check a grammar before using it.

## A few limits to know about

TextMate support includes multiline rules, nested repositories, capture
retokenization, external includes, and injections. Selectors can use grouped
alternatives and exclusions, such as `(string | comment) - comment.block`, plus
`&`, comma alternatives, direct-parent paths (`source > string`), and wildcard
scope segments (`source.*`). Injection selectors also support `L:` and `R:` priority.

Merge theme includes before loading a theme. Capture styling stays within the
consuming match, and grammar cycles that make no progress raise an error.

`ResourceLimits` lets you cap input size, line length, nesting, token count, and
execution time. Oniguruma also limits backtracking and match-stack use, but a
running search can't be interrupted by a wall-clock deadline. Use a separate,
killable process if you need a hard deadline for untrusted input or grammars.

Code and HTML attributes are escaped. Output uses inline styles, which your page's
Content Security Policy or sanitizer may block. Only pass trusted values to
`HtmlLayout.trusted_css`. Line endings become LF in the rendered HTML; control
characters that can't round-trip through HTML are rejected.

## Development

Create and activate a virtual environment, then install the development extras:

```console
python -m pip install -e ".[dev,browser-test]"
python -m pytest
python -m ruff check .
python -m ruff format --check .
python -m mypy
python -m build
python -m twine check --strict dist/*
```

Editable installs build the native extension required by the test suite.
Browser tests need Chromium; set `HILITE_BROWSER` to its executable path to
enable them. The suite checks token scopes against pinned TextMate reference
fixtures without needing Node.

After changing native code, rebuild with `python native/build.py --inplace`
or rerun the editable install. `python -m build` creates a source archive and a
platform-specific native wheel. Check Rust changes with
`cargo fmt --manifest-path native/Cargo.toml --check` and
`cargo clippy --manifest-path native/Cargo.toml --lib -- -D warnings`.

[`bench_highlighter.py`](benchmarks/bench_highlighter.py) measures highlighting across
languages, input sizes, and layouts. Run it with `--help` for the available options.

The [test workflow](.github/workflows/tests.yml) checks Python 3.14 on Linux,
Windows, and macOS. It builds native wheels from the source archive, then tests
the installed wheels with coverage and Chromium. Linux wheels use manylinux.

The [release workflow](.github/workflows/release.yml) runs those checks again when
a GitHub release is published. A final release tagged `v0.1.0` must match the
version in `pyproject.toml`; prereleases and manual runs only validate. Publishing
uses the `pypi` environment and requires a PyPI trusted publisher configured for
`release.yml`. It uploads the distributions that passed CI.
