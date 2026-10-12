"""Uji pemasangan aplikasi admin di bawah awalan jalur.

Dipakai saat admin berbagi hostname dengan sistem lain (ops.joderma.id)
supaya ikut memakai kebijakan Cloudflare Access yang sudah ada di sana, dan
staf tidak diminta login dua kali.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest
from flask import Flask
from flask.testing import FlaskClient

from joderma_survey import db
from joderma_survey.awalan import rapikan_awalan
from joderma_survey.pengguna import buat_pengguna
from joderma_survey.web_admin import buat_app

SANDI = "sandi-uji-yang-panjang"
AWALAN = "/survei"


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
    path = tmp_path / "uji.db"
    conn = db.buka(path)
    db.migrasi(conn)
    buat_pengguna(conn, "dirops", "direktur", SANDI)
    conn.close()
    return path


@pytest.fixture
def klien(path_basis: Path) -> Iterator[FlaskClient]:
    app: Flask = buat_app(path_basis, kunci_rahasia="kunci-uji")
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_halaman_terbuka_di_bawah_awalan(klien: FlaskClient) -> None:
    assert klien.get(f"{AWALAN}/masuk").status_code == 200


def test_tautan_dibuat_dengan_awalan(klien: FlaskClient) -> None:
    """Inti masalahnya: tanpa ini semua tautan menunjuk akar hostname.

    Halaman masuk sendiri tidak memuat tautan absolut -- formulirnya mengirim
    ke alamat yang sama -- jadi yang diperiksa halaman setelah masuk, yang
    menu atasnya dibuat url_for.
    """
    klien.post(f"{AWALAN}/masuk", data={"nama": "dirops", "sandi": SANDI})
    isi = klien.get(f"{AWALAN}/kirim").get_data(as_text=True)
    for jalur in ("/kirim", "/unggah", "/hasil", "/keluar"):
        assert f'"{AWALAN}{jalur}"' in isi, f"tautan {jalur} tidak berawalan"
    assert 'href="/kirim"' not in isi, "ada tautan tanpa awalan"
    assert f"{AWALAN}{AWALAN}" not in isi, "awalan terpasang dua kali"


def test_pengalihan_memakai_awalan(klien: FlaskClient) -> None:
    """Gejala paling membingungkan bila salah: login berhasil lalu terlempar
    ke aplikasi tetangga di hostname yang sama."""
    jawab = klien.post(f"{AWALAN}/masuk", data={"nama": "dirops", "sandi": SANDI})
    assert jawab.status_code == 302
    assert AWALAN in jawab.headers["Location"], jawab.headers["Location"]


def test_alur_penuh_di_bawah_awalan(klien: FlaskClient) -> None:
    klien.post(f"{AWALAN}/masuk", data={"nama": "dirops", "sandi": SANDI})
    for jalur in ("/kirim", "/unggah", "/hasil"):
        assert klien.get(f"{AWALAN}{jalur}").status_code == 200, jalur


def test_awalan_tidak_terpasang_dua_kali(klien: FlaskClient) -> None:
    """Mengisi APPLICATION_ROOT sekaligus SCRIPT_NAME menghasilkan
    /survei/survei/kirim -- halaman terbuka, tapi semua tautannya rusak."""
    jawab = klien.post(f"{AWALAN}/masuk", data={"nama": "dirops", "sandi": SANDI})
    assert jawab.headers["Location"].count("/survei") == 1, jawab.headers["Location"]
    isi = klien.get(f"{AWALAN}/kirim").get_data(as_text=True)
    assert "/survei/survei" not in isi


def test_akar_awalan_mengalihkan(klien: FlaskClient) -> None:
    klien.post(f"{AWALAN}/masuk", data={"nama": "dirops", "sandi": SANDI})
    jawab = klien.get(AWALAN)
    assert jawab.status_code == 302
    assert AWALAN in jawab.headers["Location"]


def test_tanpa_masuk_dialihkan_ke_masuk_berawalan(klien: FlaskClient) -> None:
    jawab = klien.get(f"{AWALAN}/kirim")
    assert jawab.status_code == 302
    assert f"{AWALAN}/masuk" in jawab.headers["Location"]


def test_kuki_dibatasi_ke_awalan(klien: FlaskClient) -> None:
    """Kuki tidak boleh ikut terkirim ke aplikasi tetangga di hostname sama."""
    jawab = klien.post(f"{AWALAN}/masuk", data={"nama": "dirops", "sandi": SANDI})
    kuki = jawab.headers.get("Set-Cookie", "")
    assert "joderma_survei_sesi" in kuki, "nama kuki harus khas, bukan 'session'"
    assert f"Path={AWALAN}" in kuki, kuki


def test_jalur_tanpa_awalan_tetap_dilayani(klien: FlaskClient) -> None:
    """Sengaja longgar: pemeriksaan langsung ke 127.0.0.1 tetap bekerja.

    Skrip pemasangan memeriksa /masuk tanpa awalan, dan jalur itu hanya
    terjangkau dari dalam mesin karena aplikasinya terikat ke localhost.
    """
    assert klien.get("/masuk").status_code == 200


def test_jalur_milik_tetangga_tidak_disamar(klien: FlaskClient) -> None:
    """Jalur asing tetap 404 dari sisi kita, bukan diam-diam dilayani."""
    assert klien.get("/jalur-aplikasi-lain").status_code == 404


# --------------------------------------------------------------------------
# Tanpa awalan, perilakunya harus persis seperti semula
# --------------------------------------------------------------------------


@pytest.fixture
def klien_tanpa_awalan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[FlaskClient]:
    monkeypatch.setenv("JODERMA_KUKI_AMAN", "0")
    monkeypatch.delenv("JODERMA_AWALAN_ADMIN", raising=False)
    path = tmp_path / "polos.db"
    conn = db.buka(path)
    db.migrasi(conn)
    buat_pengguna(conn, "dirops", "direktur", SANDI)
    conn.close()
    app: Flask = buat_app(path, kunci_rahasia="kunci-uji")
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_tanpa_awalan_tetap_seperti_semula(klien_tanpa_awalan: FlaskClient) -> None:
    assert klien_tanpa_awalan.get("/masuk").status_code == 200
    jawab = klien_tanpa_awalan.post(
        "/masuk", data={"nama": "dirops", "sandi": SANDI}
    )
    assert jawab.status_code == 302
    assert "/survei" not in jawab.headers["Location"]


def test_tanpa_awalan_kuki_tidak_dibatasi(klien_tanpa_awalan: FlaskClient) -> None:
    jawab = klien_tanpa_awalan.post(
        "/masuk", data={"nama": "dirops", "sandi": SANDI}
    )
    assert "Path=/survei" not in jawab.headers.get("Set-Cookie", "")
