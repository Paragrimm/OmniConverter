"""Which targets are possible for a source, and which backend handles each pair."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from omniconverter.core.backend import Backend, Conversion
from omniconverter.core.errors import ToolMissingError, UnsupportedConversion
from omniconverter.core.formats import CATEGORY_ORDER, FORMATS, Format, get_format
from omniconverter.core.probe import MediaInfo
from omniconverter.core.tools import ToolLocator

_FORMAT_ORDER = {fid: i for i, fid in enumerate(FORMATS)}


@dataclass(frozen=True)
class TargetChoice:
    format: Format
    available: bool
    missing_tools: tuple[str, ...] = ()  # what to install to make it available


class Registry:
    def __init__(self, backends: Iterable[Backend], locator: ToolLocator) -> None:
        self.locator = locator
        self.backends = list(backends)
        self._index: dict[tuple[str, str], list[tuple[Conversion, Backend]]] = defaultdict(list)
        for backend in self.backends:
            for conv in backend.conversions():
                self._index[(conv.source, conv.target)].append((conv, backend))
        for candidates in self._index.values():
            candidates.sort(key=lambda cb: cb[0].priority, reverse=True)

    def _missing(self, conv: Conversion) -> tuple[str, ...]:
        return tuple(t for t in conv.requires if not self.locator.available(t))

    def _candidates(
        self, source: str, target: str, media: MediaInfo | None
    ) -> list[tuple[Conversion, Backend]]:
        return [(c, b) for c, b in self._index.get((source, target), []) if b.supports(c, media)]

    def resolve(
        self, source: Format, target: Format, media: MediaInfo | None = None
    ) -> tuple[Backend, Conversion]:
        """Best available backend for the pair; raises if unsupported or tools are missing."""
        candidates = self._candidates(source.id, target.id, media)
        if not candidates:
            raise UnsupportedConversion(f"{source.label} → {target.label}")
        for conv, backend in candidates:
            if not self._missing(conv):
                return backend, conv
        raise ToolMissingError(self._missing(candidates[0][0])[0])

    def targets(self, source: Format, media: MediaInfo | None = None) -> list[TargetChoice]:
        choices = []
        target_ids = {dst for (src, dst) in self._index if src == source.id}
        for target_id in target_ids:
            candidates = self._candidates(source.id, target_id, media)
            if not candidates:
                continue
            missing_sets = [self._missing(c) for c, _ in candidates]
            available = any(not m for m in missing_sets)
            missing = () if available else min(missing_sets, key=len)
            choices.append(TargetChoice(get_format(target_id), available, missing))
        return sort_targets(choices)

    def common_targets(
        self, sources: Sequence[tuple[Format, MediaInfo | None]]
    ) -> list[TargetChoice]:
        """Targets possible for *all* sources (multi-file selection)."""
        if not sources:
            return []
        merged: dict[str, TargetChoice] | None = None
        for fmt, media in sources:
            current = {c.format.id: c for c in self.targets(fmt, media)}
            if merged is None:
                merged = current
                continue
            merged = {
                fid: TargetChoice(
                    c.format,
                    c.available and current[fid].available,
                    tuple(dict.fromkeys(c.missing_tools + current[fid].missing_tools)),
                )
                for fid, c in merged.items()
                if fid in current
            }
        return sort_targets((merged or {}).values())


def sort_targets(choices: Iterable[TargetChoice]) -> list[TargetChoice]:
    return sorted(
        choices,
        key=lambda c: (CATEGORY_ORDER.index(c.format.category), _FORMAT_ORDER[c.format.id]),
    )
