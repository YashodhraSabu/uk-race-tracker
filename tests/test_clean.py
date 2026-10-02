from tracker.clean import clean_html

PAGE = """<html><head><title>Race</title><style>.x{}</style><script>var t = Date.now();</script></head>
<body>
  <nav><a href="/">Home</a><a href="/enter">Enter</a></nav>
  <header><h1>Bath Half</h1><div class="hero">14 March 2027</div></header>
  <main>
    <p>The ballot opens on <strong>1 May</strong> at 10:00.</p>
    <p>The ballot opens on <strong>1 May</strong> at 10:00.</p>
    <ul><li>Half marathon</li><li>Fun run</li></ul>
    <div aria-hidden="true">decorative</div>
    <form><input name="email"><button>Sign up</button></form>
  </main>
  <footer>&copy; 2026 Organiser Ltd</footer>
</body></html>"""


def test_keeps_visible_text_including_header_dates():
    text = clean_html(PAGE)
    assert text.splitlines() == [
        "Race",
        "Bath Half",
        "14 March 2027",
        "The ballot opens on 1 May at 10:00.",
        "Half marathon",
        "Fun run",
    ]


def test_drops_scripts_menus_footers_and_forms():
    text = clean_html(PAGE)
    for gone in ("Date.now", "Home", "Sign up", "2026 Organiser", "decorative", ".x{}"):
        assert gone not in text


def test_is_stable_across_whitespace_changes():
    assert clean_html(PAGE) == clean_html(PAGE.replace("\n", "\n\n   ").replace("<p>", "<p>  "))


def test_empty_page():
    assert clean_html("   ") == ""
