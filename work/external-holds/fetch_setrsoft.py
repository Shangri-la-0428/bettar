"""Download public research meshes only. Never execute upstream code."""
from pathlib import Path
import concurrent.futures, hashlib, json, struct, urllib.request

ROOT = Path(__file__).resolve().parent / "setrsoft"
API = "https://huggingface.co/api/datasets/setrsoft/climbing-holds/tree/main?recursive=true&limit=1000"
BASE = "https://huggingface.co/datasets/setrsoft/climbing-holds/resolve/main/"

def read(url):
    with urllib.request.urlopen(url, timeout=40) as r:
        return r.read()

ROOT.mkdir(parents=True, exist_ok=True)
tree = json.loads(read(API))
(ROOT / "upstream-tree.json").write_text(json.dumps(tree, indent=2))
paths = [x["path"] for x in tree if x.get("type")=="file" and (x["path"].endswith("/hold.glb") or x["path"].endswith("/metadata.json") or x["path"] in ("README.md", "CONTRIBUTING.md", "train.jsonl", "meta/global_index.json"))]

def fetch(path):
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    data = target.read_bytes() if target.exists() else read(BASE + path)
    if path.endswith(".glb"):
        if data[:4] != b"glTF" or struct.unpack_from("<I", data, 8)[0] != len(data):
            raise ValueError("invalid GLB " + path)
    target.write_bytes(data)
    return {"relative_path": path, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "download_url": BASE + path}

records=[]
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
    jobs={pool.submit(fetch,path):path for path in paths}
    for job in concurrent.futures.as_completed(jobs):
        try:
            record=job.result(); records.append(record)
            print(json.dumps({"downloaded":record["relative_path"],"bytes":record["bytes"]}), flush=True)
        except Exception as e:
            print(json.dumps({"failed":jobs[job],"error":str(e)}), flush=True)
(ROOT / "download-manifest.json").write_text(json.dumps(sorted(records,key=lambda r:r["relative_path"]), indent=2))
print(json.dumps({"files":len(records),"bytes":sum(r["bytes"] for r in records)}), flush=True)
