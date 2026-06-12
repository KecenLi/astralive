import os

import google.auth
from google.auth.exceptions import DefaultCredentialsError

from app.config import Settings


class GoogleGenAIClientFactory:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._default_project: str | None = None

    def vertex_client(self):
        from google import genai
        from google.genai import types

        self._prepare_credentials_env()
        project = self._vertex_project()
        endpoint = self.settings.vertex_ai_api_endpoint.strip().rstrip("/")
        default_endpoint = "https://aiplatform.googleapis.com"
        http_options = (
            types.HttpOptions(base_url=endpoint, api_version="v1")
            if endpoint and endpoint != default_endpoint
            else None
        )
        return genai.Client(
            vertexai=True,
            project=project,
            location=self.settings.vertex_ai_location,
            http_options=http_options,
        )

    def gemini_client(self):
        from google import genai

        if not self.settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is not configured.")
        return genai.Client(api_key=self.settings.gemini_api_key)

    def _vertex_project(self) -> str:
        self._prepare_credentials_env()
        if self.settings.vertex_ai_project:
            return self.settings.vertex_ai_project
        if self._default_project:
            return self._default_project
        try:
            _credentials, project = google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
        except DefaultCredentialsError as exc:
            raise RuntimeError(
                "Application Default Credentials were not found. Run "
                "`gcloud auth application-default login` first."
            ) from exc
        if not project:
            raise RuntimeError("VERTEX_AI_PROJECT is not configured and ADC did not provide a project.")
        self._default_project = project
        return project

    def _prepare_credentials_env(self) -> None:
        credentials_path = self.settings.google_application_credentials.strip()
        if credentials_path and not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = credentials_path
