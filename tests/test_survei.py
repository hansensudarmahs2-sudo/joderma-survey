"""Uji isi survei: token, pertanyaan, dan penyimpanan jawaban.

Penekanan khusus pada pemisahan identitas dari jawaban (keputusan 4.1).
"""

from __future__ import annotations

import datetime as dt
import sqlite3

import pytest
from bantu import laporan, transaksi

from joderma_survey import db
from joderma_survey.daftar_kirim import buat_undangan
from joderma_survey.survei import (
    AMBANG_NILAI_RENDAH,
    JawabanTidakValid,
    StatusLink,
    catat_dibuka,
    periksa_token,
    perlu_tampil,
    pertanyaan_untuk,
    simpan_jawaban,
)

HARI_H = dt.date(2026, 10, 11)

LENGKAP = {
    "keseluruhan": "5", "penjelasan_dokter": "4", "waktu_tunggu": "3",
    "sikap_staf": "5", "kenyamanan": "4", "kejelasan_biaya": "5",
    "perbaikan": "Tempat parkir kurang luas.", "izin_kontak": "tidak",
}


@pytest.fixture
def conn() -> sqlite3.Connection:
    sambungan = db.buka(":memory:")
    db.migrasi(sambungan)
    yield sambungan
    sambungan.close()


@pytest.fixture
def token(conn: sqlite3.Connection) -> str:
    lap = laporan(transaksi(no_id="J00143", pasien="Tatik Mindari",
                            dokter="dr. Yohanes Widjaja Sp.DVE"))
    uid = db.simpan_laporan(conn, lap, diunggah_pada=HARI_H).unggahan_id
    buat_undangan(conn, lap, uid, hari_ini=HARI_H)
    return conn.execute("SELECT token FROM undangan").fetchone()["token"]


def undangan_dari(conn: sqlite3.Connection, token: str) -> object:
    status, undangan = periksa_token(conn, token, HARI_H)
    assert status is StatusLink.SIAP
    return undangan


# --------------------------------------------------------------------------
# Keadaan link (F8)
# --------------------------------------------------------------------------


def test_token_sah_siap_dipakai(conn: sqlite3.Connection, token: str) -> None:
    status, undangan = periksa_token(conn, token, HARI_H)
    assert status is StatusLink.SIAP
    assert undangan is not None
    assert undangan.nama == "Tatik Mindari"
    assert undangan.set_pertanyaan == "RJ"


@pytest.mark.parametrize("buruk", ["", "   ", "tidak-ada", "x" * 50, None])
def test_token_tidak_dikenal(conn: sqlite3.Connection, buruk: object) -> None:
    status, undangan = periksa_token(conn, buruk, HARI_H)  # type: ignore[arg-type]
    assert status is StatusLink.TIDAK_DIKENAL
    assert undangan is None


def test_link_kedaluwarsa_tepat_hari_ke_30(
    conn: sqlite3.Connection, token: str
) -> None:
    assert periksa_token(conn, token, HARI_H + dt.timedelta(days=29))[0] is StatusLink.SIAP
    assert (
        periksa_token(conn, token, HARI_H + dt.timedelta(days=30))[0]
        is StatusLink.KEDALUWARSA
    )


def test_link_sekali_pakai(conn: sqlite3.Connection, token: str) -> None:
    simpan_jawaban(conn, undangan_dari(conn, token), LENGKAP, hari_ini=HARI_H)
    assert periksa_token(conn, token, HARI_H)[0] is StatusLink.SUDAH_DIISI


def test_link_dibatalkan(conn: sqlite3.Connection, token: str) -> None:
    db.batalkan_undangan(conn, token, pada=HARI_H)
    assert periksa_token(conn, token, HARI_H)[0] is StatusLink.DIBATALKAN


