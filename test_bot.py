import xml.etree.ElementTree as ET

from bot import (
    Edit,
    Thumb,
    commons_page_url,
    is_broken,
    osm_change_xml,
    parse_thumb_url,
    same_file,
    tag_changes,
)

THUMB = (
    "https://upload.wikimedia.org/wikipedia/commons/thumb/e/e9/"
    "Strassenschild_Kirchbergerstrasse.jpg/800px-Strassenschild_Kirchbergerstrasse.jpg"
)


def test_example_from_readme():
    thumb = parse_thumb_url(THUMB)
    assert thumb == Thumb("Strassenschild_Kirchbergerstrasse.jpg", 800)
    name = thumb.name
    assert commons_page_url(name) == (
        "https://commons.wikimedia.org/wiki/File:Strassenschild_Kirchbergerstrasse.jpg"
    )


def test_percent_encoded_name_is_decoded():
    import hashlib

    name = "Zürich_Hauptbahnhof.jpg"
    h = hashlib.md5(name.encode()).hexdigest()
    url = (
        f"https://upload.wikimedia.org/wikipedia/commons/thumb/{h[0]}/{h[:2]}/"
        f"Z%C3%BCrich_Hauptbahnhof.jpg/1024px-Z%C3%BCrich_Hauptbahnhof.jpg"
    )
    assert parse_thumb_url(url) == Thumb(name, 1024)
    assert commons_page_url(name).endswith("File:Zürich_Hauptbahnhof.jpg")


def test_svg_and_long_name_thumbnails():
    import hashlib

    name = "Flag_of_Switzerland.svg"
    h = hashlib.md5(name.encode()).hexdigest()
    base = f"https://upload.wikimedia.org/wikipedia/commons/thumb/{h[0]}/{h[:2]}/{name}/"
    assert parse_thumb_url(base + "512px-Flag_of_Switzerland.svg.png") == Thumb(name, 512)
    assert parse_thumb_url(base + "800px-thumbnail.jpg") == Thumb(name, 800)
    assert parse_thumb_url(base + "page1-960px-thumbnail.jpg") == Thumb(name, 960)
    assert parse_thumb_url(base + "lossy-page1-120px-thumbnail.jpg") == Thumb(name, 120)
    assert parse_thumb_url(base + "500px--thumbnail.webm.jpg") == Thumb(name, 500)
    # no width -> can't tell whether it works -> don't touch
    assert parse_thumb_url(base + "thumbnail.jpg") is None


def test_rejects_everything_else():
    for value in [
        "",
        "https://commons.wikimedia.org/wiki/File:Strassenschild_Kirchbergerstrasse.jpg",
        # original file, not a thumbnail
        "https://upload.wikimedia.org/wikipedia/commons/e/e9/Strassenschild_Kirchbergerstrasse.jpg",
        # other wikis
        THUMB.replace("/commons/", "/de/"),
        # wrong hash directory
        THUMB.replace("/e/e9/", "/a/ab/"),
        # multiple values / trailing junk
        THUMB + ";" + THUMB,
        THUMB + "?download",
        "https://example.org/wikipedia/commons/thumb/e/e9/X.jpg/800px-X.jpg",
    ]:
        assert parse_thumb_url(value) is None, value


def test_is_broken():
    jpg = {"mediatype": "BITMAP", "width": 4032}
    svg = {"mediatype": "DRAWING", "width": 900}
    # non-standard widths are refused
    for w in (800, 1024, 425, 640, 332):
        assert is_broken(Thumb("X.jpg", w), jpg)
    # standard widths work ...
    for w in (20, 120, 250, 330, 500, 960, 1280, 1920, 3840):
        assert not is_broken(Thumb("X.jpg", w), jpg)
    # ... unless a bitmap would have to be upscaled
    assert is_broken(Thumb("X.jpg", 1920), {"mediatype": "BITMAP", "width": 1600})
    assert not is_broken(Thumb("X.svg", 1920), svg)


