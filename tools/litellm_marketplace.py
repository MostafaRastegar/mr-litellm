#!/usr/bin/env python3
"""litellm-marketplace — marketplace client for LiteLLM-hosted Claude Code plugins.

Why this exists
---------------
LiteLLM can host a Claude Code plugin marketplace at
    <proxy>/claude-code/marketplace.json
Claude Code consumes it natively (`claude plugin marketplace add ...`), but
OpenCode and Cline CLI have no marketplace concept:

  * `opencode plugin` only installs npm modules.
  * `cline plugin` only installs from a keyword/npm/git/URL/local path.
  * Neither can read a marketplace JSON document.

Both tools *do* read local skills as `<skills_dir>/<name>/SKILL.md`, which is
the exact layout Claude Code plugins ship. So this CLI bridges the gap: it
reads the LiteLLM marketplace, resolves each plugin's git source, and installs
the plugin's skills into every supported agent's skills directory.

Design notes
------------
* Stdlib + `git` only. No pip install required.
* Every install is recorded in a manifest so `remove` deletes only files this
  tool placed there - never a user's own hand-written skills.
* Target directories are resolved per agent and can be overridden with
  LITELLM_MARKETPLACE_TARGETS (colon-separated paths) for testing.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

# -------------------------------------------------------------------------
# Constants
# -------------------------------------------------------------------------

DEFAULT_MARKETPLACE_URL = os.environ.get(
    "LITELLM_MARKETPLACE_URL", "http://localhost:4000/claude-code/marketplace.json"
)
DEFAULT_MARKETPLACE_NAME = os.environ.get("LITELLM_MARKETPLACE_NAME", "litellm")

STATE_DIR = Path(
    os.environ.get("LITELLM_MARKETPLACE_STATE", Path.home() / ".litellm-marketplace")
)
MANIFEST_PATH = STATE_DIR / "manifest.json"
GIT_CACHE_DIR = STATE_DIR / "git-cache"

# Skills directory per supported agent, in install order.
AGENT_SKILL_DIRS: dict[str, Path] = {
    "opencode": Path.home() / ".config" / "opencode" / "skills",
    "cline": Path.home() / ".cline" / "skills",
    "claude": Path.home() / ".claude" / "skills",
}

DEFAULT_PROXY_URL = os.environ.get("LITELLM_PROXY_URL", "http://localhost:4000")

# Agent MCP configuration files
AGENT_MCP_CONFIGS: dict[str, Path] = {
    "opencode": Path.home() / ".config" / "opencode" / "opencode.jsonc",
    "cline": Path.home() / ".cline" / "data" / "settings" / "cline_mcp_settings.json",
    "claude": Path.home() / ".claude.json",
}


# -------------------------------------------------------------------------
# Small helpers
# -------------------------------------------------------------------------


class MarketError(Exception):
    """Any user-facing failure."""


def log(msg: str) -> None:
    print(msg, flush=True)


def ok(msg: str) -> None:
    print(f"  \u2714 {msg}", flush=True)


def warn(msg: str) -> None:
    print(f"  ! {msg}", file=sys.stderr, flush=True)


def die(msg: str, code: int = 1) -> None:
    print(f"\u2718 {msg}", file=sys.stderr, flush=True)
    raise SystemExit(code)


def http_get_json(url: str, token: str | None = None) -> dict[str, Any]:
    """Fetch JSON over HTTP with a stdlib client (no requests dependency)."""
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise MarketError(f"HTTP {exc.code} fetching {url}: {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise MarketError(
            f"Cannot reach {url} ({exc.reason}). Is the LiteLLM proxy running?"
        ) from exc
    except json.JSONDecodeError as exc:
        raise MarketError(f"{url} did not return valid JSON: {exc}") from exc


def run_git(args: list[str], cwd: Path | None = None) -> str:
    """Run git, raising MarketError with git's stderr on failure."""
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except FileNotFoundError as exc:
        raise MarketError("git was not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise MarketError(f"git {' '.join(args)} timed out") from exc
    if proc.returncode != 0:
        raise MarketError(f"git {' '.join(args)} failed:\n{proc.stderr.strip()}")
    return proc.stdout


# -------------------------------------------------------------------------
# Marketplace model
# -------------------------------------------------------------------------


@dataclass
class Plugin:
    name: str
    version: str = ""
    description: str = ""
    category: str = ""
    keywords: list[str] = field(default_factory=list)
    source: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> "Plugin":
        kw = raw.get("keywords") or []
        if isinstance(kw, str):
            kw = [k.strip() for k in kw.split(",") if k.strip()]
        return cls(
            name=raw.get("name", ""),
            version=str(raw.get("version") or ""),
            description=raw.get("description") or raw.get("domain") or "",
            category=raw.get("category") or raw.get("domain") or "",
            keywords=list(kw),
            source=raw.get("source") or {},
        )

    def git_url(self) -> str:
        """Normalise any supported source form into a cloneable git URL."""
        src = self.source.get("source", "")
        if src == "github":
            repo = self.source.get("repo", "")
            if not repo:
                raise MarketError(
                    f"plugin '{self.name}' has a github source with no repo"
                )
            return f"https://github.com/{repo}.git"
        if src in ("url", "git", "git-subdir"):
            url = self.source.get("url", "")
            if not url:
                raise MarketError(
                    f"plugin '{self.name}' has a {src} source with no url"
                )
            return url
        raise MarketError(
            f"plugin '{self.name}' has unsupported source type {src!r} "
            "(supported: github, url, git-subdir)"
        )

    def subdir(self) -> str | None:
        """Relative subdirectory holding the plugin, for git-subdir sources."""
        if self.source.get("source") == "git-subdir":
            return (self.source.get("path") or "").strip("/") or None
        return None

    def label(self) -> str:
        bits = [self.name]
        if self.version:
            bits.append(f"v{self.version}")
        if self.description:
            bits.append(f"\u2014 {self.description}")
        return " ".join(bits)


def fetch_marketplace(url: str) -> tuple[str, list[Plugin]]:
    data = http_get_json(url)
    plugins = [Plugin.from_api(p) for p in data.get("plugins") or []]
    return data.get("name") or DEFAULT_MARKETPLACE_NAME, plugins


# -------------------------------------------------------------------------
# Manifest (so `remove` only deletes what we installed)
# -------------------------------------------------------------------------


def load_manifest() -> dict[str, Any]:
    if not MANIFEST_PATH.exists():
        return {"version": 1, "installed": {}}
    try:
        data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        warn(f"manifest at {MANIFEST_PATH} was unreadable; starting fresh")
        return {"version": 1, "installed": {}}
    data.setdefault("version", 1)
    data.setdefault("installed", {})
    return data


def save_manifest(data: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = MANIFEST_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(MANIFEST_PATH)


# -------------------------------------------------------------------------
# Git cache
# -------------------------------------------------------------------------


def clone_or_update(plugin: Plugin, *, refresh: bool) -> Path:
    """Clone (or fast-forward) the plugin repo; return the checkout path."""
    url = plugin.git_url()
    dest = GIT_CACHE_DIR / plugin.name
    GIT_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    if dest.exists() and (dest / ".git").is_dir():
        if refresh:
            log(f"\u25b8 Refreshing cached clone of {plugin.name}")
            run_git(["fetch", "--depth", "1", "origin", "HEAD"], cwd=dest)
            run_git(["reset", "--hard", "FETCH_HEAD"], cwd=dest)
        return dest

    if dest.exists():
        shutil.rmtree(dest)

    log(f"\u25b8 Cloning {url}")
    with tempfile.TemporaryDirectory(dir=str(GIT_CACHE_DIR)) as tmpd:
        tmp = Path(tmpd) / "repo"
        run_git(["clone", "--depth", "1", url, str(tmp)])
        shutil.move(str(tmp), str(dest))
    return dest


# -------------------------------------------------------------------------
# Skill discovery + install
# -------------------------------------------------------------------------


def find_skill_files(root: Path, subdir: str | None) -> list[Path]:
    """Locate SKILL.md files.

    Search order mirrors how Claude Code plugins are laid out:
      1. <root>/skills/<name>/SKILL.md      (plugin convention)
      2. <root>/<name>/SKILL.md             (loose repo of skills)
      3. <root>/SKILL.md                    (single-skill repo)
    """
    base = root / subdir if subdir else root
    if not base.is_dir():
        raise MarketError(f"plugin path {base} does not exist in the repository")

    found: list[Path] = []

    skills_dir = base / "skills"
    if skills_dir.is_dir():
        found = sorted(skills_dir.glob("*/SKILL.md"))

    if not found:
        found = sorted(
            p
            for p in base.glob("*/SKILL.md")
            if p.parent.name not in {"skills", "node_modules", ".git"}
        )

    if not found and (base / "SKILL.md").is_file():
        found = [base / "SKILL.md"]

    if not found:
        found = sorted(
            p
            for p in base.rglob("SKILL.md")
            if ".git" not in p.parts and "node_modules" not in p.parts
        )

    return found


def target_dirs() -> dict[str, Path]:
    override = os.environ.get("LITELLM_MARKETPLACE_TARGETS")
    if override:
        out: dict[str, Path] = {}
        for raw in override.split(":"):
            if raw.strip():
                p = Path(raw.strip()).expanduser()
                out[p.parent.name] = p
        return out
    return dict(AGENT_SKILL_DIRS)


def install_skills(plugin: Plugin, checkout: Path) -> dict[str, list[str]]:
    """Copy skills into every existing agent skills dir. Returns {agent: [names]}."""
    files = find_skill_files(checkout, plugin.subdir())
    if not files:
        raise MarketError(
            f"no SKILL.md found in {plugin.name} - nothing to install for "
            "OpenCode/Cline"
        )

    dirs = target_dirs()
    existing = {name: d for name, d in dirs.items() if d.parent.is_dir()}
    if not existing:
        raise MarketError(
            "no agent skills directory found "
            f"(looked for: {', '.join(str(d) for d in dirs.values())})"
        )

    installed: dict[str, list[str]] = {}
    for agent, skills_root in existing.items():
        placed: list[str] = []
        for skill_md in files:
            skill_name = skill_md.parent.name
            dest = skills_root / skill_name
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copy2(skill_md, dest / "SKILL.md")
            placed.append(skill_name)
            ok(f"{skill_name} \u2192 {agent}")
        installed[agent] = sorted(placed)
    return installed


def remove_skills(plugin_name: str, record: dict[str, Any]) -> None:
    """Delete only the files we recorded, then prune empty dirs."""
    dirs = target_dirs()
    removed_any = False
    for agent, names in (record.get("installed") or {}).items():
        root = dirs.get(agent)
        if root is None:
            continue
        for name in names:
            skill_dir = root / name
            target = skill_dir / "SKILL.md"
            if target.exists():
                target.unlink()
                removed_any = True
                ok(f"removed {name} from {agent}")
            if skill_dir.is_dir() and not any(skill_dir.iterdir()):
                skill_dir.rmdir()
    if not removed_any:
        log(f"  (nothing on disk for {plugin_name})")

    cache = GIT_CACHE_DIR / plugin_name
    if cache.exists():
        shutil.rmtree(cache)
        ok(f"removed cached clone for {plugin_name}")


# -------------------------------------------------------------------------
# Commands
# -------------------------------------------------------------------------


def cmd_list(args: argparse.Namespace) -> int:
    mkt_name, plugins = fetch_marketplace(args.url)
    installed = load_manifest().get("installed", {})

    if args.json:
        print(
            json.dumps(
                {
                    "marketplace": mkt_name,
                    "plugins": [
                        {**p.__dict__, "installed": p.name in installed}
                        for p in plugins
                    ],
                },
                indent=2,
            )
        )
        return 0

    if not plugins:
        log(f"Marketplace '{mkt_name}' has no published plugins.")
        return 0

    log(f"Marketplace: {mkt_name}  ({args.url})")
    log("")
    for p in plugins:
        mark = "\u2714 installed" if p.name in installed else ""
        log(f"  {mark:>11}  {p.label()}")
        if p.keywords:
            log(f"               keywords: {', '.join(p.keywords)}")
    log("")
    log(f"{len(plugins)} plugin(s). Install with: litellm-marketplace install <name>")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    _, plugins = fetch_marketplace(args.url)
    needle = args.query.lower()
    hits = [
        p
        for p in plugins
        if needle in p.name.lower()
        or needle in p.description.lower()
        or needle in p.category.lower()
        or any(needle in k.lower() for k in p.keywords)
    ]
    if not hits:
        log(f"No plugin matches {args.query!r}.")
        return 1
    for p in hits:
        log(f"  {p.label()}")
    return 0


def pick_plugin(plugins: Iterable[Plugin], name: str) -> Plugin:
    for p in plugins:
        if p.name == name:
            return p
    available = ", ".join(p.name for p in plugins) or "(none)"
    raise MarketError(
        f"plugin '{name}' not found in marketplace. Available: {available}"
    )


def cmd_info(args: argparse.Namespace) -> int:
    _, plugins = fetch_marketplace(args.url)
    plugin = pick_plugin(plugins, args.plugin)
    record = load_manifest()["installed"].get(plugin.name)

    log(plugin.name)
    log(f"  version    : {plugin.version or '(unset)'}")
    log(f"  description: {plugin.description or '(none)'}")
    log(f"  category   : {plugin.category or '(none)'}")
    log(f"  keywords   : {', '.join(plugin.keywords) or '(none)'}")
    log(f"  source     : {plugin.source.get('source', '?')}")
    try:
        log(f"  git url    : {plugin.git_url()}")
    except MarketError as exc:
        log(f"  git url    : (invalid - {exc})")
    if plugin.subdir():
        log(f"  subdir     : {plugin.subdir()}")
    if record:
        log("  installed  : yes")
        for agent, names in (record.get("installed") or {}).items():
            log(f"    {agent}: {', '.join(names)}")
    else:
        log("  installed  : no")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    log("Environment")
    log(f"  marketplace url : {args.url}")
    try:
        mkt_name, plugins = fetch_marketplace(args.url)
        log(f"  reachable       : yes (name={mkt_name}, {len(plugins)} plugin(s))")
    except MarketError as exc:
        log(f"  reachable       : NO - {exc}")
    
    proxy = get_default_proxy_url(getattr(args, "url", None))
    token = getattr(args, "token", None) or find_litellm_token()
    log(f"  litellm proxy   : {proxy}")
    if token:
        try:
            mcp_srvs = fetch_mcp_servers(proxy, token)
            log(f"  mcp endpoint    : reachable ({len(mcp_srvs)} server(s))")
        except Exception as exc:
            log(f"  mcp endpoint    : NO - {exc}")
    else:
        log("  mcp endpoint    : unauthenticated (no LITELLM_MASTER_KEY found)")

    log(f"  state dir       : {STATE_DIR}")
    log(f"  manifest        : {'present' if MANIFEST_PATH.exists() else 'absent'}")
    log("")
    log("Agent skills directories")
    for name, path in target_dirs().items():
        mark = "yes" if path.parent.is_dir() else "NO"
        log(f"  {name:<9} {mark:<4} {path}")
    log("")
    log("Agent MCP configuration files")
    for name, path in AGENT_MCP_CONFIGS.items():
        mark = "yes" if path.is_file() else "NO"
        log(f"  {name:<9} {mark:<4} {path}")
    try:
        run_git(["--version"])
        log("\n  git             : ok")
    except MarketError as exc:
        log(f"\n  git             : FAIL - {exc}")
    return 0




def cmd_install(args: argparse.Namespace) -> int:
    mkt_name, plugins = fetch_marketplace(args.url)
    plugin = pick_plugin(plugins, args.plugin)

    manifest = load_manifest()
    if plugin.name in manifest["installed"] and not args.force:
        log(f"'{plugin.name}' is already installed (use --force to reinstall).")
        return 0

    log(f"\u25b8 Installing {plugin.label()}")
    checkout = clone_or_update(plugin, refresh=args.force)
    installed = install_skills(plugin, checkout)

    manifest["installed"][plugin.name] = {
        "marketplace": mkt_name,
        "version": plugin.version,
        "source": plugin.source,
        "git_dir": str(checkout),
        "installed": installed,
    }
    save_manifest(manifest)

    total = sum(len(v) for v in installed.values())
    log("")
    log(
        f"\u2714 Installed {plugin.name}: {total} skill-slot(s) across "
        f"{len(installed)} agent(s)."
    )
    if "opencode" not in installed:
        warn("OpenCode skills dir not found; skipped OpenCode.")
    if "cline" not in installed:
        warn("Cline skills dir not found; skipped Cline.")
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    manifest = load_manifest()
    targets = [args.plugin] if args.plugin else sorted(manifest["installed"])
    if not targets:
        log("Nothing installed from the marketplace yet.")
        return 0

    _, plugins = fetch_marketplace(args.url)
    failures = 0
    for name in targets:
        try:
            plugin = pick_plugin(plugins, name)
            log(f"\u25b8 Updating {name}")
            checkout = clone_or_update(plugin, refresh=True)
            installed = install_skills(plugin, checkout)
            prev = manifest["installed"].get(name, {})
            manifest["installed"][name] = {
                "marketplace": prev.get("marketplace", DEFAULT_MARKETPLACE_NAME),
                "version": plugin.version,
                "source": plugin.source,
                "git_dir": str(checkout),
                "installed": installed,
            }
            ok(f"{name} updated to v{plugin.version or '?'}")
        except MarketError as exc:
            warn(f"{name}: {exc}")
            failures += 1

    save_manifest(manifest)
    if failures:
        log(f"\u2718 {failures} plugin(s) failed to update.")
        return 1
    log("\u2714 All plugins up to date.")
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    manifest = load_manifest()
    names = [args.plugin] if args.plugin else sorted(manifest["installed"])
    if not names:
        log("Nothing installed from the marketplace yet.")
        return 0

    for name in names:
        record = manifest["installed"].get(name)
        if record is None:
            warn(f"'{name}' is not tracked by this tool; skipping.")
            continue
        log(f"\u25b8 Removing {name}")
        remove_skills(name, record)
        del manifest["installed"][name]

    save_manifest(manifest)
    log("\u2714 Done.")
    return 0


# -------------------------------------------------------------------------
# MCP Models and Discovery
# -------------------------------------------------------------------------


@dataclass
class MCPServer:
    server_id: str
    server_name: str
    alias: str = ""
    description: str = ""
    transport: str = "http"
    url: str | None = None
    command: str | None = None
    args: list[str] = field(default_factory=list)

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> "MCPServer":
        return cls(
            server_id=raw.get("server_id", ""),
            server_name=raw.get("server_name") or raw.get("alias") or "",
            alias=raw.get("alias", ""),
            description=raw.get("description") or "",
            transport=raw.get("transport") or "http",
            url=raw.get("url"),
            command=raw.get("command"),
            args=raw.get("args") or [],
        )

    def label(self) -> str:
        bits = [self.server_name]
        if self.description:
            bits.append(f"\u2014 {self.description}")
        return " ".join(bits)


def get_default_proxy_url(mkt_url: str | None = None) -> str:
    if os.environ.get("LITELLM_PROXY_URL"):
        return os.environ["LITELLM_PROXY_URL"].rstrip("/")
    if mkt_url:
        import urllib.parse
        p = urllib.parse.urlsplit(mkt_url)
        if p.scheme and p.netloc:
            return f"{p.scheme}://{p.netloc}"
    return DEFAULT_PROXY_URL.rstrip("/")


def find_litellm_token() -> str:
    """Find LiteLLM master / API key from env or .env file."""
    for var in ("LITELLM_MASTER_KEY", "LITELLM_API_KEY", "OPENAI_API_KEY"):
        val = os.environ.get(var)
        if val:
            return val

    candidates = [
        Path.cwd() / ".env",
        Path(__file__).resolve().parent.parent / ".env",
    ]
    for env_path in candidates:
        if env_path.is_file():
            try:
                for line in env_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    for key in ("LITELLM_MASTER_KEY", "LITELLM_API_KEY", "OPENAI_API_KEY"):
                        if line.startswith(f"{key}="):
                            val = line.split("=", 1)[1].strip()
                            if (val.startswith('"') and val.endswith('"')) or (
                                val.startswith("'") and val.endswith("'")
                            ):
                                val = val[1:-1]
                            if val:
                                return val
            except OSError:
                pass
    return ""


def fetch_mcp_servers(proxy_url: str, token: str) -> list[MCPServer]:
    url = f"{proxy_url.rstrip('/')}/v1/mcp/server"
    data = http_get_json(url, token=token)
    if isinstance(data, list):
        return [MCPServer.from_api(s) for s in data]
    return []


# -------------------------------------------------------------------------
# MCP Agent Config Updaters
# -------------------------------------------------------------------------


def strip_jsonc_comments(text: str) -> str:
    import re
    def replacer(match):
        s = match.group(0)
        return " " if s.startswith("/") else s
    pattern = re.compile(
        r'//.*?$|/\*.*?\*/|\'(?:\\.|[^\\\'])*\'|"(?:\\.|[^\\"])*"',
        re.DOTALL | re.MULTILINE,
    )
    stripped = re.sub(pattern, replacer, text)
    return re.sub(r',(\s*[}\]])', r'\1', stripped)


def load_json_or_jsonc(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    raw = path.read_text(encoding="utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return json.loads(strip_jsonc_comments(raw))


def save_atomic_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def update_cline_mcp(server_name: str, endpoint_url: str, token: str) -> bool:
    path = AGENT_MCP_CONFIGS["cline"]
    data = load_json_or_jsonc(path)
    data.setdefault("mcpServers", {})
    data["mcpServers"][server_name] = {
        "transport": {
            "type": "streamableHttp",
            "url": endpoint_url,
            "headers": {
                "Authorization": f"Bearer {token}"
            },
        }
    }
    save_atomic_json(path, data)
    return True


def remove_cline_mcp(server_name: str) -> bool:
    path = AGENT_MCP_CONFIGS["cline"]
    if not path.is_file():
        return False
    data = load_json_or_jsonc(path)
    if "mcpServers" in data and server_name in data["mcpServers"]:
        del data["mcpServers"][server_name]
        save_atomic_json(path, data)
        return True
    return False


def is_cline_mcp_installed(server_name: str) -> bool:
    path = AGENT_MCP_CONFIGS["cline"]
    if not path.is_file():
        return False
    data = load_json_or_jsonc(path)
    return server_name in data.get("mcpServers", {})


def update_opencode_mcp(server_name: str, endpoint_url: str, token: str) -> bool:
    path = AGENT_MCP_CONFIGS["opencode"]
    data = load_json_or_jsonc(path)
    data.setdefault("mcp", {})
    data["mcp"][server_name] = {
        "type": "remote",
        "url": endpoint_url,
        "headers": {
            "Authorization": f"Bearer {token}"
        },
    }
    save_atomic_json(path, data)
    return True


def remove_opencode_mcp(server_name: str) -> bool:
    path = AGENT_MCP_CONFIGS["opencode"]
    if not path.is_file():
        return False
    data = load_json_or_jsonc(path)
    if "mcp" in data and server_name in data["mcp"]:
        del data["mcp"][server_name]
        save_atomic_json(path, data)
        return True
    return False


def is_opencode_mcp_installed(server_name: str) -> bool:
    path = AGENT_MCP_CONFIGS["opencode"]
    if not path.is_file():
        return False
    data = load_json_or_jsonc(path)
    return server_name in data.get("mcp", {})


def update_claude_mcp(server_name: str, endpoint_url: str, token: str) -> bool:
    path = AGENT_MCP_CONFIGS["claude"]
    data = load_json_or_jsonc(path)
    data.setdefault("mcpServers", {})
    data["mcpServers"][server_name] = {
        "type": "http",
        "url": endpoint_url,
        "headers": {
            "Authorization": f"Bearer {token}"
        },
    }
    save_atomic_json(path, data)
    return True


def remove_claude_mcp(server_name: str) -> bool:
    path = AGENT_MCP_CONFIGS["claude"]
    if not path.is_file():
        return False
    data = load_json_or_jsonc(path)
    if "mcpServers" in data and server_name in data["mcpServers"]:
        del data["mcpServers"][server_name]
        save_atomic_json(path, data)
        return True
    return False


def is_claude_mcp_installed(server_name: str) -> bool:
    path = AGENT_MCP_CONFIGS["claude"]
    if not path.is_file():
        return False
    data = load_json_or_jsonc(path)
    return server_name in data.get("mcpServers", {})


MCP_AGENT_HANDLERS = {
    "cline": (update_cline_mcp, remove_cline_mcp, is_cline_mcp_installed),
    "opencode": (update_opencode_mcp, remove_opencode_mcp, is_opencode_mcp_installed),
    "claude": (update_claude_mcp, remove_claude_mcp, is_claude_mcp_installed),
}



# -------------------------------------------------------------------------
# MCP Commands
# -------------------------------------------------------------------------


def cmd_mcp_list(args: argparse.Namespace) -> int:
    proxy = get_default_proxy_url(getattr(args, "url", None))
    token = getattr(args, "token", None) or find_litellm_token()
    if not token:
        raise MarketError(
            "LiteLLM authentication token is required to list MCP servers. "
            "Set LITELLM_MASTER_KEY in environment or pass --token."
        )

    servers = fetch_mcp_servers(proxy, token)
    if getattr(args, "json", False):
        out = []
        for s in servers:
            installed_in = [
                ag for ag, (_, _, is_inst) in MCP_AGENT_HANDLERS.items() if is_inst(s.server_name)
            ]
            out.append({
                "server_name": s.server_name,
                "server_id": s.server_id,
                "description": s.description,
                "transport": s.transport,
                "url": f"{proxy}/{s.server_name}/mcp",
                "installed_in": installed_in,
            })
        print(json.dumps(out, indent=2))
        return 0

    if not servers:
        log(f"No MCP servers found on {proxy}.")
        return 0

    log(f"LiteLLM MCP Servers ({proxy}/v1/mcp/server)")
    log("")
    for s in servers:
        installed_in = [
            ag for ag, (_, _, is_inst) in MCP_AGENT_HANDLERS.items() if is_inst(s.server_name)
        ]
        status = f"[{', '.join(installed_in)}]" if installed_in else ""
        log(f"  {s.server_name:<20} {s.description}")
        log(f"    endpoint: {proxy}/{s.server_name}/mcp {status}")
    log("")
    log(f"{len(servers)} server(s). Install with: litellm-marketplace mcp install <server>")
    return 0


def cmd_mcp_install(args: argparse.Namespace) -> int:
    proxy = get_default_proxy_url(getattr(args, "url", None))
    token = getattr(args, "token", None) or find_litellm_token()
    if not token:
        raise MarketError(
            "LiteLLM authentication token is required to configure MCP servers. "
            "Set LITELLM_MASTER_KEY in environment or pass --token."
        )

    servers = fetch_mcp_servers(proxy, token)
    server_names = {s.server_name: s for s in servers}
    if args.server not in server_names:
        avail = ", ".join(server_names.keys()) or "(none)"
        raise MarketError(f"MCP server '{args.server}' not found on proxy {proxy}. Available: {avail}")

    server = server_names[args.server]
    endpoint_url = f"{proxy}/{server.server_name}/mcp"

    agent_choice = getattr(args, "agent", "all")
    target_agents = list(MCP_AGENT_HANDLERS.keys()) if agent_choice == "all" else [agent_choice]
    log(f"\u25b8 Installing MCP server '{server.server_name}' ({endpoint_url})")

    installed_agents = []
    for ag in target_agents:
        updater, _, _ = MCP_AGENT_HANDLERS[ag]
        updater(server.server_name, endpoint_url, token)
        ok(f"configured for {ag} ({AGENT_MCP_CONFIGS[ag]})")
        installed_agents.append(ag)

    # Record in manifest
    manifest = load_manifest()
    manifest.setdefault("mcp_servers", {})
    manifest["mcp_servers"][server.server_name] = {
        "url": endpoint_url,
        "agents": installed_agents,
    }
    save_manifest(manifest)
    log(f"\u2714 Installed {server.server_name} into {len(installed_agents)} agent(s).")
    return 0


def cmd_mcp_remove(args: argparse.Namespace) -> int:
    agent_choice = getattr(args, "agent", "all")
    target_agents = list(MCP_AGENT_HANDLERS.keys()) if agent_choice == "all" else [agent_choice]
    manifest = load_manifest()
    installed_mcp = manifest.get("mcp_servers", {})

    names = [args.server] if args.server else list(installed_mcp.keys())
    if not names:
        log("No MCP servers tracked in manifest to remove.")
        return 0

    for name in names:
        log(f"\u25b8 Removing MCP server '{name}'")
        for ag in target_agents:
            _, remover, _ = MCP_AGENT_HANDLERS[ag]
            if remover(name):
                ok(f"removed from {ag}")
            else:
                log(f"  (not configured in {ag})")
        if name in installed_mcp:
            del installed_mcp[name]

    manifest["mcp_servers"] = installed_mcp
    save_manifest(manifest)
    log("\u2714 Done.")
    return 0


def cmd_mcp_sync(args: argparse.Namespace) -> int:
    proxy = get_default_proxy_url(getattr(args, "url", None))
    token = getattr(args, "token", None) or find_litellm_token()
    if not token:
        raise MarketError(
            "LiteLLM authentication token is required to sync MCP servers. "
            "Set LITELLM_MASTER_KEY in environment or pass --token."
        )

    servers = fetch_mcp_servers(proxy, token)
    if not servers:
        log(f"No MCP servers available on {proxy} to sync.")
        return 0

    agent_choice = getattr(args, "agent", "all")
    target_agents = list(MCP_AGENT_HANDLERS.keys()) if agent_choice == "all" else [agent_choice]
    log(f"\u25b8 Syncing {len(servers)} MCP server(s) to agent(s): {', '.join(target_agents)}")

    manifest = load_manifest()
    manifest.setdefault("mcp_servers", {})

    for s in servers:
        endpoint_url = f"{proxy}/{s.server_name}/mcp"
        installed_agents = []
        for ag in target_agents:
            updater, _, _ = MCP_AGENT_HANDLERS[ag]
            updater(s.server_name, endpoint_url, token)
            ok(f"{s.server_name} \u2192 {ag}")
            installed_agents.append(ag)
        manifest["mcp_servers"][s.server_name] = {
            "url": endpoint_url,
            "agents": installed_agents,
        }

    save_manifest(manifest)
    log(f"\u2714 Synced {len(servers)} MCP server(s).")
    return 0

# -------------------------------------------------------------------------
# CLI
# -------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="litellm-marketplace",
        description=(
            "Install LiteLLM-hosted Claude Code plugins as OpenCode / Cline "
            "skills. Claude Code reads the marketplace natively; this tool "
            "brings the same plugins to agents that have no marketplace support."
        ),
    )
    p.add_argument(
        "--url",
        default=DEFAULT_MARKETPLACE_URL,
        help=f"marketplace.json URL (default: {DEFAULT_MARKETPLACE_URL})",
    )
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("list", help="list plugins in the marketplace")
    s.add_argument("--json", action="store_true", help="machine-readable output")
    s.set_defaults(func=cmd_list)

    s = sub.add_parser("search", help="search plugins by name/description/keyword")
    s.add_argument("query")
    s.set_defaults(func=cmd_search)

    s = sub.add_parser("install", help="install a plugin's skills")
    s.add_argument("plugin")
    s.add_argument("-f", "--force", action="store_true", help="reinstall if present")
    s.set_defaults(func=cmd_install)

    s = sub.add_parser("update", help="update installed plugins to latest")
    s.add_argument("plugin", nargs="?", help="plugin name (default: all)")
    s.set_defaults(func=cmd_update)

    s = sub.add_parser("remove", help="remove installed plugin skills")
    s.add_argument("plugin", nargs="?", help="plugin name (default: all)")
    s.set_defaults(func=cmd_remove)

    s = sub.add_parser("info", help="show details for one plugin")
    s.add_argument("plugin")
    s.set_defaults(func=cmd_info)

    s = sub.add_parser("doctor", help="check connectivity and agent directories")
    s.set_defaults(func=cmd_doctor)

    # MCP subparser: litellm-marketplace mcp <list|install|remove|sync>
    mcp_parser = sub.add_parser("mcp", help="manage LiteLLM MCP servers")
    mcp_parser.add_argument(
        "--token",
        default=None,
        help="LiteLLM API key (default: read from LITELLM_MASTER_KEY or .env)",
    )
    mcp_sub = mcp_parser.add_subparsers(dest="mcp_command", required=True)

    ml = mcp_sub.add_parser("list", help="list MCP servers discovered on LiteLLM")
    ml.add_argument("--json", action="store_true", help="machine-readable output")
    ml.set_defaults(func=cmd_mcp_list)

    mi = mcp_sub.add_parser("install", help="configure a LiteLLM MCP server in agents")
    mi.add_argument("server", help="server name (e.g. deepwiki)")
    mi.add_argument(
        "--agent",
        choices=["cline", "opencode", "claude", "all"],
        default="all",
        help="target agent (default: all)",
    )
    mi.set_defaults(func=cmd_mcp_install)

    mr = mcp_sub.add_parser("remove", help="remove an MCP server configuration")
    mr.add_argument("server", nargs="?", help="server name (default: all installed)")
    mr.add_argument(
        "--agent",
        choices=["cline", "opencode", "claude", "all"],
        default="all",
        help="target agent (default: all)",
    )
    mr.set_defaults(func=cmd_mcp_remove)

    ms = mcp_sub.add_parser("sync", help="sync all LiteLLM MCP servers to agents")
    ms.add_argument(
        "--agent",
        choices=["cline", "opencode", "claude", "all"],
        default="all",
        help="target agent (default: all)",
    )
    ms.set_defaults(func=cmd_mcp_sync)

    # Top-level convenience aliases: litellm-marketplace mcp-list, mcp-install, mcp-remove, mcp-sync
    al = sub.add_parser("mcp-list", help="alias for mcp list")
    al.add_argument("--token", default=None, help="LiteLLM API key")
    al.add_argument("--json", action="store_true", help="machine-readable output")
    al.set_defaults(func=cmd_mcp_list)

    ai = sub.add_parser("mcp-install", help="alias for mcp install")
    ai.add_argument("server", help="server name")
    ai.add_argument("--token", default=None, help="LiteLLM API key")
    ai.add_argument(
        "--agent",
        choices=["cline", "opencode", "claude", "all"],
        default="all",
        help="target agent (default: all)",
    )
    ai.set_defaults(func=cmd_mcp_install)

    ar = sub.add_parser("mcp-remove", help="alias for mcp remove")
    ar.add_argument("server", nargs="?", help="server name")
    ar.add_argument(
        "--agent",
        choices=["cline", "opencode", "claude", "all"],
        default="all",
        help="target agent (default: all)",
    )
    ar.set_defaults(func=cmd_mcp_remove)

    as_alias = sub.add_parser("mcp-sync", help="alias for mcp sync")
    as_alias.add_argument("--token", default=None, help="LiteLLM API key")
    as_alias.add_argument(
        "--agent",
        choices=["cline", "opencode", "claude", "all"],
        default="all",
        help="target agent (default: all)",
    )
    as_alias.set_defaults(func=cmd_mcp_sync)


    return p


def main(argv: list[str] | None = None) -> int:
    # If invoked as litellm-mcp or mcp is passed as first arg shorthand
    if argv is None:
        argv = sys.argv[1:]
    prog_name = Path(sys.argv[0]).name
    if prog_name == "litellm-mcp" and argv and argv[0] not in ("-h", "--help"):
        if argv[0] not in ("list", "install", "remove", "sync"):
            argv = ["mcp", *argv]
        else:
            argv = ["mcp", *argv]

    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except MarketError as exc:
        die(str(exc))
        return 1
    except KeyboardInterrupt:
        print()
        return 130



if __name__ == "__main__":
    raise SystemExit(main())
