"""Unit tests for _clean_text: escaped angle brackets must survive markup stripping."""

from main import _clean_text


def test_escaped_generics_inside_code_are_preserved():
    html = "<p>Use <code>List&lt;String&gt; names = new ArrayList&lt;&gt;();</code></p>"
    assert _clean_text(html) == "Use `List<String> names = new ArrayList<>();`"


def test_escaped_html_tags_in_prose_are_preserved():
    html = "<p>Wrap it in a &lt;div&gt; and a &lt;b&gt;bold&lt;/b&gt; tag.</p>"
    assert _clean_text(html) == "Wrap it in a <div> and a <b>bold</b> tag."


def test_real_markup_is_still_stripped():
    html = "<p>Hello <a href=\"https://example.com\">world</a><br/>line two</p><pre><code>x = 1\n</code></pre>"
    assert _clean_text(html) == "Hello world\nline two\n\n`x = 1\n`"


def test_escaped_title_is_decoded():
    assert _clean_text("How to sort List&lt;Map&lt;String, Object&gt;&gt; in Java?") == (
        "How to sort List<Map<String, Object>> in Java?"
    )


def test_other_entities_still_decode():
    assert _clean_text("<p>Tom &amp; Jerry say &quot;hi&quot; &#39;there&#39;</p>") == "Tom & Jerry say \"hi\" 'there'"


def test_empty_and_none():
    assert _clean_text(None) == ""
    assert _clean_text("") == ""


if __name__ == "__main__":
    import sys

    failures = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL {name}: {exc}")
    sys.exit(1 if failures else 0)
