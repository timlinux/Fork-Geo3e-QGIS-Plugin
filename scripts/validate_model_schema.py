# -*- coding: utf-8 -*-

"""Validate geest/resources/model.json against geest/resources/schema.json.

Pre-commit/CI only - jsonschema is a dev dependency (see
requirements-dev.txt and flake.nix), not bundled with the plugin. The
model structure only changes when a developer edits model.json by hand,
so catching a malformed edit here is cheaper than a user hitting it at
runtime.
"""

import json
import sys
from pathlib import Path

import jsonschema

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "geest" / "resources" / "schema.json"
MODEL_PATH = REPO_ROOT / "geest" / "resources" / "model.json"


def main() -> int:
    schema = json.loads(SCHEMA_PATH.read_text())
    model = json.loads(MODEL_PATH.read_text())

    try:
        jsonschema.validate(instance=model, schema=schema)
    except jsonschema.ValidationError as e:
        print(f"{MODEL_PATH} does not match {SCHEMA_PATH}:", file=sys.stderr)
        print(f"  at {'.'.join(str(p) for p in e.absolute_path)}: {e.message}", file=sys.stderr)
        return 1

    print(f"{MODEL_PATH} matches {SCHEMA_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
