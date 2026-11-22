"""Security regression tests for Paper Distill MCP Server.

Run: python tests/test_security.py
  or: pytest tests/test_security.py

Covers two reported issues:
  1. Path traversal: a tool argument must never decide where a file is written.
  2. HTTP transport: requests need the right Host, a local Origin and the bearer token.

Tests run without network access or API keys.
"""
import asyncio
import contextlib
import os
import sys
import tempfile
from pathlib import Path

# Ensure project root on sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from generate.daily_digest import generate_all
from generate.obsidian_note import write_paper_notes, write_research_notes
from generate.validation import ensure_within, safe_filename, safe_relative_dir, validate_date
from mcp_server.http_security import (
    ALLOWED_HOSTS_ENV,
    ALLOWED_ORIGINS_ENV,
    TOKEN_ENV,
    LocalRequestGuard,
    load_http_security,
    local_hosts,
)

PORT = 8765
TOKEN = "test-token-0123456789"
PAPER = {"title": "A test paper", "authors": ["Ada Lovelace"], "year": 2026, "doi": "10.1234/test"}


# ── helpers ────────────────────────────────────────────────────────────────

@contextlib.contextmanager
def _environ(**values):
    """Temporarily set environment variables (None removes one)."""
    saved = {key: os.environ.get(key) for key in values}
    try:
        for key, value in values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _files(folder: Path) -> list[str]:
    return sorted(str(p.relative_to(folder)) for p in folder.rglob("*") if p.is_file())


def _bad_dates(outside: Path) -> list:
    return [
        str(outside / "ABS"),            # absolute path
        "../../../../../outside/REL",    # relative traversal
        "2026-11-22/../../x",            # date-like prefix, then traversal
        "..",
        "",
        "2026-13-40",                    # right shape, not a real date
        "2026-1-5",                      # not zero-padded
        "２０２６-11-22",                 # non-ASCII digits
        "2026-11-22\n",
        None,
        20261122,
    ]


def _raises_value_error(func, *args, **kwargs) -> bool:
    try:
        func(*args, **kwargs)
    except ValueError:
        return True
    return False


# ── 1. path traversal ──────────────────────────────────────────────────────

def test_validate_date():
    assert validate_date("2026-11-22") == "2026-11-22"
    assert validate_date("2024-02-29") == "2024-02-29"
    for bad in _bad_dates(Path("/tmp/outside")):
        assert _raises_value_error(validate_date, bad), f"accepted {bad!r}"
    print("  [PASS] validate_date accepts real dates only")


def test_path_helpers():
    assert safe_relative_dir("nlp/agents", "other") == Path("nlp") / "agents"
    assert safe_relative_dir("../../etc", "other") == Path("etc")
    assert safe_relative_dir("/abs/dir", "other") == Path("abs") / "dir"
    assert safe_relative_dir("..\\..\\win", "other") == Path("win")
    assert safe_relative_dir("..", "other") == Path("other")
    assert safe_relative_dir(None, "other") == Path("other")
    assert safe_filename("../../evil", "untitled") == "....evil"
    assert safe_filename("..", "untitled") == "untitled"
    assert safe_filename(None, "untitled") == "untitled"
    assert safe_filename("注意力机制: 综述", "untitled") == "注意力机制 综述"

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "base"
        base.mkdir()
        assert ensure_within(base, base / "a" / "b.md") == base / "a" / "b.md"
        assert _raises_value_error(ensure_within, base, base / ".." / "b.md")
        assert _raises_value_error(ensure_within, base, Path(tmp) / "elsewhere.md")
    print("  [PASS] path helpers keep names inside their folder")


def test_generate_all_rejects_bad_dates():
    with tempfile.TemporaryDirectory() as tmp:
        root, outside = Path(tmp) / "data_dir", Path(tmp) / "outside"
        root.mkdir()
        outside.mkdir()
        for bad in _bad_dates(outside):
            assert _raises_value_error(generate_all, [dict(PAPER)], bad, root), f"accepted {bad!r}"
        assert _files(outside) == [], f"wrote outside the data dir: {_files(outside)}"
        assert _files(root) == [], f"partial output for a rejected date: {_files(root)}"

        result = generate_all([dict(PAPER)], "2026-11-22", root)
        assert Path(result["astro_digest"]).name == "2026-11-22.json"
        assert Path(result["daily_note"]).name == "2026-11-22.md"
        assert all(root.resolve() in Path(p).resolve().parents for p in (result["astro_digest"], result["daily_note"]))
    print("  [PASS] generate_all rejects bad dates and writes nothing for them")


