import sys

from omniconverter.cli import is_cli_invocation

if is_cli_invocation(sys.argv[1:]):
    # e.g. "OmniConverter.AppImage --to mp4 clip.mov" or "--integrate install"
    from omniconverter.cli import main
else:
    from omniconverter.gui.app import main

sys.exit(main())
