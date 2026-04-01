import json
import os
from pathlib import Path

from .models import default_state


class StateStorage:
    def __init__(self, base_path: Path) -> None:
        self.base_path = Path(base_path)
        self.legacy_file_path = self.base_path / "data" / "championship_state.json"
        self.file_path = self._get_persistent_file_path()

    def _get_persistent_file_path(self) -> Path:
        local_app_data = os.getenv("LOCALAPPDATA", "").strip()
        if local_app_data:
            return Path(local_app_data) / "VCT da Resenha" / "data" / "championship_state.json"
        return self.legacy_file_path

    def _load_state_file(self, file_path: Path) -> dict:
        with file_path.open("r", encoding="utf-8") as file_handle:
            data = json.load(file_handle)

        state = default_state()
        state.update(data)
        return state

    def load(self) -> dict:
        if self.file_path.exists():
            return self._load_state_file(self.file_path)

        if self.legacy_file_path.exists():
            state = self._load_state_file(self.legacy_file_path)
            self.save(state)
            return state

        return default_state()

    def save(self, state: dict) -> None:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        with self.file_path.open("w", encoding="utf-8") as file_handle:
            json.dump(state, file_handle, indent=2, ensure_ascii=True)