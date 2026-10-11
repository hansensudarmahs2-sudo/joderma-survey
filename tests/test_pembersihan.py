"""Uji pembersihan data kotor laporan Omnicare.

Semua kasus nyata diambil dari laporan contoh September 2026 dan diberi
nomor barisnya, supaya bisa dilacak kembali ke sumbernya.
"""

from __future__ import annotations

import pytest

from joderma_survey.cabang import ATURAN_RM, aturan_untuk_rm, cabang_dari_kode
from joderma_survey.pembersihan import (
    StatusRM,
    curiga_bukan_pasien,
    normalisasi_nama,
    normalisasi_rm,
)

# --------------------------------------------------------------------------
# Tahap 1: spasi dan huruf -- selalu aman
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("masuk", "harap"),
    [
        ("J07536 ", "J07536"),   # Jemur baris 295, 690
        ("J08018 ", "J08018"),   # baris 350, 492
        ("J08041 ", "J08041"),   # baris 456, 457, 655
        ("JC0972 ", "JC0972"),   # Citraland baris 42
        ("JC0661 ", "JC0661"),   # baris 282
        ("jc0308", "JC0308"),    # baris 214
        ("Jc1070", "JC1070"),    # baris 300
        ("  J00143  ", "J00143"),
        ("J 07536", "J07536"),   # spasi di tengah pun dirapikan
        ("\tJC0987\n", "JC0987"),
    ],
)
def test_spasi_dan_huruf_dirapikan(masuk: str, harap: str) -> None:
    hasil = normalisasi_rm(masuk)
    assert hasil.rm == harap
    assert hasil.status is StatusRM.BAKU
    assert hasil.asli == masuk, "isi sel asli harus tersimpan untuk jejak audit"


@pytest.mark.parametrize("rm", ["J00001", "J08146", "J00143", "JC0027", "JC1099"])
def test_rm_sudah_baku_tidak_diubah(rm: str) -> None:
    hasil = normalisasi_rm(rm)
    assert hasil.rm == rm
    assert hasil.status is StatusRM.BAKU
    assert not hasil.perlu_ditinjau
    assert hasil.bisa_dipakai


# --------------------------------------------------------------------------
# Tahap 3: lebar angka
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("masuk", "harap"),
    [
        ("J0635", "J00635"),        # Jemur baris 116, 182, 309
        ("J7958", "J07958"),        # baris 153
        ("J001062", "J01062"),      # baris 372, 494
        ("J00000002", "J00002"),    # baris 551, 612, 734
        ("J5772", "J05772"),        # Citraland baris 248, 292
    ],
)
def test_lebar_angka_dinormalisasi_kasus_nyata(masuk: str, harap: str) -> None:
    """Kelima RM menyimpang yang benar-benar ada di laporan September 2026."""
    hasil = normalisasi_rm(masuk)
    assert hasil.rm == harap
    assert hasil.status is StatusRM.DINORMALISASI
    assert hasil.perlu_ditinjau, "harus muncul di ringkasan unggahan"
    assert masuk in hasil.catatan and harap in hasil.catatan


@pytest.mark.parametrize(
    ("masuk", "harap"),
    [
        ("J1", "J00001"), ("J01", "J00001"), ("J001", "J00001"),
        ("J0001", "J00001"), ("J00001", "J00001"), ("J000001", "J00001"),
        ("JC1", "JC0001"), ("JC01", "JC0001"), ("JC0001", "JC0001"),
        ("JC00001", "JC0001"),
    ],
)
def test_nol_di_depan_hanya_kosmetik(masuk: str, harap: str) -> None:
    """Nilai angkanya identitas; banyaknya nol di depan tidak bermakna."""
    assert normalisasi_rm(masuk).rm == harap


def test_bentuk_berbeda_nilai_sama_jadi_satu_rm() -> None:
    """Inilah alasan normalisasi dilakukan: satu pasien tidak boleh terhitung dua."""
    bentuk = ["J0635", "J00635", "J000635", "j0635 ", " J00635"]
    assert len({normalisasi_rm(b).rm for b in bentuk}) == 1


