from examples.lines_and_layout import build_line_example
from examples.basic_snippets import SNIPPETS, build_gallery
from examples.themes_and_overrides import build_theme_comparison


def test_language_gallery_renders_every_snippet() -> None:
    page = build_gallery()

    assert all(f'<h2>{heading}</h2>' in page for heading in SNIPPETS)
    assert page.count('data-hilite-code') >= len(SNIPPETS)
    assert '&lt;3' in page


def test_theme_gallery_renders_all_configurations() -> None:
    page = build_theme_comparison()

    assert page.count('data-hilite-code') >= 4
    assert 'Imported VS Code-style theme data' in page
    assert 'Custom theme with forced overrides' in page
    assert 'color:#ff8fab' in page


def test_line_layout_gallery_uses_gutter_and_selected_lines() -> None:
    page = build_line_example()

    assert 'data-hilite-gutter' in page
    assert page.count('data-line=') == 8
    assert 'box-shadow:0 18px 45px rgba(0,0,0,.3)' in page
    assert '40 │' in page
