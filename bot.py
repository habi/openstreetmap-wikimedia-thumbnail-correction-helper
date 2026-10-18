#!/usr/bin/env python3
"""Replace broken Wikimedia Commons thumbnail URLs in OSM `image` tags with the
file's description page on Commons.

    image=https://upload.wikimedia.org/wikipedia/commons/thumb/e/e9/Foo.jpg/800px-Foo.jpg
 -> image=https://commons.wikimedia.org/wiki/File:Foo.jpg

Wikimedia only serves thumbnails in a fixed set of widths (and, for bitmaps, no wider
than the original); other hotlinked thumbnails return HTTP 400. The description page
also carries author and license information, which a bare thumbnail does not.

Only the `image` key is touched, only if its *whole* value is a single Commons
thumbnail URL, and only if that thumbnail no longer works. Everything else is left alone.

Load on external services is kept low:
  * Overpass: one query per run, restricted to an area, returning tags only.
  * Wikimedia: whether a thumbnail works is decided from its width, without fetching
    it; existence, renames and original size come from the API in batches of 50
    titles with `maxlag`, sequentially.
  * OSM API: elements are fetched with multi-fetch calls, all edits go into one changeset.

Runs as a dry run unless `--apply` is given.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from urllib.parse import quote, unquote

import requests

USER_AGENT = os.environ.get(
    "BOT_USER_AGENT",
    "wikimedia-thumbnails-osm-bot/1.0 (https://github.com/habi/osm-wikimedia-thumbnails-correction-bot)",
)
OVERPASS_URL = os.environ.get("OVERPASS_URL", "https://overpass-api.de/api/interpreter")
OSM_API = os.environ.get("OSM_API", "https://api.openstreetmap.org/api/0.6")
COMMONS_API = "https://commons.wikimedia.org/w/api.php"

CHANGESET_COMMENT = (
    "Replace broken Wikimedia Commons thumbnail URLs in image=* "
    "with links to the file description page on Commons"
)

# The whole value must be exactly one Commons thumbnail URL. The file name is taken
# from the directory segment, not the last segment, as thumbnail names vary
# (800px-X.jpg, 800px-X.svg.png, page1-800px-X.pdf.jpg, ...).
THUMB_RE = re.compile(
    r"^https?://upload\.wikimedia\.org/wikipedia/commons/thumb/"
    r"(?P<h1>[0-9a-f])/(?P<h2>[0-9a-f]{2})/(?P<name>[^/?#]+)/(?P<thumb>[^/?#]+)$"
)
# Thumbnail widths Wikimedia serves to external requests, see
# https://www.mediawiki.org/wiki/Common_thumbnail_sizes (T414805)
STANDARD_WIDTHS = {20, 40, 60, 120, 250, 330, 500, 960, 1280, 1920, 3840}
WIDTH_RE = re.compile(r"(?:^|-)(\d+)px-")
# Same constraint in Overpass regex syntax (pre-filter only, THUMB_RE decides).
OVERPASS_REGEX = r"^https?://upload\\.wikimedia\\.org/wikipedia/commons/thumb/"


def log(*args):
    print(*args, file=sys.stderr, flush=True)


IN_ACTIONS = os.environ.get("GITHUB_ACTIONS") == "true"


def log_group(title: str, lines: list[str]):
    """Log a list, collapsible in the GitHub Actions log."""
    if IN_ACTIONS:
        log(f"::group::{title}")
    else:
        log(f"\n{title}")
    for line in lines:
        log(f"  {line}")
    if IN_ACTIONS:
        log("::endgroup::")


def osm_url(ref: str) -> str:
    return f"https://www.openstreetmap.org/{ref}"


def session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    return s


def request_with_retry(s: requests.Session, method: str, url: str, *, tries: int = 4, **kw):
    """Retry on rate limiting / overload with exponential backoff."""
    delay = 30
    timeout = kw.pop("timeout", 360)
    for attempt in range(1, tries + 1):
        r = s.request(method, url, timeout=timeout, **kw)
        if r.status_code not in (429, 502, 503, 504) or attempt == tries:
            r.raise_for_status()
            return r
        wait = int(r.headers.get("Retry-After", delay))
        log(f"  {r.status_code} from {url}, retrying in {wait}s")
        time.sleep(wait)
        delay *= 2


# --- URL handling -----------------------------------------------------------


@dataclass(frozen=True)
class Thumb:
    name: str  # Commons file name, with underscores
    width: int


def parse_thumb_url(url: str) -> Thumb | None:
    """Return file name and width of a Commons thumbnail URL, else None."""
    m = THUMB_RE.match(url.strip())
    if not m:
        return None
    w = WIDTH_RE.search(unquote(m["thumb"]))
    if not w:
        return None
    name = unquote(m["name"])
    # Commons stores files under md5(name)[0]/md5(name)[0:2]. If that doesn't match,
    # we didn't decode the name correctly (or the URL is odd), so don't touch it.
    digest = hashlib.md5(name.encode("utf-8")).hexdigest()
    if m["h1"] != digest[0] or m["h2"] != digest[:2]:
        return None
    return Thumb(name, int(w[1]))


def is_broken(thumb: Thumb, info: dict) -> bool:
    """Whether Wikimedia refuses to serve this thumbnail. `info` is the file's imageinfo."""
    if thumb.width not in STANDARD_WIDTHS:
        return True
    # Bitmaps are not upscaled; asking for more than the original gives a 400.
    return info.get("mediatype") == "BITMAP" and thumb.width > info.get("width", thumb.width)


