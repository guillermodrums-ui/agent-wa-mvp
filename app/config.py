import os
import yaml
from pathlib import Path


def load_client_config() -> dict:
    config_path = os.getenv("CLIENT_CONFIG_PATH", "config/config.yaml")
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # Load catalog if exists
    catalog_path = Path(config_path).parent / "catalogo.txt"
    catalog_text = ""
    if catalog_path.exists():
        catalog_text = catalog_path.read_text(encoding="utf-8")

    # Inject catalog into system prompt
    if catalog_text:
        config["agent"]["system_prompt"] += f"\n\n--- CATÁLOGO DE PRODUCTOS ---\n{catalog_text}\n--- FIN CATÁLOGO ---"

    return config


OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
