"""SSRF guard tests for user/admin-supplied outbound URLs.

conftest sets OUTBOUND_ALLOW_PRIVATE_HOSTS=true (worker tests use real local
receivers), so these tests force the production behaviour explicitly.
"""

import pytest

from app.core import outbound
from app.core.config import settings
from app.core.exceptions import ValidationFailedError


@pytest.fixture(autouse=True)
def _strict(monkeypatch):
    monkeypatch.setattr(settings, "outbound_allow_private_hosts", False)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/hook",
        "http://localhost/hook",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.5/hook",
        "http://[::1]/hook",
        "http://metadata.google.internal/hook",
        "http://receiver.local/hook",
        "ftp://example.com/hook",
        "http:///no-host",
    ],
)
def test_private_or_invalid_urls_are_rejected(url):
    with pytest.raises(ValidationFailedError):
        outbound.validate_outbound_url(url)
    with pytest.raises(ValidationFailedError):
        outbound.assert_deliverable_url(url)


def test_public_literal_ip_is_allowed():
    url = "https://93.184.216.34/hook"
    assert outbound.validate_outbound_url(url) == url
    assert outbound.assert_deliverable_url(url) == url


def test_unresolvable_host_is_rejected_at_delivery():
    with pytest.raises(ValidationFailedError):
        outbound.assert_deliverable_url("https://no-such-host.invalid/hook")


def test_flag_allows_private_hosts(monkeypatch):
    monkeypatch.setattr(settings, "outbound_allow_private_hosts", True)
    assert outbound.validate_outbound_url("http://127.0.0.1/hook")
