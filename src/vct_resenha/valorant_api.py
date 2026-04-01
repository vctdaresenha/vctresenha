import json
import os
import re
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


MAPS_ENDPOINT = "https://valorant-api.com/v1/maps"
HENRIK_ACCOUNT_ENDPOINTS = (
    "https://api.henrikdev.xyz/valorant/v2/account/{name}/{tag}",
    "https://api.henrikdev.xyz/valorant/v1/account/{name}/{tag}",
)
HENRIK_MATCH_ENDPOINTS = (
    "https://api.henrikdev.xyz/valorant/v4/matches/{region}/{name}/{tag}",
    "https://api.henrikdev.xyz/valorant/v3/matches/{region}/{name}/{tag}",
)
HENRIK_API_KEY_ENV_VARS = ("HENRIKDEV_API_KEY", "HDEV_API_KEY")
HENRIK_API_KEY_SPLIT_PATTERN = re.compile(r"[\r\n,;]+")

DEFAULT_COMPETITIVE_ROTATION = [
    "Pearl",
    "Breeze",
    "Corrode",
    "Split",
    "Abyss",
    "Haven",
    "Bind",
]

EXCLUDED_MAP_NAMES = {
    "The Range",
    "Basic Training",
    "District",
    "Kasbah",
    "Drift",
    "Piazza",
    "Glitch",
    "Skirmish A",
    "Skirmish B",
    "Skirmish C",
}


class HenrikRateLimitError(RuntimeError):
    pass


def split_henrik_api_keys(value: object) -> list[str]:
    if value is None:
        return []

    raw_values: list[str] = []
    if isinstance(value, str):
        raw_values = HENRIK_API_KEY_SPLIT_PATTERN.split(value)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            raw_values.extend(split_henrik_api_keys(item))
    else:
        raw_values = HENRIK_API_KEY_SPLIT_PATTERN.split(str(value))

    normalized_keys: list[str] = []
    seen_keys: set[str] = set()
    for item in raw_values:
        current_key = str(item or "").strip()
        if not current_key or current_key in seen_keys:
            continue
        seen_keys.add(current_key)
        normalized_keys.append(current_key)
    return normalized_keys


def get_henrik_api_keys() -> list[str]:
    collected_keys: list[str] = []
    for env_var in HENRIK_API_KEY_ENV_VARS:
        collected_keys.extend(split_henrik_api_keys(os.getenv(env_var, "")))
    return collected_keys


def get_henrik_api_key() -> str:
    api_keys = get_henrik_api_keys()
    return api_keys[0] if api_keys else ""


def parse_riot_id(value: str) -> tuple[str, str] | None:
    normalized_value = str(value or "").strip()
    if "#" not in normalized_value:
        return None

    name, tag = normalized_value.rsplit("#", 1)
    name = name.strip()
    tag = tag.strip()
    if not name or not tag:
        return None
    return name, tag