def commons_page_url(filename: str) -> str:
    """https://commons.wikimedia.org/wiki/File:<name>, escaping only what breaks a URL."""
    name = filename.replace(" ", "_")
    name = "".join(quote(c) if c in '%?#"<>[]{}|\\^`' else c for c in name)
    return f"https://commons.wikimedia.org/wiki/File:{name}"


# --- Overpass ---------------------------------------------------------------


def overpass_query(area: str) -> str:
    if area and area.lower() != "world":
        scope = f'area["ISO3166-1"="{area}"][admin_level=2]->.a;\n'
        selector = f'nwr(area.a)["image"~"{OVERPASS_REGEX}"];'
    else:
        scope = ""
        selector = f'nwr["image"~"{OVERPASS_REGEX}"];'
    return f"[out:json][timeout:600];\n{scope}{selector}\nout tags;"


def find_candidates(s: requests.Session, area: str) -> list[dict]:
    query = overpass_query(area)
    log(f"Overpass query:\n{query}")
    r = request_with_retry(s, "POST", OVERPASS_URL, data={"data": query}, timeout=660)
    elements = r.json()["elements"]
    log(f"Overpass returned {len(elements)} elements")
    return elements


# --- Commons ----------------------------------------------------------------


def lookup_commons_files(s: requests.Session, names: list[str]) -> dict[str, tuple[str, dict]]:
    """For up to 50 file names, return {name: (current name, imageinfo)}, following
    redirects of renamed files. Files that don't exist are left out."""
    assert len(names) <= 50
    params = {
        "action": "query",
        "format": "json",
        "formatversion": "2",
        "redirects": "1",
        "prop": "imageinfo",
        "iiprop": "size|mediatype",
        "maxlag": "5",
        "titles": "|".join("File:" + n for n in names),
    }
    while True:
        r = request_with_retry(s, "GET", COMMONS_API, params=params, timeout=60)
        data = r.json()
        if data.get("error", {}).get("code") != "maxlag":
            break
        wait = int(r.headers.get("Retry-After", 5))
        log(f"  Commons lagged, waiting {wait}s")
        time.sleep(wait)
    q = data["query"]
    # Follow the chain: requested -> normalized -> redirected -> page
    normalized = {x["from"]: x["to"] for x in q.get("normalized", [])}
    redirects = {x["from"]: x["to"] for x in q.get("redirects", [])}
    pages = {
        p["title"]: (p.get("imageinfo") or [{}])[0]
        for p in q.get("pages", [])
        if not p.get("missing") and not p.get("invalid") and p.get("ns") == 6
    }
    result = {}
    for name in names:
        t = "File:" + name
        t = normalized.get(t, t)
        t = redirects.get(t, t)
        if t in pages:
            result[name] = (t[len("File:") :].replace(" ", "_"), pages[t])
    return result


# --- OSM API ----------------------------------------------------------------


@dataclass
class Edit:
    elem: ET.Element
    old: str
    new: str

    @property
    def ref(self) -> str:
        return f"{self.elem.tag}/{self.elem.get('id')}"


