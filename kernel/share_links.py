"""Backend single-source of the self-contained agent import-link format.
Mirrors mobile/lib/core/share_config.dart `customLink` (kali://import?n=&d=)."""
from urllib.parse import urlencode


def build_import_link(*, name: str, bundle: str) -> str:
    """Return `kali://import?n=<name>&d=<bundle>` with query-encoding.

    Args:
        name: Agent slug/name.
        bundle: base64url(.tar.gz) self-contained skill bundle.

    Returns:
        A `kali://import?...` deep link with the name and bundle query-encoded.
    """
    return "kali://import?" + urlencode({"n": name, "d": bundle})
