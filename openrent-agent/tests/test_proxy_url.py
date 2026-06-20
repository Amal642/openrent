from types import SimpleNamespace

from app.proxy.url import build_account_proxy_url


def test_build_account_proxy_url_prefers_linked_proxy():
    account = SimpleNamespace(
        proxy=SimpleNamespace(
            is_active=True,
            host="proxy.example",
            port=8080,
            username="user@example.com",
            password="p@ss",
        ),
        proxy_server=None,
        proxy_username=None,
        proxy_password=None,
    )

    result = build_account_proxy_url(account)

    assert result == "http://user%40example.com:p%40ss@proxy.example:8080"
