"""Finite, synthetic standard inventory. Counts are stock, not installed copies."""
from __future__ import annotations

import copy
from collections import Counter

from .geometry import grip_surfaces, mounting_faces

TEMPLATES = [
    ("jug", "J-01 标准把手", 6, (.17, .12, .09)),
    ("directional_edge", "E-01 扣边（兼容模板）", 4, (.16, .10, .07)),
    ("crimp", "C-01 浅扣边 Crimp", 6, (.12, .065, .03)),
    ("pocket", "H-01 指洞 Pocket", 2, (.16, .14, .065)),
    ("foothold", "F-01 标准脚点", 8, (.10, .07, .045)),
    ("sloper", "S-01 圆坡面", 2, (.46, .36, .18)),
    ("pinch", "P-01 捏点", 2, (.22, .34, .14)),
    ("rail", "R-01 长条扣边 Rail", 2, (.45, .13, .12)),
    ("volume", "V-01 三角体积块", 2, (.90, .72, .28)),
]


# Shape family, intended role and installation direction are separate axes.
# A family can support several roles; selected grip_surface.limbs remains the
# authority for a particular contact. In particular, a pocket's internal finger
# contact is not a foothold merely because its outside rim can be stepped on.
def hold_taxonomy(kind):
    family, form = {
        "jug": ("jug", "positive_lip"), "crimp": ("crimp", "edge"),
        "directional_edge": ("crimp", "edge"), "pinch": ("pinch", "opposed_faces"),
        "sloper": ("sloper", "convex"), "pocket": ("pocket", "recess"),
        "rail": ("crimp", "rail"), "foothold": ("foot_chip", "chip"),
        "volume": ("volume", "volume"),
    }[kind]
    result = {"family": family, "form": form,
              "preferred_role": "structure" if kind == "volume" else "foot" if kind == "foothold" else "hand",
              "roles": ["structure", "hand", "foot"] if kind == "volume" else ["foot"] if kind == "foothold" else ["hand", "foot"]}
    if kind in {"directional_edge", "rail"}:
        result["legacy_alias"] = kind
    return result


def catalog_metadata():
    out = []
    for kind, name, count, size in TEMPLATES:
        record = {"id": kind, "type": kind, "template_id": f"std-{kind}", "template_name": name,
                  "width": size[0], "height": size[1], "depth": size[2],
                  "default_count": count, "min_count": 0, "max_count": 20}
        record["taxonomy"] = hold_taxonomy(kind)
        record["grip_surfaces"] = grip_surfaces(record)
        if kind == "volume":
            record["mounting_faces"] = mounting_faces(record)
        out.append(record)
    return out


def make_inventory(overrides=None):
    overrides = {} if overrides is None else overrides
    if not isinstance(overrides, dict) or set(overrides)-{t[0] for t in TEMPLATES}:
        raise ValueError("catalog_counts must contain known template type keys")
    if any(type(n) is not int or not 0 <= n <= 20 for n in overrides.values()):
        raise ValueError("每款库存数量必须为 0–20 的整数。")
    inventory, stock = [], []
    for template in catalog_metadata():
        kind = template["type"]
        count = overrides.get(kind, template["default_count"])
        stock.append({k: template[k] for k in ("template_id", "template_name", "type")} | {"count": count})
        for i in range(count):
            item = {k: copy.deepcopy(v) for k, v in template.items() if k not in {"id", "default_count", "min_count", "max_count"}}
            item.update(id=f"{kind}_{i+1:02d}", source="synthetic_assumption", pull_direction=[0, -1, 0],
                        contact={"id": "main", "position": [0, 0, item["depth"]], "radius": .015,
                                 "limbs": ["LF", "RF"] if kind in {"foothold", "volume"} else ["LH", "RH"]})
            if kind in {"crimp", "pocket"}:
                working = item["grip_surfaces"][0]
                item["contact"] = {"id": "main", "position": copy.deepcopy(working["position"]),
                                   "radius": min(working["radii"]), "limbs": copy.deepcopy(working["limbs"])}
            inventory.append(item)
    return inventory, stock


def validate_catalog(request):
    inventory = request["scene"]["inventory"]
    stock = request["scene"].get("catalog_stock", [])
    templates = {t["template_id"]: t for t in catalog_metadata()}
    if len(stock) != len(templates) or {s["template_id"] for s in stock} != set(templates):
        raise ValueError("catalog_stock must record each standard template once")
    if len({h["id"] for h in inventory}) != len(inventory):
        raise ValueError("catalog inventory IDs must be unique")
    actual = Counter(h.get("template_id") for h in inventory)
    for record in stock:
        template = templates[record["template_id"]]
        if actual[record["template_id"]] != record["count"] or any(record[k] != template[k] for k in ("type", "template_name")):
            raise ValueError("catalog stock count/type/name does not match inventory")
    for item in inventory:
        template = templates.get(item.get("template_id"))
        if template is None:
            raise ValueError("inventory references unknown standard template")
        for field in ("template_name", "type", "width", "height", "depth", "grip_surfaces", "mounting_faces", "taxonomy"):
            if item.get(field) != template.get(field):
                raise ValueError(f"{item['id']}: standard template geometry differs: {field}")
