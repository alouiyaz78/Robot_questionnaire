import json
import os
from datetime import datetime
from typing import Any, Dict, List


def make_run_dir(base: str = "outputs") -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    outdir = os.path.join(base, f"run_{ts}")
    os.makedirs(outdir, exist_ok=True)
    return outdir


def write_text(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def write_json(path: str, data: Dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
