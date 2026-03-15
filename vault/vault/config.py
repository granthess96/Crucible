import tomllib
from pathlib import Path
from dataclasses import dataclass

@dataclass
class GarageConfig:
    endpoint:   str
    access_key: str
    secret_key: str
    bucket:     str
    region:     str

@dataclass
class ServerConfig:
    host: str
    port: int

@dataclass
class VaultConfig:
    server: ServerConfig
    garage: GarageConfig

def load(path: Path = Path("vault.toml")) -> VaultConfig:
    with path.open("rb") as f:
        raw = tomllib.load(f)
    return VaultConfig(
        server=ServerConfig(**raw["server"]),
        garage=GarageConfig(**raw["garage"]),
    )
