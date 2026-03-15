from pathlib import Path
from vault.config import load
from vault.garage import GarageStore
from vault import api

def main():
    cfg = load(Path("vault.toml"))
    api.store = GarageStore(cfg.garage)

    from waitress import serve
    print(f"Vault listening on {cfg.server.host}:{cfg.server.port}")
    serve(api.app, host=cfg.server.host, port=cfg.server.port)

if __name__ == "__main__":
    main()
