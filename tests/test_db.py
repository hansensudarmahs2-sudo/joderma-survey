"""Uji basis data: skema, migrasi, penyimpanan, dan riwayat undangan."""

from __future__ import annotations

import datetime as dt
import json
import sqlite3

import pytest
from bantu import laporan, transaksi

from joderma_survey import db
from joderma_survey.aturan import boleh_dikirim
from joderma_survey.skema import MIGRASI, VERSI_TERBARU

HARI_H = dt.date(2026, 10, 11)


@pytest.fixture
def conn() -> sqlite3.Connection:
    sambungan = db.buka(":memory:")
    db.migrasi(sambungan)
    yield sambungan
    sambungan.close()


@pytest.fixture
def unggahan_id(conn: sqlite3.Connection) -> int:
    hasil = db.simpan_laporan(conn, laporan(transaksi()), diunggah_pada=HARI_H)
    return hasil.unggahan_id


# --------------------------------------------------------------------------
# Migrasi
# --------------------------------------------------------------------------


def test_migrasi_dari_kosong() -> None:
    c = db.buka(":memory:")
    assert db.versi_skema(c) == 0
    diterapkan = db.migrasi(c)
    assert diterapkan == [versi for versi, _ in MIGRASI]
    assert db.versi_skema(c) == VERSI_TERBARU


def test_migrasi_aman_dipanggil_berulang(conn: sqlite3.Connection) -> None:
    assert db.migrasi(conn) == []
    assert db.migrasi(conn) == []
    assert db.versi_skema(conn) == VERSI_TERBARU


def test_semua_tabel_ada(conn: sqlite3.Connection) -> None:
    nama = {
        b["name"]
        for b in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {
        "pasien", "unggahan", "transaksi", "undangan", "pertanyaan",
        "sesi_jawaban", "jawaban", "izin_kontak", "pengguna", "skema_versi",
    } <= nama


def test_foreign_key_ditegakkan(conn: sqlite3.Connection) -> None:
    """SQLite mematikan foreign key secara bawaan; buka() harus menyalakannya."""
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO transaksi (unggahan_id, cabang_kode, no_faktur, rm,"
            " tanggal, layanan, dokter, harga) VALUES (999,'30376',1,'J00001',"
            " '2026-09-01','RJ','dr',0.0)"
        )


def test_tabel_strict_menolak_tipe_salah(conn: sqlite3.Connection) -> None:
    """STRICT menolak nilai yang tidak bisa disimpan di tipe kolomnya.

    Catatan: afinitas kolom tetap berlaku lebih dulu, jadi angka yang masuk
    ke kolom TEXT akan diubah menjadi teks, bukan ditolak. Yang tertangkap
    adalah teks atau pecahan yang masuk ke kolom INTEGER.
    """
    with pytest.raises(sqlite3.IntegrityError, match="INTEGER column"):
        conn.execute(
            "INSERT INTO unggahan (nama_berkas, cabang_kode, periode_awal,"
            " periode_akhir, diunggah_pada, baris_data, baris_dipakai,"
            " pasien_unik, ringkasan) VALUES ('x','30376','2026-09-01',"
            " '2026-09-30','2026-10-11','banyak',0,0,'{}')"
        )


def test_tabel_strict_menolak_pecahan_di_kolom_bulat(
    conn: sqlite3.Connection,
) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="INTEGER column"):
        conn.execute(
            "INSERT INTO unggahan (nama_berkas, cabang_kode, periode_awal,"
            " periode_akhir, diunggah_pada, baris_data, baris_dipakai,"
            " pasien_unik, ringkasan) VALUES ('x','30376','2026-09-01',"
            " '2026-09-30','2026-10-11',1.5,0,0,'{}')"
        )


def test_peran_pengguna_dibatasi(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO pengguna (nama, peran, hash_sandi, dibuat_pada)"
        " VALUES ('hansen','direktur','x','2026-10-11')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO pengguna (nama, peran, hash_sandi, dibuat_pada)"
            " VALUES ('lain','admin','x','2026-10-11')"
        )


def test_tiga_peran_diterima(conn: sqlite3.Connection) -> None:
    """Owner punya login sendiri (keputusan 4.5 tahap 2)."""
    for i, peran in enumerate(("owner", "direktur", "cs")):
        conn.execute(
            "INSERT INTO pengguna (nama, peran, hash_sandi, dibuat_pada)"
            " VALUES (?,?,'x','2026-10-11')",
            (f"pengguna{i}", peran),
        )
    jumlah = conn.execute("SELECT COUNT(*) AS n FROM pengguna").fetchone()["n"]
    assert jumlah == 3


