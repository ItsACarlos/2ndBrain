"""Interface for ``python -m brain``."""

from argparse import ArgumentParser
from collections.abc import Sequence

from . import __version__
from .app import main as run_app

__all__ = ["main"]


def main(args: Sequence[str] | None = None) -> None:
    """Entry point — parse CLI args then start the Slack listener."""
    parser = ArgumentParser(
        description="2ndBrain: Gemini-powered Slack→Obsidian capture system"
    )
    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=__version__,
    )
    parser.parse_args(args)
    # After parsing (handles --version / --help), run the actual app
    run_app()


if __name__ == "__main__":
    main()
