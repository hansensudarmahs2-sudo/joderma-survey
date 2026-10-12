"""Uji cadangan basis data (F16, gap G1)."""

from __future__ import annotations

import datetime as dt
import sqlite3
import tarfile
from pathlib import Path

import pytest

from joderma_survey import db
from joderma_survey.cadangan import (
    AWALAN,
    CadanganGagal,
    buat_cadangan,
    pangkas,
    sidik_jari,
)


@pytest.fixture
def basis(tmp_path: Path) -> Path:
    path = tmp_path / "uji.db"
    conn = db.buka(path)
    db.migrasi(conn)
    conn.execute(
        "INSERT INTO pasien (rm, nama_terakhir, awalan, pertama_terlihat,"
        " terakhir_terlihat) VALUES ('J00001','Uji','J','2026-09-01','2026-09-01')"
    )
    conn.close()
    return path


def buka_arsip(path: Path) -> list[str]:
    with tarfile.open(path) as t:
        return t.getnames()


# --------------------------------------------------------------------------
# Salinan yang konsisten
# --------------------------------------------------------------------------


def test_cadangan_dasar(basis: Path, tmp_path: Path) -> None:
    hasil = buat_cadangan(basis, tmp_path / "cadangan")
    assert hasil.berkas.exists()
    assert hasil.berkas.name.startswith(AWALAN)
    assert hasil.berkas.suffixes[-2:] == [".tar", ".gz"]
    assert hasil.ukuran > 0
    assert len(hasil.sidik) == 64
    assert buka_arsip(hasil.berkas) == ["uji.db"]


def test_konsisten_saat_basis_sedang_dipakai(basis: Path, tmp_path: Path) -> None:
    """Inti modul ini: cp pada basis data WAL yang aktif bisa robek.

    Sambungan sengaja dibiarkan terbuka dengan transaksi yang belum dilipat
    ke berkas utama, meniru aplikasi yang sedang berjalan.
    """
    conn = db.buka(basis)
    for i in range(2, 60):
        conn.execute(
            "INSERT INTO pasien (rm, nama_terakhir, awalan, pertama_terlihat,"
            " terakhir_terlihat) VALUES (?,?,'J','2026-09-01','2026-09-01')",
            (f"J{i:05d}", f"Pasien {i}"),
        )
    try:
        hasil = buat_cadangan(basis, tmp_path / "cadangan")
        pulih = tmp_path / "pulih"
        pulih.mkdir()
        with tarfile.open(hasil.berkas) as t:
            t.extractall(pulih, filter="data")
        salinan = db.buka(pulih / "uji.db")
        assert salinan.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert salinan.execute(
            "SELECT COUNT(*) n FROM pasien"
        ).fetchone()["n"] == 59
        salinan.close()
    finally:
        conn.close()


def test_pulih_menjaga_aturan_jeda(basis: Path, tmp_path: Path) -> None:
    """Yang paling merugikan kalau hilang bukan jawabannya, tapi status jeda."""
    conn = db.buka(basis)
    conn.execute(
        "INSERT INTO unggahan (nama_berkas, cabang_kode, periode_awal,"
        " periode_akhir, diunggah_pada, baris_data, baris_dipakai, pasien_unik,"
        " ringkasan) VALUES ('x','30376','2026-09-01','2026-09-30','2026-10-11',"
        " 1,1,1,'{}')"
    )
    db.catat_undangan(conn, rm="J00001", cabang_kode="30376", no_faktur=1,
                      unggahan_id=1, dibuat_pada=dt.date(2026, 10, 11))
    conn.close()

    hasil = buat_cadangan(basis, tmp_path / "cadangan")
    pulih = tmp_path / "pulih"
    pulih.mkdir()
    with tarfile.open(hasil.berkas) as t:
        t.extractall(pulih, filter="data")

    from joderma_survey.aturan import boleh_dikirim

    salinan = db.buka(pulih / "uji.db")
    riwayat = db.riwayat(salinan, "J00001")
    assert len(riwayat) == 1
    assert not boleh_dikirim(riwayat, dt.date(2026, 10, 20)).boleh
    assert boleh_dikirim(riwayat, dt.date(2026, 11, 10)).boleh
    salinan.close()


def test_basis_tidak_ada(tmp_path: Path) -> None:
    with pytest.raises(CadanganGagal, match="tidak ada"):
        buat_cadangan(tmp_path / "hantu.db", tmp_path / "cadangan")


def test_basis_rusak_ditolak(tmp_path: Path) -> None:
    rusak = tmp_path / "rusak.db"
    rusak.write_bytes(b"ini jelas bukan basis data sqlite")
    with pytest.raises(CadanganGagal):
        buat_cadangan(rusak, tmp_path / "cadangan")


