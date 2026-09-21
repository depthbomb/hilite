import argparse
from pathlib import Path
from examples.demo_assets import html_page, CUSTOM_THEME, demo_registry
from hilite import (
    HtmlLayout,
    GutterStyle,
    Highlighter,
    LineOptions,
    LineSelection,
    LineHighlightStyle,
)

SOURCE = """const inventory = [
  { name: "keyboard", stock: 8 },
  { name: "monitor", stock: 0 },
  { name: "mouse", stock: 14 },
];

const available = inventory.filter((item) => item.stock > 0);
console.log(`Available: ${available.length}`);"""


def build_line_example() -> str:
    highlighter = Highlighter(demo_registry())
    layout = HtmlLayout(
        font_family='"Cascadia Code", "JetBrains Mono", monospace',
        font_size='15px',
        line_height='1.65',
        padding='1.25rem',
        border='1px solid #514263',
        border_radius='0.75rem',
        tab_size=2,
        trusted_css={'box-shadow': '0 18px 45px rgba(0,0,0,.3)'},
    )
    lines = LineOptions(
        numbers=True,
        number_start=40,
        emphasize=LineSelection(lines={3}, ranges=[(7, 8)]),
        gutter=GutterStyle(
            min_width='4.5ch',
            padding='1.25rem 0.85rem',
            separator=' │',
        ),
        highlight=LineHighlightStyle(
            background='#40344d',
            foreground='#ffffff',
            bold=True,
        ),
    )
    fragment = highlighter.highlight(
        SOURCE,
        language='javascript',
        theme=CUSTOM_THEME,
        layout=layout,
        lines=lines,
    )
    return html_page('Line numbers and layout', [('Configured JavaScript block', fragment)])


def main() -> None:
    parser = argparse.ArgumentParser(description='Show line numbers, emphasis, and layout options.')
    parser.add_argument('-o', '--output', type=Path, help='write the page instead of printing it')
    arguments = parser.parse_args()
    page = build_line_example()
    if arguments.output is None:
        print(page)
    else:
        arguments.output.write_text(page, encoding='utf-8')
        print(f'wrote {arguments.output}')


if __name__ == '__main__':
    main()
