# Dublin's Protected Buildings

A map of every building on Dublin City Council's Record of Protected Structures
(RPS), with build dates, photos and history from the National Inventory of
Architectural Heritage (NIAH), and the city's Z2 / Z8 conservation zones.

Live at **https://sumitnarang.com/old-build/**. A hobby, non-commercial project.

## Run it locally

```bash
cp .env.example .env          # paste a public Mapbox token (pk.…) into MAPBOX_TOKEN
python3 serve.py              # writes web/config.js, serves http://localhost:8766/web/index.html
```

No build step and no dependencies: Python 3 standard library for the pipeline and
server, plain HTML/CSS/JS for the page (Mapbox GL JS v3.9 from Mapbox's CDN).

## Data pipeline

The generated data in `web/data/` is committed, so you only need this to refresh it.

```bash
python3 run_pipeline.py               # all stages
python3 run_pipeline.py --from zones  # re-run from one stage onwards
```

| Stage | File | What it does |
|---|---|---|
| fetch | `pipeline/fetch.py` | Downloads the RPS CSV from Smart Dublin to `data/raw/rps.csv` |
| normalize | `pipeline/normalize.py` | Reads the CSV (cp1252, not UTF-8), repairs Excel-mangled numbers (`07-Aug` → `7-8`), converts Irish Grid to WGS84 |
| niah | `pipeline/niah.py` | Matches rows to NIAH records (street + number, then street, then location) for dates, type, appraisal and photo |
| zones | `pipeline/zones.py` | Tags each row with the Z2 / Z8 zone it sits in and simplifies the zone shapes for the map |
| build | `pipeline/build.py` | Writes `web/data/structures.json` (slim rows), `web/data/zones.geojson` and `web/data/details/*.json` (40 shards, loaded when a card opens) |

Notes on the data:

- The RPS coordinates are Irish Grid (TM65, EPSG:29902). `pipeline/irish_grid.py`
  converts them; about 98% of central-Dublin points land inside an OSM building.
  The council's own RPS GeoJSON is misprojected, so it isn't used.
- About 47% of RPS rows match an NIAH record. Dublin 4 and 6 have almost none,
  because NIAH hasn't published its survey of the south suburbs.
- Architectural Conservation Areas aren't available as open data, so they aren't shown.

## Deploy

The site is static and is served by nginx on the Hetzner server, from
`/var/www/old-build` at `sumitnarang.com/old-build/`.

```bash
./deploy.sh
```

It copies `web/` to `dist/`, writes `dist/config.js` from `.env.production`, uploads
`dist/` with rsync and checks the live URLs. `.env.production` holds the server
login and the production Mapbox token (the same one as the mountains project, restricted to
`https://sumitnarang.com/*`):

```
MAPBOX_TOKEN=pk.…
MAP_STYLE=mapbox://styles/mapbox/light-v11
DEPLOY_SERVER=user@host       # SSH login for the server (see server.md)
```

The nginx config (`/etc/nginx/sites-available/sumitnarang`) has:

```nginx
location = /old-build {
    return 301 /old-build/;
}

location /old-build/ {
    alias /var/www/old-build/;
    index index.html;
    try_files $uri $uri/ =404;
    add_header Cache-Control "no-cache" always;
}
```

The redirect matters: the page loads its files by relative path, so without the
trailing slash it would look for `/data/…` instead of `/old-build/data/…`.

## Secrets

`.env`, `.env.production`, `web/config.js` and `dist/` are git-ignored and must never be
committed. Mapbox tokens are public by design (the browser needs them), so the
production token is protected by its URL restriction, not by being hidden.

## Credits

- Record of Protected Structures: Dublin City Council, via
  [Smart Dublin](https://data.smartdublin.ie/dataset/record-protected-structures-dcc) (CC-BY 4.0)
- Building records and photos: [National Inventory of Architectural Heritage](https://www.buildingsofireland.ie)
- Conservation zones: Dublin City Development Plan 2022–2028, via Smart Dublin
- Map: © Mapbox © OpenStreetMap; satellite imagery © Maxar
