"""Command-line entrypoint for uvx and installed tools."""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import cast

from open_claude_design import bridge
from open_claude_design.auth import (
    DesignAuthError,
    automatic_browser_login_available,
    delete_standalone_credential,
    login_design,
)
from open_claude_design.config import (
    BRIDGE_COMMAND_NAMES,
    DEFAULT_INSTALL_SCOPE,
    INSTALL_SCOPES,
    VERSION,
)
from open_claude_design.installer import (
    Action,
    InstallError,
    Scope,
    doctor,
    package_summary,
    run_skills_action,
)

BRIDGE_COMMANDS = frozenset(BRIDGE_COMMAND_NAMES)


def _agents(value: str) -> tuple[str, ...]:
    selected = tuple(part.strip() for part in value.split(",") if part.strip())
    if not selected:
        raise argparse.ArgumentTypeError("at least one agent is required")
    invalid = sorted(agent for agent in selected if re.fullmatch(r"[a-z0-9][a-z0-9-]*", agent) is None)
    if invalid:
        raise argparse.ArgumentTypeError(f"invalid agent id(s): {', '.join(invalid)}")
    return selected


def _add_install_options(parser: argparse.ArgumentParser) -> None:
    target = parser.add_mutually_exclusive_group()
    target.add_argument(
        "--agents",
        type=_agents,
        help="Comma-separated skills CLI agent ids; omitted auto-detects installed agents.",
    )
    target.add_argument(
        "--all-agents",
        action="store_true",
        help="Install for every available Agent Skills integration.",
    )
    parser.add_argument("--scope", choices=INSTALL_SCOPES, default=DEFAULT_INSTALL_SCOPE)
    parser.add_argument("--yes", "-y", action="store_true", help="Accept detected agents without prompting.")
    parser.add_argument("--dry-run", action="store_true", help="Report changes without writing files.")
    parser.add_argument("--json", action="store_true", help="Output JSON.")


def build_parser() -> argparse.ArgumentParser:
    """Build the public CLI parser."""
    parser = argparse.ArgumentParser(prog="open-claude-design")
    parser.add_argument("--version", action="version", version=VERSION)
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name in ("install", "update"):
        child = subparsers.add_parser(name, help=f"{name.title()} portable Agent Skills.")
        _add_install_options(child)

    remove = subparsers.add_parser("uninstall", help="Remove Open Claude Design skills from every agent in one scope.")
    remove.add_argument("--scope", choices=INSTALL_SCOPES, default=DEFAULT_INSTALL_SCOPE)
    remove.add_argument("--yes", "-y", action="store_true", help="Remove without prompting.")
    remove.add_argument("--dry-run", action="store_true", help="Report changes without writing files.")
    remove.add_argument("--json", action="store_true", help="Output JSON.")

    login = subparsers.add_parser("login", help="Connect a Claude.ai account to Claude Design.")
    login.add_argument(
        "--manual",
        action="store_true",
        help="Print a browser URL and paste the returned code instead of using a localhost callback.",
    )
    login.add_argument(
        "--timeout",
        type=int,
        default=300,
        metavar="SECONDS",
        help="Browser callback timeout (default: 300).",
    )

    logout = subparsers.add_parser("logout", help="Remove Open Claude Design's standalone credential.")
    logout.add_argument("--yes", "-y", action="store_true", help="Remove without prompting.")

    check = subparsers.add_parser("doctor", help="Verify installed artifacts and bridge prerequisites.")
    target = check.add_mutually_exclusive_group()
    target.add_argument("--agents", type=_agents, help="Comma-separated skills CLI agent ids.")
    target.add_argument("--all-agents", action="store_true", help="Check every supported agent.")
    check.add_argument("--scope", choices=INSTALL_SCOPES, default=DEFAULT_INSTALL_SCOPE)
    check.add_argument("--offline", action="store_true", help="Skip live Claude Design authentication.")
    check.add_argument("--json", action="store_true", help="Output JSON.")

    listing = subparsers.add_parser("list", help="List packaged skills.")
    listing.add_argument("--json", action="store_true", help="Output JSON.")

    return parser


def _selected_agents(args: argparse.Namespace) -> tuple[str, ...]:
    if getattr(args, "all_agents", False):
        return ("*",)
    return cast(tuple[str, ...], getattr(args, "agents", None) or ())


def _print(payload: object, *, json_mode: bool) -> None:
    if json_mode:
        print(json.dumps(payload, ensure_ascii=True))
    elif isinstance(payload, list):
        for item in payload:
            text = str(item)
            print(
                "".join(
                    character
                    if unicodedata.category(character) not in {"Cc", "Cf", "Zl", "Zp"}
                    else f"\\u{ord(character):04x}"
                    for character in text
                )
            )
    else:
        print(json.dumps(payload, ensure_ascii=True, indent=2))


def main(argv: list[str] | None = None) -> int:
    """Run the Open Claude Design CLI."""
    incoming = list(sys.argv[1:] if argv is None else argv)
    if incoming and incoming[0] in BRIDGE_COMMANDS:
        return bridge.main(incoming)
    args = build_parser().parse_args(incoming)
    if args.command == "list":
        payload = package_summary()
        _print(payload, json_mode=args.json)
        return 0

    try:
        if args.command == "login":
            if args.timeout < 1:
                raise DesignAuthError("--timeout must be at least one second.")
            if not args.manual and not automatic_browser_login_available():
                raise DesignAuthError(
                    "No local browser session is available. Run open-claude-design login --manual in an "
                    "interactive terminal; open its URL on your host browser and paste the returned code into "
                    "that terminal, not into a coding-agent chat."
                )
            login_design(
                manual=args.manual,
                timeout_seconds=args.timeout,
                allow_manual_fallback=sys.stdin.isatty(),
            )
            return 0
        if args.command == "logout":
            if not args.yes:
                if not sys.stdin.isatty():
                    raise DesignAuthError("logout requires --yes when stdin is not interactive.")
                answer = input("Remove the Open Claude Design credential? [y/N] ").strip().lower()
                if answer not in {"y", "yes"}:
                    print("Credential kept.")
                    return 0
            removed = delete_standalone_credential()
            print("Open Claude Design credential removed." if removed else "No standalone credential was stored.")
            return 0
        agents = _selected_agents(args)
        scope = cast(Scope, args.scope)
        if args.command in {"install", "update", "uninstall"}:
            payload = run_skills_action(
                cast(Action, args.command),
                agents,
                scope,
                project_root=Path.cwd(),
                yes=args.yes,
                dry_run=args.dry_run,
                capture_output=args.json,
            )
        elif args.command == "doctor":
            payload = doctor(agents, scope, project_root=Path.cwd(), check_auth=not args.offline)
        else:
            raise InstallError(f"Unknown command: {args.command}")
    except (DesignAuthError, InstallError, OSError, ValueError) as error:
        if getattr(args, "json", False):
            print(json.dumps({"error": str(error)}, ensure_ascii=True))
        else:
            safe_error = "".join(
                character
                if unicodedata.category(character) not in {"Cc", "Cf", "Zl", "Zp"}
                else f"\\u{ord(character):04x}"
                for character in str(error)
            )
            print(f"✗ {safe_error}", file=sys.stderr)
        return 1
    _print(payload, json_mode=getattr(args, "json", False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
