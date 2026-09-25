"""Exception types. Messages are meant to be shown to users; ``details`` carries tool output."""

from __future__ import annotations


class ConversionError(Exception):
    def __init__(self, message: str, details: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class Cancelled(ConversionError):
    def __init__(self) -> None:
        super().__init__("cancelled")


class ToolMissingError(ConversionError):
    def __init__(self, tool_id: str) -> None:
        from omniconverter.core.tools import tool_label
        from omniconverter.i18n import t

        super().__init__(t("error.tool_missing", tool=tool_label(tool_id)))
        self.tool_id = tool_id


class UnsupportedConversion(ConversionError):
    pass


class OptionError(ConversionError):
    def __init__(self, key: str, problem: str) -> None:
        super().__init__(f"{key}: {problem}")
        self.key = key
