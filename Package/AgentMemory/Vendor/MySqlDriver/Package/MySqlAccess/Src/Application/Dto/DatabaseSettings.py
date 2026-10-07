from dataclasses import dataclass


@dataclass(frozen=True)
class DatabaseSettings:
    host: str = "127.0.0.1"
    port: int = 3306
    user: str = "nanocode_memory"
    password: str = ""
    database: str = "nanocode_memory"
    connect_timeout: int = 10
    tls: bool = True

