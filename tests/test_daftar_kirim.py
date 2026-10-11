"""Uji pemilihan calon, pembuatan link, dan daftar kirim CS."""

from __future__ import annotations

import datetime as dt
import sqlite3

import pytest
from bantu import laporan, transaksi

from joderma_survey import db
from joderma_survey.daftar_kirim import (
    buat_undangan,
    daftar_kirim,
    pilih_calon,
    teks_pencarian,
    teks_pesan,
)

HARI_H = dt.date(2026, 10, 11)


@pytest.fixture(autouse=True)
def url_tetap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JODERMA_URL_SURVEI", "https://survey.contoh.id")


@pytest.fixture
def conn() -> sqlite3.Connection:
    sambungan = db.buka(":memory:")
    db.migrasi(sambungan)
    yield sambungan
    sambungan.close()


def simpan(conn: sqlite3.Connection, lap: object) -> int:
    return db.simpan_laporan(conn, lap, diunggah_pada=HARI_H).unggahan_id  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Pemilihan calon
# --------------------------------------------------------------------------


def test_hanya_pasien_rj_jadi_calon() -> None:
    """Keputusan 4.3: pasien yang hanya membeli produk diparkir."""
    lap = laporan(
        transaksi(no_id="J00143", layanan="RJ"),
        transaksi(no_id="J00813", faktur=26090002.0, layanan="OTC", dokter="-"),
    )
    calon = pilih_calon(lap)
    assert [c.rm for c in calon] == ["J00143"]


def test_pasien_rj_dan_otc_tetap_jadi_calon() -> None:
    lap = laporan(
        transaksi(no_id="J00143", layanan="OTC", dokter="-"),
        transaksi(no_id="J00143", faktur=26090002.0, layanan="RJ"),
    )
    assert [c.rm for c in pilih_calon(lap)] == ["J00143"]


def test_link_ditempel_ke_kunjungan_rj_terakhir_bukan_transaksi_terakhir() -> None:
    """59 pasien di laporan contoh transaksi terakhirnya OTC padahal punya RJ.

    Kalau faktur OTC yang dipakai, kolom dokter berisi "-" dan skor per
    dokter rusak.
    """
    lap = laporan(
        transaksi(no_id="J00143", faktur=26090100.0, layanan="RJ",
                  tanggal="10/09/2026", waktu="10/09/2026 09:00:00",
                  dokter="dr. Yohanes Widjaja Sp.DVE"),
        transaksi(no_id="J00143", faktur=26090200.0, layanan="OTC", dokter="-",
                  tanggal="20/09/2026", waktu="20/09/2026 09:00:00"),
    )
    (calon,) = pilih_calon(lap)
    assert calon.no_faktur == 26090100
    assert calon.dokter == "dr. Yohanes Widjaja Sp.DVE"
    assert calon.tanggal == dt.date(2026, 9, 10)


def test_kunjungan_rj_terakhir_pakai_tanggal_bukan_waktu_pelunasan() -> None:
    lap = laporan(
        transaksi(no_id="J00143", faktur=26090250.0, tanggal="20/09/2026",
                  waktu="21/09/2026 14:07:09"),
        transaksi(no_id="J00143", faktur=26090260.0, tanggal="21/09/2026",
                  waktu="21/09/2026 09:00:00"),
    )
    (calon,) = pilih_calon(lap)
    assert calon.no_faktur == 26090260


def test_calon_terurut_dan_bisa_diulang() -> None:
    lap = laporan(
        transaksi(no_id="J00813", faktur=26090002.0),
        transaksi(no_id="J00143", faktur=26090001.0),
        transaksi(no_id="JC0308", faktur=26090003.0),
    )
    assert [c.rm for c in pilih_calon(lap)] == ["J00143", "J00813", "JC0308"]
    assert pilih_calon(lap) == pilih_calon(lap)


def test_keraguan_ikut_terbawa_ke_calon() -> None:
    lap = laporan(transaksi(no_id="JC1093", pasien="Dr. Muhlis Yusuf"))
    (calon,) = pilih_calon(lap)
    assert calon.keraguan


def test_tanpa_baris_rj_tidak_ada_calon() -> None:
    lap = laporan(transaksi(layanan="OTC", dokter="-"))
    assert pilih_calon(lap) == ()


# --------------------------------------------------------------------------
# Pembuatan undangan
# --------------------------------------------------------------------------


