"""CLI mirrors the local engine; output artifacts never overwrite implicitly."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

from .engine import (default_request, generate, make_bundle, propose,
                     validate_bundle, validate_request)


def read(path):
    try:
        return json.loads(Path(path).read_text(), parse_constant=lambda x: (_ for _ in ()).throw(ValueError(f"non-finite {x}")))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(str(exc)) from exc


def write(path, value, force=False):
    text = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if not path:
        print(text, end="")
        return
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("w" if force else "x") as f:
            f.write(text)
    except FileExistsError as exc:
        raise ValueError(f"output exists: {path}; choose a new path or use --force") from exc


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m boulderlab")
    sub = parser.add_subparsers(dest="command", required=True)
    defaults = sub.add_parser("defaults")
    defaults.add_argument("--body", choices=["A", "B"], default="A")
    defaults.add_argument("--scenario", choices=["foot_first", "sidepull", "foot_reposition"], default="foot_first")
    defaults.add_argument("--mode", choices=["free", "fixed"], default="free")
    defaults.add_argument("--angle", type=float, default=0)
    defaults.add_argument("--hand-moves", type=int, default=2)
    defaults.add_argument("--seed", type=int, default=42)
    defaults.add_argument("--budget", type=int, default=3)
    for name in ("generate", "propose", "evaluate"):
        p = sub.add_parser(name)
        p.add_argument("--request", required=True)
        if name == "evaluate":
            p.add_argument("--candidates", required=True)
    check = sub.add_parser("validate")
    source = check.add_mutually_exclusive_group(required=True)
    source.add_argument("--request")
    source.add_argument("--bundle")
    bundle = sub.add_parser("bundle")
    bundle.add_argument("--run", required=True)
    for p in (defaults, *[sub.choices[n] for n in ("generate", "propose", "evaluate", "bundle")]):
        p.add_argument("--out")
        p.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "defaults":
            result = default_request(args.body, args.scenario, args.mode, args.angle, args.hand_moves, args.seed, args.budget)
        elif args.command == "validate":
            if args.request:
                validate_request(read(args.request))
            else:
                validate_bundle(read(args.bundle))
            print(json.dumps({"valid": True}))
            return 0
        elif args.command == "bundle":
            run = Path(args.run)
            result = validate_bundle(read(run / "bundle.json" if run.is_dir() else run))
        else:
            request = read(args.request)
            validate_request(request)
            if args.command == "propose":
                result = [propose(request, i) for i in range(request["budget"])]
            elif args.command == "generate":
                result = generate(request)
            else:
                candidates = read(args.candidates)
                if isinstance(candidates, dict):
                    candidates = candidates.get("candidates", [candidates])
                result = make_bundle(request, candidates)
        if args.command in {"generate", "evaluate"} and args.out and not Path(args.out).suffix:
            directory = Path(args.out)
            if directory.exists() and not args.force:
                raise ValueError(f"run directory exists: {directory}")
            directory.mkdir(parents=True, exist_ok=True)
            for name, data in [("request", result["request"]), ("candidates", result["candidates"]),
                               ("evaluations", result["evaluations"]), ("manifest", result["manifest"]), ("bundle", result)]:
                write(directory / f"{name}.json", data, args.force)
        else:
            write(args.out, result, args.force)
        return 0
    except (ValueError, TypeError, KeyError) as exc:
        print(f"Invalid input: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Execution error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
