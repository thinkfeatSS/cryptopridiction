import os
try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
except ImportError:
    try:
        from pydantic import BaseSettings
        SettingsConfigDict = None
    except ImportError:
        class BaseSettings:
            pass
        SettingsConfigDict = None

class Settings(BaseSettings):
    PROJECT_NAME: str = "Quantitative Crypto Trading Terminal"
    API_V1_STR: str = "/api"
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    
    # MySQL Database Settings
    MYSQL_HOST: str = os.getenv("MYSQL_HOST", "localhost")
    MYSQL_PORT: int = int(os.getenv("MYSQL_PORT", "3306"))
    MYSQL_USER: str = os.getenv("MYSQL_USER", "root")
    MYSQL_PASSWORD: str = os.getenv("MYSQL_PASSWORD", "")
    MYSQL_DB: str = os.getenv("MYSQL_DB", "crypto_trading")
    
    DATABASE_URL: str = os.getenv("DATABASE_URL", "mysql+pymysql://root:@localhost:3306/crypto_trading")
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    EXPORT_DIR: str = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "export_app_data"))
    WEBSOCKET_FEED_ENABLED: bool = os.getenv("WEBSOCKET_FEED_ENABLED", "true").lower() in ("true", "1", "yes")
    # Signal Expiry Policy: when False (default), signals and positions never expire by time/horizon/TTL
    # and strictly wait until Take Profit (TP) or Stop Loss (SL) is hit.
    ENABLE_SIGNAL_EXPIRY: bool = os.getenv("ENABLE_SIGNAL_EXPIRY", "false").lower() in ("true", "1", "yes")

    # WhatsApp Automation & Broadcast Settings
    WHATSAPP_ENABLED: bool = os.getenv("WHATSAPP_ENABLED", "false").lower() in ("true", "1", "yes")
    WHATSAPP_GATEWAY_TYPE: str = os.getenv("WHATSAPP_GATEWAY_TYPE", "evolution_api")
    WHATSAPP_API_URL: str = os.getenv("WHATSAPP_API_URL", "http://whatsapp:8080")
    WHATSAPP_API_KEY: str = os.getenv("WHATSAPP_API_KEY", "crypto_quant_secret_2026")
    WHATSAPP_INSTANCE_NAME: str = os.getenv("WHATSAPP_INSTANCE_NAME", "crypto_bot")
    WHATSAPP_GROUP_ID: str = os.getenv("WHATSAPP_GROUP_ID", "")
    WHATSAPP_CHANNEL_ID: str = os.getenv("WHATSAPP_CHANNEL_ID", "")
    
    # Automated Quality & Trigger Filters
    WHATSAPP_MIN_GRADE: str = os.getenv("WHATSAPP_MIN_GRADE", "Grade A")
    WHATSAPP_MIN_WIN_PROB: float = float(os.getenv("WHATSAPP_MIN_WIN_PROB", "0.70"))
    WHATSAPP_SEND_TP_UPDATES: bool = os.getenv("WHATSAPP_SEND_TP_UPDATES", "true").lower() in ("true", "1", "yes")
    WHATSAPP_SEND_SL_UPDATES: bool = os.getenv("WHATSAPP_SEND_SL_UPDATES", "true").lower() in ("true", "1", "yes")
    WHATSAPP_SEND_REGIME_ALERTS: bool = os.getenv("WHATSAPP_SEND_REGIME_ALERTS", "true").lower() in ("true", "1", "yes")
    WHATSAPP_RATE_LIMIT_SECONDS: float = float(os.getenv("WHATSAPP_RATE_LIMIT_SECONDS", "2.0"))

    # Fundamental & News Intelligence Settings
    COINMARKETCAL_API_KEY: str = os.getenv("COINMARKETCAL_API_KEY", "")
    COINMARKETCAP_API_KEY: str = os.getenv("COINMARKETCAP_API_KEY", "")
    COINGECKO_API_KEY: str = os.getenv("COINGECKO_API_KEY", "")
    CRYPTOPANIC_API_KEY: str = os.getenv("CRYPTOPANIC_API_KEY", "")
    FUNDAMENTAL_CACHE_TTL_SECONDS: int = int(os.getenv("FUNDAMENTAL_CACHE_TTL_SECONDS", "1800"))  # 30 mins
    FEAR_GREED_ENABLED: bool = os.getenv("FEAR_GREED_ENABLED", "true").lower() in ("true", "1", "yes")
    DEFILLAMA_ENABLED: bool = os.getenv("DEFILLAMA_ENABLED", "true").lower() in ("true", "1", "yes")
    NEWS_SENTIMENT_ENABLED: bool = os.getenv("NEWS_SENTIMENT_ENABLED", "true").lower() in ("true", "1", "yes")

    if SettingsConfigDict:
        model_config = SettingsConfigDict(
            env_file=".env",
            env_file_encoding="utf-8",
            extra="ignore",
            case_sensitive=False
        )

settings = Settings()
