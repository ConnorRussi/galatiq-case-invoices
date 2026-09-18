"""Validated ingestion configuration."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field


class _ConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ModelSettings(_ConfigModel):
    flash_model: str = "protected.gpt-4.1-mini"


class LimitSettings(_ConfigModel):
    request_timeout_seconds: int = Field(default=45, ge=1)

class DocumentSettings(_ConfigModel):
    max_file_bytes: int = Field(default=10_000_000, ge=1)
    max_pdf_pages: int = Field(default=25, ge=1)
    max_extracted_characters: int = Field(default=100_000, ge=1)
    minimum_alphanumeric_characters: int = Field(default=20, ge=0)


class IngestionSettings(_ConfigModel):
    models: ModelSettings = Field(default_factory=ModelSettings)
    limits: LimitSettings = Field(default_factory=LimitSettings)
    documents: DocumentSettings = Field(default_factory=DocumentSettings)


def load_settings(path: Path | None = None) -> IngestionSettings:
    workspace = Path(__file__).resolve().parents[4]
    load_dotenv(workspace / ".env")
    config_path = path or Path(__file__).with_name("config.toml")
    with config_path.open("rb") as handle:
        payload = tomllib.load(handle)

    for section, schema in (
        ("models", ModelSettings),
        ("limits", LimitSettings),
        ("documents", DocumentSettings),
    ):
        for name in schema.model_fields:
            override = os.getenv(f"INGESTION_{section}_{name}".upper())
            if override is not None:
                payload.setdefault(section, {})[name] = override
    return IngestionSettings.model_validate(payload)


def get_tamu_api_key() -> str | None:
    return os.getenv("TAMU_CHAT_API_KEY")


def get_tamu_base_url() -> str | None:
    return os.getenv("TAMU_CHAT_BASE_URL")