def fetch_osm_elements(s: requests.Session, kind: str, ids: list[int]) -> list[ET.Element]:
    out = []
    for i in range(0, len(ids), 100):
        chunk = ids[i : i + 100]
        r = s.get(f"{OSM_API}/{kind}s", params={f"{kind}s": ",".join(map(str, chunk))}, timeout=120)
        if r.status_code == 404 and len(chunk) > 1:
            # One of them vanished; fall back to fetching individually.
            for one in chunk:
                out += fetch_osm_elements(s, kind, [one])
            continue
        if r.status_code in (404, 410):
            continue
        r.raise_for_status()
        out += [e for e in ET.fromstring(r.content) if e.tag == kind and e.get("visible") != "false"]
    return out


@dataclass
class Report:
    """What happened to every element the bot looked at, for the log and job summary."""

    edits: list[Edit]
    working: list[str]  # still served, left alone
    not_found: list[str]  # file deleted on Commons
    changed: list[str]  # image=* changed since the Overpass snapshot
    unchecked: int  # not looked at because of --max-edits


def plan_edits(s: requests.Session, candidates: list[dict], max_edits: int) -> Report:
    report = Report([], [], [], [], 0)
    thumbs = {}  # (type, id) -> (url, Thumb)
    for c in candidates:
        url = c.get("tags", {}).get("image", "")
        thumb = parse_thumb_url(url)
        if thumb:
            thumbs[(c["type"], c["id"])] = (url, thumb)
    log(f"{len(thumbs)} elements have a parseable Commons thumbnail URL")

    # Ask Commons 50 files at a time, and stop as soon as we have enough broken links.
    broken = {}  # (type, id) -> (url, new url)
    names = sorted({t.name for _, t in thumbs.values()})
    checked = set()
    for i in range(0, len(names), 50):
        if len(broken) >= max_edits:
            break
        if i:
            time.sleep(1)
        files = lookup_commons_files(s, names[i : i + 50])
        for key, (url, thumb) in sorted(thumbs.items()):
            if thumb.name not in names[i : i + 50] or len(broken) >= max_edits:
                continue
            checked.add(key)
            ref = f"{key[0]}/{key[1]}"
            if thumb.name not in files:
                report.not_found.append(f"{osm_url(ref)}  File:{thumb.name} does not exist on Commons")
                continue
            current_name, info = files[thumb.name]
            if is_broken(thumb, info):
                broken[key] = (url, commons_page_url(current_name))
            else:
                report.working.append(f"{osm_url(ref)}  {thumb.width}px still served: {url}")
    report.unchecked = len(thumbs) - len(checked)
    log(f"{len(broken)} of them are broken thumbnails (limit {max_edits})")

    # Re-read the live data: Overpass may lag behind the main database.
    elements = []
    for kind in ("node", "way", "relation"):
        ids = sorted(i for k, i in broken if k == kind)
        if ids:
            elements += fetch_osm_elements(s, kind, ids)

    found = set()
    for elem in elements:
        key = (elem.tag, int(elem.get("id")))
        found.add(key)
        old, new = broken[key]
        tag = elem.find("tag[@k='image']")
        if tag is None or tag.get("v") != old:
            report.changed.append(f"{osm_url(elem.tag + '/' + elem.get('id'))}  image=* changed since the Overpass snapshot")
            continue
        report.edits.append(Edit(elem, old, new))
    for key in sorted(set(broken) - found):
        report.changed.append(f"{osm_url(f'{key[0]}/{key[1]}')}  deleted since the Overpass snapshot")
    return report


def edit_lines(edits: list[Edit]) -> list[str]:
    return [f"{osm_url(e.ref)}\n    - {e.old}\n    + {e.new}" for e in edits]


