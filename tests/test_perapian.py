"""Uji perapian data dan ekspor (F11, F12)."""

from __future__ import annotations

import csv
import datetime as dt
import json
import sqlite3
from pathlib import Path

import pytest
from bantu import laporan, transaksi

from joderma_survey import db
from joderma_survey.daftar_kirim import buat_undangan
from joderma_survey.ekspor import ekspor, kode_dokter
from joderma_survey.perapian import Periode, rapikan, saring_teks, sel_dari
from joderma_survey.survei import StatusLink, periksa_token, simpan_jawaban

HARI_H = dt.date(2026, 10, 11)
PERIODE = Periode(dt.date(2026, 10, 1), dt.date(2026, 10, 31))

JAWAB = {
    "keseluruhan": "5", "penjelasan_dokter": "4", "waktu_tunggu": "4",
    "sikap_staf": "5", "kenyamanan": "4", "kejelasan_biaya": "4",
    "perbaikan": "Parkir kurang luas.", "izin_kontak": "tidak",
}


@pytest.fixture
def conn() -> sqlite3.Connection:
    sambungan = db.buka(":memory:")
    db.migrasi(sambungan)
    yield sambungan
    sambungan.close()


def siapkan(
    conn: sqlite3.Connection, jumlah: int = 6, kode_cabang: str = "30376",
    layanan: str = "RJ", dokter: str = "dr. Yohanes Widjaja Sp.DVE",
) -> list[str]:
    """Buat `jumlah` pasien beserta undangannya, kembalikan tokennya."""
    awalan = "J0" if kode_cabang == "30376" else "JC"
    lebar = 4 if kode_cabang == "30376" else 2
    baris = [
        transaksi(no_id=f"{awalan}{i:0{lebar}d}", faktur=26100000.0 + i,
                  pasien=f"Pasien {i}", layanan=layanan, dokter=dokter,
                  tanggal="05/10/2026", waktu="05/10/2026 10:00:00")
        for i in range(1, jumlah + 1)
    ]
    lap = laporan(*baris, kode_cabang=kode_cabang,
                  judul="TRANSAKSI PENJUALAN PER 01 OKTOBER 2026 S/D 31 OKTOBER 2026")
    uid = db.simpan_laporan(conn, lap, diunggah_pada=HARI_H).unggahan_id
    buat_undangan(conn, lap, uid, hari_ini=HARI_H)
    return [
        b["token"]
        for b in conn.execute(
            "SELECT token FROM undangan WHERE cabang_kode = ? AND diisi_pada IS NULL",
            (kode_cabang,),
        )
    ]


def isi(conn: sqlite3.Connection, token: str, **ubah: str) -> None:
    status, undangan = periksa_token(conn, token, HARI_H)
    assert status is StatusLink.SIAP and undangan is not None
    simpan_jawaban(conn, undangan, dict(JAWAB, **ubah), hari_ini=HARI_H)


# --------------------------------------------------------------------------
# Penyaringan teks bebas (gap G16)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("masuk", "label"),
    [
        ("Hubungi 081234567890", "TELEPON"),
        ("WA saya +62 812 3456 7890", "TELEPON"),
        ("email saya budi@contoh.co.id", "SUREL"),
        ("nomor RM saya J00635", "NOMOR_RM"),
        ("RM JC1093 ya", "NOMOR_RM"),
        ("NIK 3578011234567890", "ANGKA_PANJANG"),
    ],
)
def test_keterangan_pengenal_disensor(masuk: str, label: str) -> None:
    bersih, disensor = saring_teks(masuk)
    assert label in disensor
    assert f"[{label}]" in bersih


def test_teks_biasa_tidak_diubah() -> None:
    teks = "Pelayanan ramah, tapi ruang tunggu panas."
    assert saring_teks(teks) == (teks, ())


def test_nama_lengkap_pasien_disensor() -> None:
    bersih, disensor = saring_teks(
        "Saya Tatik Mindari ingin menyampaikan keluhan", ["Tatik Mindari"]
    )
    assert "NAMA" in disensor
    assert "Tatik Mindari" not in bersih


