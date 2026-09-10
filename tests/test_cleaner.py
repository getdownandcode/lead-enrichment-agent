from lead_agent.cleaner import clean_page


def test_cleaner_removes_boilerplate_and_prioritizes_relevant_links():
    html = """
    <html><head><title>Acme</title><meta name='description' content='Builds widgets'></head>
    <body><nav>Menus and things</nav><main><h1>Widget platform</h1><p>Talk to us: hello@acme.test</p>
    <a href='/pricing'>Pricing</a><a href='/about'>About</a>
    <a href='https://www.linkedin.com/in/jane-doe'>Jane</a></main><script>bad()</script></body></html>
    """
    result = clean_page("https://acme.test", html, "httpx", 200, 1000)
    assert result.title == "Acme"
    assert "Menus" not in result.text
    assert result.emails == ["hello@acme.test"]
    assert result.discovered_links[0] == "https://acme.test/about"
    assert result.linkedin_urls == ["https://www.linkedin.com/in/jane-doe"]