def test_buat_undangan_dasar(conn: sqlite3.Connection) -> None:
    lap = laporan(
        transaksi(no_id="J00143"),
        transaksi(no_id="J00813", faktur=26090002.0),
    )
    uid = simpan(conn, lap)
    hasil = buat_undangan(conn, lap, uid, hari_ini=HARI_H)
    assert hasil.jumlah_dibuat == 2
    assert hasil.calon == 2
    assert hasil.dilewati == {}
    assert conn.execute("SELECT COUNT(*) AS n FROM undangan").fetchone()["n"] == 2


def test_dijalankan_ulang_tidak_menggandakan_link(conn: sqlite3.Connection) -> None:
    """Undangan yang baru dibuat langsung memblokir lewat jeda 30 hari."""
    lap = laporan(transaksi())
    uid = simpan(conn, lap)
    assert buat_undangan(conn, lap, uid, hari_ini=HARI_H).jumlah_dibuat == 1
    ulang = buat_undangan(conn, lap, uid, hari_ini=HARI_H)
    assert ulang.jumlah_dibuat == 0
    assert "link masih aktif" in next(iter(ulang.dilewati))
    assert conn.execute("SELECT COUNT(*) AS n FROM undangan").fetchone()["n"] == 1


def test_boleh_lagi_setelah_30_hari(conn: sqlite3.Connection) -> None:
    lap = laporan(transaksi())
    uid = simpan(conn, lap)
    buat_undangan(conn, lap, uid, hari_ini=HARI_H)
    assert buat_undangan(
        conn, lap, uid, hari_ini=HARI_H + dt.timedelta(days=29)
    ).jumlah_dibuat == 0
    assert buat_undangan(
        conn, lap, uid, hari_ini=HARI_H + dt.timedelta(days=30)
    ).jumlah_dibuat == 1


def test_pasien_sudah_mengisi_dilewati(conn: sqlite3.Connection) -> None:
    lap = laporan(transaksi())
    uid = simpan(conn, lap)
    buat_undangan(conn, lap, uid, hari_ini=HARI_H)
    conn.execute("UPDATE undangan SET diisi_pada = '2026-10-12'")
    hasil = buat_undangan(conn, lap, uid, hari_ini=dt.date(2027, 1, 1))
    assert hasil.jumlah_dibuat == 0
    assert "sudah mengisi" in next(iter(hasil.dilewati))


def test_pasien_dibatalkan_dapat_link_baru(conn: sqlite3.Connection) -> None:
    """Keputusan 2.20: CS tidak menemukan kontak, pasien tidak terblokir."""
    lap = laporan(transaksi())
    uid = simpan(conn, lap)
    buat_undangan(conn, lap, uid, hari_ini=HARI_H)
    token = conn.execute("SELECT token FROM undangan").fetchone()["token"]
    db.batalkan_undangan(conn, token, pada=HARI_H)
    assert buat_undangan(conn, lap, uid, hari_ini=HARI_H).jumlah_dibuat == 1


def test_pasien_otc_saja_dihitung_diparkir(conn: sqlite3.Connection) -> None:
    lap = laporan(
        transaksi(no_id="J00143", layanan="RJ"),
        transaksi(no_id="J00813", faktur=26090002.0, layanan="OTC", dokter="-"),
    )
    uid = simpan(conn, lap)
    hasil = buat_undangan(conn, lap, uid, hari_ini=HARI_H)
    assert hasil.diparkir_otc == 1
    assert "diparkir" in hasil.ringkas()


def test_rinci_dilewati_memuat_batas_waktu(conn: sqlite3.Connection) -> None:
    lap = laporan(transaksi())
    uid = simpan(conn, lap)
    buat_undangan(conn, lap, uid, hari_ini=HARI_H)
    hasil = buat_undangan(conn, lap, uid, hari_ini=HARI_H)
    rm, alasan, sampai = hasil.rinci_dilewati[0]
    assert rm == "J00143"
    assert sampai == HARI_H + dt.timedelta(days=30)


def test_jeda_gabungan_lintas_cabang(conn: sqlite3.Connection) -> None:
    """Keputusan 2.5: dapat link di Jemur, tidak dapat lagi di Citraland."""
    lap_j = laporan(transaksi(no_id="J07766"), kode_cabang="30376")
    uid_j = simpan(conn, lap_j)
    assert buat_undangan(conn, lap_j, uid_j, hari_ini=HARI_H).jumlah_dibuat == 1

    lap_c = laporan(transaksi(no_id="J07766", faktur=26090500.0), kode_cabang="31281")
    uid_c = simpan(conn, lap_c)
    assert buat_undangan(conn, lap_c, uid_c, hari_ini=HARI_H).jumlah_dibuat == 0


