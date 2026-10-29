"""Command line entry point for the NeuSymNav runtime.

Imports for the runtime and its optional dependencies are delayed until the
selected command is executed. Importing this module therefore stays safe for
headless source checks and does not import Qt, a simulator, or model packages.
"""
from __future__ import annotations

import argparse
import importlib
import json
import math
import sys
from typing import Any


MAX_CAMPAIGN_DURATION_S = 600.0
_OUTCOMES = {"completed", "failed", "incomplete"}


class _JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        print(json.dumps({"error": "invalid_arguments", "message": message}), file=sys.stderr)
        raise SystemExit(2)


def _duration(value: str) -> float:
    try:
        duration = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("duration must be a finite number in (0, 600] seconds") from exc
    if not math.isfinite(duration) or duration <= 0 or duration > MAX_CAMPAIGN_DURATION_S:
        raise argparse.ArgumentTypeError("duration must be a finite number in (0, 600] seconds")
    return duration


def _parser() -> argparse.ArgumentParser:
    parser = _JsonArgumentParser(prog="neusymnav", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True, parser_class=_JsonArgumentParser)

    preflight = commands.add_parser("preflight", help="check configured runtime readiness")
    preflight.add_argument("--config", required=True, metavar="PATH")

    run = commands.add_parser("run", help="run a bounded simulator campaign")
    run.add_argument("--config", required=True, metavar="PATH")
    run.add_argument("--duration-s", required=True, type=_duration, metavar="N")
    run.add_argument("--out", required=True, metavar="PATH")

    replay = commands.add_parser("replay", help="replay one recorded episode")
    replay.add_argument("--input", required=True, metavar="PATH")
    replay.add_argument("--config", required=True, metavar="PATH")
    replay.add_argument("--out", required=True, metavar="PATH")

    evaluate = commands.add_parser("evaluate", help="evaluate an offline suite")
    evaluate.add_argument("--suite", required=True, metavar="PATH")
    evaluate.add_argument("--out", required=True, metavar="PATH")
    return parser


def _load_launcher():
    return importlib.import_module("neusymnav.runtime.launcher")


def _emit_result(result: Any) -> int:
    if not isinstance(result, dict):
        raise ValueError("command returned a non-object result; expected a JSON object")
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0


def _emit_outcome(result: Any) -> int:
    if not isinstance(result, dict):
        raise ValueError("runtime returned a non-object result; expected an outcome object")
    outcome = result.get("outcome")
    if outcome not in _OUTCOMES:
        raise ValueError("runtime result must set outcome to completed, failed, or incomplete")
    _emit_result(result)
    return 0 if outcome == "completed" else 1


def _evaluate(suite: str, out: str) -> int:
    try:
        protocol = importlib.import_module("neusymnav.evaluation.protocol")
    except ModuleNotFoundError as exc:
        if exc.name in {"neusymnav.evaluation", "neusymnav.evaluation.protocol"}:
            raise RuntimeError(
                "offline evaluation is not available yet: evaluation.protocol is scheduled for P10"
            ) from exc
        raise
    result = protocol.evaluate_suite(suite, out=out)
    return _emit_outcome(result)


def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "evaluate":
        return _evaluate(args.suite, args.out)

    launcher = _load_launcher()
    if args.command == "preflight":
        result = launcher.preflight(args.config)
        if not isinstance(result, dict) or type(result.get("ready")) is not bool:
            raise ValueError("launcher preflight must return an object with a boolean ready field")
        _emit_result(result)
        return 0 if result["ready"] else 1
    if args.command == "run":
        result = launcher.run(args.config, duration_s=args.duration_s, out=args.out)
        return _emit_outcome(result)
    if args.command == "replay":
        result = launcher.replay(args.input, args.config, out=args.out)
        return _emit_outcome(result)
    raise ValueError(f"unsupported command: {args.command}")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return _dispatch(args)
    except Exception as exc:
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
