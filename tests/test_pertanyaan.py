"""Uji pemuatan pertanyaan dari berkas konfigurasi (F10)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from joderma_survey import db
from joderma_survey.pertanyaan import (
    BERKAS_BAWAAN,
    KonfigurasiTidakValid,
    bandingkan,
    muat_berkas,
    terapkan,
)

BERKAS_NYATA = Path(__file__).resolve().parent.parent / "config" / "pertanyaan.toml"

MINIMAL = """
[[pertanyaan]]
set = "RJ"
kode = "keseluruhan"
teks = "Bagaimana kunjungan Anda?"
jenis = "skala_1_5"
wajib = true
"""


@pytest.fixture
def conn() -> sqlite3.Connection:
    sambungan = db.buka(":memory:")
    db.migrasi(sambungan)
    yield sambungan
    sambungan.close()


def tulis(tmp_path: Path, isi: str) -> Path:
    path = tmp_path / "pertanyaan.toml"
    path.write_text(isi, encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# Berkas sungguhan harus cocok dengan yang ter-seed
# --------------------------------------------------------------------------


def test_berkas_proyek_cocok_dengan_basis_data(conn: sqlite3.Connection) -> None:
    """config/pertanyaan.toml harus sama persis dengan seed migrasi.

    Kalau tidak, menjalankan perintah pertanyaan akan membuat revisi baru
    tanpa ada yang benar-benar berubah.
    """
    rencana = bandingkan(conn, muat_berkas(BERKAS_NYATA))
    assert not rencana.ada_perubahan, rencana.ringkas()
    assert len(rencana.tetap) == 9


def test_berkas_bawaan_menunjuk_berkas_proyek() -> None:
    assert BERKAS_BAWAAN == Path("config/pertanyaan.toml")


def test_berkas_proyek_sah() -> None:
    daftar = muat_berkas(BERKAS_NYATA)
    assert len(daftar) == 9
    assert [p.urutan for p in daftar] == list(range(1, 10))
    assert sum(1 for p in daftar if p.wajib) == 1


# --------------------------------------------------------------------------
# Pembacaan dan pemeriksaan
# --------------------------------------------------------------------------


def test_urutan_mengikuti_berkas(tmp_path: Path) -> None:
    isi = MINIMAL + """
[[pertanyaan]]
set = "RJ"
kode = "kedua"
teks = "Pertanyaan kedua"
jenis = "teks"
"""
    daftar = muat_berkas(tulis(tmp_path, isi))
    assert [(p.kode, p.urutan) for p in daftar] == [("keseluruhan", 1), ("kedua", 2)]


def test_urutan_terpisah_per_set(tmp_path: Path) -> None:
    isi = MINIMAL + """
[[pertanyaan]]
set = "OTC"
kode = "otc_keseluruhan"
teks = "Bagaimana pembelian Anda?"
jenis = "skala_1_5"
wajib = true
"""
    daftar = muat_berkas(tulis(tmp_path, isi))
    assert [(p.set_pertanyaan, p.urutan) for p in daftar] == [("RJ", 1), ("OTC", 1)]


def test_berkas_tidak_ada(tmp_path: Path) -> None:
    with pytest.raises(KonfigurasiTidakValid, match="tidak ada"):
        muat_berkas(tmp_path / "hantu.toml")


def test_toml_rusak(tmp_path: Path) -> None:
    with pytest.raises(KonfigurasiTidakValid, match="bukan TOML"):
        muat_berkas(tulis(tmp_path, "[[pertanyaan\nkode ="))


def test_berkas_kosong(tmp_path: Path) -> None:
    with pytest.raises(KonfigurasiTidakValid, match="minimal satu blok"):
        muat_berkas(tulis(tmp_path, "# kosong saja\n"))


@pytest.mark.parametrize(
    ("isi", "pesan"),
    [
        ('[[pertanyaan]]\nset="RJ"\nkode="a"\nteks="T"\njenis="bintang"\nwajib=true\n',
         "jenis"),
        ('[[pertanyaan]]\nset="RJ"\nkode="a"\nteks="T"\njenis="teks"\nperan="admin"\nwajib=true\n',
         "peran"),
        ('[[pertanyaan]]\nset="RJ"\nkode="a"\nteks="T"\njenis="skala_1_5"\nwajib=true\ntampil_bila="kapan_saja"\n',
         "tampil_bila"),
        ('[[pertanyaan]]\nset="RJ"\nkode="a"\njenis="teks"\nwajib=true\n', "teks"),
        ('[[pertanyaan]]\nset="RJ"\nteks="T"\njenis="teks"\nwajib=true\n', "kode"),
        ('[[pertanyaan]]\nkode="a"\nteks="T"\njenis="teks"\nwajib=true\n', "set"),
        ('[[pertanyaan]]\nset="RJ"\nkode="a"\nteks="T"\njenis="teks"\nwajib="ya"\n',
         "true/false"),
        ('[[pertanyaan]]\nset="RJ"\nkode="a"\nteks="T"\njenis="teks"\nwajib=true\nwarna="merah"\n',
         "tidak dikenal"),
    ],
)
def test_isi_tidak_sah_ditolak(tmp_path: Path, isi: str, pesan: str) -> None:
    with pytest.raises(KonfigurasiTidakValid, match=pesan):
        muat_berkas(tulis(tmp_path, isi))


def test_kode_berulang_ditolak(tmp_path: Path) -> None:
    isi = MINIMAL + """
