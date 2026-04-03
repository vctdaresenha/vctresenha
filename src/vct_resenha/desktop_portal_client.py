from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import AppSettings


class PortalClientError(RuntimeError):
    pass


class PortalAdminClient:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings

    @staticmethod
    def _default_headers() -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36 VCTDaResenhaDesktop/1.0",
        }

    def is_configured(self) -> bool:
        return bool(self.settings.portal.base_url and self.settings.portal.admin_token)

    def _request(
        self,
        method: str,
        path: str,
        payload: dict | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> dict:
        if not self.is_configured():
            raise PortalClientError("Portal nao configurado no arquivo config/app_settings.json.")

        url = f"{self.settings.portal.base_url}{path}"
        data = None
        headers = self._default_headers()
        headers["X-Admin-Token"] = self.settings.portal.admin_token
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if extra_headers:
            headers.update(extra_headers)

        request = Request(url, data=data, headers=headers, method=method.upper())
        try:
            with urlopen(request, timeout=20.0) as response:
                raw_body = response.read().decode("utf-8")
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            message = body or str(exc)
            if body:
                try:
                    payload = json.loads(body)
                except json.JSONDecodeError:
                    payload = None
                if isinstance(payload, dict) and payload.get("detail"):
                    message = str(payload.get("detail"))
            raise PortalClientError(message) from exc
        except URLError as exc:
            raise PortalClientError(f"Nao foi possivel conectar ao portal: {exc}") from exc

        if not raw_body:
            return {}
        return json.loads(raw_body)

    def list_pending_submissions(self) -> list[dict]:
        payload = self._request("GET", "/api/admin/submissions")
        return payload.get("items", []) if isinstance(payload, dict) else []

    def approve_submission(self, submission_id: int, henrik_api_keys: list[str] | str | None = None) -> dict:
        extra_headers: dict[str, str] = {}
        if isinstance(henrik_api_keys, str):
            normalized_keys = henrik_api_keys.strip()
        else:
            normalized_keys = ", ".join(str(item).strip() for item in (henrik_api_keys or []) if str(item).strip())
        if normalized_keys:
            extra_headers["X-Henrik-Api-Keys"] = normalized_keys
        return self._request("POST", f"/api/admin/submissions/{submission_id}/approve", extra_headers=extra_headers)

    def reject_submission(self, submission_id: int, reason: str) -> dict:
        return self._request("POST", f"/api/admin/submissions/{submission_id}/reject", {"reason": reason})

    def list_approved_teams(self) -> list[dict]:
        payload = self._request("GET", "/api/admin/teams")
        return payload.get("items", []) if isinstance(payload, dict) else []

    def list_users(self) -> list[dict]:
        payload = self._request("GET", "/api/admin/users")
        return payload.get("items", []) if isinstance(payload, dict) else []

    def update_user_riot_id(self, user_id: int, riot_id: str) -> dict:
        payload = self._request("POST", f"/api/admin/users/{user_id}/riot-id", {"riot_id": str(riot_id).strip()})
        return payload if isinstance(payload, dict) else {}

    def get_admin_settings(self) -> dict:
        payload = self._request("GET", "/api/admin/settings")
        return payload if isinstance(payload, dict) else {}

    def set_registrations_open(self, is_open: bool) -> dict:
        payload = self._request("POST", "/api/admin/settings/registrations", {"open": bool(is_open)})
        return payload if isinstance(payload, dict) else {}

    def download_logo(self, logo_url: str, output_path: Path) -> str:
        if not logo_url:
            return ""

        if logo_url.startswith("/"):
            full_url = f"{self.settings.portal.base_url}{logo_url}"
        else:
            full_url = logo_url

        output_path.parent.mkdir(parents=True, exist_ok=True)
        headers = self._default_headers()
        headers["Accept"] = "image/png,image/*,*/*;q=0.8"
        request = Request(full_url, headers=headers)
        try:
            with urlopen(request, timeout=20.0) as response:
                output_path.write_bytes(response.read())
        except Exception as exc:
            raise PortalClientError(f"Nao foi possivel baixar a logo do portal: {exc}") from exc
        return str(output_path)

    def sync_approved_profiles(self, destination_dir: Path, max_profiles: int = 8) -> list[dict]:
        teams = self.list_approved_teams()[:max_profiles]
        profiles: list[dict] = []
        for slot_index, team in enumerate(teams):
            logo_path = ""
            logo_url = str(team.get("logo_url", "")).strip()
            if logo_url:
                logo_path = self.download_logo(logo_url, destination_dir / f"portal_team_{team.get('id', slot_index + 1)}.png")

            players = team.get("players", []) if isinstance(team.get("players", []), list) else []
            profiles.append(
                {
                    "slot": slot_index,
                    "name": str(team.get("name", "")).strip(),
                    "logo_path": logo_path,
                    "coach": str(team.get("coach", "")).strip(),
                    "portal_view_url": str(team.get("public_view_url", "")).strip(),
                    "players": (list(players) + ["", "", "", "", ""])[:5],
                }
            )
        return profiles