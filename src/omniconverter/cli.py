"""Command line interface: ``omniconvert FILE… --to FORMAT``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from omniconverter import __version__
from omniconverter.config import Settings
from omniconverter.core.converter import Converter, SourceFile
from omniconverter.core.errors import ConversionError
from omniconverter.core.formats import FORMATS, Category, get_format
from omniconverter.core.options import Kind, format_time
from omniconverter.core.tools import TOOLS, ToolLocator, install_hint
from omniconverter.i18n import t

_CLI_FLAGS = {"--to", "-t", "--list", "--options", "--tools", "--integrate", "--help", "-h",
              "--version", "--text", "--generate"}
GENERATORS = [f.id for f in FORMATS.values() if f.category is Category.GENERATOR and f.id != "text"]


def is_cli_invocation(argv: Sequence[str]) -> bool:
    return any(a.split("=", 1)[0] in _CLI_FLAGS for a in argv)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="omniconvert",
        description=t("cli.description"),
        epilog=t("cli.epilog"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("files", nargs="*", type=Path, metavar="FILE")
    p.add_argument("--text", metavar="TEXT", help=t("cli.help.text"))
    p.add_argument("--generate", choices=GENERATORS, help=t("cli.help.generate"))
    p.add_argument("-t", "--to", metavar="FORMAT", help=t("cli.help.to"))
    p.add_argument("-o", "--output", type=Path, metavar="PATH", help=t("cli.help.output"))
    p.add_argument("-s", "--set", action="append", default=[], metavar="KEY=VALUE",
                   help=t("cli.help.set"))
    p.add_argument("--overwrite", action="store_true", help=t("cli.help.overwrite"))
    p.add_argument("--list", action="store_true", help=t("cli.help.list"))
    p.add_argument("--options", action="store_true", help=t("cli.help.options"))
    p.add_argument("--tools", action="store_true", help=t("cli.help.tools"))
    p.add_argument("--integrate", choices=("install", "uninstall", "status"),
                   help=t("cli.help.integrate"))
    p.add_argument("-q", "--quiet", action="store_true", help=t("cli.help.quiet"))
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # e.g. cp1252 when redirected on Windows
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    settings = Settings.load()
    settings.apply()
    parser = build_parser()
    args = parser.parse_args(argv)
    converter = Converter(ToolLocator(settings.tool_paths))

    try:
        if args.tools:
            return cmd_tools(converter.locator)
        if args.integrate:
            return cmd_integrate(args.integrate)
        without_file = [x for x in (args.text, args.generate) if x is not None]
        if len(without_file) > 1 or (without_file and args.files):
            parser.error(t("cli.error.source_conflict"))
        if args.text is not None:
            sources = [SourceFile.from_text(args.text)]
        elif args.generate:
            sources = [SourceFile.generator(args.generate)]
        elif not args.files:
            parser.error(t("cli.error.no_files"))
        else:
            sources = [converter.inspect(f) for f in args.files]
        if args.list:
            return cmd_list(converter, sources)
        if not args.to:
            parser.error(t("cli.error.no_target"))
        target = get_format(args.to)
        if args.options:
            return cmd_options(converter, sources[0], target)
        return cmd_convert(converter, sources, target, args)
    except KeyError as exc:
        print(t("cli.error.unknown_format", fmt=exc.args[0]), file=sys.stderr)
        return 2
    except ConversionError as exc:
        print(f"{t('cli.error')}: {exc.message}", file=sys.stderr)
        if exc.details and not args.quiet:
            print(exc.details, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print(f"\n{t('cli.cancelled')}", file=sys.stderr)
        return 130


def parse_sets(pairs: list[str]) -> dict[str, str]:
    values = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not key.strip():
            raise ConversionError(t("cli.error.bad_set", value=pair))
        values[key.strip()] = value.strip()
    return values


def cmd_convert(converter: Converter, sources: list[SourceFile], target, args) -> int:
    raw = parse_sets(args.set)
    output: Path | None = args.output
    many = len(sources) > 1
    if many and output is not None and output.exists() and not output.is_dir():
        raise ConversionError(t("cli.error.output_dir"))
    failures = 0
    for index, source in enumerate(sources, 1):
        values: dict = raw
        if source.path is None:  # fix random defaults (the seed), it is part of the name
            values = converter.resolve_options(source, target, raw)
        if output is None:
            out = converter.output_path(source, target, values)
        elif many or output.is_dir():
            out = converter.output_path(source, target, values, output)
        else:
            out = output
            if out.exists() and not args.overwrite:
                raise ConversionError(t("cli.error.exists", path=str(out)))
        label = f"[{index}/{len(sources)}] " if many else ""
        show_progress = not args.quiet and sys.stderr.isatty()
        progress = _progress_printer(f"{label}{source.name}") if show_progress else None
        try:
            result = converter.convert(source, target, out, values, on_progress=progress,
                                       lenient=many)
        except ConversionError as exc:
            if not many:
                raise
            failures += 1
            print(f"\r{label}{source.name}: {exc.message}", file=sys.stderr)
            continue
        if not args.quiet:
            print(f"\r{label}{source.name} → {result}", file=sys.stderr)
    return 1 if failures else 0


def _progress_printer(name: str):
    def show(fraction: float | None) -> None:
        text = "…" if fraction is None else f"{fraction * 100:5.1f} %"
        print(f"\r{name}  {text}   ", end="", file=sys.stderr, flush=True)

    return show


def cmd_list(converter: Converter, sources: list[SourceFile]) -> int:
    for source in sources:
        media = source.media
        info = ""
        if media and media.duration:
            info = f" · {format_time(media.duration)}"
            if media.width:
                info += f" · {media.width}×{media.height}"
        if source.path is None:
            print(source.name)
        else:
            print(f"{source.name} ({source.format.label}{info})")
        for choice in converter.targets([source]):
            if choice.available:
                print(f"  {choice.format.id:<6} {choice.format.label}")
            else:
                need = ", ".join(TOOLS[x].label for x in choice.missing_tools)
                print(f"  {choice.format.id:<6} {choice.format.label}  "
                      f"({t('cli.needs', tools=need)})")
    return 0


def cmd_options(converter: Converter, source: SourceFile, target) -> int:
    options = converter.options(source, target)
    if not options:
        print(t("cli.no_options"))
        return 0
    for opt in options:
        if opt.kind is Kind.CHOICE:
            values = " | ".join(str(v) for v, _ in opt.choices)
        elif opt.kind is Kind.INT:
            values = f"{opt.minimum}…{opt.maximum}"
        elif opt.kind is Kind.BOOL:
            values = "yes | no"
        elif opt.kind is Kind.TIME:
            values = "1:30 | 0:01:30.5 | 90"
        else:
            values = opt.kind.value
        default = format_time(opt.default) if opt.kind is Kind.TIME else opt.default
        print(f"  {opt.key:<15} {opt.label} [{values}]  default: {default!s}")
    return 0


def cmd_tools(locator: ToolLocator) -> int:
    for tool_id, spec in TOOLS.items():
        path = locator.find(tool_id)
        if path:
            print(f"  ✔ {spec.label:<12} {path}")
        else:
            print(f"  ✘ {spec.label:<12} {t('cli.tool_missing')}: {install_hint(tool_id)}")
    return 0


def cmd_integrate(action: str) -> int:
    from omniconverter import integration

    if action == "status":
        print(t("cli.integration_on") if integration.is_installed() else t("cli.integration_off"))
        return 0
    changed = integration.install() if action == "install" else integration.uninstall()
    for item in changed:
        print(f"  {item}")
    print(t("cli.integration_installed") if action == "install" else t("cli.integration_removed"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
