import xml.etree.ElementTree as ET

from bot import Edit, Thumb, commons_page_url, is_broken, osm_change_xml, parse_thumb_url

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


def test_osm_change_only_touches_image():
    elem = ET.fromstring(
        '<way id="1" version="3" user="x" uid="1" timestamp="t" visible="true" changeset="9">'
        '<nd ref="1"/><nd ref="2"/>'
        f'<tag k="highway" v="residential"/><tag k="image" v="{THUMB}"/></way>'
    )
    new = "https://commons.wikimedia.org/wiki/File:Strassenschild_Kirchbergerstrasse.jpg"
    root = ET.fromstring(osm_change_xml([Edit(elem, THUMB, new)], 42))
    way = root.find("modify/way")
    assert way.attrib == {"id": "1", "version": "3", "changeset": "42"}
    assert [n.get("ref") for n in way.findall("nd")] == ["1", "2"]
    assert {t.get("k"): t.get("v") for t in way.findall("tag")} == {
        "highway": "residential",
        "image": new,
    }
