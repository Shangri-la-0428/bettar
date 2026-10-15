"""Bounded, atomic local records of a routesetting session.

Project persistence never searches or solves poses. Current checks are verified
by the existing bundle contract; an edited or obsolete check cannot become a
fresh success merely because the enclosing project was saved.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import tempfile
from threading import RLock
from uuid import UUID, uuid4

from . import engine

SCHEMA = "bettar-project/1"
MAX_PROJECT_BYTES = 16 * 1024 * 1024
MAX_PROJECTS = 100
_LOCK = RLock()


class ProjectConflict(ValueError):
    def __init__(self, revision: int):
        super().__init__("记录已在其他页面更新，请重新打开记录后再保存。当前修改尚未保存。")
        self.revision = revision


class ProjectCorrupt(ValueError):
    pass


def _id(value):
    if not isinstance(value, str):
        raise ValueError("记录 ID 必须是 UUID。")
    try:
        if str(UUID(value)) != value:
            raise ValueError()
    except (ValueError, AttributeError):
        raise ValueError("记录 ID 必须是规范 UUID。") from None
    return value


def _text(value, name, maximum, *, empty=False):
    if not isinstance(value, str) or len(value) > maximum or (not empty and not value.strip()):
        raise ValueError(f"{name}必须是{'非空' if not empty else ''}文本，最多 {maximum} 字符。")
    return value


def _finite(value, depth=0):
    if depth > 60:
        raise ValueError("记录嵌套过深。")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("记录含无效数值。")
    if isinstance(value, dict):
        for item in value.values():
            _finite(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _finite(item, depth + 1)


def _bytes(value):
    _finite(value)
    raw = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
    if len(raw) > MAX_PROJECT_BYTES:
        raise ValueError("定线记录超过 16 MB，请导出并开始一条新记录。")
    return raw


def _canonical_bundle(bundle, *, obsolete=False):
    """Accept unsealed edits using the same validation as /api/bundle.

    Frontend edits append a new candidate without re-signing the bundle. Keep
    valid checks on older revisions, and discard checks only when their actual
    request/candidate fingerprint has changed. Same-fingerprint forged results
    still go through the full evaluation validator and are rejected.
    """
    if not isinstance(bundle, dict):
        raise ValueError("方案缺少检查包。")
    request, candidates = bundle["request"], copy.deepcopy(bundle["candidates"])
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= 100:
        raise ValueError("每个方案须保留 1–100 个修订。")
    evaluations = bundle.get("evaluations", [])
    if not isinstance(evaluations, list):
        raise ValueError("检查结果必须是数组。")
    candidate_map = {c["id"]: c for c in candidates}
    if obsolete:
        for candidate in candidates:
            # Embedded baseline/alternative checks share the obsolete evaluator
            # too. Leaving these attached would either show stale evidence or
            # prevent a fresh evaluation of the otherwise editable geometry.
            candidate.pop("setting_report", None)
    kept = []
    dropped = obsolete and bool(evaluations)
    for evaluation in evaluations:
        candidate = candidate_map.get(evaluation.get("candidate_id"))
        if candidate is None:
            raise ValueError("检查结果指向不存在的修订。")
        if obsolete or evaluation.get("version") != engine.VERSION or evaluation.get("fingerprint") != engine.fingerprint(request, candidate):
            dropped = True
        else:
            kept.append(evaluation)
    if not dropped:
        try:
            return engine.validate_bundle(bundle), False
        except ValueError as exc:
            # A changed digest is expected for an appended manual revision or a
            # newly completed check. All retained results are verified below.
            if "bundle integrity mismatch" not in str(exc) and "stale evaluator" not in str(exc):
                raise
    normalized = engine.make_bundle(request, candidates, kept)
    normalized["reviews"] = copy.deepcopy(bundle.get("reviews", []))
    return engine.validate_bundle(normalized), dropped


def _gym_compatibility(record, gym):
    messages = []
    if record["gym_id"] != gym["id"]:
        messages.append("该记录所属岩馆当前不可用，保留原墙体供查看。")
    elif record["gym_version"] != gym["version"]:
        messages.append("岩馆墙体版本已变化，保留原墙体供查看；请在当前区域新建记录。")
    elif record["region_id"] not in {region["id"] for region in gym["regions"]}:
        messages.append("原定线区域已不存在，保留原墙体供查看。")
    else:
        region = next(region for region in gym["regions"] if region["id"] == record["region_id"])
        if record["brief"]["wall_profile"] != region["wall_profile"]:
            messages.append("记录墙形与所选区域不一致，请在该区域新建记录。")
    return messages


def _validate_gym_binding(request, gym, region_id):
    """A saved official gym draft cannot redefine the wall or its neighbours.

    Generic bundle import still supports custom installation regions. This
    narrower project endpoint binds the advertised example gym to its actual
    immutable context, independently of client-supplied constraint labels.
    """
    from .example_gym import all_panels, get_region, _neighbour_stock
    region = get_region(gym["id"], region_id)
    binding = request.get("route_constraints", {}).get("installation_region")
    if not binding or binding.get("patches") != region["patches"]:
        raise ValueError("记录的安装范围必须与示例岩馆区域一致。")
    expected_editable = gym["preview"]["request"]["route_constraints"]["installation_region"]["editable_placement_ids"]
    if set(binding.get("editable_placement_ids", [])) != set(expected_editable):
        raise ValueError("记录不能扩大示例区域的可编辑岩点名单。")
    scene = request.get("scene", {})
    if scene.get("wall_panels") != all_panels() or scene.get("angle_deg") != 0:
        raise ValueError("记录不能修改示例岩馆的整体墙形。")
    expected_fixed, expected_stock = {}, {}
    for other, stock in _neighbour_stock().items():
        if other != region_id:
            expected_fixed.update({point["id"]: point for point in stock["placements"]})
            expected_stock.update({item["id"]: item for item in stock["inventory"]})
    fixed = binding.get("fixed_placements", [])
    if len(fixed) != len(expected_fixed) or {point["id"]: point for point in fixed} != expected_fixed:
        raise ValueError("记录不能移动或删除示例岩馆的周边岩点。")
    inventory = {item["id"]: item for item in scene.get("inventory", [])}
    if any(inventory.get(key) != item for key, item in expected_stock.items()):
        raise ValueError("记录不能改变示例岩馆的周边库存与接触面。")


def _validate_record(payload):
    if not isinstance(payload, dict):
        raise ValueError("定线记录必须是对象。")
    record = copy.deepcopy(payload)
    allowed = {"id", "revision", "name", "gym_id", "gym_version", "region_id", "brief", "entries", "selected_variant", "notes", "status", "created_at", "updated_at", "compatibility", "interrupted"}
    if set(record) - allowed:
        raise ValueError("记录包含未支持的字段。")
    for key, maximum in (("name", 120), ("gym_id", 120), ("gym_version", 200), ("region_id", 120)):
        _text(record.get(key), key, maximum)
    _text(record.setdefault("notes", ""), "备注", 10000, empty=True)
    if record.get("status") not in {"draft", "generating", "editing"}:
        raise ValueError("记录状态无效。")
    brief = record.get("brief")
    if not isinstance(brief, dict) or set(brief) - {"wall_profile", "style", "difficulty", "gym_id", "region_id"}:
        raise ValueError("定线条件无效。")
    if brief.get("wall_profile") not in {"overhang", "roof", "dihedral", "arete"} or brief.get("style") not in {"balance", "power", "sustained"} or brief.get("difficulty") not in {"easy", "medium", "hard"}:
        raise ValueError("墙形、风格或大致难度无效。")
    for key in ("gym_id", "region_id"):
        if key in brief and brief[key] != record[key]:
            raise ValueError("定线条件与记录区域不一致。")
    entries = record.get("entries")
    if not isinstance(entries, list) or len(entries) > 3:
        raise ValueError("每次记录最多三条方案。")
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) - {"variant", "state", "result", "error", "duplicateOf", "selectedCandidateId"}:
            raise ValueError("方案记录格式无效。")
        variant = entry.get("variant")
        if type(variant) is not int or variant not in range(3) or variant in seen:
            raise ValueError("方案编号必须是互不重复的 0、1、2。")
        seen.add(variant)
        if entry.get("state") not in {"waiting", "running", "ready", "error"}:
            raise ValueError("方案状态无效。")
        if "error" in entry:
            _text(entry["error"], "方案错误", 2000, empty=True)
        if "duplicateOf" in entry and (type(entry["duplicateOf"]) is not int or entry["duplicateOf"] not in range(3) or entry["duplicateOf"] == variant):
            raise ValueError("重复方案编号无效。")
        result = entry.get("result")
        if entry["state"] == "ready" and result is None:
            raise ValueError("已生成的方案缺少结果。")
        if result is not None:
            if not isinstance(result, dict) or not isinstance(result.get("brief"), dict) or not isinstance(result.get("bundle"), dict):
                raise ValueError("生成结果格式无效。")
            if result["brief"].get("variant") != variant:
                raise ValueError("生成结果与方案编号不一致。")
            for source in (result["brief"], result["bundle"].get("request", {}).get("generation_brief", {})):
                for key, expected in {**brief, "gym_version": record["gym_version"], "variant": variant}.items():
                    if key in source and source[key] != expected:
                        raise ValueError("生成结果与记录的区域或条件不一致。")
            region = result["bundle"].get("request", {}).get("route_constraints", {}).get("installation_region")
            if region is not None:
                if not isinstance(region, dict) or any(region.get(key) != record[key] for key in ("gym_id", "gym_version", "region_id")):
                    raise ValueError("实际安装区域与定线记录不一致。")
            for key in ("id", "label", "geometry_digest", "sequence_digest"):
                _text(result.get(key), f"result.{key}", 300, empty=key.endswith("digest"))
            if result.get("status") not in {"complete", "unverified", "search_unresolved"}:
                raise ValueError("生成结果状态无效。")
            if type(result.get("elapsed_ms")) not in {int, float} or result["elapsed_ms"] < 0:
                raise ValueError("生成用时无效。")
            selected = entry.get("selectedCandidateId")
            if selected is not None and selected not in {c.get("id") for c in result["bundle"].get("candidates", [])}:
                raise ValueError("所选修订不属于当前方案。")
        elif "selectedCandidateId" in entry:
            raise ValueError("未生成方案不能选择修订。")
    selected = record.get("selected_variant")
    if selected is not None and (type(selected) is not int or selected not in seen):
        raise ValueError("当前方案不在记录中。")
    for key in ("compatibility", "interrupted"):
        record.pop(key, None)
    return record


class ProjectStore:
    def __init__(self, directory: Path, gym):
        self.directory = Path(directory)
        self.gym = gym

    def _path(self, project_id):
        return self.directory / f"{_id(project_id)}.json"

    def _read(self, project_id):
        path = self._path(project_id)
        if path.stat().st_size > MAX_PROJECT_BYTES:
            raise ProjectCorrupt("记录超过大小限制，原文件已保留。")
        try:
            wrapper = json.loads(path.read_text(encoding="utf-8"))
            _finite(wrapper)
            if wrapper.get("schema") != SCHEMA or wrapper.get("digest") != engine.canonical_hash(wrapper["record"]):
                raise ValueError("记录摘要或版本不匹配")
            record = _validate_record(wrapper["record"])
            if record["id"] != project_id or type(record["revision"]) is not int or record["revision"] < 1:
                raise ValueError("记录身份不匹配")
            for key in ("created_at", "updated_at"):
                _text(record.get(key), key, 80)
                datetime.fromisoformat(record[key])
            return record
        except (ValueError, KeyError, TypeError, AttributeError, RecursionError) as exc:
            raise ProjectCorrupt(f"定线记录损坏或格式不兼容，原文件已保留：{exc}") from exc

    def _prepare(self, record, *, restoring):
        record = copy.deepcopy(record)
        messages = _gym_compatibility(record, self.gym)
        read_only = bool(messages)
        for entry in record["entries"]:
            result = entry.get("result")
            if result is not None:
                bundle = result["bundle"]
                manifest = bundle.get("manifest", {})
                obsolete = manifest.get("engine_version") != engine.VERSION or manifest.get("code_hash") != engine.code_hash()
                try:
                    result["bundle"], dropped = _canonical_bundle(bundle, obsolete=obsolete or read_only)
                    if obsolete or dropped:
                        messages.append("检查器或草稿已变化，旧检查已失效；可继续调整并重新检查。")
                except (ValueError, KeyError, TypeError, AttributeError) as exc:
                    if not restoring:
                        raise
                    # Preserve the entire original request and revisions for
                    # recovery. Never render obsolete checks as valid results.
                    bundle["evaluations"] = []
                    messages.append(f"旧草稿暂不能由当前检查器读取，仅供查看：{exc}")
                    read_only = True
            if restoring and entry["state"] in {"running", "waiting"}:
                entry["state"] = "error"
                entry["error"] = "上次生成未完成，可重新生成。"
                record["interrupted"] = True
        if restoring and record["status"] == "generating":
            record["status"] = "draft"
            record["interrupted"] = True
        record["compatibility"] = {"status": "unavailable" if read_only else "stale" if messages else "current", "read_only": read_only, "messages": list(dict.fromkeys(messages))}
        return record

    def load(self, project_id):
        with _LOCK:
            return self._prepare(self._read(project_id), restoring=True)

    def list(self):
        projects, errors = [], []
        with _LOCK:
            for path in self.directory.glob("*.json"):
                try:
                    _id(path.stem)
                    raw = self._read(path.stem)
                    # Listing does not validate/recompute every historical LP.
                    # The full load verifies checks before the UI can use them.
                    messages = _gym_compatibility(raw, self.gym)
                    old_engine = any(entry.get("result") and (
                        entry["result"]["bundle"].get("manifest", {}).get("engine_version") != engine.VERSION or
                        entry["result"]["bundle"].get("manifest", {}).get("code_hash") != engine.code_hash()) for entry in raw["entries"])
                    projects.append({key: raw[key] for key in ("id", "revision", "name", "gym_id", "gym_version", "region_id", "brief", "status", "created_at", "updated_at")} | {"compatibility": {"status": "unavailable" if messages else "stale" if old_engine else "current", "read_only": bool(messages), "messages": messages}})
                except (ValueError, OSError) as exc:
                    errors.append({"id": path.stem, "error": str(exc)})
        projects.sort(key=lambda item: (item["updated_at"], item["id"]), reverse=True)
        return {"projects": projects, "last_project_id": projects[0]["id"] if projects else None, "errors": errors}

    def save(self, payload):
        _bytes(payload)
        record = _validate_record(payload)
        if "id" in record and record["id"] is not None:
            _id(record["id"])
        if type(record.get("revision", 0)) is not int or record.get("revision", 0) < 0:
            raise ValueError("记录修订号无效。")
        with _LOCK:
            old = self._read(record["id"]) if record.get("id") else None
            if old and record.get("revision") != old["revision"]:
                raise ProjectConflict(old["revision"])
            if not old and record.get("revision", 0) != 0:
                raise ValueError("新记录修订号必须为 0。")
            if old and (record["gym_id"], record["gym_version"], record["region_id"]) != (old["gym_id"], old["gym_version"], old["region_id"]):
                raise ValueError("已保存记录不能换到其他区域，请新建定线记录。")
            gym_errors = _gym_compatibility(record, self.gym)
            if gym_errors:
                raise ValueError("；".join(gym_errors))
            previous = {entry["variant"]: entry.get("result") for entry in old["entries"]} if old else {}
            for entry in record["entries"]:
                result = entry.get("result")
                if result is None:
                    continue
                request = result["bundle"]["request"]
                _validate_gym_binding(request, self.gym, record["region_id"])
                before = previous.get(entry["variant"])
                if before and (before["id"] != result["id"] or before["bundle"]["request"] != request):
                    raise ValueError("已有方案的场地与生成请求不能被改写；请保留当前记录并新建生成。")
            self.directory.mkdir(parents=True, exist_ok=True)
            if not old and sum(1 for _ in self.directory.glob("*.json")) >= MAX_PROJECTS:
                raise ValueError("本机已保存 100 条记录，请先备份记录文件。")
            record = self._prepare(record, restoring=False)
            now = datetime.now(timezone.utc).isoformat()
            record.update(id=old["id"] if old else str(uuid4()), revision=old["revision"] + 1 if old else 1,
                          created_at=old["created_at"] if old else now, updated_at=now)
            persisted = {key: value for key, value in record.items() if key not in {"compatibility", "interrupted"}}
            wrapper = {"schema": SCHEMA, "record": persisted, "digest": engine.canonical_hash(persisted)}
            raw = _bytes(wrapper)
            destination = self._path(record["id"])
            descriptor, temporary = tempfile.mkstemp(prefix=".project-", suffix=".tmp", dir=self.directory)
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, destination)
                directory_fd = os.open(self.directory, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            return record
