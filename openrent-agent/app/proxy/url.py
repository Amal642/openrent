from urllib.parse import quote, urlsplit, urlunsplit


def build_account_proxy_url(account):
    """Build an authenticated proxy URL without logging its credentials."""
    linked = getattr(account, "proxy", None)
    if linked and linked.is_active and linked.host:
        server = f"http://{linked.host}:{linked.port}"
        if not linked.username:
            return server
        username = quote(linked.username, safe="")
        password = quote(linked.password or "", safe="")
        return f"http://{username}:{password}@{linked.host}:{linked.port}"

    proxy_server = (getattr(account, "proxy_server", None) or "").strip()
    if not proxy_server:
        return None

    parsed = urlsplit(
        proxy_server if "://" in proxy_server else f"http://{proxy_server}"
    )
    proxy_username = getattr(account, "proxy_username", None)
    if not proxy_username:
        return urlunsplit(parsed)

    username = quote(proxy_username, safe="")
    password = quote(getattr(account, "proxy_password", None) or "", safe="")
    netloc = parsed.netloc.split("@", 1)[-1]
    return urlunsplit(
        (
            parsed.scheme,
            f"{username}:{password}@{netloc}",
            parsed.path,
            parsed.query,
            parsed.fragment,
        )
    )