def test_sudah_diisi_menang_atas_kedaluwarsa(
    conn: sqlite3.Connection, token: str
) -> None:
    """Pesan 'sudah terisi' lebih berguna bagi pasien daripada 'kedaluwarsa'."""
    simpan_jawaban(conn, undangan_dari(conn, token), LENGKAP, hari_ini=HARI_H)
    jauh = HARI_H + dt.timedelta(days=200)
    assert periksa_token(conn, token, jauh)[0] is StatusLink.SUDAH_DIISI


# --------------------------------------------------------------------------
# Pencatatan pembukaan link
# --------------------------------------------------------------------------


def test_catat_dibuka_hanya_sekali(conn: sqlite3.Connection, token: str) -> None:
    assert catat_dibuka(conn, token, HARI_H)
    assert not catat_dibuka(conn, token, HARI_H + dt.timedelta(days=1))
    baris = conn.execute("SELECT dibuka_pada FROM undangan").fetchone()
    assert baris["dibuka_pada"] == "2026-10-11", "pembukaan pertama yang dicatat"


def test_dibuka_memisahkan_tidak_sampai_dari_tidak_diisi(
    conn: sqlite3.Connection, token: str
) -> None:
    belum = conn.execute(
        "SELECT COUNT(*) n FROM undangan WHERE dibuka_pada IS NULL"
    ).fetchone()["n"]
    assert belum == 1
    catat_dibuka(conn, token, HARI_H)
    dibuka = conn.execute(
        "SELECT COUNT(*) n FROM undangan WHERE dibuka_pada IS NOT NULL"
        " AND diisi_pada IS NULL"
    ).fetchone()["n"]
    assert dibuka == 1, "dibuka tapi belum diisi"


# --------------------------------------------------------------------------
# Pertanyaan
# --------------------------------------------------------------------------


def test_pertanyaan_set_rj(conn: sqlite3.Connection) -> None:
    daftar = pertanyaan_untuk(conn, "RJ")
    assert [p.kode for p in daftar] == [
        "keseluruhan", "penjelasan_dokter", "waktu_tunggu", "sikap_staf",
        "kenyamanan", "kejelasan_biaya", "keluhan_lanjutan", "perbaikan",
        "izin_kontak",
    ]
    assert sum(1 for p in daftar if p.wajib) == 1
    assert sum(1 for p in daftar if p.skala) == 6


def test_hanya_revisi_aktif_diambil(conn: sqlite3.Connection) -> None:
    conn.execute("UPDATE pertanyaan SET aktif=0 WHERE kode='waktu_tunggu'")
    conn.execute(
        "INSERT INTO pertanyaan (kode, revisi, set_pertanyaan, teks, jenis,"
        " urutan, wajib, peran, tampil_bila, mengubah_makna, aktif, dibuat_pada)"
        " VALUES ('waktu_tunggu',2,'RJ','Teks baru','skala_1_5',3,0,'biasa',"
        " NULL,1,1,'2026-11-01')"
    )
    daftar = pertanyaan_untuk(conn, "RJ")
    (tanya,) = [p for p in daftar if p.kode == "waktu_tunggu"]
    assert tanya.revisi == 2
    assert tanya.teks == "Teks baru"


def test_set_tidak_dikenal_kosong(conn: sqlite3.Connection) -> None:
    assert pertanyaan_untuk(conn, "OTC") == ()


# --------------------------------------------------------------------------
# Pertanyaan bersyarat
# --------------------------------------------------------------------------


def test_perlu_tampil_tanpa_syarat(conn: sqlite3.Connection) -> None:
    (biasa,) = [p for p in pertanyaan_untuk(conn, "RJ") if p.kode == "perbaikan"]
    assert perlu_tampil(biasa, {})
    assert perlu_tampil(biasa, {"keseluruhan": 5})


@pytest.mark.parametrize(
    ("nilai", "harap"),
    [({}, False), ({"keseluruhan": 5}, False), ({"keseluruhan": 3}, False),
     ({"keseluruhan": 2}, True), ({"keseluruhan": 1}, True),
     ({"keseluruhan": 5, "waktu_tunggu": 2}, True)],
)
def test_pertanyaan_lanjutan_muncul_saat_nilai_rendah(
    conn: sqlite3.Connection, nilai: dict[str, int], harap: bool
) -> None:
    (lanjut,) = [
        p for p in pertanyaan_untuk(conn, "RJ") if p.kode == "keluhan_lanjutan"
    ]
    assert lanjut.bersyarat
    assert perlu_tampil(lanjut, nilai) is harap


