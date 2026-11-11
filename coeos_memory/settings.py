"""Settings, read from one place by the hooks, the commands and the extension.

Order, first match wins:
  1. an environment variable (COEOS_*)
  2. the settings typed in the Coeos Memory extension of the Claude app
  3. ~/.config/coeos-memory/config.json, written by `coeos_memory init`
  4. the default

A secret typed in the extension is kept encrypted by the app and handed only
to the extension's own server. The hooks cannot read it: for them, declare
the key in the environment (see docs/settings.md).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

EXTENSION_ID = "local.mcpb.odyssai.coeos-memory"
CONFIG_FILE = Path.home() / ".config" / "coeos-memory" / "config.json"
DEFAULT_VAULT = Path.home() / "coeos-memory-vault"


def _extension_settings_file() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif (Path.home() / "Library").is_dir():
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "Claude" / "Claude Extensions Settings" / f"{EXTENSION_ID}.json"


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _clean(value) -> str:
    """'' for an unset value, including a placeholder the app left unresolved."""
    value = str(value or "").strip()
    return "" if value.startswith("${") else value


def _get(env: str, key: str, default: str = "") -> str:
    value = _clean(os.environ.get(env))
    if value:
        return value
    extension = _read_json(_extension_settings_file()).get("userConfig")
    if isinstance(extension, dict) and _clean(extension.get(key)):
        return _clean(extension[key])
    return _clean(_read_json(CONFIG_FILE).get(key)) or default


def vault_dir() -> Path:
    """The folder that holds daily/ and knowledge/. Open it in Obsidian."""
    return Path(_get("COEOS_MEMORY_DIR", "memory_dir", str(DEFAULT_VAULT))).expanduser()


def capture_model() -> str:
    """Claude model that summarises a session. A small one is enough."""
    return _get("COEOS_CAPTURE_MODEL", "capture_model", "haiku")


def compile_model() -> str:
    """Claude model that writes the wiki articles."""
    return _get("COEOS_COMPILE_MODEL", "compile_model", "sonnet")


def decision() -> dict:
    """{'url', 'model', 'api_key'}. An empty url means: no decision model.

    `url` is the API base, the part before /systemone, for instance
    https://openrouter.ai/api/v1.
    """
    url = _get("COEOS_DECISION_URL", "decision_endpoint").rstrip("/")
    api_key = _clean(os.environ.get("COEOS_DECISION_API_KEY"))
    if not api_key and "openrouter.ai" in url:
        api_key = _clean(os.environ.get("OPENROUTER_API_KEY"))
    return {
        "url": url,
        "model": _get("COEOS_DECISION_MODEL", "decision_model"),
        "api_key": api_key,
    }


def lightrag() -> dict:
    """{'url', 'api_key'}. An empty url means: nothing is sent to a RAG."""
    return {
        "url": _get("COEOS_LIGHTRAG_URL", "lightrag_url").rstrip("/"),
        "api_key": _clean(os.environ.get("COEOS_LIGHTRAG_API_KEY")),
    }


def rag_sources() -> list[str]:
    """Glob patterns of the files kept in the RAG. Default: the wiki articles."""
    raw = _get("COEOS_RAG_SOURCES", "rag_sources")
    patterns = [p.strip() for p in raw.split(",") if p.strip()] or ["{vault}/knowledge/**/*.md"]
    return [p.replace("{vault}", str(vault_dir())) for p in patterns]


def write_config(values: dict) -> None:
    """Merge `values` into the user config file."""
    config = _read_json(CONFIG_FILE)
    config.update(values)
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
