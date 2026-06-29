from urllib.parse import parse_qs, urlsplit

from kernel.share_links import build_import_link


def test_build_import_link_roundtrips_cyrillic_name() -> None:
    link = build_import_link(name="повар", bundle="AAAA")
    parts = urlsplit(link)
    assert parts.scheme == "kali" and parts.netloc == "import"
    q = parse_qs(parts.query)
    assert q["n"] == ["повар"] and q["d"] == ["AAAA"]
