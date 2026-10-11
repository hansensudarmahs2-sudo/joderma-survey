"""Uji sandi dan hak akses (F14)."""

from __future__ import annotations

import sqlite3

import pytest

from joderma_survey import db
from joderma_survey.pengguna import (
    IZIN,
    KEMAMPUAN,
    PERAN,
    SandiTidakValid,
    boleh,
    buat_pengguna,
    cari_pengguna,
    hash_sandi,
    masuk,
    periksa_sandi,
)

SANDI = "sandi-uji-yang-cukup-panjang"


@pytest.fixture
def conn() -> sqlite3.Connection:
    sambungan = db.buka(":memory:")
    db.migrasi(sambungan)
    yield sambungan
    sambungan.close()


# --------------------------------------------------------------------------
# Sandi
# --------------------------------------------------------------------------


def test_sandi_benar_dan_salah() -> None:
    tersimpan = hash_sandi(SANDI)
    assert periksa_sandi(SANDI, tersimpan)
    assert not periksa_sandi(SANDI + "x", tersimpan)
    assert not periksa_sandi("", tersimpan)


def test_sandi_tidak_disimpan_apa_adanya() -> None:
    tersimpan = hash_sandi(SANDI)
    assert SANDI not in tersimpan
    assert tersimpan.startswith("scrypt$")


def test_garam_berbeda_setiap_kali() -> None:
    """Dua pengguna bersandi sama tidak boleh punya hash yang sama."""
    assert hash_sandi(SANDI) != hash_sandi(SANDI)
    assert periksa_sandi(SANDI, hash_sandi(SANDI))


@pytest.mark.parametrize("sandi", ["", "pendek", "123456789", None, 12345])
def test_sandi_terlalu_pendek_ditolak(sandi: object) -> None:
    with pytest.raises(SandiTidakValid):
        hash_sandi(sandi)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "tersimpan",
    ["", "bukan-format", "scrypt$a$b$c$d$e", "scrypt$16384$8$1$zz$zz",
     "bcrypt$1$2$3$4$5", "scrypt$16384$8$1$00"],
)
def test_bentuk_simpan_rusak_ditolak(tersimpan: str) -> None:
    assert not periksa_sandi(SANDI, tersimpan)


def test_sandi_unicode_didukung() -> None:
    sandi = "sandi-dengan-huruf-ç-dan-emoji-🔑"
    assert periksa_sandi(sandi, hash_sandi(sandi))


# --------------------------------------------------------------------------
# Hak akses (F14)
# --------------------------------------------------------------------------


def test_cs_hanya_daftar_kirim() -> None:
    """F14: CS hanya dapat membuka daftar kirim."""
    assert boleh("cs", "lihat_daftar_kirim")
    assert boleh("cs", "batalkan_undangan")
    assert not boleh("cs", "lihat_hasil")
    assert not boleh("cs", "unggah_laporan")
    assert not boleh("cs", "kelola_pertanyaan")
    assert not boleh("cs", "kelola_pengguna")


def test_direktur_penuh() -> None:
    for kemampuan in KEMAMPUAN:
        assert boleh("direktur", kemampuan), kemampuan


def test_owner_boleh_unggah_dan_lihat_hasil() -> None:
    """F14 menyebut owner dan direktur untuk unggah laporan dan hasil survei."""
    assert boleh("owner", "unggah_laporan")
    assert boleh("owner", "lihat_hasil")


def test_owner_tidak_mengelola_pengguna() -> None:
    """Pengelolaan sistem ada di direktur (tabel peran PRD)."""
    assert not boleh("owner", "kelola_pengguna")


def test_hasil_survei_tertutup_untuk_cs() -> None:
    """Syarat inti F14 dan bagian Privasi PRD."""
    terbuka = [p for p in PERAN if boleh(p, "lihat_hasil")]
    assert terbuka == ["owner", "direktur"]


def test_unggah_tertutup_untuk_cs() -> None:
    terbuka = [p for p in PERAN if boleh(p, "unggah_laporan")]
    assert terbuka == ["owner", "direktur"]


def test_kemampuan_tak_dikenal_selalu_ditolak() -> None:
    """Salah tulis nama kemampuan tidak boleh diam-diam membuka akses."""
    for peran in PERAN:
        assert not boleh(peran, "lihat_hasil_survei")
        assert not boleh(peran, "")
        assert not boleh(peran, "admin")


def test_peran_tak_dikenal_tidak_punya_hak() -> None:
    for kemampuan in KEMAMPUAN:
        assert not boleh("admin", kemampuan)
        assert not boleh("", kemampuan)


def test_izin_hanya_memuat_kemampuan_yang_dikenal() -> None:
    for peran, daftar in IZIN.items():
        assert peran in PERAN
        assert daftar <= set(KEMAMPUAN), f"{peran} punya kemampuan asing"


# --------------------------------------------------------------------------
# Pengguna di basis data
# --------------------------------------------------------------------------


def test_buat_dan_cari_pengguna(conn: sqlite3.Connection) -> None:
    dibuat = buat_pengguna(conn, "hansen", "direktur", SANDI)
    assert dibuat.nama == "hansen"
    ditemukan = cari_pengguna(conn, "hansen")
    assert ditemukan is not None
    assert ditemukan.peran == "direktur"
    assert ditemukan.aktif


def test_cari_pengguna_tidak_ada(conn: sqlite3.Connection) -> None:
    assert cari_pengguna(conn, "tidak-ada") is None


def test_nama_pengguna_unik(conn: sqlite3.Connection) -> None:
    buat_pengguna(conn, "hansen", "direktur", SANDI)
    with pytest.raises(sqlite3.IntegrityError):
        buat_pengguna(conn, "hansen", "cs", SANDI)


def test_peran_tak_dikenal_ditolak(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="peran tidak dikenal"):
        buat_pengguna(conn, "x", "admin", SANDI)


def test_nama_kosong_ditolak(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="nama pengguna kosong"):
        buat_pengguna(conn, "   ", "cs", SANDI)


def test_masuk_berhasil(conn: sqlite3.Connection) -> None:
    buat_pengguna(conn, "hansen", "direktur", SANDI)
    pengguna = masuk(conn, "hansen", SANDI)
    assert pengguna is not None
    assert pengguna.peran == "direktur"
    assert pengguna.boleh("unggah_laporan")


def test_masuk_sandi_salah(conn: sqlite3.Connection) -> None:
    buat_pengguna(conn, "hansen", "direktur", SANDI)
    assert masuk(conn, "hansen", "sandi-yang-salah-panjang") is None


def test_masuk_pengguna_tidak_ada(conn: sqlite3.Connection) -> None:
    assert masuk(conn, "tidak-ada", SANDI) is None


def test_masuk_pengguna_nonaktif(conn: sqlite3.Connection) -> None:
    buat_pengguna(conn, "mantan", "cs", SANDI)
    conn.execute("UPDATE pengguna SET aktif = 0 WHERE nama = 'mantan'")
    assert masuk(conn, "mantan", SANDI) is None


def test_nama_dirapikan_spasinya(conn: sqlite3.Connection) -> None:
    buat_pengguna(conn, "  hansen  ", "direktur", SANDI)
    assert masuk(conn, "hansen", SANDI) is not None
    assert masuk(conn, "  hansen ", SANDI) is not None


def test_ketiga_peran_bisa_dibuat(conn: sqlite3.Connection) -> None:
    for i, peran in enumerate(PERAN):
        buat_pengguna(conn, f"orang{i}", peran, SANDI)
    assert conn.execute("SELECT COUNT(*) AS n FROM pengguna").fetchone()["n"] == 3
