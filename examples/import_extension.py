import argparse
from pathlib import Path
from hilite import Theme, Highlighter, LineOptions


def highlight_from_extension(
    extension: Path,
    source_file: Path,
    language: str,
    *,
    theme_file: Path | None = None,
    line_numbers: bool = False,
) -> str:
    from hilite import GrammarRegistry

    registry = GrammarRegistry()
    registry.import_extension(extension)
    highlighter = Highlighter(registry)
    highlighter.validate(language)
    theme = Theme.from_file(theme_file) if theme_file is not None else Theme()
    source = source_file.read_text(encoding='utf-8')
    return highlighter.highlight(
        source,
        language=language,
        theme=theme,
        lines=LineOptions(numbers=line_numbers),
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Highlight a file with grammar data from an installed VS Code extension.'
    )
    parser.add_argument('extension', type=Path, help='extension directory containing package.json')
    parser.add_argument('source', type=Path, help='UTF-8 source file to highlight')
    parser.add_argument('language', help='language ID or registered alias from the extension')
    parser.add_argument('--theme', type=Path, help='optional VS Code or TextMate theme file')
    parser.add_argument('--line-numbers', action='store_true')
    parser.add_argument(
        '-o', '--output', type=Path, help='write the fragment instead of printing it'
    )
    arguments = parser.parse_args()
    fragment = highlight_from_extension(
        arguments.extension,
        arguments.source,
        arguments.language,
        theme_file=arguments.theme,
        line_numbers=arguments.line_numbers,
    )
    if arguments.output is None:
        print(fragment)
    else:
        arguments.output.write_text(fragment, encoding='utf-8')
        print(f'wrote {arguments.output}')


if __name__ == '__main__':
    main()
