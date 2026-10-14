"""Loopback-only HTTP bridge for the local Beta Atelier workbench."""
from __future__ import annotations

import argparse
import json
import logging
import math
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from uuid import uuid4

from .engine import default_request, generate, evaluate, make_bundle, validate_bundle, catalog_metadata
from .beta_audit import audit_beta

ROOT = Path(__file__).resolve().parent.parent
MAX_BODY = 8 * 1024 * 1024
SCENARIOS = [
    {"id": "foot_first", "label": "脚先行", "description": "先调整脚位，再完成手部换点。"},
    {"id": "sidepull", "label": "侧拉横移", "description": "围绕有方向的手点组织横移；受力尚未验证。"},
    {"id": "foot_reposition", "label": "脚点重定位", "description": "保持手部接触，重新安排脚位与后续换手。"},
]
STYLE_EXAMPLES = (
    ("power", "力量与爆发"),
    ("sustained", "持续输出"),
    ("technical", "技术变化"),
)
ROUTE_EXAMPLES = (
    ("mixed_flow", "难点后转换与缓和"),
    ("power_finish", "前段消耗后力量收尾"),
    ("sustained_finish", "技巧转换后连续输出"),
)
SETTING_EXAMPLES = (
    ("diagonal_balance", "斜向移重"),
    ("opposing_sidepulls", "对向侧拉"),
    ("roof_exit", "仰角转出"),
)
WALL_EXAMPLES = (("overhang", "25°仰角"), ("roof", "立面—水平屋檐—出口"),
                 ("dihedral", "凹角"), ("arete", "凸角"))


def setting_examples(hold_source: str = "assets") -> dict:
    if hold_source not in {"assets", "templates"}:
        raise ValueError("岩点来源必须是 assets 或 templates。")
    examples = []
    for program, label in SETTING_EXAMPLES:
        prefix = "setting-templates" if hold_source == "templates" else "setting"
        path = ROOT / "fixtures" / f"{prefix}-{program}-bundle.json"
        if not path.is_file():
            raise FileNotFoundError("定线迭代示例尚未生成，请运行 .venv/bin/python scripts/prepare_demo.py --profile setting。")
        examples.append({"id": program, "label": label,
                         "bundle": validate_bundle(json.loads(path.read_text(encoding="utf-8")))})
    return {"examples": examples}


def generate_setting_comparison(settings: dict) -> dict:
    if set(settings) - {"body_id", "seed", "budget", "hold_source", "wall_profile"}:
        raise ValueError("定线迭代对照包含未支持的参数。")
    requests = [(program, label, default_request(profile="setting", setting_program=program, **settings))
                for program, label in SETTING_EXAMPLES]
    examples = []
    for program, label, request in requests:
        bundle = generate(request)
        save_run(bundle)
        examples.append({"id": program, "label": label, "bundle": bundle})
    return {"examples": examples}


def wall_examples(wall_profile: str | None = None) -> dict:
    if wall_profile is not None and wall_profile not in dict(WALL_EXAMPLES):
        raise ValueError("unknown wall_profile")
    examples = []
    for profile, label in WALL_EXAMPLES:
        if wall_profile is not None and wall_profile != profile:
            continue
        path = ROOT / "fixtures" / f"wall-{profile}-bundle.json"
        if not path.is_file():
            raise FileNotFoundError("墙形适配示例尚未生成。")
        bundle = validate_bundle(json.loads(path.read_text(encoding="utf-8")))
        if bundle["request"].get("setting_design", {}).get("wall_profile") != profile:
            raise ValueError("wall example profile does not match fixture name")
        examples.append({"id": profile, "label": label, "bundle": bundle})
    return {"examples": examples}


def route_examples() -> dict:
    examples = []
    for program, label in ROUTE_EXAMPLES:
        path = ROOT / "fixtures" / f"route-{program}-bundle.json"
        if not path.is_file():
            raise FileNotFoundError("完整线路示例尚未生成，请运行 .venv/bin/python scripts/prepare_demo.py --profile route。")
        examples.append({"id": program, "label": label,
                         "bundle": validate_bundle(json.loads(path.read_text(encoding="utf-8")))})
    return {"examples": examples}