def test_ambang_sesuai_metodologi() -> None:
    assert AMBANG_NILAI_RENDAH == 2


def test_jawaban_lanjutan_diabaikan_bila_tak_ada_nilai_rendah(
    conn: sqlite3.Connection, token: str
) -> None:
    """Peramban bisa saja mengirim kolom tersembunyi; isinya diabaikan."""
    kiriman = dict(LENGKAP, keluhan_lanjutan="tidak seharusnya tersimpan")
    sesi = simpan_jawaban(conn, undangan_dari(conn, token), kiriman, hari_ini=HARI_H)
    kode = _kode_jawaban(conn, sesi)
    assert "keluhan_lanjutan" not in kode


def test_jawaban_lanjutan_tersimpan_saat_ada_nilai_rendah(
    conn: sqlite3.Connection, token: str
) -> None:
    kiriman = dict(LENGKAP, waktu_tunggu="1",
                   keluhan_lanjutan="Menunggu dua jam tanpa kabar.")
    sesi = simpan_jawaban(conn, undangan_dari(conn, token), kiriman, hari_ini=HARI_H)
    assert "keluhan_lanjutan" in _kode_jawaban(conn, sesi)


def _kode_jawaban(conn: sqlite3.Connection, sesi: str) -> dict[str, object]:
    return {
        b["kode"]: b["nilai_angka"] if b["nilai_angka"] is not None else b["nilai_teks"]
        for b in conn.execute(
            "SELECT p.kode, j.nilai_angka, j.nilai_teks FROM jawaban j"
            " JOIN pertanyaan p ON p.id = j.pertanyaan_id WHERE j.sesi_id = ?",
            (sesi,),
        )
    }


# --------------------------------------------------------------------------
# Penyimpanan jawaban
# --------------------------------------------------------------------------


def test_simpan_jawaban_lengkap(conn: sqlite3.Connection, token: str) -> None:
    sesi = simpan_jawaban(conn, undangan_dari(conn, token), LENGKAP, hari_ini=HARI_H)
    isi = _kode_jawaban(conn, sesi)
    assert isi["keseluruhan"] == 5
    assert isi["waktu_tunggu"] == 3
    assert isi["perbaikan"] == "Tempat parkir kurang luas."
    assert isi["izin_kontak"] == 0


def test_undangan_ditandai_terisi(conn: sqlite3.Connection, token: str) -> None:
    simpan_jawaban(conn, undangan_dari(conn, token), LENGKAP, hari_ini=HARI_H)
    baris = conn.execute("SELECT diisi_pada FROM undangan").fetchone()
    assert baris["diisi_pada"] == "2026-10-11"


def test_tanggal_saja_tanpa_jam(conn: sqlite3.Connection, token: str) -> None:
    """Jam akan mempermudah mencocokkan jawaban dengan orang (gap G11)."""
    simpan_jawaban(conn, undangan_dari(conn, token), LENGKAP, hari_ini=HARI_H)
    for tabel, kolom in (("undangan", "diisi_pada"), ("sesi_jawaban", "diisi_pada")):
        nilai = conn.execute(f"SELECT {kolom} v FROM {tabel}").fetchone()["v"]
        assert len(nilai) == 10 and ":" not in nilai, f"{tabel}.{kolom} = {nilai!r}"


def test_hanya_pertanyaan_terjawab_tersimpan(
    conn: sqlite3.Connection, token: str
) -> None:
    sesi = simpan_jawaban(
        conn, undangan_dari(conn, token), {"keseluruhan": "4"}, hari_ini=HARI_H
    )
    assert set(_kode_jawaban(conn, sesi)) == {"keseluruhan"}


