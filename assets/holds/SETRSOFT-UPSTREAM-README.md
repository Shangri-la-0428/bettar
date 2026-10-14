---
license: cc-by-sa-4.0
pretty_name: Climbing Holds 3D dataset
tags:
  - 3d
  - climbing
  - sports
  - glb
  - blender
configs:
  - config_name: default
    data_files:
      - split: train
        path: "train.jsonl"
---

> [!IMPORTANT]
> **This dataset is in construction.** The current files are raw scans intended for establishing the structure.
> **Using them?** Help us clean them up or identify the brands by consulting the [CONTRIBUTING.md](./CONTRIBUTING.md) guide.



# GUI for contributions
[https://setrsoft.github.io/holds-dataset-hub/](https://setrsoft.github.io/holds-dataset-hub/)

[Or send your files here](https://e.pcloud.com/#/puplink?code=4oC7Z7Nbd93wTksRulHQggI5k9uJxddPX)

# Climbing Holds 3D dataset (SetRsoft)

## 📋 Project Overview
This dataset is a community-driven open-source dataset of 3D-scanned climbing holds and walls. It is designed to work seamlessly with the **SetRsoft** application, providing route setters and gym managers with high-quality assets for 3D route setting and inventory management.

## 📂 Structure
The dataset follows a strict directory-based structure to ensure portability and ease of integration:

```text
data/
├── [hold_id]/
├──── hold.glb          # Web-ready 3D model (or .obj, .stl)
├──── hold.blend        # Source file for editing in Blender (optional)
├──── texture.png       # Texture (PNG, JPG, etc.)
├──── images/           # Optional: photos for generation, reference images (e.g. dimensions)
├────   └── *.png, *.jpg, ...
└──── metadata.json     # Hold specifications (brand, model, size, status, note, etc.)
```

**Accepted file formats in each hold directory:**

- **3D mesh:** `.glb`, `.gltf`, `.obj`, `.stl` (at least one required for a complete hold).
- **Textures:** `.png`, `.jpg`, `.jpeg`, `.tga`, `.bmp`, `.webp` (optional).
- **images/** subfolder: photos used for generation and reference images (e.g. dimensions); any common image format.

Example of metadata.json :

Use **timestamps** (Unix epoch in seconds) for `created_at` and `last_update`, please specify the **timezone offset** `timezone_offset`).

Optional fields: **note** (contributor notes or text about the hold), **status** (workflow state: `to_render`, `to_clean`, or `to_identify`).

```json
{
  "id": 1,
  "hold_id": "0000000001",
  "created_at": 1721573121,
  "last_update": 1721573121,
  "timezone_offset": "+01:00",
  "type": "volume",
  "labels": ["XXL", "slopper"],
  "color_of_scan": "#FF3200",
  "available_colors": ["#FF3200"],
  "manufacturer": "trikit",
  "model": "unknown",
  "size": "XL",
  "note": "Optional notes about this hold.",
  "status": "to_clean"
}
```

**Status values:** `to_render` (only photos, no mesh yet), `to_clean` (GLB/Blend present but hold not cleaned), `to_identify` (brand or model not in allowed references).

# ⚖️ License & Intellectual Property
Dataset License: CC-BY-SA-4.0.

**Important Note:** The 3D shapes of certain holds remain the intellectual property of their respective manufacturers. This dataset is provided for educational and gym management purposes. Commercial reproduction (such as 3D printing for sale) of branded shapes is strictly prohibited and governed by industrial design laws.

# 🔗 Related Projects
- SetRSoft App: GitHub Repository — The main application logic (GPLv3).
- Website: setrsoft.com.