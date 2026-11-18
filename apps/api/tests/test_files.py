"""Uploads, type sniffing, virus scan, linking and access."""

import uuid

import pytest
from _flows import enrol
from fastapi.testclient import TestClient

from heinzel_api import files
from heinzel_api.db import tenant_session

pytestmark = pytest.mark.usefixtures("seeded")

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 200
PDF = b"%PDF-1.7\n" + b"x" * 100


def _upload(api, data, name="foto.jpg", module="aufgaben"):
    return api.post(
        f"/api/v1/files?module={module}",
        content=data,
        headers={"x-filename": name, "content-type": "application/octet-stream"},
    )


def test_upload_and_download(api, make_user):
    enrol(api, make_user())
    r = _upload(api, JPEG, name="../../etc/Rampe vereist.JPG")
    assert r.status_code == 201, r.text
    att = r.json()
    assert att["content_type"] == "image/jpeg" and att["is_image"]
    assert att["filename"] == "Rampe vereist.jpg"
    got = api.get(att["url"])
    assert got.status_code == 200 and got.content == JPEG
    assert got.headers["content-disposition"].startswith("inline")
    assert "sandbox" in got.headers["content-security-policy"]


def test_rejections(api, make_user):
    enrol(api, make_user())
    assert _upload(api, b"<html>hi</html>").json()["detail"] == "file_type"
    assert _upload(api, b"").json()["detail"] == "empty_file"
    assert _upload(api, JPEG + b"EVIL").json()["detail"] == "file_infected"
    assert _upload(api, JPEG, module="nope").status_code == 404
    pdf = _upload(api, PDF, name="Offerte").json()
    assert pdf["filename"] == "Offerte.pdf"
    assert api.get(pdf["url"]).headers["content-disposition"].startswith("attachment")


def test_staged_files_are_private(api, make_user):
    enrol(api, make_user())
    url = _upload(api, JPEG).json()["url"]
    other = TestClient(api.app, base_url="http://localhost")
    enrol(other, make_user())
    assert other.get(url).status_code == 404


def test_link_and_module_access_check(api, make_user, app_factory):
    enrol(api, make_user())
    att_id = uuid.UUID(_upload(api, JPEG).json()["id"])
    owner = uuid.UUID(api.get("/api/v1/me").json()["id"])
    other = TestClient(api.app, base_url="http://localhost")
    enrol(other, make_user())
    other_id = uuid.UUID(other.get("/api/v1/me").json()["id"])

    tid = api.app.state.registry.by_slug("schmelzi").id
    with tenant_session(app_factory, tid) as s:
        files.link(
            s, [att_id], module="aufgaben", target_type="task", target_id="T1", user_id=owner
        )
        with pytest.raises(files.UploadRejected):  # someone else's staged file
            files.link(
                s, [att_id], module="aufgaben", target_type="task", target_id="T2", user_id=other_id
            )

    files.register_access("aufgaben", "task", lambda s, uid, tid_: uid == other_id and tid_ == "T1")
    try:
        assert other.get(f"/api/v1/files/{att_id}").status_code == 200
    finally:
        files._access.pop(("aufgaben", "task"), None)
    assert other.get(f"/api/v1/files/{att_id}").status_code == 404


def test_verify_and_copy_for_moving_storage(api, make_user, seeded, tmp_path):
    """heinzel files verify / files copy: the tools for moving files to another backend."""
    from heinzel_api.cli import copy_files, verify_files

    enrol(api, make_user())
    att = _upload(api, JPEG).json()
    storage = api.app.state.storage
    key = next(k for k in storage.iter_keys() if k.endswith(att["id"]))
    storage.put("stray/file", b"x")

    report = verify_files(seeded, storage)
    assert att["id"] not in report["missing"] + report["corrupt"]
    assert "stray/file" in report["orphans"]

    target = files.LocalStorage(tmp_path)
    counts = copy_files(seeded, storage, target)
    assert target.get(key) == JPEG and counts["copied"] >= 1
    assert copy_files(seeded, storage, target)["skipped"] >= 1  # resumable

    storage.put(key, JPEG + b"changed")
    assert att["id"] in verify_files(seeded, storage)["corrupt"]


def test_local_storage_rejects_escaping_keys(tmp_path):
    store = files.LocalStorage(tmp_path / "files")
    store.put("t/2026/11/a", b"1")
    assert store.exists("t/2026/11/a") and list(store.iter_keys()) == ["t/2026/11/a"]
    with pytest.raises(ValueError):
        store.put("../outside", b"x")


def _zip(entries: dict[str, bytes]) -> bytes:
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return buf.getvalue()


def test_sniff_office_and_text():
    ct = b'<?xml version="1.0"?><Types></Types>'
    docx = _zip({"[Content_Types].xml": ct, "word/document.xml": b"<w/>"})
    xlsx = _zip({"[Content_Types].xml": ct, "xl/workbook.xml": b"<x/>"})
    pptx = _zip({"[Content_Types].xml": ct, "ppt/presentation.xml": b"<p/>"})
    assert files.sniff(docx) == files.DOCX
    assert files.sniff(xlsx) == files.XLSX
    assert files.sniff(pptx) == files.PPTX
    odt = _zip({"mimetype": files.ODT.encode(), "content.xml": b"<o/>"})
    assert files.sniff(odt) == files.ODT
    # macros, plain archives and binaries are refused
    macro = (
        b'<Types><Override ContentType="application/vnd.ms-word.document.macroEnabled.main+xml"/>'
    )
    assert files.sniff(_zip({"[Content_Types].xml": macro, "word/document.xml": b""})) is None
    assert (
        files.sniff(
            _zip({"[Content_Types].xml": ct, "word/document.xml": b"", "word/vbaProject.bin": b""})
        )
        is None
    )
    assert files.sniff(_zip({"mimetype": files.ODT.encode(), "Basic/script.xml": b""})) is None
    assert files.sniff(_zip({"a.exe": b"MZ"})) is None
    assert files.sniff(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 100, "alt.doc") is None
    # text by extension, only when it is text
    assert files.sniff("Grüezi\nmiteinander".encode(), "notiz.txt") == files.TXT
    assert files.sniff(b"a;b\n1;2\n", "liste.CSV") == files.CSV
    assert files.sniff("caf\xe9".encode("latin-1"), "alt.txt") == files.TXT
    assert files.sniff(b"MZ\x00\x01binary", "trick.txt") is None
    assert files.sniff(b"plain", "notiz.md") is None
    assert files.clean_filename("Offerte 2026.DOCX", files.DOCX) == "Offerte 2026.docx"


def test_upload_office_document(api, make_user):
    enrol(api, make_user())
    ct = b'<?xml version="1.0"?><Types></Types>'
    docx = _zip({"[Content_Types].xml": ct, "word/document.xml": b"<w/>"})
    att = _upload(api, docx, name="Protokoll.docx").json()
    assert att["content_type"] == files.DOCX and not att["is_image"]
    assert _upload(api, b"a;b\n", name="liste.csv").json()["content_type"] == "text/csv"
