import argparse
from pathlib import Path
from hilite import Style, ThemeRule, Highlighter
from examples.demo_assets import html_page, dark_theme, LIGHT_THEME, CUSTOM_THEME, demo_registry

SOURCE = '''def fibonacci(limit: int) -> list[int]:
    """Return Fibonacci numbers below limit."""
    # Start with the two seed values.
    values = [0, 1]
    while values[-1] + values[-2] < limit:
        values.append(values[-1] + values[-2])
    return values

print(fibonacci(100))'''


def build_theme_comparison() -> str:
    highlighter = Highlighter(demo_registry())
    forced_overrides = (
        ThemeRule('comment', Style(foreground='#ff8fab', italic=False)),
        ThemeRule('constant.numeric', Style(background='#40344d', bold=True)),
    )
    sections = [
        (
            'Imported VS Code-style theme data',
            highlighter.highlight(SOURCE, language='python', theme=dark_theme()),
        ),
        (
            'Custom light Theme object',
            highlighter.highlight(SOURCE, language='python', theme=LIGHT_THEME),
        ),
        (
            'Custom dark Theme object',
            highlighter.highlight(SOURCE, language='python', theme=CUSTOM_THEME),
        ),
        (
            'Custom theme with forced overrides',
            highlighter.highlight(
                SOURCE,
                language='python',
                theme=CUSTOM_THEME,
                overrides=forced_overrides,
            ),
        ),
    ]
    return html_page('Themes and overrides', sections)


def main() -> None:
    parser = argparse.ArgumentParser(description='Compare imported, custom, and overridden themes.')
    parser.add_argument('-o', '--output', type=Path, help='write the page instead of printing it')
    arguments = parser.parse_args()
    page = build_theme_comparison()
    if arguments.output is None:
        print(page)
    else:
        arguments.output.write_text(page, encoding='utf-8')
        print(f'wrote {arguments.output}')


if __name__ == '__main__':
    main()
