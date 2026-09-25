"""User settings. Deliberately tiny: no history, no recently used files, no telemetry IDs."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from omniconverter import APP_NAME, runtime


def config_dir() -> Path:
    override = os.environ.get("OMNICONVERTER_CONFIG_DIR")
    if override:
        return Path(override)
    if runtime.is_portable():
        return runtime.app_dir() / "settings"
    from platformdirs import user_config_path

    return user_config_path(APP_NAME, appauthor=False)


@dataclass
class Settings:
    language: str = "auto"  # "auto", "de" or "en"
    tool_paths: dict[str, str] = field(default_factory=dict)

    @classmethod
    def path(cls) -> Path:
        return config_dir() / "settings.json"

    @classmethod
    def load(cls) -> Settings:
        try:
            data = json.loads(cls.path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        settings = cls()
        if isinstance(data.get("language"), str):
            settings.language = data["language"]
        if isinstance(data.get("tool_paths"), dict):
            settings.tool_paths = {str(k): str(v) for k, v in data["tool_paths"].items() if v}
        return settings

    def save(self) -> None:
        path = self.path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        os.replace(tmp, path)

    def apply(self) -> None:
        """Activate the language setting."""
        from omniconverter.i18n import set_language

        set_language(None if self.language == "auto" else self.language)
