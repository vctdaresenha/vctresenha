from .models import SUPPORTED_BRACKET_SIZES, get_bracket_template


def clean_lines(raw_text: str) -> list[str]:
    return [line.strip() for line in raw_text.splitlines() if line.strip()]


def infer_bracket_size(team_names: list[str]) -> int | None:
    return len(team_names) if len(team_names) in SUPPORTED_BRACKET_SIZES else None


def build_resolved_matches(team_names: list[str], bracket_size: int, results: dict, schedule: dict | None = None) -> list[dict]:
    resolved_lookup: dict[str, dict] = {}
    resolved_matches: list[dict] = []
    schedule = schedule or {}

    for match in get_bracket_template(bracket_size):
        team1 = _resolve_slot(match["slot1"], team_names, results, resolved_lookup)
        team2 = _resolve_slot(match["slot2"], team_names, results, resolved_lookup)
        match_result = results.get(match["id"], {})
        winner = _resolve_winner_name(match_result, team1, team2)
        enriched_match = {
            **match,
            "team1": team1,
            "team2": team2,
            "winner": winner,
            "scheduled_date": schedule.get(match["id"], ""),
            "team1_score": match_result.get("team1_score", ""),
            "team2_score": match_result.get("team2_score", ""),
            "map_name": match_result.get("map_name", ""),
            "official_result": match_result.get("official_result", ""),
            "official_acs": match_result.get("official_acs", ""),
            "official_kd": match_result.get("official_kd", ""),
            "official_mvp": match_result.get("official_mvp", ""),
            "official_data": match_result.get("official_data", {}),
            "notes": match_result.get("notes", ""),
        }
        resolved_lookup[match["id"]] = enriched_match
        resolved_matches.append(enriched_match)

    return resolved_matches


def match_can_receive_result(match: dict) -> bool:
    return match["team1"] != "A definir" and match["team2"] != "A definir"


def winner_slot_from_name(match: dict, winner_name: str) -> str | None:
    if winner_name == match["team1"]:
        return "team1"
    if winner_name == match["team2"]:
        return "team2"
    return None


def match_display_label(match: dict) -> str:
    return (
        f"{match['id']} | {match['title']} | {match['team1']} vs {match['team2']} | "
        f"{match['best_of']}"
    )


def _resolve_slot(slot: dict, team_names: list[str], results: dict, resolved_lookup: dict) -> str:
    if slot["kind"] == "team":
        team_index = slot["index"]
        return team_names[team_index] if team_index < len(team_names) else "A definir"

    referenced_match = resolved_lookup.get(slot["match"])
    referenced_result = results.get(slot["match"], {})
    winner_slot = referenced_result.get("winner_slot")

    if not referenced_match or winner_slot not in {"team1", "team2"}:
        return "A definir"

    if slot["kind"] == "winner":
        return referenced_match[winner_slot]

    losing_slot = "team2" if winner_slot == "team1" else "team1"
    return referenced_match[losing_slot]


def _resolve_winner_name(match_result: dict, team1: str, team2: str) -> str:
    winner_slot = match_result.get("winner_slot")
    if winner_slot == "team1":
        return team1
    if winner_slot == "team2":
        return team2
    return ""