def test_nama_satu_kata_tidak_disensor() -> None:
    """Banyak nama depan Indonesia juga kata biasa; menyensornya merusak makna."""
    bersih, disensor = saring_teks("Pelayanan Wati sangat ramah", ["Wati"])
    assert disensor == ()
    assert bersih == "Pelayanan Wati sangat ramah"


def test_saring_teks_kosong() -> None:
    assert saring_teks("") == ("", ())
    assert saring_teks("   ") == ("", ())
    assert saring_teks(None) == ("", ())  # type: ignore[arg-type]


def test_beberapa_jenis_sekaligus() -> None:
    bersih, disensor = saring_teks("RM J00635 telepon 081234567890")
    assert set(disensor) == {"NOMOR_RM", "TELEPON"}
    assert "J00635" not in bersih and "081234567890" not in bersih


# --------------------------------------------------------------------------
# Perapian
# --------------------------------------------------------------------------


def test_sel_dari() -> None:
    assert sel_dari("30376", "RJ") == "30376/RJ"
    assert sel_dari("31281", "") == "31281/-"


def test_hitungan_pengiriman(conn: sqlite3.Connection) -> None:
    token = siapkan(conn, 6)
    isi(conn, token[0])
    isi(conn, token[1])
    r = rapikan(conn, periode=PERIODE)
    assert r.undangan == 6
    assert r.terisi == 2
    assert r.dibuka == 0, "membuka dicatat halaman survei, bukan di sini"


def test_tingkat_pengisian_punya_selang(conn: sqlite3.Connection) -> None:
    token = siapkan(conn, 10)
    for t in token[:4]:
        isi(conn, t)
    r = rapikan(conn, periode=PERIODE)
    assert r.tingkat_pengisian is not None
    assert r.tingkat_pengisian.nilai == pytest.approx(0.4)
    assert r.tingkat_pengisian.bawah < 0.4 < r.tingkat_pengisian.atas


def test_pembatalan_terhitung(conn: sqlite3.Connection) -> None:
    token = siapkan(conn, 4)
    db.batalkan_undangan(conn, token[0], pada=HARI_H)
    r = rapikan(conn, periode=PERIODE)
    assert r.dibatalkan == 1


def test_ringkasan_per_pertanyaan(conn: sqlite3.Connection) -> None:
    token = siapkan(conn, 12)
    for i, t in enumerate(token):
        isi(conn, t, keseluruhan=str(4 + i % 2))
    r = rapikan(conn, periode=PERIODE)
    (p,) = [x for x in r.pertanyaan if x.kode == "keseluruhan"]
    assert p.dijawab == 12
    assert p.ringkasan is not None
    assert p.ringkasan.rata_rata is not None
    assert p.ringkasan.rata_rata.nilai == pytest.approx(4.5)
    assert p.ringkasan.top2 is not None
    assert p.ringkasan.top2.nilai == pytest.approx(1.0)


def test_pertanyaan_dikosongkan_terhitung(conn: sqlite3.Connection) -> None:
    token = siapkan(conn, 4)
    isi(conn, token[0])
    isi(conn, token[1], perbaikan="")
    r = rapikan(conn, periode=PERIODE)
    (p,) = [x for x in r.pertanyaan if x.kode == "perbaikan"]
    assert p.dijawab == 1
    assert p.dikosongkan == 1
    assert p.tingkat_pengisian_butir == pytest.approx(0.5)


def test_pertanyaan_bersyarat_tidak_dihitung_dikosongkan(
    conn: sqlite3.Connection,
) -> None:
    """Hanya sebagian responden yang ditawari, jadi 'dikosongkan' tak bermakna."""
    token = siapkan(conn, 4)
    isi(conn, token[0])
    isi(conn, token[1], waktu_tunggu="1", keluhan_lanjutan="Lama sekali")
    r = rapikan(conn, periode=PERIODE)
    (p,) = [x for x in r.pertanyaan if x.kode == "keluhan_lanjutan"]
    assert p.dijawab == 1
    assert p.dikosongkan == 0


