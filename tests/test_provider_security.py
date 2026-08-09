from __future__ import annotations

from datetime import date

import httpx
import pytest

from litwatch.config import Topic
from litwatch.provider_security import ProviderBaseUrlError, validate_provider_base_url
from litwatch.sources.arxiv import ArxivSource
from litwatch.sources.crossref import CrossrefSource
from litwatch.sources.openalex import OpenAlexSource
from litwatch.sources.semantic_scholar import SemanticScholarSource


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1",
        "https://127.0.0.1",
        "https://0.0.0.0",
        "https://localhost",
        "https://service.localhost",
        "https://10.0.0.1",
        "https://172.16.0.1",
        "https://192.168.1.1",
        "https://169.254.169.254",
        "https://100.64.0.1",
        "https://224.0.0.1",
        "https://[::1]",
        "https://[fc00::1]",
        "https://[fe80::1]",
        "https://host.docker.internal",
    ],
)
def test_provider_url_rejects_local_and_non_public_targets(url: str):
    def private_resolver(_hostname: str, _port: int) -> tuple[str, ...]:
        return ("192.168.65.2",)

    with pytest.raises(ProviderBaseUrlError):
        validate_provider_base_url(url, resolver=private_resolver)


def test_provider_url_allows_hostname_only_when_all_dns_answers_are_public():
    def public_resolver(_hostname: str, _port: int) -> tuple[str, ...]:
        return ("8.8.8.8", "1.1.1.1")

    url = "https://provider.example.test/api/search"

    assert validate_provider_base_url(url, resolver=public_resolver) == url


def test_provider_url_rejects_hostname_when_any_dns_answer_is_private():
    def rebound_resolver(_hostname: str, _port: int) -> tuple[str, ...]:
        return ("8.8.8.8", "10.0.0.7")

    with pytest.raises(ProviderBaseUrlError, match="non-public"):
        validate_provider_base_url(
            "https://provider.example.test/api/search",
            resolver=rebound_resolver,
        )


def test_provider_url_rejects_dns_failure():
    def failed_resolver(_hostname: str, _port: int) -> tuple[str, ...]:
        raise OSError("offline test resolver")

    with pytest.raises(ProviderBaseUrlError, match="safely resolved"):
        validate_provider_base_url(
            "https://provider.example.test/api/search",
            resolver=failed_resolver,
        )


@pytest.mark.parametrize(
    "source",
    [
        OpenAlexSource(),
        SemanticScholarSource(),
        ArxivSource(min_request_interval=0),
        CrossrefSource(),
    ],
)
def test_provider_clients_disable_automatic_redirects(source):
    assert source.client.follow_redirects is False
    source.client.close()


def test_public_endpoint_redirect_to_private_target_is_not_followed():
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(
            302,
            headers={"location": "https://127.0.0.1/private"},
            request=request,
        )

    source = SemanticScholarSource(
        base_url="https://provider.example.test",
        max_retries=0,
    )
    source.client.close()
    source.client = httpx.Client(
        follow_redirects=False,
        transport=httpx.MockTransport(handler),
    )
    topic = Topic(id="test", name="Test", query="underwater acoustics")

    with pytest.raises(httpx.HTTPStatusError):
        source.search(topic, date(2020, 1, 1), date(2026, 8, 9), 1)

    assert len(requests) == 1
    assert requests[0].startswith("https://provider.example.test/")
