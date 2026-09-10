import pytest

from lead_agent.utils import email_category, emails_in, normalize_domain, same_domain


def test_normalize_domain_accepts_urls_and_domains():
    assert normalize_domain("HTTPS://www.Example.com/path") == "example.com"
    assert normalize_domain("example.com") == "example.com"


def test_normalize_domain_rejects_invalid_value():
    with pytest.raises(ValueError):
        normalize_domain("not a domain")


def test_extracts_and_classifies_emails():
    assert emails_in("Email SALES@Example.com, invalid@localhost") == ["sales@example.com"]
    assert email_category("sales@example.com") == "sales"


def test_same_domain_does_not_allow_lookalikes():
    assert same_domain("https://docs.example.com/a", "example.com")
    assert not same_domain("https://example.com.evil.test", "example.com")