def test_pertanyaan_wajib_kosong_ditolak(
    conn: sqlite3.Connection, token: str
) -> None:
    with pytest.raises(JawabanTidakValid, match="wajib"):
        simpan_jawaban(conn, undangan_dari(conn, token), {"penjelasan_dokter": "4"},
                       hari_ini=HARI_H)


def test_penolakan_tidak_menandai_terisi(
    conn: sqlite3.Connection, token: str
) -> None:
    """Pasien harus masih bisa mengulang setelah kiriman ditolak."""
    with pytest.raises(JawabanTidakValid):
        simpan_jawaban(conn, undangan_dari(conn, token), {}, hari_ini=HARI_H)
    assert periksa_token(conn, token, HARI_H)[0] is StatusLink.SIAP
    assert conn.execute("SELECT COUNT(*) n FROM sesi_jawaban").fetchone()["n"] == 0


@pytest.mark.parametrize("buruk", ["0", "6", "-1", "abc", "3.5", "99"])
def test_nilai_skala_di_luar_jangkauan_ditolak(
    conn: sqlite3.Connection, token: str, buruk: str
) -> None:
    with pytest.raises(JawabanTidakValid):
        simpan_jawaban(conn, undangan_dari(conn, token), {"keseluruhan": buruk},
                       hari_ini=HARI_H)


def test_teks_terlalu_panjang_ditolak(
    conn: sqlite3.Connection, token: str
) -> None:
    kiriman = dict(LENGKAP, perbaikan="x" * 2001)
    with pytest.raises(JawabanTidakValid, match="melebihi"):
        simpan_jawaban(conn, undangan_dari(conn, token), kiriman, hari_ini=HARI_H)


def test_link_terpakai_tidak_bisa_diisi_dua_kali(
    conn: sqlite3.Connection, token: str
) -> None:
    undangan = undangan_dari(conn, token)
    simpan_jawaban(conn, undangan, LENGKAP, hari_ini=HARI_H)
    with pytest.raises(JawabanTidakValid, match="sudah terpakai"):
        simpan_jawaban(conn, undangan, LENGKAP, hari_ini=HARI_H)
    assert conn.execute("SELECT COUNT(*) n FROM sesi_jawaban").fetchone()["n"] == 1


def test_durasi_tersimpan(conn: sqlite3.Connection, token: str) -> None:
    simpan_jawaban(conn, undangan_dari(conn, token), LENGKAP, hari_ini=HARI_H,
                   durasi_detik=73)
    assert conn.execute(
        "SELECT durasi_detik v FROM sesi_jawaban"
    ).fetchone()["v"] == 73


# --------------------------------------------------------------------------
# Pemisahan identitas dari jawaban -- bagian terpenting (keputusan 4.1)
# --------------------------------------------------------------------------


def test_sesi_jawaban_tidak_menyimpan_identitas(
    conn: sqlite3.Connection, token: str
) -> None:
    simpan_jawaban(conn, undangan_dari(conn, token), LENGKAP, hari_ini=HARI_H)
    kolom = {
        b["name"] for b in conn.execute("PRAGMA table_info(sesi_jawaban)")
    }
    assert "rm" not in kolom
    assert "undangan_id" not in kolom
    assert "token" not in kolom
    assert "nama" not in kolom


def test_tanpa_izin_tidak_ada_jembatan_ke_pasien(
    conn: sqlite3.Connection, token: str
) -> None:
    simpan_jawaban(conn, undangan_dari(conn, token), LENGKAP, hari_ini=HARI_H)
    assert conn.execute("SELECT COUNT(*) n FROM izin_kontak").fetchone()["n"] == 0


def test_dengan_izin_jembatan_dibuat(conn: sqlite3.Connection, token: str) -> None:
    kiriman = dict(LENGKAP, izin_kontak="ya")
    sesi = simpan_jawaban(conn, undangan_dari(conn, token), kiriman, hari_ini=HARI_H)
    baris = conn.execute("SELECT sesi_id, rm FROM izin_kontak").fetchone()
    assert baris["sesi_id"] == sesi
    assert baris["rm"] == "J00143"