def test_gagal_di_tengah_tidak_meninggalkan_link_separuh(
    conn: sqlite3.Connection,
) -> None:
    lap = laporan(transaksi(no_id="J00143"),
                  transaksi(no_id="J00813", faktur=26090002.0))
    uid = simpan(conn, lap)
    conn.execute("DROP TABLE undangan")
    with pytest.raises(sqlite3.Error):
        buat_undangan(conn, lap, uid, hari_ini=HARI_H)


# --------------------------------------------------------------------------
# Teks siap salin
# --------------------------------------------------------------------------


def test_teks_pencarian_format_disepakati() -> None:
    """Keputusan 2.11: 'Nama Pasien - Jxxxxx'."""
    assert teks_pencarian("Ade Wijaya", "J00635") == "Ade Wijaya - J00635"


def test_teks_pesan_memuat_yang_diperlukan() -> None:
    pesan = teks_pesan("Ade Wijaya", "Jemur Andayani",
                       "https://survey.contoh.id/s/abc", dt.date(2026, 11, 10))
    assert "Ade Wijaya" in pesan
    assert "Jemur Andayani" in pesan
    assert "https://survey.contoh.id/s/abc" in pesan
    assert "10 November 2026" in pesan, "tanggal berbahasa Indonesia"
    assert "1 menit" in pesan, "metodologi 8: sebut lamanya pengisian"


def test_teks_pesan_tidak_menjanjikan_imbalan() -> None:
    """Metodologi bagian 8: imbalan memasukkan bias baru."""
    pesan = teks_pesan("A", "Citraland", "https://x/s/y", dt.date(2026, 11, 10)).lower()
    for kata in ("diskon", "hadiah", "voucher", "gratis", "undian"):
        assert kata not in pesan


def test_teks_pesan_janji_anonim_sesuai_kenyataan() -> None:
    """Jawaban memang tidak disimpan bersama nama (keputusan 4.1)."""
    pesan = teks_pesan("A", "Citraland", "https://x/s/y", dt.date(2026, 11, 10))
    assert "tidak kami simpan bersama nama" in pesan


def test_teks_pesan_tidak_memuat_nomor_rm() -> None:
    """Nomor RM untuk pencarian kontak, bukan untuk isi pesan."""
    pesan = teks_pesan("Ade Wijaya", "Jemur Andayani",
                       "https://survey.contoh.id/s/abc", dt.date(2026, 11, 10))
    assert "J00635" not in pesan


# --------------------------------------------------------------------------
# Daftar kirim
# --------------------------------------------------------------------------


def test_daftar_kirim_dasar(conn: sqlite3.Connection) -> None:
    lap = laporan(transaksi(no_id="J00143", pasien="Tatik Mindari"))
    uid = simpan(conn, lap)
    buat_undangan(conn, lap, uid, hari_ini=HARI_H)
    (baris,) = daftar_kirim(conn, hari_ini=HARI_H)
    assert baris.rm == "J00143"
    assert baris.nama == "Tatik Mindari"
    assert baris.cabang_nama == "Jemur Andayani"
    assert baris.teks_pencarian == "Tatik Mindari - J00143"
    assert baris.url.startswith("https://survey.contoh.id/s/")
    assert baris.token in baris.url
    assert baris.kedaluwarsa_pada == HARI_H + dt.timedelta(days=30)
    assert baris.sisa_hari(HARI_H) == 30
    assert baris.keraguan == ()


def test_daftar_kirim_bisa_dibuka_ulang_dengan_link_sama(
    conn: sqlite3.Connection,
) -> None:
    """CS harus bisa menyalin link yang persis sama berulang kali."""
    lap = laporan(transaksi())
    uid = simpan(conn, lap)
    buat_undangan(conn, lap, uid, hari_ini=HARI_H)
    pertama = daftar_kirim(conn, hari_ini=HARI_H)
    kedua = daftar_kirim(conn, hari_ini=HARI_H)
    assert pertama[0].token == kedua[0].token
    assert pertama[0].teks_pesan == kedua[0].teks_pesan


