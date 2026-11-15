"""Server settings, read from the environment (.env is loaded by the pipeline module).

AGENT_MODE        bedrock (default) | demo  (demo = scripted boss/presenter, no LLM, real worker numbers)
COGNITO_USER_POOL_ID, COGNITO_CLIENT_ID   set both to verify Cognito ID tokens; otherwise dev auth
COGNITO_REGION    default us-east-1
CORS_ORIGINS      comma-separated list, default "*"
"""
import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Settings:
    agent_mode: str = "bedrock"
    cognito_pool_id: str | None = None
    cognito_client_id: str | None = None
    cognito_region: str = "us-east-1"
    cors_origins: list[str] = field(default_factory=lambda: ["*"])
    ticket_ttl_seconds: int = 30

    @property
    def auth_mode(self) -> str:
        return "cognito" if self.cognito_pool_id and self.cognito_client_id else "dev"


def load_settings() -> Settings:
    mode = os.getenv("AGENT_MODE", "bedrock").strip().lower()
    origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]
    return Settings(agent_mode="demo" if mode == "demo" else "bedrock",
                    cognito_pool_id=os.getenv("COGNITO_USER_POOL_ID") or None,
                    cognito_client_id=os.getenv("COGNITO_CLIENT_ID") or None,
                    cognito_region=os.getenv("COGNITO_REGION", "us-east-1"),
                    cors_origins=origins or ["*"])