def test_jawaban_izin_juga_tersimpan_sebagai_jawaban(
    conn: sqlite3.Connection, token: str
) -> None:
    """Supaya tingkat pemberian izin bisa dihitung dari sisi analisis."""
    sesi = simpan_jawaban(conn, undangan_dari(conn, token),
                          dict(LENGKAP, izin_kontak="ya"), hari_ini=HARI_H)
    assert _kode_jawaban(conn, sesi)["izin_kontak"] == 1


@pytest.mark.parametrize("jawab", ["tidak", "", None])
def test_izin_selain_ya_tidak_membuat_jembatan(
    conn: sqlite3.Connection, token: str, jawab: str | None
) -> None:
    kiriman = dict(LENGKAP)
    if jawab is None:
        kiriman.pop("izin_kontak")
    else:
        kiriman["izin_kontak"] = jawab
    simpan_jawaban(conn, undangan_dari(conn, token), kiriman, hari_ini=HARI_H)
    assert conn.execute("SELECT COUNT(*) n FROM izin_kontak").fetchone()["n"] == 0


def test_izin_nilai_tak_dikenal_ditolak(
    conn: sqlite3.Connection, token: str
) -> None:
    kiriman = dict(LENGKAP, izin_kontak="mungkin")
    with pytest.raises(JawabanTidakValid, match="ya atau tidak"):
        simpan_jawaban(conn, undangan_dari(conn, token), kiriman, hari_ini=HARI_H)


def test_sifat_kunjungan_disalin_untuk_analisis(
    conn: sqlite3.Connection, token: str
) -> None:
    """Cabang, layanan, dan dokter diperlukan pembobotan dan skor per dokter."""
    simpan_jawaban(conn, undangan_dari(conn, token), LENGKAP, hari_ini=HARI_H)
    baris = conn.execute(
        "SELECT cabang_kode, layanan, dokter, set_pertanyaan FROM sesi_jawaban"
    ).fetchone()
    assert baris["cabang_kode"] == "30376"
    assert baris["layanan"] == "RJ"
    assert baris["dokter"] == "dr. Yohanes Widjaja Sp.DVE"
    assert baris["set_pertanyaan"] == "RJ"


def test_id_sesi_acak_bukan_berurutan(conn: sqlite3.Connection) -> None:
    lap = laporan(
        transaksi(no_id="J00143", faktur=26090001.0),
        transaksi(no_id="J00813", faktur=26090002.0),
    )
    uid = db.simpan_laporan(conn, lap, diunggah_pada=HARI_H).unggahan_id
    buat_undangan(conn, lap, uid, hari_ini=HARI_H)
    sesi = []
    for b in conn.execute("SELECT token FROM undangan"):
        status, undangan = periksa_token(conn, b["token"], HARI_H)
        assert status is StatusLink.SIAP
        sesi.append(simpan_jawaban(conn, undangan, LENGKAP, hari_ini=HARI_H))
    assert len(set(sesi)) == 2
    assert all(len(s) >= 16 and not s.isdigit() for s in sesi)


def test_jawaban_tidak_bisa_ditelusuri_balik_tanpa_izin(
    conn: sqlite3.Connection, token: str
) -> None:
    """Uji menyeluruh: dari sesi jawaban, tidak ada jalan ke nomor RM."""
    sesi = simpan_jawaban(conn, undangan_dari(conn, token), LENGKAP, hari_ini=HARI_H)
    lewat_izin = conn.execute(
        "SELECT rm FROM izin_kontak WHERE sesi_id = ?", (sesi,)
    ).fetchone()
    assert lewat_izin is None
    isi_sesi = dict(
        conn.execute("SELECT * FROM sesi_jawaban WHERE id = ?", (sesi,)).fetchone()
    )
    assert not any("J00143" == str(v) for v in isi_sesi.values())