def generate_route_comparison(settings: dict) -> dict:
    allowed = {"body_id", "angle_deg", "hand_moves", "seed", "budget"}
    if set(settings) - allowed:
        raise ValueError("完整线路对照包含未支持的参数。")
    shared = {"hand_moves": 10, **settings}
    requests = [(program, label, default_request(profile="route", route_program=program, **shared))
                for program, label in ROUTE_EXAMPLES]
    examples = []
    for program, label, request in requests:
        bundle = generate(request)
        save_run(bundle)
        examples.append({"id": program, "label": label, "bundle": bundle})
    return {"examples": examples}


def style_examples() -> dict:
    """Load separately signed bundles; never combine unlike request fingerprints."""
    examples = []
    for goal, label in STYLE_EXAMPLES:
        path = ROOT / "fixtures" / f"style-{goal}-bundle.json"
        if not path.is_file():
            raise FileNotFoundError("风格示例尚未生成，请运行 .venv/bin/python scripts/prepare_demo.py。")
        bundle = validate_bundle(json.loads(path.read_text(encoding="utf-8")))
        examples.append({"id": goal, "label": label, "bundle": bundle})
    return {"examples": examples}


def generate_style_comparison(settings: dict) -> dict:
    """Compare objectives under shared board/body/rhythm and bounded search settings."""
    allowed = {"body_id", "angle_deg", "seed", "budget", "rhythm"}
    if set(settings) - allowed:
        raise ValueError("风格对照包含未支持的参数。")
    shared = {"rhythm": "late_crux", **settings}
    # Construct all requests before spending time on any generation.
    requests = [(goal, label, default_request(profile="style", style_goal=goal, **shared))
                for goal, label in STYLE_EXAMPLES]
    examples = []
    for goal, label, request in requests:
        bundle = generate(request)
        save_run(bundle)
        examples.append({"id": goal, "label": label, "bundle": bundle})
    return {"examples": examples}


def save_run(bundle: dict) -> None:
    directory = ROOT / ".runtime" / "runs"
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{uuid4().hex}.json"
    destination.write_text(json.dumps(bundle, ensure_ascii=False, allow_nan=False, indent=2), encoding="utf-8")


def finite_tree(value):
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("数据含无效数值。请使用有限数字。")
    if isinstance(value, dict):
        for child in value.values():
            finite_tree(child)
    elif isinstance(value, list):
        for child in value:
            finite_tree(child)


