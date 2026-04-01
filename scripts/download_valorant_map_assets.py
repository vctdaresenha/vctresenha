import json
import sys
from pathlib import Path
from urllib.request import Request, urlopen


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from vct_resenha.valorant_api import fetch_all_maps  # noqa: E402


ASSET_DIR = REPO_ROOT / "assets" / "mapas"
MANIFEST_PATH = ASSET_DIR / "catalog.json"


def slugify_map_name(map_name: str) -> str:
    sanitized = "".join(character.lower() if character.isalnum() else "-" for character in map_name.strip())
    while "--" in sanitized:
        sanitized = sanitized.replace("--", "-")
    return sanitized.strip("-") or "mapa"


def download_file(url: str, destination: Path) -> None:
    request = Request(url, headers={"User-Agent": "VCT-da-Resenha/1.0"})
    with urlopen(request, timeout=20.0) as response:
        destination.write_bytes(response.read())


def main() -> int:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    maps_catalog = fetch_all_maps(timeout=15.0)
    downloaded = 0
    manifest: list[dict] = []

    for map_item in maps_catalog:
        image_url = map_item.get("image_url") or map_item.get("splash_url") or map_item.get("icon_url") or ""
        if not image_url:
            print(f"[skip] {map_item['name']}: sem imagem na API")
            manifest.append({"name": map_item["name"], "file": ""})
            continue

        file_name = f"{slugify_map_name(map_item['name'])}.png"
        destination = ASSET_DIR / file_name
        try:
            download_file(image_url, destination)
        except Exception as exc:  # pragma: no cover - utilitario manual
            print(f"[erro] {map_item['name']}: {exc}")
            manifest.append({"name": map_item["name"], "file": ""})
            continue

        downloaded += 1
        manifest.append({"name": map_item["name"], "file": file_name})
        print(f"[ok] {map_item['name']} -> {destination}")

    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=True), encoding="utf-8")
    print(f"Concluido. {downloaded} mapa(s) baixado(s) em {ASSET_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())