def test_generate_digest_tool_rejects_bad_dates():
    from fastmcp import Client

    from mcp_server.server import mcp

    async def call(arguments: dict) -> bool:
        async with Client(mcp) as client:
            try:
                await client.call_tool("generate_digest", arguments)
            except Exception:
                return False
            return True

    with tempfile.TemporaryDirectory() as tmp:
        root, outside = Path(tmp) / "data_dir", Path(tmp) / "outside"
        outside.mkdir()
        with _environ(PAPER_DISTILL_DATA_DIR=str(root)):
            for bad in (str(outside / "ABS"), "../../../../../outside/REL", "2026-11-22/../../x"):
                accepted = asyncio.run(call({"papers": [dict(PAPER)], "date": bad}))
                assert not accepted, f"tool accepted date {bad!r}"
            hostile_topics = {"topics": [{"area": "../../../../outside/AREA", "title": "../note", "papers": []}]}
            accepted = asyncio.run(call({"papers": [dict(PAPER)], "date": "2026-11-22", "topics": hostile_topics}))
            assert accepted, "a valid date should be accepted"
        assert _files(outside) == [], f"wrote outside the data dir: {_files(outside)}"
        written = _files(root)
        assert "site/src/content/digests/2026-11-22.json" in [w.replace(os.sep, "/") for w in written]
    print("  [PASS] generate_digest tool cannot write outside the data dir")


def test_research_notes_stay_in_notes_folder():
    with tempfile.TemporaryDirectory() as tmp:
        base, outside = Path(tmp) / "vault", Path(tmp) / "outside"
        base.mkdir()
        outside.mkdir()
        topics = {
            "topics": [
                {"area": "../../outside/AREA", "title": "one", "papers": []},
                {"area": str(outside / "ABS"), "title": "two", "papers": []},
                {"area": "..", "title": "../three", "papers": []},
                {"area": "nlp/agents", "title": "four", "papers": []},
            ]
        }
        paths = write_research_notes(topics, "2026-11-22", base)
        notes_root = (base / "研究笔记").resolve()
        assert len(paths) == 4
        for path in paths:
            assert notes_root in path.resolve().parents, f"note escaped: {path}"
        assert (base / "研究笔记" / "nlp" / "agents" / "four.md").exists(), "nested areas must keep working"
        assert _files(outside) == []
    print("  [PASS] research notes stay inside the notes folder")


def test_paper_note_filename_is_sanitized():
    with tempfile.TemporaryDirectory() as tmp:
        out, outside = Path(tmp) / "papers", Path(tmp) / "outside"
        outside.mkdir()
        papers = [dict(PAPER, citekey="../outside/evil"), dict(PAPER, citekey=str(outside / "abs"))]
        paths = write_paper_notes(papers, "2026-11-22", out)
        for path in paths:
            assert path.resolve().parent == out.resolve(), f"paper note escaped: {path}"
        assert _files(outside) == []
    print("  [PASS] paper note file names are sanitized")


# ── 2. HTTP transport ──────────────────────────────────────────────────────

def _guard(**overrides) -> tuple[LocalRequestGuard, list]:
    """Return a guard around a dummy app, and the list that records calls reaching the app."""
    reached: list = []

    async def app(scope, receive, send):
        reached.append(scope["type"])
        if scope["type"] == "http":
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

    options = {"allowed_hosts": local_hosts(PORT), "token": TOKEN}
    options.update(overrides)
    return LocalRequestGuard(app, **options), reached


def _request(guard: LocalRequestGuard, headers: list[tuple[str, str]], method: str = "POST") -> int:
    """Send one HTTP request through the guard and return the response status."""
    sent: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "method": method,
        "path": "/mcp",
        "headers": [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in headers],
    }
    asyncio.run(guard(scope, receive, send))
    return sent[0]["status"]


HOST = ("Host", f"127.0.0.1:{PORT}")
AUTH = ("Authorization", f"Bearer {TOKEN}")


def test_guard_host_header():
    guard, reached = _guard()
    for good in (f"127.0.0.1:{PORT}", f"localhost:{PORT}", f"LOCALHOST:{PORT}", f"[::1]:{PORT}"):
        assert _request(guard, [("Host", good), AUTH]) == 200, good
    assert len(reached) == 4

    for bad in (f"attacker.example:{PORT}", "attacker.example", f"127.0.0.1:{PORT + 1}", "127.0.0.1",
                f"127.0.0.1.attacker.example:{PORT}", ""):
        assert _request(guard, [("Host", bad), AUTH]) == 421, bad
    assert _request(guard, [AUTH]) == 421, "missing Host"
    assert _request(guard, [HOST, ("Host", f"attacker.example:{PORT}"), AUTH]) == 421, "two Host headers"
    assert len(reached) == 4, "a rejected request reached the app"
    print("  [PASS] guard rejects foreign Host headers (DNS rebinding)")


def test_guard_origin_header():
    guard, reached = _guard()
    for good in ("http://localhost:3000", f"http://127.0.0.1:{PORT}", "http://[::1]:5173", "https://localhost"):
        assert _request(guard, [HOST, AUTH, ("Origin", good)]) == 200, good
    for bad in (f"http://attacker.example:{PORT}", "https://attacker.example", "null",
                "http://localhost.attacker.example", "http://127.0.0.1.attacker.example", "file://"):
        assert _request(guard, [HOST, AUTH, ("Origin", bad)]) == 403, bad
    assert len(reached) == 4

    guard, _ = _guard(allowed_origins=["https://app.example.org"])
    assert _request(guard, [HOST, AUTH, ("Origin", "https://app.example.org")]) == 200
    assert _request(guard, [HOST, AUTH, ("Origin", "https://other.example.org")]) == 403
    print("  [PASS] guard rejects web-page Origins")


