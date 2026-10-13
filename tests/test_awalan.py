"""Uji pemasangan aplikasi admin di bawah awalan jalur.

Dipakai saat admin berbagi hostname dengan sistem lain (ops.joderma.id)
supaya ikut memakai kebijakan Cloudflare Access yang sudah ada di sana, dan
staf tidak diminta login dua kali. Sejak 13 Okt 2026 login-nya pun memakai
sesi ops (lihat tests/test_web_admin.py).
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest
from flask import Flask
from flask.testing import FlaskClient

from joderma_survey import db
from joderma_survey.awalan import rapikan_awalan
from joderma_survey.sesi_ops import BELUM_MASUK, BERHAK, HasilSesi
from joderma_survey.web_admin import buat_app

AWALAN = "/survei"
HOST_OPS = "ops.contoh.id"
LOGIN_OPS = f"https://{HOST_OPS}/akun/login/?next="


def pemeriksa(kuki: str | None) -> HasilSesi:
    if kuki == "kuki-dirops":
        return HasilSesi(BERHAK, "dirops", "Direktur Ops", "direktur")
    return HasilSesi(BELUM_MASUK)


def masuk(klien: FlaskClient) -> None:
    # Kuki sesi ops berjalur "/", jadi peramban mengirimnya juga ke /survei.
    klien.set_cookie("sessionid", "kuki-dirops", path="/")


@pytest.mark.parametrize(
    ("masuk", "harap"),
    [("survei", "/survei"), ("/survei", "/survei"), ("/survei/", "/survei"),
     ("  /survei/  ", "/survei"), ("a/b", "/a/b"), ("", ""), ("   ", ""),
     ("/", ""), ("///", "")],
)
def test_rapikan_awalan(masuk: str, harap: str) -> None:
    assert rapikan_awalan(masuk) == harap


@pytest.fixture
def path_basis(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("JODERMA_KUKI_AMAN", "0")
    monkeypatch.setenv("JODERMA_AWALAN_ADMIN", AWALAN)
    monkeypatch.setenv("JODERMA_OPS_HOST", HOST_OPS)
    path = tmp_path / "uji.db"
    conn = db.buka(path)
    db.migrasi(conn)
    conn.close()
    return path


@pytest.fixture
def klien(path_basis: Path) -> Iterator[FlaskClient]:
    app: Flask = buat_app(path_basis, kunci_rahasia="kunci-uji", pemeriksa_sesi=pemeriksa)
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_halaman_terbuka_di_bawah_awalan(klien: FlaskClient) -> None:
    masuk(klien)
    assert klien.get(f"{AWALAN}/kirim").status_code == 200


def test_tautan_dibuat_dengan_awalan(klien: FlaskClient) -> None:
    """Inti masalahnya: tanpa ini semua tautan menunjuk akar hostname."""
    masuk(klien)
    isi = klien.get(f"{AWALAN}/kirim").get_data(as_text=True)
    for jalur in ("/kirim", "/unggah", "/hasil"):
        assert f'"{AWALAN}{jalur}"' in isi, f"tautan {jalur} tidak berawalan"
    assert 'href="/kirim"' not in isi, "ada tautan tanpa awalan"
    assert f"{AWALAN}{AWALAN}" not in isi, "awalan terpasang dua kali"


def test_pengalihan_memakai_awalan(klien: FlaskClient) -> None:
    """Gejala paling membingungkan bila salah: terlempar ke aplikasi
    tetangga di hostname yang sama."""
    masuk(klien)
    jawab = klien.get(f"{AWALAN}/")
    assert jawab.status_code == 302
    assert jawab.headers["Location"].endswith(f"{AWALAN}/unggah"), jawab.headers["Location"]


def test_alur_penuh_di_bawah_awalan(klien: FlaskClient) -> None:
    masuk(klien)
    for jalur in ("/kirim", "/unggah", "/hasil"):
        assert klien.get(f"{AWALAN}{jalur}").status_code == 200, jalur


def test_awalan_tidak_terpasang_dua_kali(klien: FlaskClient) -> None:
    """Mengisi APPLICATION_ROOT sekaligus SCRIPT_NAME menghasilkan
    /survei/survei/kirim -- halaman terbuka, tapi semua tautannya rusak."""
    masuk(klien)
    jawab = klien.get(f"{AWALAN}/")
    assert jawab.headers["Location"].count("/survei") == 1, jawab.headers["Location"]
    isi = klien.get(f"{AWALAN}/kirim").get_data(as_text=True)
    assert "/survei/survei" not in isi


def test_akar_awalan_mengalihkan(klien: FlaskClient) -> None:
    masuk(klien)
    jawab = klien.get(AWALAN)
    assert jawab.status_code == 302
    assert AWALAN in jawab.headers["Location"]


def test_belum_login_ops_dialihkan_dengan_next_berawalan(klien: FlaskClient) -> None:
    jawab = klien.get(f"{AWALAN}/kirim?cabang=30376")
    assert jawab.status_code == 302
    assert jawab.headers["Location"] == (
        LOGIN_OPS + "/survei/kirim%3Fcabang%3D30376"
    )


def test_belum_login_ops_di_akar_awalan(klien: FlaskClient) -> None:
    jawab = klien.get(f"{AWALAN}/")
    assert jawab.headers["Location"] == LOGIN_OPS + "/survei/"


def test_next_tetap_berawalan_walau_tanpa_awalan_di_url(klien: FlaskClient) -> None:
    """Permintaan langsung ke 127.0.0.1 tanpa /survei: peramban tetap harus
    kembali lewat ops.joderma.id/survei."""
    jawab = klien.get("/hasil")
    assert jawab.headers["Location"] == LOGIN_OPS + "/survei/hasil"


def test_kuki_dibatasi_ke_awalan(klien: FlaskClient) -> None:
    """Kuki tidak boleh ikut terkirim ke aplikasi tetangga di hostname sama."""
    jawab = klien.get(f"{AWALAN}/kirim")
    kuki = jawab.headers.get("Set-Cookie", "")
    assert "joderma_survei_sesi" in kuki, "nama kuki harus khas, bukan 'session'"
    assert f"Path={AWALAN}" in kuki, kuki


def test_jalur_tanpa_awalan_tetap_dilayani(klien: FlaskClient) -> None:
    """Sengaja longgar: pemeriksaan langsung ke 127.0.0.1 tetap bekerja.

    Skrip pemasangan memeriksa / tanpa awalan, dan jalur itu hanya
    terjangkau dari dalam mesin karena aplikasinya terikat ke localhost.
    """
    assert klien.get("/").status_code == 302
    masuk(klien)
    assert klien.get("/kirim").status_code == 200


def test_jalur_milik_tetangga_tidak_disamar(klien: FlaskClient) -> None:
    """Jalur asing tetap 404 dari sisi kita, bukan diam-diam dilayani."""
    assert klien.get("/jalur-aplikasi-lain").status_code == 404


def test_masuk_tidak_ada_di_bawah_awalan(klien: FlaskClient) -> None:
    assert klien.get(f"{AWALAN}/masuk").status_code == 404


# --------------------------------------------------------------------------
# Tanpa awalan, perilakunya harus persis seperti semula
# --------------------------------------------------------------------------


@pytest.fixture
def klien_tanpa_awalan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[FlaskClient]:
    monkeypatch.setenv("JODERMA_KUKI_AMAN", "0")
    monkeypatch.setenv("JODERMA_OPS_HOST", HOST_OPS)
    monkeypatch.delenv("JODERMA_AWALAN_ADMIN", raising=False)
    path = tmp_path / "polos.db"
    conn = db.buka(path)
    db.migrasi(conn)
    conn.close()
    app: Flask = buat_app(path, kunci_rahasia="kunci-uji", pemeriksa_sesi=pemeriksa)
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_tanpa_awalan_tetap_seperti_semula(klien_tanpa_awalan: FlaskClient) -> None:
    masuk(klien_tanpa_awalan)
    jawab = klien_tanpa_awalan.get("/")
    assert jawab.status_code == 302
    assert "/survei" not in jawab.headers["Location"]


def test_tanpa_awalan_next_tanpa_awalan(klien_tanpa_awalan: FlaskClient) -> None:
    jawab = klien_tanpa_awalan.get("/kirim")
    assert jawab.headers["Location"] == LOGIN_OPS + "/kirim"


def test_tanpa_awalan_kuki_tidak_dibatasi(klien_tanpa_awalan: FlaskClient) -> None:
    jawab = klien_tanpa_awalan.get("/kirim")
    assert "Path=/survei" not in jawab.headers.get("Set-Cookie", "")
