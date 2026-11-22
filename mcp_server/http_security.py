"""Request checks for the optional HTTP transport.

The HTTP transport listens on 127.0.0.1 and is meant for MCP clients on the same
machine. A port on localhost can still be reached by any web page the user has
open: with DNS rebinding the page points its own domain at 127.0.0.1, and a page
can also send cross-site requests to the port directly. This module closes both
routes and adds authentication:

* the ``Host`` header must name this server, which blocks DNS rebinding;
* an ``Origin`` header, when present, must be a local origin, which blocks
  requests made by web pages;
* every request must carry the bearer token.

Environment variables:

* ``PAPER_DISTILL_HTTP_TOKEN``: the bearer token. If it is not set, a random
  token is generated for each run and printed at startup.
* ``PAPER_DISTILL_ALLOWED_HOSTS``: extra ``Host`` values, comma-separated, for a
  reverse proxy or tunnel in front of the server (for example
  ``papers.example.org``). Requires ``PAPER_DISTILL_HTTP_TOKEN``.
* ``PAPER_DISTILL_ALLOWED_ORIGINS``: extra browser origins, comma-separated
  (for example ``https://app.example.org``).
"""
from __future__ import annotations

import hmac
import secrets
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

TOKEN_ENV = "PAPER_DISTILL_HTTP_TOKEN"
ALLOWED_HOSTS_ENV = "PAPER_DISTILL_ALLOWED_HOSTS"
ALLOWED_ORIGINS_ENV = "PAPER_DISTILL_ALLOWED_ORIGINS"

# Names under which a browser or client on this machine addresses the server.
_LOOPBACK_HOSTNAMES = ("127.0.0.1", "localhost", "[::1]")
_LOOPBACK_ORIGIN_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


@dataclass(frozen=True)
class HttpSecurity:
    """Settings for :class:`LocalRequestGuard`."""

    allowed_hosts: frozenset[str]
    allowed_origins: frozenset[str]
    token: str
    token_generated: bool


def _split_list(value: str) -> list[str]:
    return [item.strip().lower().rstrip("/") for item in value.split(",") if item.strip()]


def local_hosts(port: int) -> frozenset[str]:
    """Return the ``Host`` header values that address this server locally."""
    hosts = {f"{name}:{port}" for name in _LOOPBACK_HOSTNAMES}
    if port == 80:  # clients leave the default port out of the Host header
        hosts.update(_LOOPBACK_HOSTNAMES)
    return frozenset(hosts)


def load_http_security(port: int, environ: Mapping[str, str]) -> HttpSecurity:
    """Build the HTTP security settings from the environment.

    Raises:
        ValueError: if extra hosts are allowed but no token has been set. A
            server that answers to a public host name must not rely on a token
            that changes at every start and is only shown in the local console.
    """
    extra_hosts = _split_list(environ.get(ALLOWED_HOSTS_ENV, ""))
    extra_origins = _split_list(environ.get(ALLOWED_ORIGINS_ENV, ""))

    token = environ.get(TOKEN_ENV, "").strip()
    generated = not token
    if generated:
        if extra_hosts:
            raise ValueError(
                f"{ALLOWED_HOSTS_ENV} is set, so {TOKEN_ENV} must be set to a long random secret."
            )
        token = secrets.token_urlsafe(32)

    return HttpSecurity(
        allowed_hosts=local_hosts(port) | frozenset(extra_hosts),
        allowed_origins=frozenset(extra_origins),
        token=token,
        token_generated=generated,
    )


def _origin_is_local(origin: str) -> bool:
    """Return True for http(s) origins on this machine, such as http://localhost:3000."""
    try:
        parts = urlsplit(origin)
        hostname = (parts.hostname or "").lower()
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and hostname in _LOOPBACK_ORIGIN_HOSTS


def _header_values(scope: Scope, name: bytes) -> list[bytes]:
    return [value for key, value in scope.get("headers", []) if key.lower() == name]


class LocalRequestGuard:
    """ASGI middleware that rejects requests failing the Host, Origin or token check."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        allowed_hosts: Iterable[str],
        token: str,
        allowed_origins: Iterable[str] = (),
    ) -> None:
        if not token:
            raise ValueError("a bearer token is required")
        self.app = app
        self.allowed_hosts = frozenset(host.lower() for host in allowed_hosts)
        self.allowed_origins = frozenset(origin.lower().rstrip("/") for origin in allowed_origins)
        self._token = token.encode("utf-8")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        hosts = _header_values(scope, b"host")
        if len(hosts) != 1 or hosts[0].decode("latin-1").strip().lower() not in self.allowed_hosts:
            await _reject(send, 421, "Misdirected Request: unexpected Host header")
            return

        origins = _header_values(scope, b"origin")
        if origins and not (len(origins) == 1 and self._origin_allowed(origins[0].decode("latin-1"))):
            await _reject(send, 403, "Forbidden: unexpected Origin header")
            return

        # A CORS preflight never carries credentials, so it is checked for Host and Origin only.
        if scope.get("method") != "OPTIONS" and not self._token_matches(_header_values(scope, b"authorization")):
            await _reject(
                send,
                401,
                "Unauthorized: send 'Authorization: Bearer <token>'",
                extra_headers=[(b"www-authenticate", b"Bearer")],
            )
            return

        await self.app(scope, receive, send)

    def _origin_allowed(self, origin: str) -> bool:
        origin = origin.strip()
        return origin.lower().rstrip("/") in self.allowed_origins or _origin_is_local(origin)

    def _token_matches(self, values: list[bytes]) -> bool:
        if len(values) != 1:
            return False
        scheme, _, credential = values[0].strip().partition(b" ")
        return scheme.lower() == b"bearer" and hmac.compare_digest(credential.strip(), self._token)


async def _reject(
    send: Send,
    status: int,
    message: str,
    extra_headers: list[tuple[bytes, bytes]] | None = None,
) -> None:
    body = message.encode("utf-8")
    headers = [
        (b"content-type", b"text/plain; charset=utf-8"),
        (b"content-length", str(len(body)).encode("ascii")),
        *(extra_headers or []),
    ]
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})