[[pertanyaan]]
set = "RJ"
kode = "keseluruhan"
teks = "Pertanyaan lain dengan kode sama"
jenis = "teks"
"""
    with pytest.raises(KonfigurasiTidakValid, match="berulang"):
        muat_berkas(tulis(tmp_path, isi))


def test_tanpa_pertanyaan_wajib_ditolak(tmp_path: Path) -> None:
    isi = '[[pertanyaan]]\nset="RJ"\nkode="a"\nteks="T"\njenis="teks"\n'
    with pytest.raises(KonfigurasiTidakValid, match="minimal satu pertanyaan harus wajib"):
        muat_berkas(tulis(tmp_path, isi))


def test_dua_pertanyaan_izin_ditolak(tmp_path: Path) -> None:
    isi = MINIMAL + """
[[pertanyaan]]
set = "RJ"
kode = "izin1"
teks = "Boleh dihubungi?"
jenis = "ya_tidak"
peran = "izin_kontak"

[[pertanyaan]]
set = "RJ"
kode = "izin2"
teks = "Boleh dihubungi lagi?"
jenis = "ya_tidak"
peran = "izin_kontak"
"""
    with pytest.raises(KonfigurasiTidakValid, match="satu pertanyaan izin_kontak"):
        muat_berkas(tulis(tmp_path, isi))


def test_izin_harus_ya_tidak(tmp_path: Path) -> None:
    isi = MINIMAL + """
[[pertanyaan]]
set = "RJ"
kode = "izin"
teks = "Boleh dihubungi?"
jenis = "teks"
peran = "izin_kontak"
"""
    with pytest.raises(KonfigurasiTidakValid, match="harus berjenis ya_tidak"):
        muat_berkas(tulis(tmp_path, isi))


def test_bersyarat_tanpa_skala_ditolak(tmp_path: Path) -> None:
    isi = """
[[pertanyaan]]
set = "RJ"
kode = "a"
teks = "Teks bebas"
jenis = "teks"
wajib = true

