"""Environment configuration; paths are relative to the project, not the shell."""
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WEIGHTS = {
    "civil": 20, "discipline": 25, "professional": 20, "mississippi": 10,
    "rfq_rfp": 10, "consulting": 10, "design": 15, "unrelated": -65,
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")
    database_url: str = "sqlite:///./data/opportunities.db"
    scraper_user_agent: str = "MississippiCivilOpportunityFinder/0.1 (local research tool)"
    scraper_timeout: float = Field(default=20, gt=0)
    scraper_delay: float = Field(default=2, ge=0)
    scraper_retries: int = Field(default=3, ge=0, le=5)
    enable_scheduler: bool = False
    scrape_hour: int = Field(default=7, ge=0, le=23)
    scrape_minute: int = Field(default=0, ge=0, le=59)
    scheduler_timezone: str = "America/Chicago"
    due_soon_days: int = Field(default=7, ge=0)
    scoring_weights: dict[str, int] = Field(default_factory=lambda: DEFAULT_WEIGHTS.copy())

    @field_validator("scheduler_timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        ZoneInfo(value)
        return value

    @field_validator("scoring_weights")
    @classmethod
    def valid_weights(cls, value: dict[str, int]) -> dict[str, int]:
        unknown = value.keys() - DEFAULT_WEIGHTS.keys()
        if unknown:
            raise ValueError(f"Unknown score factors: {sorted(unknown)}")
        return DEFAULT_WEIGHTS | value