def test_izin_kontak_terhitung(conn: sqlite3.Connection) -> None:
    token = siapkan(conn, 4)
    isi(conn, token[0], izin_kontak="ya")
    isi(conn, token[1], izin_kontak="tidak")
    r = rapikan(conn, periode=PERIODE)
    assert r.izin_kontak == 1


def test_teks_bebas_terkumpul_dan_disaring(conn: sqlite3.Connection) -> None:
    token = siapkan(conn, 4)
    isi(conn, token[0], perbaikan="Hubungi saya di 081234567890")
    r = rapikan(conn, periode=PERIODE)
    (t,) = [x for x in r.teks_bebas if x["kode"] == "perbaikan"]
    assert "081234567890" not in str(t["teks"])
    assert "TELEPON" in t["disensor"]  # type: ignore[operator]
    assert any("disensor sebagian" in p for p in r.peringatan)


def test_peringatan_jawaban_sedikit(conn: sqlite3.Connection) -> None:
    token = siapkan(conn, 20)
    isi(conn, token[0])
    r = rapikan(conn, periode=PERIODE)
    assert any("terlalu lebar untuk menyimpulkan" in p for p in r.peringatan)


def test_tanpa_jawaban(conn: sqlite3.Connection) -> None:
    siapkan(conn, 5)
    r = rapikan(conn, periode=PERIODE)
    assert r.terisi == 0
    assert any("Belum ada jawaban" in p for p in r.peringatan)


def test_sel_tanpa_responden_diperingatkan(conn: sqlite3.Connection) -> None:
    siapkan(conn, 4, kode_cabang="30376")
    token_c = siapkan(conn, 4, kode_cabang="31281")
    isi(conn, token_c[0])
    r = rapikan(conn, periode=PERIODE)
    assert any("tanpa satu pun responden" in p for p in r.peringatan)


def test_pembobotan_antar_cabang(conn: sqlite3.Connection) -> None:
    token_j = siapkan(conn, 20, kode_cabang="30376")
    token_c = siapkan(conn, 20, kode_cabang="31281")
    for t in token_j[:2]:
        isi(conn, t)
    for t in token_c[:10]:
        isi(conn, t)
    r = rapikan(conn, periode=PERIODE)
    bobot = {s.nama: s.bobot for s in r.sel}
    assert bobot["30376/RJ"] > bobot["31281/RJ"], (
        "Jemur kurang terwakili, jadi bobotnya lebih besar"
    )
    assert r.n_efektif < 12


def test_disaring_per_cabang(conn: sqlite3.Connection) -> None:
    token_j = siapkan(conn, 4, kode_cabang="30376")
    token_c = siapkan(conn, 4, kode_cabang="31281")
    isi(conn, token_j[0])
    isi(conn, token_c[0])
    assert rapikan(conn, periode=PERIODE, cabang_kode="30376").terisi == 1
    assert rapikan(conn, periode=PERIODE).terisi == 2


def test_periode_menyaring(conn: sqlite3.Connection) -> None:
    token = siapkan(conn, 4)
    isi(conn, token[0])
    kosong = Periode(dt.date(2026, 11, 1), dt.date(2026, 11, 30))
    assert rapikan(conn, periode=kosong).terisi == 0


# --------------------------------------------------------------------------
# Ekspor
# --------------------------------------------------------------------------


def test_kode_dokter_tetap() -> None:
    peta = kode_dokter(["dr. Budi", "dr. Ani", "-", "", "dr. Budi"])
    assert peta == {"dr. Ani": "D1", "dr. Budi": "D2"}


def test_ekspor_menulis_berkas(conn: sqlite3.Connection, tmp_path: Path) -> None:
    token = siapkan(conn, 6)
    for t in token[:3]:
        isi(conn, t)
    hasil = ekspor(conn, tmp_path, periode=PERIODE)
    nama = {b.name for b in hasil.berkas}
    assert nama == {"konteks.md", "jawaban.csv", "teks.csv", "ringkasan.json"}
    assert all(b.exists() for b in hasil.berkas)
    assert hasil.jumlah_jawaban == 18, "3 responden x 6 pertanyaan skala"