def test_url_breaking_characters_are_escaped():
    assert commons_page_url("A?b#c.jpg") == "https://commons.wikimedia.org/wiki/File:A%3Fb%23c.jpg"
    assert commons_page_url("A b.jpg") == "https://commons.wikimedia.org/wiki/File:A_b.jpg"


NAME = "Strassenschild_Kirchbergerstrasse.jpg"
PAGE = "https://commons.wikimedia.org/wiki/File:Strassenschild_Kirchbergerstrasse.jpg"


def test_tag_changes_moves_to_wikimedia_commons_if_unset():
    expected = {"image": None, "wikimedia_commons": "File:Strassenschild Kirchbergerstrasse.jpg"}
    assert tag_changes({"image": THUMB}, NAME) == expected
    assert tag_changes({"image": THUMB, "wikimedia_commons": " "}, NAME) == expected


def test_tag_changes_keeps_existing_wikimedia_commons():
    tags = {"image": THUMB, "wikimedia_commons": "Category:Bern"}
    assert tag_changes(tags, NAME) == {"image": PAGE}
    tags = {"image": THUMB, "wikimedia_commons": "File:Other.jpg"}
    assert tag_changes(tags, NAME) == {"image": PAGE}


def test_tag_changes_drops_image_if_wikimedia_commons_names_same_file():
    for commons in [
        "File:Strassenschild Kirchbergerstrasse.jpg",
        "File:Strassenschild_Kirchbergerstrasse.jpg",
        "file:strassenschild Kirchbergerstrasse.jpg",
        "Strassenschild Kirchbergerstrasse.jpg",
        PAGE,
    ]:
        tags = {"image": THUMB, "wikimedia_commons": commons}
        assert tag_changes(tags, NAME) == {"image": None}, commons
    # file renamed on Commons, wikimedia_commons still has the old name
    tags = {"image": THUMB, "wikimedia_commons": "File:Old name.jpg"}
    assert tag_changes(tags, NAME, "Old_name.jpg") == {"image": None}


def test_same_file():
    assert same_file("File:A_b.jpg", "https://commons.wikimedia.org/wiki/File:A%20b.jpg")
    assert not same_file("File:A b.jpg", "File:A c.jpg")
    assert not same_file("File:A b.jpg", "File:A B.jpg")  # only the first letter is case-insensitive


def way(*tags):
    return ET.fromstring(
        '<way id="1" version="3" user="x" uid="1" timestamp="t" visible="true" changeset="9">'
        '<nd ref="1"/><nd ref="2"/>' + "".join(f'<tag k="{k}" v="{v}"/>' for k, v in tags) + "</way>"
    )


def change(elem, changes):
    root = ET.fromstring(osm_change_xml([Edit(elem, THUMB, changes)], 42))
    w = root.find("modify/way")
    assert w.attrib == {"id": "1", "version": "3", "changeset": "42"}
    assert [n.get("ref") for n in w.findall("nd")] == ["1", "2"]
    return {t.get("k"): t.get("v") for t in w.findall("tag")}


def test_osm_change_fixes_image():
    elem = way(("highway", "residential"), ("image", THUMB), ("wikimedia_commons", "Category:Bern"))
    assert change(elem, {"image": PAGE}) == {
        "highway": "residential",
        "image": PAGE,
        "wikimedia_commons": "Category:Bern",
    }


def test_osm_change_moves_to_wikimedia_commons():
    elem = way(("highway", "residential"), ("image", THUMB))
    assert change(elem, tag_changes({"image": THUMB}, NAME)) == {
        "highway": "residential",
        "wikimedia_commons": "File:Strassenschild Kirchbergerstrasse.jpg",
    }


def test_osm_change_drops_redundant_image():
    elem = way(("image", THUMB), ("wikimedia_commons", "File:Strassenschild Kirchbergerstrasse.jpg"))
    assert change(elem, {"image": None}) == {
        "wikimedia_commons": "File:Strassenschild Kirchbergerstrasse.jpg"
    }


