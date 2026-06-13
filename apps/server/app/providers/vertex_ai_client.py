import json
import os
from urllib import error, request

import google.auth
from google.auth.credentials import Credentials
from google.auth.exceptions import DefaultCredentialsError
from google.auth.transport.requests import Request as AuthRequest

from app.config import Settings


class VertexAIClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._credentials: Credentials | None = None
        self._default_project: str | None = None

    def generate_content(self, model: str, payload: dict) -> dict:
        project = self._project_id()
        token = self._access_token()
        endpoint = self.settings.vertex_ai_api_endpoint.rstrip("/")
        location = self.settings.vertex_ai_location
        url = (
            f"{endpoint}/v1/projects/{project}/locations/{location}/publishers/google/"
            f"models/{model}:generateContent"
        )
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            url,
            data=body,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "X-Goog-User-Project": project,
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.settings.vertex_ai_request_timeout_seconds) as response:  # noqa: S310
                return json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Vertex AI request failed with HTTP {exc.code}: {details}") from exc

    def _project_id(self) -> str:
        if self.settings.vertex_ai_project:
            return self.settings.vertex_ai_project
        self._ensure_credentials()
        if self._default_project:
            return self._default_project
        raise RuntimeError("VERTEX_AI_PROJECT is not configured and ADC did not provide a project.")

    def _access_token(self) -> str:
        credentials = self._ensure_credentials()
        if not credentials.valid:
            credentials.refresh(AuthRequest())
        if not credentials.token:
            raise RuntimeError("ADC did not return an access token.")
        return credentials.token

    def _ensure_credentials(self) -> Credentials:
        if self._credentials is None:
            credentials_path = self.settings.google_application_credentials.strip()
            if credentials_path and not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
                os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = credentials_path
            try:
                self._credentials, self._default_project = google.auth.default(
                    scopes=["https://www.googleapis.com/auth/cloud-platform"]
                )
            except DefaultCredentialsError as exc:
                raise RuntimeError(
                    "Application Default Credentials were not found. Run "
                    "`gcloud auth application-default login` first."
                ) from exc
        return self._credentials
