#!/bin/sh
set -eu
cd "$(dirname "$0")/../apps/api"
.venv/bin/python -c 'import json; from pluto.main import app; open("../../packages/openapi.json", "w").write(json.dumps(app.openapi(), indent=2)+"\n")'
cd ../web
npx openapi-typescript ../../packages/openapi.json -o lib/contracts.ts
