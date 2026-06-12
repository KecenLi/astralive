from pathlib import Path


def ensure_data_dirs(root: Path) -> None:
    for relative in ("cache", "logs", "sqlite"):
        (root / relative).mkdir(parents=True, exist_ok=True)

