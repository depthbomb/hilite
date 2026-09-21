import argparse
from pathlib import Path
from hilite import HtmlLayout, Highlighter
from examples.demo_assets import html_page, dark_theme, demo_registry

SNIPPETS = {
    'Python': (
        'python',
        """from dataclasses import dataclass

@dataclass
class Greeter:
    name: str

    def greet(self) -> str:
        # Text is escaped before it reaches HTML.
        return f"Hello, {self.name} <3"

print(Greeter("Ada").greet())""",
    ),
    'JavaScript': (
        'javascript',
        """const users = ["Ada", "Grace", "Linus"];

async function greetAll(names) {
  // Template strings keep their nested interpolation scope.
  return names.map((name) => `Hello, ${name}!`);
}

console.log(await greetAll(users));""",
    ),
    'HTML with embedded JavaScript': (
        'html',
        """<!doctype html>
<button class="greeter" data-name="Ada">Say hello</button>
<script>
  const button = document.querySelector(".greeter");
  button.addEventListener("click", () => alert(`Hello, ${button.dataset.name}!`));
</script>""",
    ),
    'JSON': (
        'json',
        """{
  "name": "hilite",
  "python": 3.14,
  "features": ["themes", "line numbers", "overrides"],
  "published": false
}""",
    ),
    'Shell': (
        'shell',
        '''#!/usr/bin/env bash
set -eu

name="${1:-world}"
# The source remains separate from the line-number gutter.
printf "Hello, %s!\\n" "$name"''',
    ),
}


def build_gallery() -> str:
    highlighter = Highlighter(demo_registry())
    theme = dark_theme()
    layout = HtmlLayout(border='1px solid #3b4252', border_radius='0.65rem')
    sections = [
        (
            heading,
            highlighter.highlight(source, language=language, theme=theme, layout=layout),
        )
        for heading, (language, source) in SNIPPETS.items()
    ]
    return html_page('Language gallery', sections)


def main() -> None:
    parser = argparse.ArgumentParser(description='Render several languages into one HTML page.')
    parser.add_argument('-o', '--output', type=Path, help='write the page instead of printing it')
    arguments = parser.parse_args()
    page = build_gallery()
    if arguments.output is None:
        print(page)
    else:
        arguments.output.write_text(page, encoding='utf-8')
        print(f'wrote {arguments.output}')


if __name__ == '__main__':
    main()