def test_ekspor_tanpa_identitas_pasien(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    """Syarat inti: tidak ada nama pasien atau nomor RM di berkas mana pun."""
    token = siapkan(conn, 4)
    isi(conn, token[0])
    hasil = ekspor(conn, tmp_path, periode=PERIODE)
    rm = [b["rm"] for b in conn.execute("SELECT rm FROM pasien")]
    nama = [b["nama_terakhir"] for b in conn.execute("SELECT nama_terakhir FROM pasien")]
    for berkas in hasil.berkas:
        isi_berkas = berkas.read_text(encoding="utf-8")
        for r in rm:
            assert r not in isi_berkas, f"{r} bocor di {berkas.name}"
        for n in nama:
            assert n not in isi_berkas, f"{n} bocor di {berkas.name}"


def test_ekspor_nama_dokter_diganti_kode(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    token = siapkan(conn, 4, dokter="dr. Yohanes Widjaja Sp.DVE")
    isi(conn, token[0])
    hasil = ekspor(conn, tmp_path, periode=PERIODE)
    jawaban = (tmp_path / "jawaban.csv").read_text(encoding="utf-8")
    assert "Yohanes" not in jawaban
    assert "D1" in jawaban
    assert not (tmp_path / "dokter.csv").exists()


def test_ekspor_pemetaan_dokter_bila_diminta(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    token = siapkan(conn, 4)
    isi(conn, token[0])
    ekspor(conn, tmp_path, periode=PERIODE, sertakan_dokter=True)
    baris = list(csv.DictReader((tmp_path / "dokter.csv").open(encoding="utf-8")))
    assert baris[0]["kode"] == "D1"
    assert "Yohanes" in baris[0]["nama"]


def test_ringkasan_json_lengkap(conn: sqlite3.Connection, tmp_path: Path) -> None:
    token = siapkan(conn, 20)
    for t in token[:12]:
        isi(conn, t)
    ekspor(conn, tmp_path, periode=PERIODE)
    d = json.loads((tmp_path / "ringkasan.json").read_text(encoding="utf-8"))
    assert d["pengiriman"]["undangan"] == 20
    assert d["pengiriman"]["terisi"] == 12
    assert d["pengiriman"]["tingkat_pengisian"]["nilai"] == pytest.approx(0.6)
    assert d["ukuran_efektif_sampel"] > 0
    assert d["sel"][0]["populasi"] == 20
    p = [x for x in d["pertanyaan"] if x["kode"] == "keseluruhan"][0]
    assert p["rata_rata"]["bawah"] <= p["rata_rata"]["nilai"] <= p["rata_rata"]["atas"]
    assert 1.0 <= p["rata_rata"]["bawah"] and p["rata_rata"]["atas"] <= 5.0


def test_konteks_memuat_batas_penafsiran(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    """Berkas konteks harus mencegah Claude agent menyimpulkan berlebihan."""
    token = siapkan(conn, 4)
    isi(conn, token[0])
    ekspor(conn, tmp_path, periode=PERIODE)
    teks = (tmp_path / "konteks.md").read_text(encoding="utf-8")
    for wajib in [
        "nonresponse bias",
        "courtesy bias",
        "tolok ukur industri",
        "tumpang tindih",
        "skor per dokter",
        "pembobotan",
    ]:
        assert wajib in teks, f"konteks tidak menyebut {wajib!r}"


def test_konteks_memuat_peringatan_periode(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    token = siapkan(conn, 20)
    isi(conn, token[0])
    ekspor(conn, tmp_path, periode=PERIODE)
    teks = (tmp_path / "konteks.md").read_text(encoding="utf-8")
    assert "terlalu lebar untuk menyimpulkan" in teks


def test_ekspor_tanpa_jawaban_tetap_jalan(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    siapkan(conn, 4)
    hasil = ekspor(conn, tmp_path, periode=PERIODE)
    assert hasil.jumlah_jawaban == 0
    assert (tmp_path / "konteks.md").exists()


def test_jawaban_csv_berisi_bobot(conn: sqlite3.Connection, tmp_path: Path) -> None:
    token = siapkan(conn, 6)
    for t in token[:3]:
        isi(conn, t)
    ekspor(conn, tmp_path, periode=PERIODE)
    baris = list(csv.DictReader((tmp_path / "jawaban.csv").open(encoding="utf-8")))
    assert baris
    assert all(float(b["bobot"]) > 0 for b in baris)
    assert {b["pertanyaan"] for b in baris} == {
        "keseluruhan", "penjelasan_dokter", "waktu_tunggu",
        "sikap_staf", "kenyamanan", "kejelasan_biaya",
    }


# --------------------------------------------------------------------------
# Perbandingan antar periode
#
# Bagian yang paling menentukan: tingkat skornya sendiri tidak banyak
# berguna, yang bisa ditindaklanjuti adalah perubahannya.
# --------------------------------------------------------------------------


def test_periode_sebelumnya_sepanjang_yang_sekarang() -> None:
    from joderma_survey.perapian import periode_sebelumnya

    okt = Periode(dt.date(2026, 10, 1), dt.date(2026, 10, 31))
    lalu = periode_sebelumnya(okt)
    assert lalu.akhir == dt.date(2026, 9, 30)
    assert (lalu.akhir - lalu.awal).days == (okt.akhir - okt.awal).days


def test_periode_sebelumnya_mingguan() -> None:
    from joderma_survey.perapian import periode_sebelumnya

    lalu = periode_sebelumnya(Periode(dt.date(2026, 10, 8), dt.date(2026, 10, 14)))
    assert lalu == Periode(dt.date(2026, 10, 1), dt.date(2026, 10, 7))


def _dua_periode(
    conn: sqlite3.Connection, nilai_lama: int, nilai_baru: int, jumlah: int = 20
) -> tuple[object, object]:
    from joderma_survey.perapian import rapikan

    token = siapkan(conn, jumlah * 2)
    for t in token[:jumlah]:
        isi(conn, t, keseluruhan=str(nilai_lama))
    conn.execute("UPDATE sesi_jawaban SET diisi_pada = '2026-09-15'")
    for t in token[jumlah:]:
        isi(conn, t, keseluruhan=str(nilai_baru))
    lalu = rapikan(conn, periode=Periode(dt.date(2026, 9, 1), dt.date(2026, 9, 30)))
    kini = rapikan(conn, periode=PERIODE)
    return kini, lalu


def test_perubahan_besar_disebut_nyata(conn: sqlite3.Connection) -> None:
    from joderma_survey.perapian import banding

    kini, lalu = _dua_periode(conn, 2, 5)
    (b,) = [x for x in banding(kini, lalu) if x.kode == "keseluruhan"]
    assert b.nyata
    assert b.arah == "naik"
    assert b.selisih == pytest.approx(3.0)


def test_perubahan_kecil_disebut_derau(conn: sqlite3.Connection) -> None:
    """Inilah yang mencegah rapat membahas kenaikan 0,05 poin."""
    from joderma_survey.perapian import banding

    kini, lalu = _dua_periode(conn, 4, 4)
    (b,) = [x for x in banding(kini, lalu) if x.kode == "keseluruhan"]
    assert not b.nyata
    assert b.arah == "derau"


def test_penurunan_terdeteksi(conn: sqlite3.Connection) -> None:
    from joderma_survey.perapian import banding

    kini, lalu = _dua_periode(conn, 5, 2)
    (b,) = [x for x in banding(kini, lalu) if x.kode == "keseluruhan"]
    assert b.arah == "turun"
    assert b.selisih is not None and b.selisih < 0


def test_tanpa_pembanding(conn: sqlite3.Connection) -> None:
    from joderma_survey.perapian import banding, rapikan

    token = siapkan(conn, 6)
    isi(conn, token[0])
    kini = rapikan(conn, periode=PERIODE)
    (b,) = [x for x in banding(kini, None) if x.kode == "keseluruhan"]
    assert b.arah == "baru"
    assert b.selisih is None
    assert not b.nyata


def test_banding_hanya_pertanyaan_skala(conn: sqlite3.Connection) -> None:
    from joderma_survey.perapian import banding

    kini, lalu = _dua_periode(conn, 4, 5)
    kode = {b.kode for b in banding(kini, lalu)}
    assert "perbaikan" not in kode and "izin_kontak" not in kode
    assert len(kode) == 6
