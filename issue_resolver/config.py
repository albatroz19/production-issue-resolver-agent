from pathlib import Path
from typing import List

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"


class RepoConfig(BaseModel):
    name: str
    path: str


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE if ENV_FILE.exists() else None,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    azure_openai_api_key: str = ""
    azure_openai_endpoint: str = ""
    azure_openai_deployment: str = "gpt-4o"
    azure_openai_api_version: str = "2024-08-01-preview"

    openai_api_key: str = ""
    openai_model: str = "gpt-4o"

    repos_root: str = "/Users/amitasharda/Desktop/Segmentation"
    repos: List[RepoConfig] = Field(
        default_factory=lambda: [
            RepoConfig(name="campaign-management-service", path="campaign-management-service"),
            RepoConfig(name="ad-management-service", path="ad-management-service"),
        ]
    )

    max_snippet_lines: int = 150
    max_files_per_request: int = 3
    agent_max_steps: int = 8

    poc_api_key: str = ""
    host: str = "0.0.0.0"
    port: int = 8098

    @property
    def service_map_path(self) -> Path:
        return PROJECT_ROOT / "config" / "service-map.yml"

    @property
    def llm_provider(self) -> str | None:
        if self.openai_api_key:
            return "openai"
        if self.azure_openai_api_key and self.azure_openai_endpoint:
            return "azure"
        return None

    @property
    def llm_enabled(self) -> bool:
        return self.llm_provider is not None

    @property
    def llm_model(self) -> str:
        if self.llm_provider == "openai":
            return self.openai_model
        return self.azure_openai_deployment


settings = Settings()
