"""Optional browser regression checks; set HILITE_BROWSER to a Chromium executable."""

import os
import pytest
from hilite import HtmlLayout, Highlighter, LineOptions, LineSelection


@pytest.mark.parametrize('source', ['one\n\nthree\n', '\n', '', 'one\n' + 'wide ' * 100])
@pytest.mark.parametrize('emphasized', [False, True])
def test_line_layout_and_copy_text(source, emphasized):
    executable = os.environ.get('HILITE_BROWSER')
    if not executable:
        pytest.skip('set HILITE_BROWSER to run browser layout checks')
    playwright = pytest.importorskip('playwright.sync_api')
    highlighter = Highlighter()
    total = source.count('\n') + 1
    fragment = highlighter.highlight(
        source,
        language='plain',
        layout=HtmlLayout(padding='23px', font_size='16px'),
        lines=LineOptions(
            numbers=True,
            emphasize=LineSelection(ranges=[(1, total)]) if emphasized else LineSelection(),
        ),
    )
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch(executable_path=executable, headless=True)
        page = browser.new_page(viewport={'width': 700, 'height': 700})
        page.set_content(fragment)
        observed = page.evaluate("""() => {
            const code = document.querySelector('[data-hilite-code]');
            const gutter = document.querySelector('[data-hilite-gutter]');
            const rows = [...code.querySelectorAll('[data-line]')];
            const style = getComputedStyle(gutter);
            return {
                text: code.textContent,
                rowTops: rows.map(row => row.getBoundingClientRect().top),
                rowHeights: rows.map(row => row.getBoundingClientRect().height),
                gutterTop: gutter.getBoundingClientRect().top + parseFloat(style.paddingTop),
                lineHeight: parseFloat(style.lineHeight),
                codeFont: getComputedStyle(code).fontSize,
                codeHeight: code.getBoundingClientRect().height,
            };
        }""")
        browser.close()
    assert observed['text'] == source
    assert observed['codeFont'] == '16px'
    assert abs(observed['codeHeight'] - total * observed['lineHeight']) < 1
    assert len(observed['rowTops']) == (total if emphasized else 0)
    for index, top in enumerate(observed['rowTops']):
        assert abs(top - (observed['gutterTop'] + index * observed['lineHeight'])) < 1
        assert abs(observed['rowHeights'][index] - observed['lineHeight']) < 1
