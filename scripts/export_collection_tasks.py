"""Export collection to Label Studio as unverified tasks, never ground truth."""
import argparse
import json
from pathlib import Path

from coc_bot.vision.collection import read_catalog


def export_tasks(root):
    tasks = []
    for row in read_catalog(root):
        tasks.append({"data": {
            "image": "/data/local-files/?d=collection/" + row["file"],
            "session": row["session"], "suggested_screen": row["screen_hint"],
            "collection_reason": row["reason"], "model": row.get("model"),
        }})
    return tasks


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("data/collection"))
    parser.add_argument("--out", type=Path, default=Path("data/labelstudio/collection_tasks.json"))
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(export_tasks(args.root), indent=2), encoding="utf-8")
    print(f"Saved unlabelled review tasks to {args.out}")