[[pertanyaan]]
set = "RJ"
kode = "lanjut"
teks = "Ceritakan"
jenis = "teks"
tampil_bila = "ada_nilai_rendah"
"""
    with pytest.raises(KonfigurasiTidakValid, match="tidak ada pertanyaan skala"):
        muat_berkas(tulis(tmp_path, isi))


# --------------------------------------------------------------------------
# Membandingkan dan menerapkan
# --------------------------------------------------------------------------


def test_uji_kering_tidak_mengubah(conn: sqlite3.Connection, tmp_path: Path) -> None:
    sebelum = conn.execute("SELECT COUNT(*) n FROM pertanyaan").fetchone()["n"]
    bandingkan(conn, muat_berkas(tulis(tmp_path, MINIMAL)))
    assert conn.execute("SELECT COUNT(*) n FROM pertanyaan").fetchone()["n"] == sebelum


def test_perubahan_teks_membuat_revisi_baru(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    isi = BERKAS_NYATA.read_text().replace(
        "Bagaimana penilaian Anda terhadap waktu tunggu sebelum dilayani?",
        "Bagaimana penilaian Anda terhadap lamanya menunggu?",
    )
    rencana = terapkan(conn, muat_berkas(tulis(tmp_path, isi)))
    assert rencana.berubah == [("waktu_tunggu", 2, True)]
    baris = conn.execute(
        "SELECT revisi, aktif, mengubah_makna FROM pertanyaan"
        " WHERE kode='waktu_tunggu' ORDER BY revisi"
    ).fetchall()
    assert [(b["revisi"], b["aktif"], b["mengubah_makna"]) for b in baris] == [
        (1, 0, 0), (2, 1, 1),
    ]


def test_perubahan_makna_adalah_bawaan(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    """Arah aman: laporan memotong rangkaian, bukan diam-diam menyambung."""
    isi = BERKAS_NYATA.read_text().replace("waktu tunggu sebelum dilayani",
                                           "waktu tunggu sebelum dilayani petugas")
    rencana = bandingkan(conn, muat_berkas(tulis(tmp_path, isi)))
    (_, _, makna) = rencana.berubah[0]
    assert makna is True


def test_ditandai_ejaan_tidak_memotong_rangkaian(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    isi = BERKAS_NYATA.read_text().replace("waktu tunggu sebelum dilayani",
                                           "waktu tunggu sebelum dilayani")
    isi = isi.replace("Bagaimana penilaian Anda terhadap waktu tunggu sebelum dilayani?",
                      "Bagaimana penilaian Anda terhadap waktu tunggu sebelum dilayani ?")
    terapkan(conn, muat_berkas(tulis(tmp_path, isi)), ejaan=["waktu_tunggu"])
    baris = conn.execute(
        "SELECT mengubah_makna FROM pertanyaan WHERE kode='waktu_tunggu' AND revisi=2"
    ).fetchone()
    assert baris["mengubah_makna"] == 0


def test_ejaan_untuk_kode_asing_ditolak(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    with pytest.raises(KonfigurasiTidakValid, match="tidak ada di berkas"):
        terapkan(conn, muat_berkas(tulis(tmp_path, MINIMAL)), ejaan=["tidak_ada"])


def test_pertanyaan_dihapus_dari_berkas_dinonaktifkan(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    rencana = terapkan(conn, muat_berkas(tulis(tmp_path, MINIMAL)))
    assert "perbaikan" in rencana.dinonaktifkan
    assert conn.execute(
        "SELECT aktif FROM pertanyaan WHERE kode='perbaikan'"
    ).fetchone()["aktif"] == 0


def test_dinonaktifkan_tidak_menghapus_jawaban(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    pid = conn.execute(
        "SELECT id FROM pertanyaan WHERE kode='perbaikan'"
    ).fetchone()["id"]
    conn.execute(
        "INSERT INTO unggahan (nama_berkas, cabang_kode, periode_awal,"
        " periode_akhir, diunggah_pada, baris_data, baris_dipakai, pasien_unik,"
        " ringkasan) VALUES ('x','30376','2026-09-01','2026-09-30','2026-10-11',"
        " 1,1,1,'{}')"
    )
    conn.execute(
        "INSERT INTO sesi_jawaban (id, diisi_pada, set_pertanyaan, cabang_kode,"
        " layanan, dokter, unggahan_id, selesai) VALUES ('s1','2026-10-11','RJ',"
        " '30376','RJ','dr',1,1)"
    )
    conn.execute(
        "INSERT INTO jawaban (sesi_id, pertanyaan_id, nilai_teks)"
        " VALUES ('s1', ?, 'Parkir sempit')",
        (pid,),
    )
    terapkan(conn, muat_berkas(tulis(tmp_path, MINIMAL)))
    assert conn.execute(
        "SELECT nilai_teks v FROM jawaban WHERE pertanyaan_id = ?", (pid,)
    ).fetchone()["v"] == "Parkir sempit"


def test_pertanyaan_baru_mulai_revisi_satu(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    isi = BERKAS_NYATA.read_text() + """
[[pertanyaan]]
set = "RJ"
kode = "kemudahan_janji"
teks = "Bagaimana penilaian Anda terhadap kemudahan membuat janji?"
jenis = "skala_1_5"
"""
    rencana = terapkan(conn, muat_berkas(tulis(tmp_path, isi)))
    assert rencana.baru == ["kemudahan_janji"]
    baris = conn.execute(
        "SELECT revisi, mengubah_makna FROM pertanyaan WHERE kode='kemudahan_janji'"
    ).fetchone()
    assert baris["revisi"] == 1
    assert baris["mengubah_makna"] == 0


def test_menerapkan_dua_kali_tidak_membuat_revisi_palsu(
    conn: sqlite3.Connection,
) -> None:
    daftar = muat_berkas(BERKAS_NYATA)
    terapkan(conn, daftar)
    sebelum = conn.execute("SELECT COUNT(*) n FROM pertanyaan").fetchone()["n"]
    rencana = terapkan(conn, daftar)
    assert not rencana.ada_perubahan
    assert conn.execute("SELECT COUNT(*) n FROM pertanyaan").fetchone()["n"] == sebelum


def test_gagal_di_tengah_tidak_meninggalkan_separuh(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    daftar = muat_berkas(tulis(tmp_path, MINIMAL))
    sebelum = conn.execute(
        "SELECT COUNT(*) n FROM pertanyaan WHERE aktif=1"
    ).fetchone()["n"]
    conn.execute("CREATE TRIGGER gagal BEFORE INSERT ON pertanyaan"
                 " BEGIN SELECT RAISE(ABORT, 'uji'); END")
    with pytest.raises(sqlite3.Error):
        terapkan(conn, daftar)
    conn.execute("DROP TRIGGER gagal")
    assert conn.execute(
        "SELECT COUNT(*) n FROM pertanyaan WHERE aktif=1"
    ).fetchone()["n"] == sebelum


def test_ringkas_terbaca(conn: sqlite3.Connection, tmp_path: Path) -> None:
    rencana = bandingkan(conn, muat_berkas(tulis(tmp_path, MINIMAL)))
    teks = rencana.ringkas()
    assert "REVISI" in teks or "NONAKTIF" in teks
    assert "jawaban lama tetap tersimpan" in teks