def test_hilbert_index_keeps_neighbours_close():
    from bot import hilbert_index

    # visits every cell of a 16x16 grid exactly once, each step to an adjacent cell
    cells = [(-90 + (y + 0.5) * 180 / 16, -180 + (x + 0.5) * 360 / 16) for x in range(16) for y in range(16)]
    order = sorted(range(256), key=lambda i: hilbert_index(cells[i], order=4))
    assert sorted(hilbert_index(c, order=4) for c in cells) == list(range(256))
    for a, b in zip(order, order[1:]):
        assert abs(a // 16 - b // 16) + abs(a % 16 - b % 16) == 1
    bern, thun, geneva = (46.948, 7.447), (46.758, 7.628), (46.204, 6.143)
    assert abs(hilbert_index(bern) - hilbert_index(thun)) < abs(hilbert_index(bern) - hilbert_index(geneva))


def test_compact_group_picks_closest_points():
    from bot import bbox, bbox_size, compact_group

    bern = {("node", i): (46.94 + i * 0.001, 7.44 + i * 0.001) for i in range(10)}
    far = {
        ("node", 100): (46.20, 6.14),  # Geneva
        ("node", 101): (47.37, 8.54),  # Zürich
        ("node", 102): (46.00, 8.95),  # Lugano
    }
    points = {**far, **bern}
    group = compact_group(points, 10)
    assert sorted(group) == sorted(bern)
    assert compact_group(points, 3) != list(far)
    assert bbox_size(bbox(points[k] for k in compact_group(points, 3))) < 1e-4
    assert sorted(compact_group(points, 50)) == sorted(points)
    assert compact_group(points, 0) == []


ARAL = (
    "https://upload.wikimedia.org/wikipedia/commons/thumb/6/60/"
    "Aral_Logo.svg/220px-Aral_Logo.svg.png"
)


def test_svg_thumbnails_are_recognised():
    from bot import is_svg

    assert is_svg(parse_thumb_url(ARAL))
    assert not is_svg(parse_thumb_url(THUMB))


def test_svg_flag_reports_nsi_match():
    from bot import nsi_matches, svg_flag

    nsi = {
        ("brand:wikidata", "Q565734"): {
            "shop=convenience": "Aral (brands/shop/convenience)",
            "amenity=fuel": "Aral (brands/amenity/fuel)",
        }
    }
    tags = {"amenity": "fuel", "brand": "Aral", "brand:wikidata": "Q565734", "image": ARAL}
    assert nsi_matches(tags, nsi) == ["brand:wikidata=Q565734: Aral (brands/amenity/fuel)"]
    # same QID under another key is not a match
    assert nsi_matches({"operator:wikidata": "Q565734"}, nsi) == []
    # fallback: brand=* without brand:wikidata, within the same NSI category
    nsi[("brand", "amenity=fuel", "avia")] = {"amenity=fuel": "Avia (brands/amenity/fuel)"}
    avia = {"amenity": "fuel", "brand": "Avia", "name": "AVIA XPress"}
    assert nsi_matches(avia, nsi) == ["brand=Avia (no brand:wikidata): Avia (brands/amenity/fuel)"]
    assert nsi_matches({**avia, "amenity": "parking"}, nsi) == []

    line = svg_flag("node/271921343", parse_thumb_url(ARAL), tags, nsi)
    assert line == (
        "https://www.openstreetmap.org/node/271921343  File:Aral_Logo.svg  "
        "[file name says logo; in NSI as brand:wikidata=Q565734: Aral (brands/amenity/fuel)]"
    )
    assert svg_flag("node/1", parse_thumb_url(ARAL), {}, nsi).endswith("not in NSI]")
    assert svg_flag("node/1", parse_thumb_url(ARAL), {}, None).endswith("NSI not checked]")