# --------------------------------------------------------------------------
# Pertanyaan Set A
# --------------------------------------------------------------------------


def test_set_a_terisi(conn: sqlite3.Connection) -> None:
    baris = conn.execute(
        "SELECT kode, jenis, urutan, wajib, peran, tampil_bila FROM pertanyaan"
        " WHERE set_pertanyaan='RJ' AND aktif=1 ORDER BY urutan"
    ).fetchall()
    assert [b["kode"] for b in baris] == [
        "keseluruhan", "penjelasan_dokter", "waktu_tunggu", "sikap_staf",
        "kenyamanan", "kejelasan_biaya", "keluhan_lanjutan", "perbaikan",
        "izin_kontak",
    ]


def test_hanya_pertanyaan_pertama_wajib(conn: sqlite3.Connection) -> None:
    """Metodologi bagian 8: hanya pertanyaan 1 yang wajib."""
    wajib = conn.execute(
        "SELECT kode FROM pertanyaan WHERE set_pertanyaan='RJ' AND wajib=1"
    ).fetchall()
    assert [b["kode"] for b in wajib] == ["keseluruhan"]


def test_enam_pertanyaan_skala(conn: sqlite3.Connection) -> None:
    """Kerangka 6+1 (keputusan 4.5)."""
    n = conn.execute(
        "SELECT COUNT(*) AS n FROM pertanyaan WHERE set_pertanyaan='RJ'"
        " AND jenis='skala_1_5'"
    ).fetchone()["n"]
    assert n == 6


def test_pertanyaan_izin_ditandai_perannya(conn: sqlite3.Connection) -> None:
    baris = conn.execute(
        "SELECT kode, jenis, urutan FROM pertanyaan WHERE peran='izin_kontak'"
    ).fetchall()
    assert len(baris) == 1
    assert baris[0]["jenis"] == "ya_tidak"
    assert baris[0]["urutan"] == 9, "pertanyaan izin selalu terakhir"


def test_satu_pertanyaan_bersyarat(conn: sqlite3.Connection) -> None:
    baris = conn.execute(
        "SELECT kode, tampil_bila FROM pertanyaan WHERE tampil_bila IS NOT NULL"
    ).fetchall()
    assert len(baris) == 1
    assert baris[0]["kode"] == "keluhan_lanjutan"
    assert baris[0]["tampil_bila"] == "ada_nilai_rendah"


def test_revisi_pertanyaan_bisa_ditambah(conn: sqlite3.Connection) -> None:
    """Menyunting = menambah revisi, bukan mengubah di tempat (keputusan 2.14)."""
    conn.execute("UPDATE pertanyaan SET aktif=0 WHERE kode='waktu_tunggu'")
    conn.execute(
        "INSERT INTO pertanyaan (kode, revisi, set_pertanyaan, teks, jenis,"
        " urutan, wajib, peran, tampil_bila, mengubah_makna, aktif, dibuat_pada)"
        " VALUES ('waktu_tunggu', 2, 'RJ', 'Teks baru', 'skala_1_5', 3, 0,"
        " 'biasa', NULL, 1, 1, '2026-11-01')"
    )
    baris = conn.execute(
        "SELECT revisi, aktif, mengubah_makna FROM pertanyaan"
        " WHERE kode='waktu_tunggu' ORDER BY revisi"
    ).fetchall()
    assert [(b["revisi"], b["aktif"], b["mengubah_makna"]) for b in baris] == [
        (1, 0, 0), (2, 1, 1),
    ]


