import os
import copy
from datetime import datetime
from pathlib import Path

import yaml


MAX_PROMPT_VERSIONS = 20


class ConfigStore:
    """Reads/writes data/runtime_config.yaml — the user's working copy.
    If the file doesn't exist, bootstraps from the factory default (config/config.yaml).
    """

    def __init__(self, runtime_path: str, defaults: dict):
        self.runtime_path = Path(runtime_path)
        self.defaults = defaults
        self._data: dict = {}
        self._ensure_runtime_file()

    # --- public API ---

    def load(self) -> dict:
        """Return current runtime config dict."""
        with open(self.runtime_path, "r", encoding="utf-8") as f:
            self._data = yaml.safe_load(f) or {}
        return self._data

    def save_prompt(self, text: str) -> None:
        self._ensure_loaded()
        old = self._data.get("system_prompt", "")
        self._data["system_prompt"] = text
        if text != old:
            self._add_prompt_version(text)
        self._write()

    def save_model_params(self, model: str, temperature: float, max_tokens: int) -> None:
        self._ensure_loaded()
        self._data["model"] = model
        self._data["temperature"] = temperature
        self._data["max_tokens"] = max_tokens
        self._write()

    def save_default_context(self, text: str) -> None:
        self._ensure_loaded()
        self._data["prompt_context_default"] = text
        self._write()

    def save_session_timeout(self, minutes: int) -> None:
        self._ensure_loaded()
        self._data["session_timeout_minutes"] = minutes
        self._write()

    def save_greeting(self, enabled: bool, text: str, patterns: list[str]) -> None:
        self._ensure_loaded()
        self._data["greeting_enabled"] = enabled
        self._data["greeting_text"] = text
        self._data["greeting_patterns"] = patterns
        self._write()

    def get_prompt_versions(self) -> list[dict]:
        self._ensure_loaded()
        return list(reversed(self._data.get("prompt_versions", [])))

    def restore_version(self, index: int) -> str:
        """Restore a prompt version by its index in the reversed list (0 = most recent)."""
        versions = self.get_prompt_versions()
        if index < 0 or index >= len(versions):
            raise IndexError(f"Version index {index} out of range (0-{len(versions)-1})")
        text = versions[index]["prompt_text"]
        self._data["system_prompt"] = text
        self._write()
        return text

    # --- helpers ---

    def _ensure_runtime_file(self) -> None:
        if self.runtime_path.exists():
            self.load()
            return

        os.makedirs(self.runtime_path.parent, exist_ok=True)
        agent = self.defaults.get("agent", {})
        self._data = {
            "system_prompt": agent.get("system_prompt", ""),
            "prompt_context_default": "",
            "model": agent.get("model", "deepseek/deepseek-chat"),
            "temperature": agent.get("temperature", 0.7),
            "max_tokens": agent.get("max_tokens", 500),
            "prompt_versions": [],
            "session_timeout_minutes": 120,
            "greeting_enabled": True,
            "greeting_text": "",
            "greeting_patterns": [],
        }
        self._write()

    def _ensure_loaded(self) -> None:
        if not self._data:
            self.load()

    def _add_prompt_version(self, text: str) -> None:
        versions = self._data.setdefault("prompt_versions", [])
        versions.append({
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "prompt_text": text,
        })
        if len(versions) > MAX_PROMPT_VERSIONS:
            self._data["prompt_versions"] = versions[-MAX_PROMPT_VERSIONS:]

    def _write(self) -> None:
        with open(self.runtime_path, "w", encoding="utf-8") as f:
            yaml.dump(self._data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
