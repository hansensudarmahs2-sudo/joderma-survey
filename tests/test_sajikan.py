"""Uji pemilihan server web (gap G17)."""

from __future__ import annotations

from typing import Any

import pytest

from joderma_survey import sajikan as modul
from joderma_survey.sajikan import ALUR, BATAS_SAMBUNGAN, TENGGAT_SALURAN, sajikan


class AppPalsu:
    def __init__(self) -> None:
        self.dijalankan: dict[str, Any] | None = None

    def run(self, **kw: Any) -> None:
        self.dijalankan = kw


def test_bawaan_memakai_waitress(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tanpa --debug harus memakai server sungguhan, bukan server Flask.

    Ini sifat yang paling penting: aman secara bawaan, sehingga unit systemd
    tidak perlu menyalakan apa pun.
    """
    dipanggil: dict[str, Any] = {}
    monkeypatch.setattr(
        "waitress.serve", lambda app, **kw: dipanggil.update(kw, app=app)
    )
    app = AppPalsu()
    sajikan(app, "127.0.0.1", 8000)
    assert app.dijalankan is None, "server pengembangan Flask tidak boleh dipakai"
    assert dipanggil["host"] == "127.0.0.1"
    assert dipanggil["port"] == 8000


def test_debug_memakai_server_flask(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "waitress.serve", lambda app, **kw: pytest.fail("waitress tidak boleh dipakai")
    )
    app = AppPalsu()
    sajikan(app, "127.0.0.1", 8000, debug=True)
    assert app.dijalankan == {"host": "127.0.0.1", "port": 8000, "debug": True}


def test_setelan_menahan_sambungan_menggantung(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pembatasan laju Cloudflare dicabut, jadi inilah satu-satunya penahan."""
    dipanggil: dict[str, Any] = {}
    monkeypatch.setattr("waitress.serve", lambda app, **kw: dipanggil.update(kw))
    sajikan(AppPalsu(), "127.0.0.1", 8001)
    assert dipanggil["threads"] == ALUR
    assert dipanggil["connection_limit"] == BATAS_SAMBUNGAN
    assert dipanggil["channel_timeout"] == TENGGAT_SALURAN
    assert dipanggil["channel_timeout"] < 120, "harus lebih ketat dari bawaan waitress"


def test_nama_server_tidak_diumumkan(monkeypatch: pytest.MonkeyPatch) -> None:
    dipanggil: dict[str, Any] = {}
    monkeypatch.setattr("waitress.serve", lambda app, **kw: dipanggil.update(kw))
    sajikan(AppPalsu(), "127.0.0.1", 8001)
    assert dipanggil["ident"] is None


def test_pesan_startup_langsung_keluar(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Dijalankan systemd, stdout tidak terhubung terminal; tanpa flush
    pesannya tertahan dan journalctl kosong."""
    monkeypatch.setattr("waitress.serve", lambda app, **kw: None)
    sajikan(AppPalsu(), "127.0.0.1", 8001, nama="survei")
    keluar = capsys.readouterr().out
    assert "survei" in keluar
    assert "waitress" in keluar
    assert "8001" in keluar


def test_mode_debug_memberi_peringatan(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    sajikan(AppPalsu(), "127.0.0.1", 8001, debug=True, nama="admin")
    keluar = capsys.readouterr().out
    assert "PENGEMBANGAN" in keluar
    assert "jangan dipakai untuk melayani pasien" in keluar


def test_alur_cukup_tapi_hemat() -> None:
    """Beban klinik ringan; alur berlebih hanya memakan memori mini PC."""
    assert 2 <= ALUR <= 8
