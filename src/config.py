from pydantic import PostgresDsn, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    PROJECT_NAME: str = "Generala API"

    # Authentication settings
    TOKEN: str | None = None

    # CORS settings
    CORS_ORIGINS: list[str] = ["*"]

    @field_validator("CORS_ORIGINS", mode="before")
    def assemble_cors_origins(cls, v: str | list[str]) -> list[str] | str:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        return v

    CORS_ALLOW_CREDENTIALS: bool = True
    CORS_ALLOW_METHODS: list[str] = ["*"]
    CORS_ALLOW_HEADERS: list[str] = ["*"]

    # Database settings
    DB_TYPE: str = "sqlite" # "sqlite" or "postgres"
    DB_USER: str | None = None
    DB_PASSWORD: str | None = None
    DB_HOST: str | None = None
    DB_PORT: str | None = None
    DB_NAME: str | None = None

    DATABASE_URL: str | None = None

    @field_validator("DATABASE_URL", mode='before')
    def assemble_db_connection(cls, v: str | None, values) -> any:
        if isinstance(v, str):
            return v
        
        data = values.data
        if data.get("DB_TYPE") == "sqlite":
            return "sqlite:///./data/generala.db"
        
        return str(PostgresDsn.build(
            scheme="postgresql",
            username=data.get("DB_USER"),
            password=data.get("DB_PASSWORD"),
            host=data.get("DB_HOST"),
            port=int(data.get("DB_PORT", 5432)),
            path=f"/{data.get('DB_NAME') or ''}",
        ))

    class Config:
        case_sensitive = True
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings() 