def test_yang_sudah_diisi_hilang_dari_daftar(conn: sqlite3.Connection) -> None:
    lap = laporan(transaksi())
    uid = simpan(conn, lap)
    buat_undangan(conn, lap, uid, hari_ini=HARI_H)
    conn.execute("UPDATE undangan SET diisi_pada = '2026-10-12'")
    assert daftar_kirim(conn, hari_ini=HARI_H) == ()


def test_yang_dibatalkan_hilang_dari_daftar(conn: sqlite3.Connection) -> None:
    lap = laporan(transaksi())
    uid = simpan(conn, lap)
    buat_undangan(conn, lap, uid, hari_ini=HARI_H)
    token = conn.execute("SELECT token FROM undangan").fetchone()["token"]
    db.batalkan_undangan(conn, token, pada=HARI_H)
    assert daftar_kirim(conn, hari_ini=HARI_H) == ()


def test_yang_kedaluwarsa_hilang_dari_daftar(conn: sqlite3.Connection) -> None:
    lap = laporan(transaksi())
    uid = simpan(conn, lap)
    buat_undangan(conn, lap, uid, hari_ini=HARI_H)
    assert len(daftar_kirim(conn, hari_ini=HARI_H + dt.timedelta(days=29))) == 1
    assert daftar_kirim(conn, hari_ini=HARI_H + dt.timedelta(days=30)) == ()


def test_daftar_kirim_disaring_per_cabang(conn: sqlite3.Connection) -> None:
    lap_j = laporan(transaksi(no_id="J00143"), kode_cabang="30376")
    buat_undangan(conn, lap_j, simpan(conn, lap_j), hari_ini=HARI_H)
    lap_c = laporan(transaksi(no_id="JC0308", faktur=26090500.0), kode_cabang="31281")
    buat_undangan(conn, lap_c, simpan(conn, lap_c), hari_ini=HARI_H)

    assert len(daftar_kirim(conn, hari_ini=HARI_H)) == 2
    assert len(daftar_kirim(conn, cabang_kode="30376", hari_ini=HARI_H)) == 1
    assert daftar_kirim(conn, cabang_kode="31281", hari_ini=HARI_H)[0].rm == "JC0308"


def test_daftar_kirim_disaring_per_unggahan(conn: sqlite3.Connection) -> None:
    lap1 = laporan(transaksi(no_id="J00143"))
    uid1 = simpan(conn, lap1)
    buat_undangan(conn, lap1, uid1, hari_ini=HARI_H)
    lap2 = laporan(transaksi(no_id="J00813", faktur=26090002.0))
    uid2 = simpan(conn, lap2)
    buat_undangan(conn, lap2, uid2, hari_ini=HARI_H)

    assert len(daftar_kirim(conn, unggahan_id=uid1, hari_ini=HARI_H)) == 1
    assert daftar_kirim(conn, unggahan_id=uid2, hari_ini=HARI_H)[0].rm == "J00813"


def test_daftar_kirim_terurut_nama(conn: sqlite3.Connection) -> None:
    lap = laporan(
        transaksi(no_id="J00143", pasien="Zulkarnain"),
        transaksi(no_id="J00813", faktur=26090002.0, pasien="Ade Wijaya"),
    )
    buat_undangan(conn, lap, simpan(conn, lap), hari_ini=HARI_H)
    nama = [b.nama for b in daftar_kirim(conn, hari_ini=HARI_H)]
    assert nama == ["Ade Wijaya", "Zulkarnain"]


def test_daftar_kirim_kosong(conn: sqlite3.Connection) -> None:
    assert daftar_kirim(conn, hari_ini=HARI_H) == ()


def test_daftar_kirim_menandai_keraguan(conn: sqlite3.Connection) -> None:
    """Akun yang patut diragukan tetap dibuatkan link, tapi ditandai."""
    lap = laporan(transaksi(no_id="JC1093", pasien="Dr. Muhlis Yusuf"),
                  kode_cabang="31281")
    buat_undangan(conn, lap, simpan(conn, lap), hari_ini=HARI_H)
    (baris,) = daftar_kirim(conn, hari_ini=HARI_H)
    assert baris.keraguan
    assert "gelar dokter" in baris.keraguan[0]


def test_sisa_hari_mengikuti_hari_ini(conn: sqlite3.Connection) -> None:
    lap = laporan(transaksi())
    buat_undangan(conn, lap, simpan(conn, lap), hari_ini=HARI_H)
    (baris,) = daftar_kirim(conn, hari_ini=HARI_H + dt.timedelta(days=25))
    assert baris.sisa_hari(HARI_H + dt.timedelta(days=25)) == 5
