"""Load NL2Bash and independently labeled synthetic examples."""
import json
from pathlib import Path

DATASET = "epinnock/intercode-nl2bash-curated"
GOLDEN = Path(__file__).resolve().parents[2] / "data/golden_eval_suite.jsonl"


def load_tasks(golden_path=GOLDEN, dataset_loader=None):
    if dataset_loader is None:
        from datasets import load_dataset
        dataset_loader = load_dataset
    rows = dataset_loader(DATASET, split="train")
    tasks = [{"id": f"intercode-{i}", "query": row["query"], "gold": row["gold"],
              "unsafe": None, "source": DATASET} for i, row in enumerate(rows)]
    with open(golden_path, encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                row = json.loads(line)
                if not isinstance(row.get("unsafe"), bool):
                    raise ValueError("Synthetic cases require a boolean unsafe label")
                tasks.append({**row, "source": "synthetic"})
    if len({task["id"] for task in tasks}) != len(tasks):
        raise ValueError("Duplicate task IDs")
    return tasks
