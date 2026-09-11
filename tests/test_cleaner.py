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


def test_cleaner_extracts_links_and_emails_from_nav_and_footer():
    html = """
    <html><head><title>Acme</title></head>
    <body>
      <header>
        <nav>
          <a href="/about">About Us</a>
          <a href="/team">Leadership</a>
        </nav>
      </header>
      <main>
        <h1>Welcome to Acme</h1>
        <p>We build tools.</p>
      </main>
      <footer>
        <a href="mailto:support@acme.test">Contact Support</a>
        <a href="https://www.linkedin.com/in/founder-doe">Founder Profile</a>
      </footer>
    </body></html>
    """
    result = clean_page("https://acme.test", html, "httpx", 200, 1000)
    assert "https://acme.test/team" in result.discovered_links
    assert "https://acme.test/about" in result.discovered_links
    assert result.emails == ["support@acme.test"]
    assert result.linkedin_urls == ["https://www.linkedin.com/in/founder-doe"]
    # Boilerplate text should still be removed from the LLM text prompt
    assert "Contact Support" not in result.text
    assert "About Us" not in result.text
    assert "Welcome to Acme" in result.text
