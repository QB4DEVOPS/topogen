"""Gooey-based GUI launcher for topogen."""

from __future__ import annotations

import sys


def main() -> int:
    """Entry point for the optional Gooey GUI.

    Uses Gooey's GooeyParser to build the same argparse UI as the CLI.
    """

    try:
        from gooey import Gooey, GooeyParser  # type: ignore
    except Exception:
        print(
            "Gooey is not installed. Install with: pip install 'topogen[gui]'",
            file=sys.stderr,
        )
        return 1

    # Late imports so CLI use doesn't require Gooey.
    from topogen.main import create_argparser
    from topogen.models import TopogenError

    @Gooey(
        program_name="topogen",
        show_success_modal=False,
        show_failure_modal=False,
        clear_before_run=True,
    )
    def _run() -> int:
        parser = create_argparser(parser_class=GooeyParser)
        args = parser.parse_args()

        # Reuse the existing CLI logic by invoking topogen.main.main().
        # Easiest approach: temporarily replace sys.argv with the parsed args.
        # But argparse doesn't expose a clean round-trip; instead we call
        # topogen.main.main() directly with the already-parsed Namespace.
        # For MVP, we re-run parsing in main() by rebuilding argv.
        # This keeps behavior identical to the CLI.
        #
        # NOTE: Gooey already parsed args from sys.argv, so this argv rebuild
        # is mostly for internal consistency.
        from topogen.main import main as cli_main

        try:
            # cli_main parses sys.argv; Gooey injects args there already.
            return int(cli_main())
        except TopogenError as exc:
            print(str(exc), file=sys.stderr)
            return 1

    return int(_run())


if __name__ == "__main__":
    raise SystemExit(main())