def test_gagal_tidak_meninggalkan_arsip_separuh(tmp_path: Path) -> None:
    rusak = tmp_path / "rusak.db"
    rusak.write_bytes(b"bukan sqlite")
    tujuan = tmp_path / "cadangan"
    with pytest.raises(CadanganGagal):
        buat_cadangan(rusak, tujuan)
    assert list(tujuan.glob("*.tar.gz")) == []
    assert list(tujuan.glob(".*")) == [], "berkas sementara harus dibersihkan"


# --------------------------------------------------------------------------
# Dokumen yang ikut
# --------------------------------------------------------------------------


def test_dokumen_ikut_disertakan(basis: Path, tmp_path: Path) -> None:
    berkas = tmp_path / "catatan.md"
    berkas.write_text("catatan penting", encoding="utf-8")
    hasil = buat_cadangan(basis, tmp_path / "cadangan", dokumen=[berkas])
    assert any("catatan.md" in n for n in buka_arsip(hasil.berkas))
    assert len(hasil.dokumen) == 1


def test_folder_dokumen_ikut_seluruh_isinya(basis: Path, tmp_path: Path) -> None:
    folder = tmp_path / "docs"
    folder.mkdir()
    (folder / "a.md").write_text("a", encoding="utf-8")
    (folder / "b.md").write_text("b", encoding="utf-8")
    hasil = buat_cadangan(basis, tmp_path / "cadangan", dokumen=[folder])
    nama = buka_arsip(hasil.berkas)
    assert sum(1 for n in nama if n.endswith(".md")) == 2


def test_dokumen_tidak_ada_dilewati(basis: Path, tmp_path: Path) -> None:
    hasil = buat_cadangan(basis, tmp_path / "cadangan",
                          dokumen=[tmp_path / "hantu.md"])
    assert hasil.dokumen == []
    assert hasil.berkas.exists()


# --------------------------------------------------------------------------
# Pemangkasan
# --------------------------------------------------------------------------


def test_pangkas_menyisakan_yang_terbaru(basis: Path, tmp_path: Path) -> None:
    tujuan = tmp_path / "cadangan"
    waktu = dt.datetime(2026, 10, 1, 3, 0, 0)
    for i in range(6):
        buat_cadangan(basis, tujuan, simpan=3,
                      sekarang=waktu + dt.timedelta(days=i))
    tersisa = sorted(p.name for p in tujuan.glob(f"{AWALAN}*.tar.gz"))
    assert len(tersisa) == 3
    assert tersisa[-1].startswith(f"{AWALAN}20261006")


def test_pangkas_tidak_menyentuh_berkas_lain(tmp_path: Path) -> None:
    """Folder cadangan bisa dipakai bersama alat sinkronisasi."""
    tujuan = tmp_path / "cadangan"
    tujuan.mkdir()
    (tujuan / "catatan-saya.txt").write_text("jangan dihapus", encoding="utf-8")
    (tujuan / "arsip-lain.tar.gz").write_text("bukan punya kita", encoding="utf-8")
    for i in range(4):
        (tujuan / f"{AWALAN}2026100{i}-030000.tar.gz").write_text("x",
                                                                  encoding="utf-8")
    dihapus = pangkas(tujuan, simpan=2)
    assert len(dihapus) == 2
    assert (tujuan / "catatan-saya.txt").exists()
    assert (tujuan / "arsip-lain.tar.gz").exists()


def test_pangkas_nol_tidak_menghapus(tmp_path: Path) -> None:
    tujuan = tmp_path / "cadangan"
    tujuan.mkdir()
    (tujuan / f"{AWALAN}20261001-030000.tar.gz").write_text("x", encoding="utf-8")
    assert pangkas(tujuan, simpan=0) == []
    assert len(list(tujuan.glob("*.tar.gz"))) == 1


def test_pangkas_folder_tidak_ada(tmp_path: Path) -> None:
    assert pangkas(tmp_path / "hantu", simpan=3) == []


def test_cadangan_berurutan_tidak_saling_menimpa(
    basis: Path, tmp_path: Path
) -> None:
    tujuan = tmp_path / "cadangan"
    a = buat_cadangan(basis, tujuan, sekarang=dt.datetime(2026, 10, 1, 3, 0, 0))
    b = buat_cadangan(basis, tujuan, sekarang=dt.datetime(2026, 10, 2, 3, 0, 0))
    assert a.berkas != b.berkas
    assert a.berkas.exists() and b.berkas.exists()


# --------------------------------------------------------------------------
# Sidik jari
# --------------------------------------------------------------------------


def test_sidik_jari_berbeda_untuk_isi_berbeda(tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    a.write_bytes(b"satu")
    b.write_bytes(b"dua")
    assert sidik_jari(a) != sidik_jari(b)


def test_sidik_jari_sama_untuk_isi_sama(tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    a.write_bytes(b"sama")
    b.write_bytes(b"sama")
    assert sidik_jari(a) == sidik_jari(b)
