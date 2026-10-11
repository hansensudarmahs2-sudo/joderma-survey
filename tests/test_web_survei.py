"""Uji halaman survei publik (F7, F8)."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Iterator

import pytest
from bantu import laporan, transaksi
from flask import Flask
from flask.testing import FlaskClient

from joderma_survey import db
from joderma_survey.daftar_kirim import buat_undangan
from joderma_survey.web_survei import buat_app

HARI_H = dt.date.today()

LENGKAP = {
    "keseluruhan": "5", "penjelasan_dokter": "4", "waktu_tunggu": "3",
    "sikap_staf": "5", "kenyamanan": "4", "kejelasan_biaya": "5",
    "perbaikan": "Tempat parkir kurang luas.", "izin_kontak": "tidak",
}


@pytest.fixture
def path_basis(tmp_path: Path) -> Path:
    path = tmp_path / "survei.db"
    conn = db.buka(path)
    db.migrasi(conn)
    lap = laporan(transaksi(no_id="J00143", pasien="Tatik Mindari",
                            dokter="dr. Yohanes Widjaja Sp.DVE"))
    uid = db.simpan_laporan(conn, lap).unggahan_id
    buat_undangan(conn, lap, uid)
    conn.close()
    return path


@pytest.fixture
def token(path_basis: Path) -> str:
    conn = db.buka(path_basis)
    t = conn.execute("SELECT token FROM undangan").fetchone()["token"]
    conn.close()
    return t


@pytest.fixture
def klien(path_basis: Path) -> Iterator[FlaskClient]:
    app: Flask = buat_app(path_basis)
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# --------------------------------------------------------------------------
# Membuka survei (F7)
# --------------------------------------------------------------------------


def test_halaman_terbuka_tanpa_login(klien: FlaskClient, token: str) -> None:
    jawab = klien.get(f"/s/{token}")
    assert jawab.status_code == 200
    assert "masuk" not in jawab.get_data(as_text=True).lower().split("<body")[0]


def test_identitas_terisi_otomatis(klien: FlaskClient, token: str) -> None:
    isi = klien.get(f"/s/{token}").get_data(as_text=True)
    assert "Tatik Mindari" in isi


def test_semua_pertanyaan_tampil(klien: FlaskClient, token: str) -> None:
    isi = klien.get(f"/s/{token}").get_data(as_text=True)
    for kode in ("keseluruhan", "penjelasan_dokter", "waktu_tunggu",
                 "sikap_staf", "kenyamanan", "kejelasan_biaya",
                 "keluhan_lanjutan", "perbaikan", "izin_kontak"):
        assert f'name="{kode}"' in isi, kode


def test_skala_berlabel_bahasa_indonesia(klien: FlaskClient, token: str) -> None:
    isi = klien.get(f"/s/{token}").get_data(as_text=True)
    for label in ("Sangat buruk", "Buruk", "Cukup", "Baik", "Sangat baik"):
        assert label in isi


def test_pertanyaan_bersyarat_tersembunyi_awalnya(
    klien: FlaskClient, token: str
) -> None:
    isi = klien.get(f"/s/{token}").get_data(as_text=True)
    assert 'data-tampil-bila="ada_nilai_rendah"' in isi
    assert "bersyarat hening" in isi


def test_halaman_tidak_memuat_nomor_rm(klien: FlaskClient, token: str) -> None:
    """Pasien tidak perlu melihat nomor rekam medisnya di halaman survei."""
    assert "J00143" not in klien.get(f"/s/{token}").get_data(as_text=True)


def test_membuka_halaman_tercatat(
    klien: FlaskClient, token: str, path_basis: Path
) -> None:
    klien.get(f"/s/{token}")
    conn = db.buka(path_basis)
    nilai = conn.execute("SELECT dibuka_pada v FROM undangan").fetchone()["v"]
    conn.close()
    assert nilai is not None


# --------------------------------------------------------------------------
# Kepala tanggapan: token tidak boleh bocor
# --------------------------------------------------------------------------


def test_referrer_policy_no_referrer(klien: FlaskClient, token: str) -> None:
    """Alamat memuat token; tanpa ini token ikut terkirim ke situs lain."""
    assert klien.get(f"/s/{token}").headers["Referrer-Policy"] == "no-referrer"


def test_tidak_diindeks_mesin_pencari(klien: FlaskClient, token: str) -> None:
    jawab = klien.get(f"/s/{token}")
    assert "noindex" in jawab.headers["X-Robots-Tag"]
    assert "noindex" in jawab.get_data(as_text=True)


def test_tidak_disimpan_cache(klien: FlaskClient, token: str) -> None:
    assert klien.get(f"/s/{token}").headers["Cache-Control"] == "no-store"


def test_tidak_ada_tautan_keluar(klien: FlaskClient, token: str) -> None:
    """Satu tautan keluar saja sudah cukup membocorkan token lewat Referer."""
    isi = klien.get(f"/s/{token}").get_data(as_text=True)
    assert "http://" not in isi
    assert "https://" not in isi


# --------------------------------------------------------------------------
# Pesan ramah (F8)
# --------------------------------------------------------------------------


def test_token_salah_memberi_pesan_ramah(klien: FlaskClient) -> None:
    jawab = klien.get("/s/token-yang-salah")
    assert jawab.status_code == 404
    isi = jawab.get_data(as_text=True)
    assert "tidak dikenali" in isi.lower()
    assert "terpotong saat disalin" in isi


def test_link_terpakai_memberi_pesan_ramah(
    klien: FlaskClient, token: str
) -> None:
    klien.post(f"/s/{token}", data=LENGKAP)
    jawab = klien.get(f"/s/{token}")
    assert jawab.status_code == 410
    assert "sudah terisi" in jawab.get_data(as_text=True).lower()


def test_link_kedaluwarsa_memberi_pesan_ramah(
    klien: FlaskClient, token: str, path_basis: Path
) -> None:
    conn = db.buka(path_basis)
    conn.execute("UPDATE undangan SET kedaluwarsa_pada = '2020-01-01'")
    conn.close()
    jawab = klien.get(f"/s/{token}")
    assert jawab.status_code == 410
    isi = jawab.get_data(as_text=True)
    assert "masa berlaku" in isi.lower()
    assert "hubungi klinik" in isi.lower()


def test_link_dibatalkan_memberi_pesan_ramah(
    klien: FlaskClient, token: str, path_basis: Path
) -> None:
    conn = db.buka(path_basis)
    db.batalkan_undangan(conn, token)
    conn.close()
    jawab = klien.get(f"/s/{token}")
    assert jawab.status_code == 410
    assert "tidak berlaku lagi" in jawab.get_data(as_text=True).lower()


def test_pesan_tidak_menyebut_nama_pasien(
    klien: FlaskClient, token: str
) -> None:
    """Halaman untuk link yang tidak berlaku tidak boleh membocorkan apa pun."""
    klien.post(f"/s/{token}", data=LENGKAP)
    assert "Tatik Mindari" not in klien.get(f"/s/{token}").get_data(as_text=True)


# --------------------------------------------------------------------------
# Tidak ada apa pun selain survei
# --------------------------------------------------------------------------


def test_akar_tidak_menampilkan_apa_pun(klien: FlaskClient) -> None:
    assert klien.get("/").status_code == 404


@pytest.mark.parametrize("jalur", ["/kirim", "/unggah", "/hasil", "/masuk", "/s/"])
def test_rute_admin_tidak_ada_di_aplikasi_survei(
    klien: FlaskClient, jalur: str
) -> None:
    """Aplikasi terpisah: subdomain survei tidak punya kode admin sama sekali."""
    assert klien.get(jalur).status_code == 404


# --------------------------------------------------------------------------
# Mengirim jawaban (F9)
# --------------------------------------------------------------------------


def test_kirim_jawaban_berhasil(
    klien: FlaskClient, token: str, path_basis: Path
) -> None:
    jawab = klien.post(f"/s/{token}", data=LENGKAP)
    assert jawab.status_code == 302
    assert jawab.headers["Location"].endswith("/terima-kasih")
    conn = db.buka(path_basis)
    assert conn.execute("SELECT COUNT(*) n FROM sesi_jawaban").fetchone()["n"] == 1
    assert conn.execute("SELECT diisi_pada v FROM undangan").fetchone()["v"]
    conn.close()


def test_halaman_terima_kasih(klien: FlaskClient) -> None:
    isi = klien.get("/terima-kasih").get_data(as_text=True)
    assert "Terima kasih" in isi


def test_kirim_dua_kali_ditolak(
    klien: FlaskClient, token: str, path_basis: Path
) -> None:
    klien.post(f"/s/{token}", data=LENGKAP)
    jawab = klien.post(f"/s/{token}", data=LENGKAP)
    assert jawab.status_code == 410
    conn = db.buka(path_basis)
    assert conn.execute("SELECT COUNT(*) n FROM sesi_jawaban").fetchone()["n"] == 1
    conn.close()


def test_jawaban_tidak_valid_menampilkan_ulang_formulir(
    klien: FlaskClient, token: str
) -> None:
    jawab = klien.post(f"/s/{token}", data={"penjelasan_dokter": "4"})
    assert jawab.status_code == 400
    isi = jawab.get_data(as_text=True)
    assert "wajib" in isi.lower()
    assert 'name="keseluruhan"' in isi, "formulir ditampilkan lagi"


def test_jawaban_sebelumnya_tidak_hilang_saat_ditolak(
    klien: FlaskClient, token: str
) -> None:
    jawab = klien.post(f"/s/{token}", data={"penjelasan_dokter": "4",
                                            "perbaikan": "Parkir sempit"})
    isi = jawab.get_data(as_text=True)
    assert "Parkir sempit" in isi
    assert 'id="penjelasan_dokter-4"' in isi and "checked" in isi


def test_nilai_di_luar_jangkauan_ditolak(klien: FlaskClient, token: str) -> None:
    jawab = klien.post(f"/s/{token}", data=dict(LENGKAP, keseluruhan="9"))
    assert jawab.status_code == 400


def test_kiriman_ditolak_tidak_memakai_link(
    klien: FlaskClient, token: str
) -> None:
    klien.post(f"/s/{token}", data={})
    assert klien.get(f"/s/{token}").status_code == 200, "link masih bisa dipakai"


def test_durasi_tercatat(
    klien: FlaskClient, token: str, path_basis: Path
) -> None:
    import time

    mulai = int(time.time()) - 65
    klien.post(f"/s/{token}", data=dict(LENGKAP, mulai=str(mulai)))
    conn = db.buka(path_basis)
    durasi = conn.execute("SELECT durasi_detik v FROM sesi_jawaban").fetchone()["v"]
    conn.close()
    assert durasi is not None and 60 <= durasi <= 120


def test_durasi_tak_masuk_akal_diabaikan(
    klien: FlaskClient, token: str, path_basis: Path
) -> None:
    klien.post(f"/s/{token}", data=dict(LENGKAP, mulai="1"))
    conn = db.buka(path_basis)
    assert conn.execute(
        "SELECT durasi_detik v FROM sesi_jawaban"
    ).fetchone()["v"] is None
    conn.close()


def test_izin_kontak_ya_membuat_jembatan(
    klien: FlaskClient, token: str, path_basis: Path
) -> None:
    klien.post(f"/s/{token}", data=dict(LENGKAP, izin_kontak="ya"))
    conn = db.buka(path_basis)
    baris = conn.execute("SELECT rm FROM izin_kontak").fetchone()
    conn.close()
    assert baris["rm"] == "J00143"


def test_izin_kontak_tidak_membiarkan_jawaban_anonim(
    klien: FlaskClient, token: str, path_basis: Path
) -> None:
    klien.post(f"/s/{token}", data=LENGKAP)
    conn = db.buka(path_basis)
    assert conn.execute("SELECT COUNT(*) n FROM izin_kontak").fetchone()["n"] == 0
    conn.close()
