"""Characterization tests for kernel.model_downloader.

The registry drives the onboarding first-run download: a wrong URL here once
404'ed silently for months (the removed HuBERT entry), so the registry shape
and the download/cleanup flow get a test floor. No network access — urlopen
is faked.
"""
import urllib.request

from kernel import model_downloader as md


class _FakeResponse:
    """Context-manager stand-in for urlopen with chunked reads."""

    def __init__(self, chunks: list[bytes], fail_after: int | None = None) -> None:
        self._chunks = list(chunks)
        self._fail_after = fail_after
        self._reads = 0
        self.headers = {"Content-Length": str(sum(len(c) for c in chunks))}

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def read(self, _size: int) -> bytes:
        if self._fail_after is not None and self._reads >= self._fail_after:
            raise OSError("connection dropped")
        self._reads += 1
        return self._chunks.pop(0) if self._chunks else b""


def test_required_models_urls_are_wellformed_huggingface_resolve_urls() -> None:
    assert md.REQUIRED_MODELS, "registry must not be empty"
    for name, info in md.REQUIRED_MODELS.items():
        assert name.endswith((".safetensors", ".wav", ".onnx", ".bin", ".txt")), name
        assert info["url"].startswith("https://huggingface.co/"), info["url"]
        assert "/resolve/" in info["url"], info["url"]
        assert info["size_mb"] > 0
        assert info["description"]


def test_get_missing_models_reports_absent_files(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(md, "MODELS_DIR", tmp_path)
    missing = {m["name"] for m in md.get_missing_models()}
    assert missing == set(md.REQUIRED_MODELS)

    present = next(iter(md.REQUIRED_MODELS))
    (tmp_path / present).write_bytes(b"x")
    missing = {m["name"] for m in md.get_missing_models()}
    assert present not in missing
    assert missing == set(md.REQUIRED_MODELS) - {present}


def test_download_model_writes_via_tmp_and_renames(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(md, "MODELS_DIR", tmp_path)
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda req, timeout: _FakeResponse([b"abc", b"def"]),
    )
    ok = md.download_model("model.bin", "https://huggingface.co/x/resolve/main/model.bin")
    assert ok is True
    assert (tmp_path / "model.bin").read_bytes() == b"abcdef"
    assert not list(tmp_path.glob("*.tmp"))


def test_download_model_cleans_tmp_on_failure(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(md, "MODELS_DIR", tmp_path)
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda req, timeout: _FakeResponse([b"abc", b"def"], fail_after=1),
    )
    ok = md.download_model("model.bin", "https://huggingface.co/x/resolve/main/model.bin")
    assert ok is False
    assert not (tmp_path / "model.bin").exists()
    assert not list(tmp_path.glob("*.tmp"))


def test_models_ready_true_when_all_present(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(md, "MODELS_DIR", tmp_path)
    assert md.models_ready() is False
    for name in md.REQUIRED_MODELS:
        (tmp_path / name).write_bytes(b"x")
    assert md.models_ready() is True