class Handler(BaseHTTPRequestHandler):
    server_version = "BetaAtelier/0.1"

    def respond(self, code: int, data: dict) -> None:
        raw = json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def local_request(self) -> bool:
        host = urlparse("http://" + self.headers.get("Host", "")).hostname
        if host not in {"localhost", "127.0.0.1", "::1"}:
            self.respond(403, {"error": "本工具仅接受本机请求。"})
            return False
        origin = self.headers.get("Origin")
        allowed_ports = {5173, 4173, 8765, self.server.server_port, self.server.web_port}
        if origin and origin not in {f"http://{host}:{port}" for host in ("127.0.0.1", "localhost") for port in allowed_ports}:
            self.respond(403, {"error": "请求来源不是本地工作台。"})
            return False
        return True

    def do_GET(self):
        if not self.local_request():
            return
        path = urlparse(self.path).path
        try:
            if path == "/api/health":
                self.respond(200, {"ok": True, "version": "0.1.0"})
            elif path == "/api/defaults":
                self.respond(200, {"request": default_request(), "body_profiles": [default_request(body_id=b)["body"] for b in ("A", "B")], "scenarios": SCENARIOS, "catalog_templates": catalog_metadata()})
            elif path == "/api/style-examples":
                self.respond(200, style_examples())
            elif path == "/api/route-examples":
                self.respond(200, route_examples())
            elif path == "/api/setting-examples":
                self.respond(200, setting_examples(parse_qs(urlparse(self.path).query).get("hold_source", ["assets"])[0]))
            elif path == "/api/wall-examples":
                self.respond(200, wall_examples(parse_qs(urlparse(self.path).query).get("wall_profile", [None])[0]))
            elif path == "/api/learned-experiment":
                from .learned_experiment import load_experiment
                self.respond(200, load_experiment(ROOT / "outputs" / "learned-study"))
            elif path.startswith("/api/learned-experiment/runs/"):
                from .learned_experiment import load_run
                self.respond(200, load_run(ROOT / "outputs" / "learned-study", path.removeprefix("/api/learned-experiment/runs/")))
            elif path == "/api/demo":
                profile = parse_qs(urlparse(self.path).query).get("profile", ["basic"])[0]
                if profile not in {"basic", "competition", "catalog", "style", "route", "setting"}:
                    raise ValueError("unknown profile")
                demo = ROOT / "fixtures" / (f"{profile}-demo-bundle.json" if profile != "basic" else "demo-bundle.json")
                if not demo.is_file():
                    self.respond(503, {"error": "示例尚未生成。请运行 .venv/bin/python scripts/prepare_demo.py。"})
                else:
                    self.respond(200, validate_bundle(json.loads(demo.read_text(encoding="utf-8"))))
            else:
                self.respond(404, {"error": "接口不存在。"})
        except FileNotFoundError as exc:
            self.respond(503, {"error": str(exc)})
        except ValueError as exc:
            self.respond(422, {"error": str(exc)})
        except Exception:
            logging.exception("Local GET failed")
            self.respond(500, {"error": "本地程序运行失败，请查看启动终端。"})

    def do_POST(self):
        if not self.local_request():
            return
        try:
            if self.headers.get("Content-Type", "").split(";", 1)[0].strip() != "application/json":
                self.respond(415, {"error": "请提交 JSON 文件。"})
                return
            size = int(self.headers.get("Content-Length", "0"))
            if size <= 0 or size > MAX_BODY:
                self.respond(413, {"error": "数据为空或超过 8 MB。"})
                return
            payload = json.loads(self.rfile.read(size))
            finite_tree(payload)
            if not isinstance(payload, dict):
                raise ValueError("请求必须是 JSON 对象。")
            path = urlparse(self.path).path
            if path == "/api/request":
                allowed = {"body_id", "scenario", "mode", "angle_deg", "hand_moves", "seed", "budget", "profile", "catalog_counts", "style_goal", "rhythm", "route_program", "setting_program", "hold_source", "wall_profile"}
                if set(payload) - allowed:
                    raise ValueError("包含未支持的场景参数。")
                self.respond(200, {"request": default_request(**payload)})
            elif path == "/api/style-comparison":
                self.respond(200, generate_style_comparison(payload))
            elif path == "/api/route-comparison":
                self.respond(200, generate_route_comparison(payload))
            elif path == "/api/setting-comparison":
                self.respond(200, generate_setting_comparison(payload))
            elif path == "/api/generate":
                request = payload["request"]
                bundle = generate(request)
                save_run(bundle)
                self.respond(200, bundle)
            elif path == "/api/evaluate":
                request, candidate = payload["request"], payload["candidate"]
                evaluation = evaluate(request, candidate)
                bundle = make_bundle(request, [candidate], [evaluation])
                save_run(bundle)
                self.respond(200, {"candidate": candidate, "evaluation": evaluation})
            elif path == "/api/beta-audit":
                if set(payload) != {"request", "candidate"}:
                    raise ValueError("替代走法检查只接受当前 request 和 candidate。")
                self.respond(200, audit_beta(payload["request"], payload["candidate"]))
            elif path == "/api/validate":
                self.respond(200, validate_bundle(payload["bundle"]))
            elif path == "/api/bundle":
                bundle = make_bundle(payload["request"], payload["candidates"], payload.get("evaluations", []))
                bundle["reviews"] = payload.get("reviews", [])
                self.respond(200, validate_bundle(bundle))
            else:
                self.respond(404, {"error": "接口不存在。"})
        except (ValueError, KeyError, TypeError) as exc:
            self.respond(422, {"error": f"数据未通过校验：{exc}"})
        except Exception:
            logging.exception("Local POST failed")
            self.respond(500, {"error": "本地程序运行失败，原方案已保留。请查看启动终端。"})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--web-port", type=int, default=5173)
    args = parser.parse_args()
    if any(not 1024 <= port <= 65535 for port in (args.port, args.web_port)):
        parser.error("ports must be in the range 1024–65535")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.web_port = args.web_port
    print(f"Beta Atelier engine: http://127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
