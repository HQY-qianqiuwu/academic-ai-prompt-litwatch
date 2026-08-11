from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from litwatch.runtime import RuntimeMode


class Topic(BaseModel):
    id: str
    name: str
    query: str
    include: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)
    domain_anchors: list[str] = Field(default_factory=list)
    method_terms: list[str] = Field(default_factory=list)
    require_domain_anchor: bool = False
    categories: list[str] = Field(default_factory=list)
    analysis_mode: str = "quick_scan"
    min_score: float = Field(default=0.3, ge=0, le=1)

    @field_validator("id")
    @classmethod
    def valid_id(cls, value: str) -> str:
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", value):
            raise ValueError("topic id must use lowercase letters, numbers, '_' or '-'")
        return value

    @field_validator("domain_anchors", "method_terms", mode="before")
    @classmethod
    def flatten_any_terms(cls, value):
        if isinstance(value, dict):
            return value.get("any", [])
        return value


class TopicFile(BaseModel):
    topics: list[Topic]


class AnalysisMode(BaseModel):
    id: str
    name: str
    description: str
    instruction: str


class AnalysisModeFile(BaseModel):
    modes: list[AnalysisMode]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LITWATCH_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    openalex_email: str = ""
    openalex_base_url: str = "https://api.openalex.org/works"
    semantic_scholar_base_url: str = "https://api.semanticscholar.org"
    semantic_scholar_api_key: str = ""
    ieee_xplore_api_key: str = ""
    semantic_scholar_anonymous: bool = False
    arxiv_base_url: str = "https://export.arxiv.org/api/query"
    crossref_base_url: str = "https://api.crossref.org/v1/works"
    crossref_email: str = ""
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-5-mini"
    llm_provider_kind: Literal["local", "cloud"] = "cloud"
    llm_max_output_tokens: int = Field(default=2_048, ge=1, le=100_000)
    llm_input_cost_per_million: float = Field(
        default=0.0, ge=0, allow_inf_nan=False
    )
    llm_output_cost_per_million: float = Field(
        default=0.0, ge=0, allow_inf_nan=False
    )
    llm_cloud_egress_consent: bool = False
    llm_fulltext_egress_consent: bool = False
    llm_max_payload_chars: int = Field(default=50_000, ge=1, le=1_000_000)
    max_tokens_per_job: int = Field(default=20_000, ge=1, le=10_000_000)
    max_cost_per_job: float = Field(
        default=1.0, gt=0, le=10_000, allow_inf_nan=False
    )
    max_daily_cost: float = Field(
        default=5.0, gt=0, le=100_000, allow_inf_nan=False
    )
    max_concurrent_llm_jobs: int = Field(default=2, ge=1, le=100)
    runtime_mode: RuntimeMode = RuntimeMode.PYTHON_DEFAULT

    smtp_host: str = ""
    smtp_port: int = 465
    smtp_username: str = ""
    smtp_password: str = ""
    email_from: str = ""
    email_to: str = ""

    zotero_user_id: str = ""
    zotero_api_key: str = ""

    database_path: Path = Path("data/litwatch.db")
    database_backup_path: Path = Path("data/backups")
    topics_path: Path = Path("config/topics.yaml")
    analysis_modes_path: Path = Path("config/analysis_modes.yaml")
    lookback_days: int = Field(default=14, ge=1, le=365)
    max_results_per_source: int = Field(default=50, ge=1, le=200)
    analyze_top_n: int = Field(default=8, ge=0, le=50)
    fulltext_top_n: int = Field(default=3, ge=0, le=20)
    request_timeout_seconds: float = Field(default=30, ge=5, le=120)
    scheduler_poll_seconds: float = Field(default=30, ge=1, le=3600)
    scheduler_lease_seconds: int = Field(default=300, ge=30, le=3600)
    job_poll_seconds: float = Field(default=1, gt=0, le=3600)
    job_lease_seconds: int = Field(default=300, ge=1, le=3600)
    job_concurrency: int = Field(default=2, ge=1, le=16)
    job_default_timeout_seconds: int = Field(default=300, ge=1, le=3600)

    def ensure_runtime_files(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.topics_path.exists():
            self.topics_path.parent.mkdir(parents=True, exist_ok=True)
            example = self.topics_path.with_name("topics.example.yaml")
            if example.exists():
                shutil.copyfile(example, self.topics_path)

    def load_topics(self) -> list[Topic]:
        self.ensure_runtime_files()
        if not self.topics_path.exists():
            raise FileNotFoundError(
                f"Missing {self.topics_path}; copy config/topics.example.yaml and edit it."
            )
        payload = yaml.safe_load(self.topics_path.read_text(encoding="utf-8")) or {}
        return TopicFile.model_validate(payload).topics

    def load_analysis_modes(self) -> list[AnalysisMode]:
        payload = yaml.safe_load(self.analysis_modes_path.read_text(encoding="utf-8")) or {}
        return AnalysisModeFile.model_validate(payload).modes