def test_nilai_berbeda_tetap_terpisah() -> None:
    """Normalisasi tidak boleh menggabungkan nomor yang nilainya memang beda."""
    assert normalisasi_rm("J00635").rm != normalisasi_rm("J06350").rm
    assert normalisasi_rm("J01062").rm != normalisasi_rm("J10620").rm
    assert normalisasi_rm("JC0108").rm != normalisasi_rm("JC1080").rm


# --------------------------------------------------------------------------
# Awalan JC harus diperiksa sebelum J
# --------------------------------------------------------------------------


def test_awalan_jc_tidak_tertukar_dengan_j() -> None:
    hasil = normalisasi_rm("JC0308")
    assert hasil.rm == "JC0308", "JC harus dikenali utuh, bukan J + 'C0308'"
    assert len(hasil.rm) == 6


def test_urutan_aturan_awalan_terpanjang_dulu() -> None:
    awalan = [a.awalan for a in ATURAN_RM]
    assert awalan.index("JC") < awalan.index("J")


def test_aturan_per_awalan_bukan_per_berkas() -> None:
    """RM berawalan J di berkas Citraland tetap pakai aturan Jemur (5 angka)."""
    aturan = aturan_untuk_rm("J05772")
    assert aturan is not None
    assert aturan.lebar_angka == 5
    assert aturan.kode_cabang == "30376"


# --------------------------------------------------------------------------
# Baris anonim
# --------------------------------------------------------------------------


@pytest.mark.parametrize("masuk", ["-", "", "  ", "--", "N/A", "n/a", " - "])
def test_baris_anonim_tidak_bisa_dipakai(masuk: str) -> None:
    hasil = normalisasi_rm(masuk)
    assert hasil.status is StatusRM.TANPA_RM
    assert hasil.rm is None
    assert not hasil.bisa_dipakai


def test_baris_anonim_tidak_perlu_ditinjau() -> None:
    """9 baris OTC anonim di Jemur itu normal, bukan masalah data."""
    assert not normalisasi_rm("-").perlu_ditinjau


# --------------------------------------------------------------------------
# Pola tidak dikenal
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "masuk",
    [
        "X1234",        # awalan asing
        "JD0001",       # cabang baru yang belum didaftarkan
        "J",            # tanpa angka
        "JC",
        "ABC",
        "12345",        # tanpa awalan
        "J-0635",
        "J0635A",
        "J00000",       # bernilai nol
        "JC0000",
        "J999999",      # melebihi J + 5 angka
        "JC99999",      # melebihi JC + 4 angka
    ],
)
def test_pola_tidak_dikenal_ditolak_dan_dilaporkan(masuk: str) -> None:
    hasil = normalisasi_rm(masuk)
    assert hasil.status is StatusRM.TIDAK_DIKENAL
    assert hasil.rm is None
    assert not hasil.bisa_dipakai
    assert hasil.perlu_ditinjau, "harus muncul di ringkasan supaya tidak hilang diam-diam"
    assert hasil.catatan


@pytest.mark.parametrize("nilai", [None, 635, 635.0, [], {}, True])
def test_nilai_bukan_teks_ditolak(nilai: object) -> None:
    hasil = normalisasi_rm(nilai)
    assert hasil.status is StatusRM.TIDAK_DIKENAL
    assert hasil.rm is None


def test_batas_format_tepat() -> None:
    assert normalisasi_rm("J99999").rm == "J99999"
    assert normalisasi_rm("J100000").status is StatusRM.TIDAK_DIKENAL
    assert normalisasi_rm("JC9999").rm == "JC9999"
    assert normalisasi_rm("JC10000").status is StatusRM.TIDAK_DIKENAL


# --------------------------------------------------------------------------
# Peringatan jangkauan
# --------------------------------------------------------------------------


def test_rm_tertinggi_nyata_tidak_memicu_peringatan() -> None:
    """J08146 dan JC1099 adalah nilai tertinggi di laporan September."""
    assert normalisasi_rm("J08146").peringatan == ()
    assert normalisasi_rm("JC1099").peringatan == ()


def test_rm_di_atas_perkiraan_memicu_peringatan_tapi_tetap_dipakai() -> None:
    hasil = normalisasi_rm("J09999")
    assert hasil.rm == "J09999", "peringatan tidak boleh membuang pasien"
    assert hasil.status is StatusRM.BAKU
    assert hasil.peringatan
    assert hasil.perlu_ditinjau
    assert "8200" in hasil.peringatan[0]


