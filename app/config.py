import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "Quantitative Crypto Trading Terminal"
    API_V1_STR: str = "/api"
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    
    # MySQL Database Settings
    MYSQL_HOST: str = "localhost"
    MYSQL_PORT: int = 3306
    MYSQL_USER: str = "root"
    MYSQL_PASSWORD: str = ""
    MYSQL_DB: str = "crypto_trading"
    
    DATABASE_URL: str = "mysql+pymysql://root:@localhost:3306/crypto_trading"
    EXPORT_DIR: str = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "export_app_data"))

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # Ignore any extra environment variables gracefully
        case_sensitive=False
    )

settings = Settings()
