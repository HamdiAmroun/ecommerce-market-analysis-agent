import json
from pathlib import Path


def load_schema(filename: str) -> dict:
    """Load a JSON schema from the schemas directory."""
    return json.loads((Path(__file__).parent / filename).read_text(encoding="utf-8"))


def schema_as_string(filename: str) -> str:
    """Load a JSON schema and return it as a formatted string for prompt injection."""
    return json.dumps(load_schema(filename), indent=2)
