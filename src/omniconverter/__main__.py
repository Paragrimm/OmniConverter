"""``python -m omniconverter``: CLI when conversion flags are given, GUI otherwise."""

import sys


def main() -> int:
    from omniconverter.cli import is_cli_invocation

    if is_cli_invocation(sys.argv[1:]):
        from omniconverter.cli import main as cli_main

        return cli_main()
    from omniconverter.gui.app import main as gui_main

    return gui_main()


if __name__ == "__main__":
    sys.exit(main())