def write_job_summary(report: Report, area: str, applied: bool, changeset: int | None):
    """Markdown overview on the GitHub Actions run page, with links to check every edit."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    out = [f"## Commons thumbnail fix: area `{area}`, {'uploaded' if applied else 'dry run'}\n"]
    if changeset:
        out.append(f"Changeset: https://www.openstreetmap.org/changeset/{changeset}\n")
    elif report.edits:
        out.append("**Dry run, nothing was uploaded.** These edits would be made:\n")
    out += [
        "| | elements |",
        "|---|---:|",
        f"| {'edited' if applied else 'to edit'} (broken thumbnail) | {len(report.edits)} |",
        f"| left alone, thumbnail still works | {len(report.working)} |",
        f"| skipped, file not on Commons | {len(report.not_found)} |",
        f"| skipped, changed in OSM meanwhile | {len(report.changed)} |",
        f"| not checked this run (limit reached) | {report.unchecked} |",
        "",
    ]
    if report.edits:
        out += ["| element | width | old `image` (broken) | new `image` |", "|---|---:|---|---|"]
        for e in report.edits:
            t = parse_thumb_url(e.old)
            out.append(f"| [{e.ref}]({osm_url(e.ref)}) | {t.width}px | [thumbnail]({e.old}) | {e.new} |")
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")


def osm_change_xml(edits: list[Edit], changeset_id: int) -> bytes:
    root = ET.Element("osmChange", version="0.6", generator=USER_AGENT)
    modify = ET.SubElement(root, "modify")
    for e in edits:
        elem = e.elem
        for attr in ("user", "uid", "timestamp", "visible"):
            elem.attrib.pop(attr, None)
        elem.set("changeset", str(changeset_id))
        elem.find("tag[@k='image']").set("v", e.new)
        modify.append(elem)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def upload(s: requests.Session, edits: list[Edit], token: str) -> int:
    s.headers["Authorization"] = f"Bearer {token}"
    xml_headers = {"Content-Type": "text/xml; charset=utf-8"}

    cs = ET.Element("osm")
    changeset = ET.SubElement(cs, "changeset")
    tags = {
        "comment": CHANGESET_COMMENT,
        "created_by": USER_AGENT,
        "bot": "yes",
    }
    if os.environ.get("CHANGESET_DESCRIPTION_URL"):
        tags["description"] = os.environ["CHANGESET_DESCRIPTION_URL"]
    for k, v in tags.items():
        ET.SubElement(changeset, "tag", k=k, v=v)
    r = s.put(f"{OSM_API}/changeset/create", data=ET.tostring(cs), headers=xml_headers, timeout=60)
    r.raise_for_status()
    cs_id = int(r.text)
    log(f"Opened changeset {cs_id}")
    try:
        r = s.post(
            f"{OSM_API}/changeset/{cs_id}/upload",
            data=osm_change_xml(edits, cs_id),
            headers=xml_headers,
            timeout=300,
        )
        if not r.ok:
            log(f"Upload failed: {r.status_code} {r.text}")
            r.raise_for_status()
    finally:
        s.put(f"{OSM_API}/changeset/{cs_id}/close", timeout=60)
        log(f"Closed changeset {cs_id}")
    return cs_id


# --- main -------------------------------------------------------------------


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--apply", action="store_true", help="actually upload the edits to OSM")
    p.add_argument(
        "--area",
        default=os.environ.get("AREA", "CH"),
        help='ISO3166-1 country code to restrict the Overpass query to (default CH, "world" = worldwide)',
    )
    p.add_argument("--max-edits", type=int, default=int(os.environ.get("MAX_EDITS", 200)))
    p.add_argument("--report", help="write planned edits as JSON to this file")
    args = p.parse_args(argv)

    token = os.environ.get("OSM_ACCESS_TOKEN")
    if args.apply and not token:
        log("--apply needs OSM_ACCESS_TOKEN")
        return 2

    s = session()
    report = plan_edits(s, find_candidates(s, args.area), args.max_edits)
    edits = report.edits

    log_group(f"Left alone, thumbnail still works ({len(report.working)})", report.working)
    log_group(f"Skipped, file not on Commons ({len(report.not_found)})", report.not_found)
    log_group(f"Skipped, changed in OSM meanwhile ({len(report.changed)})", report.changed)
    if args.report:
        with open(args.report, "w") as f:
            json.dump([{"element": e.ref, "old": e.old, "new": e.new} for e in edits], f, indent=2, ensure_ascii=False)

    cs_id = None
    if edits and args.apply:
        cs_id = upload(s, edits, token)
        log_group(f"Edited in changeset {cs_id} ({len(edits)})", edit_lines(edits))
    else:
        log_group(f"Would edit, dry run ({len(edits)})", edit_lines(edits))

    log(
        f"\nSummary for area {args.area}: "
        f"{len(edits)} {'edited' if cs_id else 'to edit'}, "
        f"{len(report.working)} still working, {len(report.not_found)} file missing, "
        f"{len(report.changed)} changed meanwhile, {report.unchecked} not checked (limit reached)."
    )
    if cs_id:
        log(f"Changeset: https://www.openstreetmap.org/changeset/{cs_id}")
    elif edits:
        log("Dry run, nothing uploaded. Use --apply to upload.")
    write_job_summary(report, args.area, bool(cs_id), cs_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
