"""Export OpenAPI schema to docs/openapi.json and docs/openapi.yaml."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.main import create_app  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "docs"


def main():
    app = create_app()
    schema = app.openapi()
    OUT.mkdir(parents=True, exist_ok=True)

    (OUT / "openapi.json").write_text(
        json.dumps(schema, indent=2), encoding="utf-8"
    )
    (OUT / "openapi.yaml").write_text(
        yaml.dump(schema, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    print(f"Wrote {OUT / 'openapi.json'}")
    print(f"Wrote {OUT / 'openapi.yaml'}")


if __name__ == "__main__":
    main()
