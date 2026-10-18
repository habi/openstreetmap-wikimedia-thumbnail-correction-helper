# osm-wikimedia-thumbnails-correction-bot

An OpenStreetMap bot that replaces **broken** Wikimedia Commons thumbnail links in
`image=*` with the file's description page on Commons:

```
image=https://upload.wikimedia.org/wikipedia/commons/thumb/e/e9/Strassenschild_Kirchbergerstrasse.jpg/800px-Strassenschild_Kirchbergerstrasse.jpg
  →   https://commons.wikimedia.org/wiki/File:Strassenschild_Kirchbergerstrasse.jpg
```

## Why

Wikimedia now only serves hotlinked thumbnails in the
[standard widths](https://www.mediawiki.org/wiki/Common_thumbnail_sizes)
(20, 40, 60, 120, 250, 330, 500, 960, 1280, 1920, 3840 px,
[T414805](https://phabricator.wikimedia.org/T414805)). Everything else returns
HTTP 400, so thousands of `image=*` tags are dead links. The description page
always works, and it shows the author and license, which a bare thumbnail does not.

## What it touches

Only `image=*` values that are **exactly one** URL of the form
`https://upload.wikimedia.org/wikipedia/commons/thumb/<h>/<hh>/<File>/<…><width>px-<…>`, where

- the `<h>/<hh>` directory matches the MD5 of the decoded file name (so the name was parsed correctly),
- the file still exists on Commons (renamed files are followed to their current name),
- the thumbnail is broken: its width is not a standard width, or it is wider than
  the original bitmap.

It leaves alone working thumbnails, original-file links (`/commons/<h>/<hh>/…`),
other wikis (`/wikipedia/de/…`), multiple values (`;`), other keys
(`wikimedia_commons`, `image:*`, …) and anything it can't parse.

## Keeping load low

- **Overpass**: one query per run, limited to a country (`AREA`, default `CH`),
  `out tags;` only (no geometry). Retries with backoff on 429/5xx. Runs weekly.
- **Wikimedia**: whether a thumbnail works comes from its width, so no thumbnail is
  ever downloaded. The Action API is queried 50 files per request, one request at a
  time with a 1 s pause, `maxlag=5`, and a descriptive User-Agent. It stops as soon
  as `MAX_EDITS` broken links have been found.
- **OSM API**: multi-fetch (`/nodes?nodes=…`) of only the elements that will be
  edited, one changeset per run, at most `MAX_EDITS` (default 200) edits.

## Running locally

```sh
pip install -r requirements.txt
python bot.py --area CH --max-edits 50 --report report.json   # dry run
OSM_ACCESS_TOKEN=… python bot.py --area CH --apply           # upload
pytest -q
```

## GitHub Action

`.github/workflows/fix-commons-thumbnails.yml` runs the tests and then the bot every
Monday, and can also be started manually (*Actions → Run workflow*). The planned
edits are attached to each run as `report.json` and shown in the job summary.

Setup:

1. Create a dedicated OSM bot account (e.g. `yourname_bot`) and an OAuth 2 application
   for it with the `write_api` scope. Get an access token and store it as the
   repository secret **`OSM_ACCESS_TOKEN`**.
2. Optional repository variables: `AREA` (ISO 3166-1 code or `world`), `MAX_EDITS`,
   `CHANGESET_DESCRIPTION_URL` (link to the bot's OSM wiki page, added to each
   changeset).
3. Scheduled runs are **dry runs** until you set the repository variable
   **`BOT_ENABLED=true`**. Manual runs upload only if *apply* is ticked.

> ⚠️ Before enabling uploads, follow the OSM
> [Automated Edits code of conduct](https://wiki.openstreetmap.org/wiki/Automated_Edits_code_of_conduct):
> document the bot on the OSM wiki, discuss it with the affected community (e.g. the
> Swiss community on community.openstreetmap.org), and use a separate bot account.
