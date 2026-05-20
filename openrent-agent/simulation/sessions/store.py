import json
from pathlib import Path


class JSONSessionStore:
    def __init__(self, base_dir: str | None = None):
        if base_dir is None:
            base_dir = Path(__file__).resolve().parents[1] / "datasets" / "runs"
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save(self, session) -> Path:
        target_path = self.base_dir / f"{session.session_id}.json"
        with target_path.open("w", encoding="utf-8") as handle:
            json.dump(session.to_dict(), handle, indent=2)
        return target_path

    def load(self, session_id: str) -> dict | None:
        target_path = self.base_dir / f"{session_id}.json"
        if not target_path.exists():
            return None
        with target_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def list_paths(self) -> list[Path]:
        return sorted(
            self.base_dir.glob("*.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
