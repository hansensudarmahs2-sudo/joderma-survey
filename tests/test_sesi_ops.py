"""Uji pemeriksa sesi ops di tingkat jaringan.

Dipakai server HTTP lokal sungguhan (127.0.0.1, porta acak) supaya yang diuji
benar-benar apa yang dikirim ``urllib``: kuki mana yang diteruskan, header
apa yang dipasang, dan bahwa pengalihan tidak pernah diikuti.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Iterator

import pytest

from joderma_survey.sesi_ops import BELUM_MASUK, BERHAK, TANPA_HAK, periksa_sesi_ops


class ServerOps:
    """Tiruan ops: jawabannya diatur tes, permintaannya dicatat."""

    def __init__(self) -> None:
        self.kode = 200
        self.isi: bytes = b"{}"
        self.header_tambahan: dict[str, str] = {}
        self.jeda = 0.0
        self.diterima: list[dict[str, Any]] = []

        induk = self

        class Penangan(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 - nama dari http.server
                induk.diterima.append(
                    {"jalur": self.path, "header": dict(self.headers.items())}
                )
                if induk.jeda:
                    time.sleep(induk.jeda)
                try:
                    self.send_response(induk.kode)
                    self.send_header("Content-Type", "application/json")
                    for k, v in induk.header_tambahan.items():
                        self.send_header(k, v)
                    self.send_header("Content-Length", str(len(induk.isi)))
                    self.end_headers()
                    self.wfile.write(induk.isi)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, *_args: Any) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Penangan)
        self.server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.alur = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.alur.start()

    def jawab(self, kode: int, data: Any) -> None:
        self.kode = kode
        self.isi = data if isinstance(data, bytes) else json.dumps(data).encode()

    def tutup(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def ops() -> Iterator[ServerOps]:
    s = ServerOps()
    yield s
    s.tutup()


def periksa(ops: ServerOps, kuki: str | None = "abc123", **kw: Any) -> Any:
    return periksa_sesi_ops(kuki, url_internal=ops.url, host="ops.contoh.id", **kw)


# --------------------------------------------------------------------------
# Apa yang dikirim ke ops
# --------------------------------------------------------------------------


def test_hanya_kuki_sessionid_dan_header_wajib(ops: ServerOps) -> None:
    ops.jawab(200, {"username": "dirops", "nama": "Dir", "peran": "direktur"})
    periksa(ops, "abc123")
    assert len(ops.diterima) == 1
    minta = ops.diterima[0]
    assert minta["jalur"] == "/akun/sesi-survei/"
    h = {k.lower(): v for k, v in minta["header"].items()}
    assert h["cookie"] == "sessionid=abc123", "hanya kuki sessionid yang diteruskan"
    assert h["host"] == "ops.contoh.id"
    assert h["x-forwarded-proto"] == "https"


def test_tanpa_kuki_tidak_bertanya_ke_ops(ops: ServerOps) -> None:
    assert periksa(ops, None).status == BELUM_MASUK
    assert periksa(ops, "").status == BELUM_MASUK
    assert ops.diterima == []


@pytest.mark.parametrize("kuki", ["a;b=c", "a\r\nX-Sisip: 1", "a b", "é", "x" * 300])
def test_kuki_janggal_tidak_diteruskan(ops: ServerOps, kuki: str) -> None:
    """Nilai kuki sesi Django hanya huruf dan angka; selain itu ditolak."""
    assert periksa(ops, kuki).status == BELUM_MASUK
    assert ops.diterima == []


# --------------------------------------------------------------------------
# Penafsiran jawaban
# --------------------------------------------------------------------------


@pytest.mark.parametrize("peran", ["direktur", "owner", "cs"])
def test_200_berhak(ops: ServerOps, peran: str) -> None:
    ops.jawab(200, {"username": "budi", "nama": "Budi S", "peran": peran})
    hasil = periksa(ops)
    assert hasil.status == BERHAK
    assert (hasil.username, hasil.nama, hasil.peran) == ("budi", "Budi S", peran)


def test_403_tanpa_hak(ops: ServerOps) -> None:
    ops.jawab(403, {"username": "budi", "nama": "Budi", "peran": None})
    hasil = periksa(ops)
    assert hasil.status == TANPA_HAK
    assert hasil.peran is None


def test_401_belum_masuk(ops: ServerOps) -> None:
    ops.jawab(401, {"masuk": "/akun/login/?next=/survei/"})
    assert periksa(ops).status == BELUM_MASUK


def test_302_tidak_diikuti(ops: ServerOps) -> None:
    """Sesi ops kedaluwarsa memberi 302; pengalihan tidak boleh diikuti."""
    ops.jawab(302, b"")
    ops.header_tambahan = {"Location": ops.url + "/akun/login/"}
    assert periksa(ops).status == BELUM_MASUK
    assert len(ops.diterima) == 1, "pengalihan diikuti"


@pytest.mark.parametrize("kode", [500, 502, 404, 400])
def test_kode_lain_belum_masuk(ops: ServerOps, kode: int) -> None:
    ops.jawab(kode, {"username": "budi", "peran": "direktur"})
    assert periksa(ops).status == BELUM_MASUK


@pytest.mark.parametrize(
    "isi",
    [
        b"bukan json",
        b"[]",
        json.dumps({"username": "budi", "peran": "raja"}).encode(),
        json.dumps({"username": "budi", "peran": None}).encode(),
        json.dumps({"username": "", "peran": "direktur"}).encode(),
        json.dumps({"peran": "direktur"}).encode(),
        json.dumps({"username": 7, "peran": "direktur"}).encode(),
    ],
)
def test_200_tak_sah_tidak_pernah_berhak(ops: ServerOps, isi: bytes) -> None:
    ops.jawab(200, isi)
    assert periksa(ops).status == BELUM_MASUK


def test_tenggat(ops: ServerOps) -> None:
    ops.jawab(200, {"username": "budi", "nama": "", "peran": "direktur"})
    ops.jeda = 1.0
    mulai = time.monotonic()
    assert periksa(ops, tenggat=0.2).status == BELUM_MASUK
    assert time.monotonic() - mulai < 0.9


def test_ops_mati() -> None:
    hasil = periksa_sesi_ops(
        "abc123", url_internal="http://127.0.0.1:9", host="ops.contoh.id", tenggat=1
    )
    assert hasil.status == BELUM_MASUK


# --------------------------------------------------------------------------
# Sambungan ujung ke ujung: aplikasi admin bawaan (tanpa pemeriksa suntikan)
# --------------------------------------------------------------------------


def test_aplikasi_bawaan_bertanya_ke_ops_dari_env(
    ops: ServerOps, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from joderma_survey import db
    from joderma_survey.web_admin import buat_app

    monkeypatch.setenv("JODERMA_KUKI_AMAN", "0")
    monkeypatch.setenv("JODERMA_AWALAN_ADMIN", "/survei")
    monkeypatch.setenv("JODERMA_OPS_INTERNAL", ops.url)
    monkeypatch.setenv("JODERMA_OPS_HOST", "ops.contoh.id")
    path = tmp_path / "uji.db"
    conn = db.buka(path)
    db.migrasi(conn)
    conn.close()
    app = buat_app(path, kunci_rahasia="kunci-uji")
    app.config["TESTING"] = True

    ops.jawab(200, {"username": "cs1", "nama": "CS Satu", "peran": "cs"})
    with app.test_client() as c:
        c.get("/survei/")  # sesi survei (kuki joderma_survei_sesi) terbentuk
        c.set_cookie("sessionid", "abc123", path="/")
        c.set_cookie("csrftoken", "milik-ops", path="/")
        assert c.get("/survei/kirim").status_code == 200
        assert c.get("/survei/hasil").status_code == 403

        h = {k.lower(): v for k, v in ops.diterima[-1]["header"].items()}
        assert h["cookie"] == "sessionid=abc123"
        assert h["host"] == "ops.contoh.id"
        assert h["x-forwarded-proto"] == "https"

        ops.jawab(401, {"masuk": "/akun/login/?next=/survei/"})
        jawab = c.get("/survei/kirim")
        assert jawab.status_code == 302
        assert jawab.headers["Location"] == (
            "https://ops.contoh.id/akun/login/?next=/survei/kirim"
        )