def test_guard_bearer_token():
    guard, reached = _guard()
    assert _request(guard, [HOST]) == 401, "no token"
    assert _request(guard, [HOST, ("Authorization", "Bearer garbage-not-a-real-token")]) == 401
    assert _request(guard, [HOST, ("Authorization", TOKEN)]) == 401, "token without the Bearer scheme"
    assert _request(guard, [HOST, ("Authorization", f"Basic {TOKEN}")]) == 401
    assert _request(guard, [HOST, AUTH, AUTH]) == 401, "two Authorization headers"
    assert reached == []
    assert _request(guard, [HOST, AUTH]) == 200
    assert _request(guard, [HOST, ("authorization", f"bearer {TOKEN}")]) == 200, "scheme is case-insensitive"
    assert _request(guard, [HOST, AUTH], method="GET") == 200

    # A CORS preflight has no credentials: Host and Origin are still checked.
    assert _request(guard, [HOST, ("Origin", "http://localhost:3000")], method="OPTIONS") == 200
    assert _request(guard, [HOST, ("Origin", "https://attacker.example")], method="OPTIONS") == 403
    assert _raises_value_error(LocalRequestGuard, None, allowed_hosts=local_hosts(PORT), token="")
    print("  [PASS] guard requires the bearer token")


def test_guard_passes_non_http_scopes():
    guard, reached = _guard()

    async def run():
        async def receive():
            return {"type": "lifespan.startup"}

        async def send(message):
            pass

        await guard({"type": "lifespan"}, receive, send)

    asyncio.run(run())
    assert reached == ["lifespan"]
    print("  [PASS] guard leaves lifespan events alone")


def test_load_http_security():
    settings = load_http_security(PORT, {})
    assert settings.token_generated and len(settings.token) >= 32
    assert settings.token != load_http_security(PORT, {}).token, "generated tokens must differ"
    assert settings.allowed_hosts == local_hosts(PORT)

    settings = load_http_security(PORT, {TOKEN_ENV: f"  {TOKEN}  "})
    assert settings.token == TOKEN and not settings.token_generated

    assert _raises_value_error(load_http_security, PORT, {ALLOWED_HOSTS_ENV: "papers.example.org"})
    settings = load_http_security(
        PORT,
        {
            TOKEN_ENV: TOKEN,
            ALLOWED_HOSTS_ENV: "Papers.Example.org, tunnel.example.net:8443",
            ALLOWED_ORIGINS_ENV: "https://App.example.org/",
        },
    )
    assert {"papers.example.org", "tunnel.example.net:8443"} <= settings.allowed_hosts
    assert settings.allowed_origins == {"https://app.example.org"}
    guard, _ = _guard(allowed_hosts=settings.allowed_hosts, allowed_origins=settings.allowed_origins)
    assert _request(guard, [("Host", "papers.example.org"), AUTH]) == 200
    assert _request(guard, [("Host", "evil.example.org"), AUTH]) == 421
    print("  [PASS] HTTP security settings load from the environment")


def test_http_app_end_to_end():
    """The real server app, with the middleware wired the way main() wires it."""
    from starlette.testclient import TestClient

    from mcp_server.server import _http_middleware, mcp

    initialize = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                   "clientInfo": {"name": "security-test", "version": "0"}},
    }
    base_headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}

    with tempfile.TemporaryDirectory() as tmp, _environ(
        PAPER_DISTILL_DATA_DIR=tmp, **{TOKEN_ENV: TOKEN, ALLOWED_HOSTS_ENV: None, ALLOWED_ORIGINS_ENV: None}
    ):
        app = mcp.http_app(path="/mcp", transport="streamable-http", middleware=_http_middleware(PORT))
        with TestClient(app, base_url=f"http://127.0.0.1:{PORT}") as client:
            def post(**headers):
                return client.post("/mcp", json=initialize, headers={**base_headers, **headers}).status_code

            auth = f"Bearer {TOKEN}"
            assert post(Host=f"attacker.example:{PORT}", Origin=f"http://attacker.example:{PORT}",
                        Authorization=auth) == 421
            assert post(Origin="https://attacker.example", Authorization=auth) == 403
            assert post() == 401
            assert post(Authorization="Bearer garbage-not-a-real-token") == 401
            assert post(Authorization=auth) == 200
    print("  [PASS] HTTP app rejects forged Host/Origin and missing tokens end to end")


# ── runner ─────────────────────────────────────────────────────────────────

def main() -> int:
    tests = [(name, func) for name, func in globals().items() if name.startswith("test_") and callable(func)]
    print(f"Running {len(tests)} security tests\n")
    failed = 0
    for name, func in tests:
        try:
            func()
        except Exception as exc:  # report every failure, then exit non-zero
            failed += 1
            print(f"  [FAIL] {name}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
