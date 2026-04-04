from pathlib import Path


def load_prompt(filename: str) -> str:
    """Load a prompt template from the prompts directory."""
    return (Path(__file__).parent / filename).read_text(encoding="utf-8").strip()