def test_citraland_di_atas_perkiraan() -> None:
    hasil = normalisasi_rm("JC5000")
    assert hasil.rm == "JC5000"
    assert hasil.peringatan


# --------------------------------------------------------------------------
# Nama pasien
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("masuk", "harap"),
    [
        ("  Ade   Wijaya ", "Ade Wijaya"),
        ("Ade Wijaya", "Ade Wijaya"),
        ("BUDI SANTOSO", "Budi Santoso"),          # huruf besar semua dirapikan
        ("Muhammad Faeyza Danish Zulkarnain", "Muhammad Faeyza Danish Zulkarnain"),
        ("Dr.berliana Kurniawati", "Dr.berliana Kurniawati"),  # tidak diubah
        ("Bagus Sutoko S.pd", "Bagus Sutoko S.pd"),
        ("", ""),
        ("   ", ""),
    ],
)
def test_normalisasi_nama(masuk: str, harap: str) -> None:
    assert normalisasi_nama(masuk) == harap


@pytest.mark.parametrize("nilai", [None, 123, []])
def test_nama_bukan_teks_jadi_kosong(nilai: object) -> None:
    assert normalisasi_nama(nilai) == ""


def test_nama_campuran_tidak_diubah_besar_kecilnya() -> None:
    """Hanya nama yang SELURUHNYA huruf besar yang dirapikan."""
    assert normalisasi_nama("Jap Inge Paat") == "Jap Inge Paat"
    assert normalisasi_nama("Enny Ls") == "Enny Ls"


# --------------------------------------------------------------------------
# Peringatan 'bukan pasien perorangan'
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "nama",
    [
        "Klinik Utama Dryn Dipo",   # Jemur baris 551, 612, 734
        "Apotek Sehat",
        "PT Maju Jaya",
        "CV Sumber Waras",
        "RS Darmo",
        "Toko Obat Bahagia",
        "Lab Prodia",
    ],
)
def test_nama_lembaga_memicu_peringatan(nama: str) -> None:
    assert curiga_bukan_pasien(nama)


@pytest.mark.parametrize(
    "nama",
    [
        "Dr. Catherina Jessica",            # Citraland baris 108
        "Dr. Muhlis Yusuf",                 # baris 1093
        "Dr.berliana Kurniawati Nur Huda",  # baris 193
        "Dr Hansen",                        # Jemur
        "Dr Elina Indriani",
        "drg. Surya",
        "Prof. Bambang",
    ],
)
def test_gelar_dokter_memicu_peringatan(nama: str) -> None:
    assert curiga_bukan_pasien(nama)


@pytest.mark.parametrize(
    "nama",
    [
        "Bagus Sutoko S.pd",      # "Sutoko" memuat "toko" -- jangan tertangkap
        "Sutoko Wijaya",
        "Ade Wijaya",
        "Tatik Mindari",
        "Made Priandini",
        "Cornellya Angeline",
        "Andri Pratama",          # memuat "dr" di tengah kata
        "Hendra Setiawan",
        "Laboratorius Tandi",     # bukan kata "lab" utuh
        "Ptari Nugroho",          # bukan kata "pt" utuh
    ],
)
def test_nama_pasien_biasa_tidak_memicu_peringatan_palsu(nama: str) -> None:
    assert curiga_bukan_pasien(nama) == (), f"peringatan palsu untuk {nama!r}"


def test_nama_kosong_memicu_peringatan() -> None:
    """9 baris OTC anonim di Jemur bernama kosong."""
    assert curiga_bukan_pasien("")
    assert curiga_bukan_pasien("   ")


def test_peringatan_menyebutkan_alasannya() -> None:
    (alasan,) = curiga_bukan_pasien("Klinik Utama Dryn Dipo")
    assert "Klinik" in alasan


# --------------------------------------------------------------------------
# Cabang
# --------------------------------------------------------------------------


def test_cabang_dari_kode() -> None:
    assert cabang_dari_kode("30376").nama == "Jemur Andayani"
    assert cabang_dari_kode("31281").nama == "Citraland"
    assert cabang_dari_kode(" 30376 ").nama == "Jemur Andayani"


def test_kode_cabang_tak_dikenal_ditolak() -> None:
    with pytest.raises(KeyError, match="tidak dikenal"):
        cabang_dari_kode("99999")