def test_revisi_ganda_ditolak(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO pertanyaan (kode, revisi, set_pertanyaan, teks, jenis,"
            " urutan, wajib, peran, tampil_bila, mengubah_makna, aktif,"
            " dibuat_pada) VALUES ('keseluruhan', 1, 'RJ', 'x', 'teks', 1, 0,"
            " 'biasa', NULL, 0, 1, '2026-11-01')"
        )


def test_jenis_pertanyaan_dibatasi(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO pertanyaan (kode, revisi, set_pertanyaan, teks, jenis,"
            " urutan, wajib, peran, tampil_bila, mengubah_makna, aktif,"
            " dibuat_pada) VALUES ('baru', 1, 'RJ', 'x', 'skala_1_10', 10, 0,"
            " 'biasa', NULL, 0, 1, '2026-11-01')"
        )


# --------------------------------------------------------------------------
# Menyimpan laporan
# --------------------------------------------------------------------------


def test_simpan_laporan_dasar(conn: sqlite3.Connection) -> None:
    lap = laporan(
        transaksi(no_id="J00143", pasien="Tatik Mindari"),
        transaksi(faktur=26090002.0, no_id="J00813", pasien="Meisia Diana"),
    )
    hasil = db.simpan_laporan(conn, lap, diunggah_pada=HARI_H)
    assert hasil.transaksi_baru == 2
    assert hasil.transaksi_sudah_ada == 0
    assert hasil.pasien_baru == 2
    assert not hasil.unggahan_ulang
    assert conn.execute("SELECT COUNT(*) AS n FROM pasien").fetchone()["n"] == 2
    assert conn.execute("SELECT COUNT(*) AS n FROM transaksi").fetchone()["n"] == 2


def test_unggah_ulang_tidak_menggandakan(conn: sqlite3.Connection) -> None:
    lap = laporan(transaksi(), transaksi(faktur=26090002.0, no_id="J00813"))
    db.simpan_laporan(conn, lap, diunggah_pada=HARI_H)
    ulang = db.simpan_laporan(conn, lap, diunggah_pada=HARI_H)
    assert ulang.transaksi_baru == 0
    assert ulang.transaksi_sudah_ada == 2
    assert ulang.unggahan_ulang
    assert conn.execute("SELECT COUNT(*) AS n FROM transaksi").fetchone()["n"] == 2


def test_faktur_sama_beda_cabang_boleh(conn: sqlite3.Connection) -> None:
    """341 nomor faktur dipakai di kedua cabang pada periode yang sama."""
    db.simpan_laporan(conn, laporan(transaksi(faktur=26090001.0), kode_cabang="30376"),
                      diunggah_pada=HARI_H)
    db.simpan_laporan(conn, laporan(transaksi(faktur=26090001.0, no_id="JC0308"),
                                    kode_cabang="31281"), diunggah_pada=HARI_H)
    assert conn.execute("SELECT COUNT(*) AS n FROM transaksi").fetchone()["n"] == 2


def test_pasien_diperbarui_bukan_diganda(conn: sqlite3.Connection) -> None:
    db.simpan_laporan(conn, laporan(transaksi(tanggal="05/09/2026",
                                              waktu="05/09/2026 10:00:00")),
                      diunggah_pada=HARI_H)
    hasil = db.simpan_laporan(
        conn,
        laporan(transaksi(faktur=26090500.0, tanggal="20/09/2026",
                          waktu="20/09/2026 10:00:00")),
        diunggah_pada=HARI_H,
    )
    assert hasil.pasien_baru == 0
    assert hasil.pasien_diperbarui == 1
    baris = conn.execute("SELECT * FROM pasien").fetchone()
    assert baris["pertama_terlihat"] == "2026-09-05"
    assert baris["terakhir_terlihat"] == "2026-09-20"


def test_awalan_rm_disimpan(conn: sqlite3.Connection) -> None:
    db.simpan_laporan(conn, laporan(transaksi(no_id="JC0308"), kode_cabang="31281"),
                      diunggah_pada=HARI_H)
    assert conn.execute("SELECT awalan FROM pasien").fetchone()["awalan"] == "JC"


def test_rm_dinormalisasi_tersimpan_dalam_bentuk_baku(conn: sqlite3.Connection) -> None:
    db.simpan_laporan(conn, laporan(transaksi(no_id="J0635", pasien="Ade Wijaya")),
                      diunggah_pada=HARI_H)
    assert conn.execute("SELECT rm FROM pasien").fetchone()["rm"] == "J00635"


def test_ringkasan_tersimpan_sebagai_json(conn: sqlite3.Connection) -> None:
    lap = laporan(transaksi(), transaksi(faktur=26090002.0, no_id="-", pasien=""))
    db.simpan_laporan(conn, lap, diunggah_pada=HARI_H)
    baris = conn.execute("SELECT ringkasan FROM unggahan").fetchone()
    isi = json.loads(baris["ringkasan"])
    assert isi["dilewati"]["baris anonim tanpa nomor RM"] == 1
    assert isi["baris_catatan_kaki"] == 2
    assert isi["layanan"]["RJ"] >= 1


def test_keraguan_tersimpan(conn: sqlite3.Connection) -> None:
    lap = laporan(transaksi(no_id="J00000002", pasien="Klinik Utama Dryn Dipo",
                            layanan="OTC", dokter="-"))
    db.simpan_laporan(conn, lap, diunggah_pada=HARI_H)
    isi = json.loads(conn.execute("SELECT ringkasan FROM unggahan").fetchone()["ringkasan"])
    assert isi["keraguan"][0]["rm"] == "J00002"
    assert isi["keraguan"][0]["alasan"]


def test_gagal_simpan_tidak_meninggalkan_separuh(conn: sqlite3.Connection) -> None:
    """Satu unggahan harus masuk utuh atau tidak sama sekali."""
    lap = laporan(transaksi())
    conn.execute("DROP TABLE transaksi")
    with pytest.raises(sqlite3.Error):
        db.simpan_laporan(conn, lap, diunggah_pada=HARI_H)
    assert conn.execute("SELECT COUNT(*) AS n FROM unggahan").fetchone()["n"] == 0
    assert conn.execute("SELECT COUNT(*) AS n FROM pasien").fetchone()["n"] == 0


# --------------------------------------------------------------------------
# Token
# --------------------------------------------------------------------------


def test_token_acak_dan_cukup_panjang() -> None:
    token = {db.buat_token() for _ in range(500)}
    assert len(token) == 500, "token tidak boleh berulang"
    assert all(len(t) >= 16 for t in token)


def test_token_tidak_berurutan() -> None:
    a, b = db.buat_token(), db.buat_token()
    assert a != b
    assert not a.isdigit() and not b.isdigit()


def test_token_unik_di_basis_data(conn: sqlite3.Connection, unggahan_id: int) -> None:
    db.catat_undangan(conn, rm="J00143", cabang_kode="30376", no_faktur=1,
                      unggahan_id=unggahan_id, token="sama", dibuat_pada=HARI_H)
    with pytest.raises(sqlite3.IntegrityError):
        db.catat_undangan(conn, rm="J00143", cabang_kode="30376", no_faktur=2,
                          unggahan_id=unggahan_id, token="sama", dibuat_pada=HARI_H)


# --------------------------------------------------------------------------
# Undangan dan riwayat
# --------------------------------------------------------------------------


def test_catat_undangan_mengisi_kedaluwarsa(
    conn: sqlite3.Connection, unggahan_id: int
) -> None:
    token = db.catat_undangan(conn, rm="J00143", cabang_kode="30376",
                              no_faktur=26090001, unggahan_id=unggahan_id,
                              dibuat_pada=HARI_H)
    baris = conn.execute(
        "SELECT * FROM undangan WHERE token = ?", (token,)
    ).fetchone()
    assert baris["dibuat_pada"] == "2026-10-11"
    assert baris["kedaluwarsa_pada"] == "2026-11-10"
    assert baris["diisi_pada"] is None
    assert baris["set_pertanyaan"] == "RJ"


def test_riwayat_kosong_untuk_pasien_baru(conn: sqlite3.Connection) -> None:
    assert db.riwayat(conn, "J00143") == ()


def test_riwayat_terbaca(conn: sqlite3.Connection, unggahan_id: int) -> None:
    db.catat_undangan(conn, rm="J00143", cabang_kode="30376", no_faktur=1,
                      unggahan_id=unggahan_id,
                      dibuat_pada=HARI_H - dt.timedelta(days=40))
    db.catat_undangan(conn, rm="J00143", cabang_kode="30376", no_faktur=2,
                      unggahan_id=unggahan_id,
                      dibuat_pada=HARI_H - dt.timedelta(days=5))
    riwayat = db.riwayat(conn, "J00143")
    assert len(riwayat) == 2
    assert riwayat[0].dibuat_pada < riwayat[1].dibuat_pada


def test_riwayat_gabungan_lintas_cabang(
    conn: sqlite3.Connection, unggahan_id: int
) -> None:
    """Keputusan 2.5: jeda berlaku gabungan, tidak disaring per cabang."""
    db.catat_undangan(conn, rm="J00143", cabang_kode="30376", no_faktur=1,
                      unggahan_id=unggahan_id, dibuat_pada=HARI_H)
    db.catat_undangan(conn, rm="J00143", cabang_kode="31281", no_faktur=2,
                      unggahan_id=unggahan_id, dibuat_pada=HARI_H)
    assert len(db.riwayat(conn, "J00143")) == 2


def test_riwayat_banyak(conn: sqlite3.Connection, unggahan_id: int) -> None:
    for rm in ("J00143", "J00813"):
        conn.execute(
            "INSERT OR IGNORE INTO pasien (rm, nama_terakhir, awalan,"
            " pertama_terlihat, terakhir_terlihat) VALUES (?,?,?,?,?)",
            (rm, "Nama", "J", "2026-09-01", "2026-09-01"),
        )
    db.catat_undangan(conn, rm="J00143", cabang_kode="30376", no_faktur=1,
                      unggahan_id=unggahan_id, dibuat_pada=HARI_H)
    hasil = db.riwayat_banyak(conn, ["J00143", "J00813", "J00143"])
    assert len(hasil["J00143"]) == 1
    assert hasil["J00813"] == ()
    assert set(hasil) == {"J00143", "J00813"}


def test_riwayat_banyak_kosong(conn: sqlite3.Connection) -> None:
    assert db.riwayat_banyak(conn, []) == {}


def test_batalkan_undangan(conn: sqlite3.Connection, unggahan_id: int) -> None:
    token = db.catat_undangan(conn, rm="J00143", cabang_kode="30376", no_faktur=1,
                              unggahan_id=unggahan_id, dibuat_pada=HARI_H)
    assert db.batalkan_undangan(conn, token, pada=HARI_H)
    assert not db.batalkan_undangan(conn, token, pada=HARI_H), "tidak dua kali"
    riwayat = db.riwayat(conn, "J00143")
    assert riwayat[0].dibatalkan_pada == HARI_H


def test_batalkan_undangan_yang_sudah_diisi_gagal(
    conn: sqlite3.Connection, unggahan_id: int
) -> None:
    token = db.catat_undangan(conn, rm="J00143", cabang_kode="30376", no_faktur=1,
                              unggahan_id=unggahan_id, dibuat_pada=HARI_H)
    conn.execute("UPDATE undangan SET diisi_pada='2026-10-12' WHERE token=?", (token,))
    assert not db.batalkan_undangan(conn, token, pada=HARI_H)


def test_batalkan_token_tidak_ada(conn: sqlite3.Connection) -> None:
    assert not db.batalkan_undangan(conn, "tidak-ada", pada=HARI_H)


# --------------------------------------------------------------------------
# Aturan jeda di atas basis data sungguhan
# --------------------------------------------------------------------------


def test_aturan_jeda_berjalan_di_atas_basis_data(
    conn: sqlite3.Connection, unggahan_id: int
) -> None:
    assert boleh_dikirim(db.riwayat(conn, "J00143"), HARI_H).boleh

    db.catat_undangan(conn, rm="J00143", cabang_kode="30376", no_faktur=1,
                      unggahan_id=unggahan_id, dibuat_pada=HARI_H)
    assert not boleh_dikirim(db.riwayat(conn, "J00143"), HARI_H).boleh
    assert not boleh_dikirim(
        db.riwayat(conn, "J00143"), HARI_H + dt.timedelta(days=29)
    ).boleh
    assert boleh_dikirim(
        db.riwayat(conn, "J00143"), HARI_H + dt.timedelta(days=30)
    ).boleh


def test_pengisian_memblokir_setahun_di_atas_basis_data(
    conn: sqlite3.Connection, unggahan_id: int
) -> None:
    token = db.catat_undangan(conn, rm="J00143", cabang_kode="30376", no_faktur=1,
                              unggahan_id=unggahan_id, dibuat_pada=HARI_H)
    conn.execute("UPDATE undangan SET diisi_pada=? WHERE token=?",
                 ("2026-10-13", token))
    riwayat = db.riwayat(conn, "J00143")
    diisi = dt.date(2026, 10, 13)
    assert not boleh_dikirim(riwayat, diisi + dt.timedelta(days=364)).boleh
    assert boleh_dikirim(riwayat, diisi + dt.timedelta(days=365)).boleh


def test_pembatalan_membuka_kembali_di_atas_basis_data(
    conn: sqlite3.Connection, unggahan_id: int
) -> None:
    token = db.catat_undangan(conn, rm="J00143", cabang_kode="30376", no_faktur=1,
                              unggahan_id=unggahan_id, dibuat_pada=HARI_H)
    assert not boleh_dikirim(db.riwayat(conn, "J00143"), HARI_H).boleh
    db.batalkan_undangan(conn, token, pada=HARI_H)
    assert boleh_dikirim(db.riwayat(conn, "J00143"), HARI_H).boleh