def fetch_latest_custom_match(region: str, name: str, tag: str, api_key: str = "", timeout: float = 8.0) -> dict | None:
    last_error: Exception | None = None
    last_rate_limit_error: HTTPError | None = None
    invalid_key_attempts = 0
    rate_limited_attempts = 0
    api_keys = _resolve_henrik_api_keys(api_key)
    quoted_name = quote(name)
    quoted_tag = quote(tag)
    for endpoint in HENRIK_MATCH_ENDPOINTS:
        url = endpoint.format(region=region, name=quoted_name, tag=quoted_tag)
        for current_api_key in api_keys:
            headers = _build_henrik_headers(current_api_key)
            try:
                payload = _fetch_json(url, headers=headers, timeout=timeout)
            except HTTPError as exc:
                last_error = exc
                if current_api_key and exc.code == 401:
                    invalid_key_attempts += 1
                    continue
                if current_api_key and exc.code == 429:
                    rate_limited_attempts += 1
                    last_rate_limit_error = exc
                    continue
                continue
            except (OSError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
                last_error = exc
                continue

            latest_match = extract_latest_custom_match(payload)
            if latest_match:
                return latest_match

    _raise_henrik_request_error(api_keys, invalid_key_attempts, rate_limited_attempts, last_error, last_rate_limit_error)
    if last_error:
        raise last_error
    return None


def fetch_latest_match(region: str, name: str, tag: str, api_key: str = "", timeout: float = 8.0) -> dict | None:
    last_error: Exception | None = None
    last_rate_limit_error: HTTPError | None = None
    invalid_key_attempts = 0
    rate_limited_attempts = 0
    api_keys = _resolve_henrik_api_keys(api_key)
    quoted_name = quote(name)
    quoted_tag = quote(tag)
    for endpoint in HENRIK_MATCH_ENDPOINTS:
        url = endpoint.format(region=region, name=quoted_name, tag=quoted_tag)
        for current_api_key in api_keys:
            headers = _build_henrik_headers(current_api_key)
            try:
                payload = _fetch_json(url, headers=headers, timeout=timeout)
            except HTTPError as exc:
                last_error = exc
                if current_api_key and exc.code == 401:
                    invalid_key_attempts += 1
                    continue
                if current_api_key and exc.code == 429:
                    rate_limited_attempts += 1
                    last_rate_limit_error = exc
                    continue
                continue
            except (OSError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
                last_error = exc
                continue

            latest_match = extract_latest_match(payload)
            if latest_match:
                return latest_match

    _raise_henrik_request_error(api_keys, invalid_key_attempts, rate_limited_attempts, last_error, last_rate_limit_error)
    if last_error:
        raise last_error
    return None


def fetch_account(name: str, tag: str, api_key: str = "", timeout: float = 8.0) -> dict | None:
    last_error: Exception | None = None
    last_rate_limit_error: HTTPError | None = None
    invalid_key_attempts = 0
    rate_limited_attempts = 0
    api_keys = _resolve_henrik_api_keys(api_key)
    quoted_name = quote(name)
    quoted_tag = quote(tag)
    for endpoint in HENRIK_ACCOUNT_ENDPOINTS:
        url = endpoint.format(name=quoted_name, tag=quoted_tag)
        for current_api_key in api_keys:
            headers = _build_henrik_headers(current_api_key)
            try:
                payload = _fetch_json(url, headers=headers, timeout=timeout)
            except HTTPError as exc:
                last_error = exc
                if current_api_key and exc.code == 401:
                    invalid_key_attempts += 1
                    continue
                if current_api_key and exc.code == 404:
                    return None
                if current_api_key and exc.code == 429:
                    rate_limited_attempts += 1
                    last_rate_limit_error = exc
                    continue
                if not current_api_key and exc.code == 404:
                    return None
                continue
            except (OSError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
                last_error = exc
                continue

            account_payload = payload.get("data", payload) if isinstance(payload, dict) else payload
            return account_payload if isinstance(account_payload, dict) else None

    _raise_henrik_request_error(api_keys, invalid_key_attempts, rate_limited_attempts, last_error, last_rate_limit_error)
    if last_error:
        raise last_error
    return None


def validate_br_riot_id(riot_id: str, api_key: str = "", timeout: float = 8.0) -> dict | None:
    parsed_riot_id = parse_riot_id(riot_id)
    if not parsed_riot_id:
        return None

    account_payload = fetch_account(parsed_riot_id[0], parsed_riot_id[1], api_key=api_key, timeout=timeout)
    if not account_payload:
        return None

    returned_name = str(
        account_payload.get("name")
        or account_payload.get("game_name")
        or account_payload.get("gameName")
        or ""
    ).strip()
    returned_tag = str(
        account_payload.get("tag")
        or account_payload.get("tag_line")
        or account_payload.get("tagLine")
        or ""
    ).strip()
    if returned_name and returned_tag:
        if returned_name.lower() != parsed_riot_id[0].lower() or returned_tag.lower() != parsed_riot_id[1].lower():
            return None

    candidate_regions = {
        str(account_payload.get(key) or "").strip().lower()
        for key in ("region", "account_region", "shard", "puuid_region", "affinity")
    }
    candidate_regions.discard("")
    allowed_regions = {"br", "latam", "na", "americas"}
    if candidate_regions and candidate_regions.isdisjoint(allowed_regions):
        return None
    return account_payload


def extract_latest_custom_match(payload: dict) -> dict | None:
    matches = _extract_match_list(payload)
    custom_matches = [match for match in matches if _is_custom_match(match)]
    if not custom_matches:
        return None
    return max(custom_matches, key=_extract_timestamp)


def extract_latest_match(payload: dict) -> dict | None:
    matches = _extract_match_list(payload)
    if not matches:
        return None
    return max(matches, key=_extract_timestamp)


def _fetch_json(url: str, headers: dict | None = None, timeout: float = 8.0) -> dict:
    request = Request(url, headers=headers or {"User-Agent": "VCT-da-Resenha/1.0"})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _build_henrik_headers(api_key: str) -> dict[str, str]:
    headers = {"User-Agent": "VCT-da-Resenha/1.0"}
    if api_key:
        headers["Authorization"] = api_key
    return headers


def _resolve_henrik_api_keys(api_key: object) -> list[str]:
    resolved_keys = split_henrik_api_keys(api_key)
    if resolved_keys:
        return resolved_keys

    env_keys = get_henrik_api_keys()
    if env_keys:
        return env_keys

    return [""]


def _raise_henrik_request_error(
    api_keys: list[str],
    invalid_key_attempts: int,
    rate_limited_attempts: int,
    last_error: Exception | None,
    last_rate_limit_error: HTTPError | None,
) -> None:
    protected_attempts = sum(1 for item in api_keys if item)
    if protected_attempts and invalid_key_attempts >= protected_attempts:
        raise PermissionError("API HenrikDev requer chave valida.") from last_error
    if protected_attempts and rate_limited_attempts >= protected_attempts:
        raise HenrikRateLimitError("Todas as chaves configuradas da API HenrikDev atingiram o limite de requisicoes.") from last_rate_limit_error


def _extract_match_list(payload: object) -> list[dict]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []

    data = payload.get("data", payload)
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if not isinstance(data, dict):
        return []

    for key in ("matches", "history", "games", "items"):
        candidate = data.get(key)
        if isinstance(candidate, list):
            return [item for item in candidate if isinstance(item, dict)]

    return []


def _is_custom_match(match: dict) -> bool:
    haystacks = [match]
    metadata = match.get("metadata")
    if isinstance(metadata, dict):
        haystacks.append(metadata)

    values: list[str] = []
    for item in haystacks:
        for key in (
            "mode",
            "queue",
            "queue_id",
            "game_mode",
            "game_type",
            "playlist",
            "match_type",
            "custom_game_name",
        ):
            value = item.get(key)
            if value is not None:
                values.append(str(value))

    combined = " ".join(values).strip().lower()
    return "custom" in combined or "tournament" in combined


def _extract_timestamp(match: dict) -> float:
    candidates: list[object] = []
    metadata = match.get("metadata")
    if isinstance(metadata, dict):
        candidates.extend(
            metadata.get(key)
            for key in ("game_start", "game_start_unix", "started_at", "startedAt", "start_time", "timestamp")
        )

    candidates.extend(match.get(key) for key in ("game_start", "started_at", "startedAt", "start_time", "timestamp"))

    for value in candidates:
        parsed = _coerce_timestamp(value)
        if parsed is not None:
            return parsed
    return 0.0


def _coerce_timestamp(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None

    raw_value = value.strip()
    if not raw_value:
        return None
    if raw_value.isdigit():
        return float(raw_value)

    try:
        return datetime.fromisoformat(raw_value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def fetch_all_maps(timeout: float = 8.0) -> list[dict]:
    request = Request(MAPS_ENDPOINT, headers={"User-Agent": "VCT-da-Resenha/1.0"})
    with urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))

    maps_by_name: dict[str, dict] = {}
    for item in payload.get("data", []):
        display_name = item.get("displayName", "").strip()
        if not display_name or display_name in EXCLUDED_MAP_NAMES:
            continue
        if not item.get("tacticalDescription"):
            continue

        maps_by_name[display_name] = {
            "name": display_name,
            "image_url": item.get("listViewIconTall") or item.get("splash") or item.get("stylizedBackgroundImage") or "",
            "splash_url": item.get("splash") or "",
            "icon_url": item.get("displayIcon") or "",
            "uuid": item.get("uuid", ""),
        }

    ordered_maps = [maps_by_name[name] for name in DEFAULT_COMPETITIVE_ROTATION if name in maps_by_name]
    if ordered_maps:
        remaining_maps = [item for name, item in sorted(maps_by_name.items()) if name not in DEFAULT_COMPETITIVE_ROTATION]
        return ordered_maps + remaining_maps

    return sorted(maps_by_name.values(), key=lambda item: item["name"])


def fetch_competitive_maps(timeout: float = 8.0) -> list[dict]:
    all_maps = fetch_all_maps(timeout=timeout)
    maps_by_name = {item["name"]: item for item in all_maps}
    competitive_maps = [maps_by_name[name] for name in DEFAULT_COMPETITIVE_ROTATION if name in maps_by_name]
    return competitive_maps or all_maps


def safe_fetch_all_maps(timeout: float = 8.0) -> list[dict]:
    try:
        return fetch_all_maps(timeout=timeout)
    except (OSError, URLError, TimeoutError, ValueError, json.JSONDecodeError):
        return [{"name": name, "image_url": "", "splash_url": "", "icon_url": "", "uuid": ""} for name in DEFAULT_COMPETITIVE_ROTATION]


def safe_fetch_competitive_maps(timeout: float = 8.0) -> list[dict]:
    try:
        return fetch_competitive_maps(timeout=timeout)
    except (OSError, URLError, TimeoutError, ValueError, json.JSONDecodeError):
        return [{"name": name, "image_url": "", "splash_url": "", "icon_url": "", "uuid": ""} for name in DEFAULT_COMPETITIVE_ROTATION]