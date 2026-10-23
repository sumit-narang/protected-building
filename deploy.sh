#!/usr/bin/env bash
# Deploy the map to https://sumitnarang.com/old-build/
#
# Copies web/ into dist/, writes dist/config.js from .env.production (the
# production Mapbox token, URL-restricted to sumitnarang.com), uploads dist/ to
# the Hetzner server (DEPLOY_SERVER in .env.production) and checks the live
# site. nginx serves /var/www/old-build at /old-build (see README.md); the
# server needs nothing else.
set -euo pipefail

REMOTE_DIR=/var/www/old-build
URL=https://sumitnarang.com/old-build/

cd "$(dirname "$0")"

if [[ ! -f .env.production ]]; then
  echo "Missing .env.production (MAPBOX_TOKEN=pk.… restricted to https://sumitnarang.com/*)." >&2
  exit 1
fi
SERVER=$(sed -n 's/^DEPLOY_SERVER=//p' .env.production)
if [[ -z "$SERVER" ]]; then
  echo "Add DEPLOY_SERVER=user@host to .env.production." >&2
  exit 1
fi

echo "Building dist/..."
rsync -a --delete --exclude config.js --exclude .DS_Store web/ dist/
python3 serve.py --build --env .env.production --out dist/config.js

echo "Uploading to $SERVER:$REMOTE_DIR..."
ssh "$SERVER" "mkdir -p $REMOTE_DIR"
rsync -avz --delete dist/ "$SERVER:$REMOTE_DIR/"

echo "Checking $URL..."
for path in "" "config.js" "data/structures.json" "data/details/0.json" "icons/favicon.png"; do
  code=$(curl -s -o /dev/null -w "%{http_code}" "$URL$path")
  echo "  $code  /old-build/$path"
  [[ "$code" == 200 ]] || { echo "Deploy check failed." >&2; exit 1; }
done
code=$(curl -s -o /dev/null -w "%{http_code} %{redirect_url}" "${URL%/}")
echo "  $code  (/old-build without the slash should 301 to /old-build/)"
echo "Done: $URL"
