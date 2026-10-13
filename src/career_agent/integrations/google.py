import os
import time
from pathlib import Path
from urllib.parse import quote, urlsplit

import httpx

from career_agent.integrations.vault import TokenVault


class IntegrationError(Exception):
    pass


GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.events.owned",
]


class GoogleClient:
    def __init__(self, *, transport=None):
        self.client = httpx.Client(transport=transport, timeout=30, follow_redirects=False)
        self.access_token, self.expires_at = None, 0

    def refresh(self):
        names = [
            "CAREER_GOOGLE_CLIENT_ID",
            "CAREER_GOOGLE_CLIENT_SECRET",
            "CAREER_GOOGLE_REFRESH_TOKEN",
        ]
        refresh_token = os.environ.get(names[2])
        if (
            not refresh_token
            and os.environ.get("CAREER_GOOGLE_VAULT_PATH")
            and os.environ.get("CAREER_GOOGLE_KEY_PATH")
        ):
            try:
                key_path = Path(os.environ["CAREER_GOOGLE_KEY_PATH"])
                vault_path = Path(os.environ["CAREER_GOOGLE_VAULT_PATH"])
                if not key_path.is_file() or not vault_path.is_file():
                    raise IntegrationError("google_encrypted_vault_missing")
                refresh_token = TokenVault(key_path, vault_path).load()["refresh_token"]
            except Exception as exc:
                raise IntegrationError("google_encrypted_vault_unreadable") from exc
        if not refresh_token or not all(os.environ.get(name) for name in names[:2]):
            raise IntegrationError("google_credentials_missing")
        try:
            response = self.client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": os.environ[names[0]],
                    "client_secret": os.environ[names[1]],
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            )
            if response.status_code != 200:
                raise IntegrationError("google_token_refresh_failed")
            data = response.json()
            self.access_token = data["access_token"]
            self.expires_at = time.monotonic() + max(0, int(data.get("expires_in", 3600)) - 60)
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise IntegrationError("google_token_refresh_failed") from exc

    def request(self, method, url, *, params=None, body=None, missing_ok=False):
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname not in {"gmail.googleapis.com", "www.googleapis.com"}
            or parsed.username is not None
        ):
            raise IntegrationError("google_destination_not_allowed")
        if method not in {"GET", "POST"} or (
            method == "POST" and not url.endswith("/calendar/v3/calendars/primary/events")
        ):
            raise IntegrationError("google_operation_not_allowed")
        if not self.access_token or time.monotonic() >= self.expires_at:
            self.refresh()
        try:
            response = self.client.request(
                method,
                url,
                params=params,
                json=body,
                headers={"Authorization": "Bearer " + self.access_token},
            )
            if response.status_code == 404 and missing_ok:
                return None
            if response.status_code == 409:
                raise IntegrationError("calendar_conflict")
            if response.status_code not in {200, 201}:
                raise IntegrationError(f"google_http_{response.status_code}")
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise IntegrationError("google_request_failed") from exc

    def profile(self):
        return self.request("GET", "https://gmail.googleapis.com/gmail/v1/users/me/profile")

    def messages(
        self,
        query=(
            "newer_than:30d (subject:application OR subject:interview "
            "OR subject:assessment OR subject:offer)"
        ),
        max_pages=50,
    ):
        rows, token, seen = [], None, set()
        for _ in range(max_pages):
            data = self.request(
                "GET",
                "https://gmail.googleapis.com/gmail/v1/users/me/messages",
                params={"q": query, "maxResults": 100, **({"pageToken": token} if token else {})},
            )
            rows.extend(data.get("messages", []))
            token = data.get("nextPageToken")
            if not token:
                return rows
            if token in seen:
                raise IntegrationError("gmail_pagination_repeated")
            seen.add(token)
        raise IntegrationError("gmail_pagination_incomplete")

    def message(self, message_id):
        return self.request(
            "GET",
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/" + quote(message_id, safe=""),
            params={
                "format": "metadata",
                "metadataHeaders": ["From", "Subject", "Date", "Authentication-Results"],
            },
        )

    def calendar_event(self, event_id):
        return self.request(
            "GET",
            "https://www.googleapis.com/calendar/v3/calendars/primary/events/"
            + quote(event_id, safe=""),
            missing_ok=True,
        )

    def create_calendar_event(self, body):
        return self.request(
            "POST", "https://www.googleapis.com/calendar/v3/calendars/primary/events", body=body
        )

    def close(self):
        self.client.close()
        self.access_token = None
