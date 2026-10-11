"""Uji modul tanggal.

Penekanan khusus pada varian nama bulan (Oktober/October/Okt/Oct), karena
masalah serupa pernah menyebabkan bug di modul finance.
"""

from __future__ import annotations

import datetime as dt

import pytest

from joderma_survey.tanggal import (
    NAMA_BULAN_ID,
    TanggalTidakDikenal,
    _ALIAS_BULAN,
    _VARIAN,
    bulan_ke_angka,
    dalam_periode,
    dari_iso,
    format_periode_id,
    ke_iso,
    kunci_urut,
    nama_bulan_id,
    parse_periode_laporan,
    parse_tanggal,
    parse_waktu,
    tanggal_mungkin_terbalik,
)

# --------------------------------------------------------------------------
# Nama bulan: seluruh varian
# --------------------------------------------------------------------------

SEMUA_VARIAN = [(v, angka) for angka, varian in _VARIAN for v in varian]


@pytest.mark.parametrize(("teks", "harap"), SEMUA_VARIAN)
def test_setiap_varian_bulan_terbaca(teks: str, harap: int) -> None:
    assert bulan_ke_angka(teks) == harap


@pytest.mark.parametrize(("teks", "harap"), SEMUA_VARIAN)
def test_varian_bulan_tidak_peduli_huruf_besar_kecil(teks: str, harap: int) -> None:
    assert bulan_ke_angka(teks.upper()) == harap
    assert bulan_ke_angka(teks.capitalize()) == harap
    assert bulan_ke_angka(f"  {teks.upper()}  ") == harap


# Keluarga yang pernah menyebabkan bug. Diuji eksplisit, bukan hanya lewat
# parametrize di atas, supaya terlihat jelas di nama tes.
@pytest.mark.parametrize(
    "teks",
    ["Oktober", "OKTOBER", "oktober", "October", "OCTOBER", "october",
     "Okt", "OKT", "okt", "Okt.", "Oct", "OCT", "oct", "oct."],
)
def test_keluarga_oktober_semuanya_sepuluh(teks: str) -> None:
    assert bulan_ke_angka(teks) == 10


@pytest.mark.parametrize(
    ("teks", "harap"),
    [("Desember", 12), ("December", 12), ("Des", 12), ("Dec", 12),
     ("Januari", 1), ("January", 1), ("Jan", 1),
     ("Agustus", 8), ("August", 8), ("Agu", 8), ("Aug", 8),
     ("Mei", 5), ("May", 5),
     ("Februari", 2), ("Pebruari", 2), ("February", 2),
     ("November", 11), ("Nopember", 11)],
)
def test_keluarga_bulan_rawan_lain(teks: str, harap: int) -> None:
    assert bulan_ke_angka(teks) == harap


@pytest.mark.parametrize(
    "teks",
    ["", "   ", "Okotber", "Sept.ember", "bulan", "13", "0", "Marc",
     "Janvier", "Oktb", "xyz", "Ocktober", "Septembre"],
)
def test_nama_bulan_tak_dikenal_ditolak(teks: str) -> None:
    with pytest.raises(TanggalTidakDikenal):
        bulan_ke_angka(teks)


@pytest.mark.parametrize("nilai", [None, 10, 10.0, [], {}, True])
def test_nama_bulan_bukan_teks_ditolak(nilai: object) -> None:
    with pytest.raises(TanggalTidakDikenal):
        bulan_ke_angka(nilai)  # type: ignore[arg-type]


def test_tidak_ada_varian_bulan_yang_bentrok() -> None:
    """Satu singkatan tidak boleh menunjuk dua bulan."""
    terlihat: dict[str, int] = {}
    for angka, varian in _VARIAN:
        for v in varian:
            kunci = v.casefold()
            assert terlihat.get(kunci, angka) == angka, f"{kunci} bentrok"
            terlihat[kunci] = angka
    assert len(terlihat) == len(_ALIAS_BULAN)


# --------------------------------------------------------------------------
# nama_bulan_id: untuk laporan PDF
# --------------------------------------------------------------------------


def test_nama_bulan_id_lengkap_dan_berbahasa_indonesia() -> None:
    assert [nama_bulan_id(n) for n in range(1, 13)] == [
        "Januari", "Februari", "Maret", "April", "Mei", "Juni",
        "Juli", "Agustus", "September", "Oktober", "November", "Desember",
    ]
    assert len(NAMA_BULAN_ID) == 12


@pytest.mark.parametrize("nilai", [0, 13, -1, 100])
def test_nama_bulan_id_di_luar_jangkauan_ditolak(nilai: int) -> None:
    with pytest.raises(TanggalTidakDikenal):
        nama_bulan_id(nilai)


@pytest.mark.parametrize("nilai", ["10", None, 10.0, True])
def test_nama_bulan_id_tipe_salah_ditolak(nilai: object) -> None:
    with pytest.raises(TanggalTidakDikenal):
        nama_bulan_id(nilai)  # type: ignore[arg-type]


def test_nama_bulan_id_bolak_balik_konsisten() -> None:
    for n in range(1, 13):
        assert bulan_ke_angka(nama_bulan_id(n)) == n


# --------------------------------------------------------------------------
# parse_tanggal
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("teks", "harap"),
    [
        ("01/09/2026", dt.date(2026, 9, 1)),
        ("30/09/2026", dt.date(2026, 9, 30)),
        ("11/10/2026", dt.date(2026, 10, 11)),
        ("31/12/2026", dt.date(2026, 12, 31)),
        ("1/9/2026", dt.date(2026, 9, 1)),      # nol di depan boleh hilang
        ("  01/09/2026  ", dt.date(2026, 9, 1)),
        ("29/02/2024", dt.date(2024, 2, 29)),   # tahun kabisat
    ],
)
def test_parse_tanggal_sah(teks: str, harap: dt.date) -> None:
    assert parse_tanggal(teks) == harap


def test_parse_tanggal_selalu_hari_bulan_tahun() -> None:
    """Angka pertama hari, kedua bulan. Tidak pernah ditafsirkan sebaliknya."""
    assert parse_tanggal("09/01/2026") == dt.date(2026, 1, 9)
    assert parse_tanggal("01/09/2026") == dt.date(2026, 9, 1)


@pytest.mark.parametrize(
    "teks",
    [
        "2026-09-01",            # ISO
        "01-09-2026",            # pemisah strip
        "01.09.2026",            # pemisah titik
        "01/09/26",              # tahun dua angka
        "1 September 2026",      # nama bulan
        "September 1, 2026",
        "01/09/2026 14:45:02",   # ada waktu
        "32/01/2026",            # hari tidak sah
        "01/13/2026",            # bulan tidak sah
        "00/09/2026",
        "01/00/2026",
        "29/02/2026",            # 2026 bukan kabisat
        "31/04/2026",            # April hanya 30 hari
        "", "   ", "abc", "//", "1/2/3/4", "01/09/20267",
    ],
)
def test_parse_tanggal_format_salah_ditolak(teks: str) -> None:
    with pytest.raises(TanggalTidakDikenal):
        parse_tanggal(teks)


@pytest.mark.parametrize("nilai", [None, 20260901, 45000.0, [], dt.date(2026, 9, 1)])
def test_parse_tanggal_bukan_teks_ditolak(nilai: object) -> None:
    with pytest.raises(TanggalTidakDikenal):
        parse_tanggal(nilai)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# parse_waktu
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("teks", "harap"),
    [
        ("01/09/2026 14:45:02", dt.datetime(2026, 9, 1, 14, 45, 2)),
        ("30/09/2026 22:29:48", dt.datetime(2026, 9, 30, 22, 29, 48)),
        ("01/09/2026 00:00:00", dt.datetime(2026, 9, 1, 0, 0, 0)),
        ("01/09/2026 9:05", dt.datetime(2026, 9, 1, 9, 5, 0)),  # detik opsional
    ],
)
def test_parse_waktu_sah(teks: str, harap: dt.datetime) -> None:
    assert parse_waktu(teks) == harap


@pytest.mark.parametrize(
    "teks",
    ["01/09/2026", "01/09/2026 25:00:00", "01/09/2026 14:60:00",
     "2026-09-01 14:45:02", "01/09/2026T14:45:02", "", "14:45:02"],
)
def test_parse_waktu_salah_ditolak(teks: str) -> None:
    with pytest.raises(TanggalTidakDikenal):
        parse_waktu(teks)


def test_waktu_jadi_pemutus_transaksi_hari_sama() -> None:
    """Dua transaksi di hari sama harus bisa diurutkan."""
    a = parse_waktu("12/09/2026 09:15:00")
    b = parse_waktu("12/09/2026 16:40:00")
    assert a < b
    assert max(a, b) == b


# --------------------------------------------------------------------------
# Simpan dan baca kembali
# --------------------------------------------------------------------------


def test_ke_iso() -> None:
    assert ke_iso(dt.date(2026, 9, 1)) == "2026-09-01"
    assert ke_iso(dt.date(2026, 10, 11)) == "2026-10-11"


def test_ke_iso_menerima_datetime() -> None:
    assert ke_iso(dt.datetime(2026, 9, 1, 14, 45)) == "2026-09-01"


@pytest.mark.parametrize("nilai", [None, "2026-09-01", 20260901])
def test_ke_iso_tipe_salah_ditolak(nilai: object) -> None:
    with pytest.raises(TanggalTidakDikenal):
        ke_iso(nilai)  # type: ignore[arg-type]


def test_bolak_balik_laporan_ke_basis_data() -> None:
    """dd/mm/yyyy -> YYYY-MM-DD -> date, tanpa berubah."""
    for teks in ["01/09/2026", "30/09/2026", "11/10/2026", "29/02/2024"]:
        tanggal = parse_tanggal(teks)
        assert dari_iso(ke_iso(tanggal)) == tanggal


@pytest.mark.parametrize("teks", ["01/09/2026", "2026-9-1x", "", "2026-13-01", "abc"])
def test_dari_iso_salah_ditolak(teks: str) -> None:
    with pytest.raises(TanggalTidakDikenal):
        dari_iso(teks)


# --------------------------------------------------------------------------
# Periode laporan: baris 0
# --------------------------------------------------------------------------

# Persis seperti di kedua laporan contoh September 2026.
BARIS_NYATA = "TRANSAKSI PENJUALAN PER 01 SEPTEMBER 2026 S/D 30 SEPTEMBER 2026"


def test_periode_dari_baris_laporan_nyata() -> None:
    assert parse_periode_laporan(BARIS_NYATA) == (
        dt.date(2026, 9, 1),
        dt.date(2026, 9, 30),
    )


@pytest.mark.parametrize(
    ("teks", "harap"),
    [
        ("PER 01 OKTOBER 2026 S/D 31 OKTOBER 2026",
         (dt.date(2026, 10, 1), dt.date(2026, 10, 31))),
        ("PER 01 October 2026 S/D 31 October 2026",
         (dt.date(2026, 10, 1), dt.date(2026, 10, 31))),
        ("PER 1 Okt 2026 S/D 31 Okt 2026",
         (dt.date(2026, 10, 1), dt.date(2026, 10, 31))),
        ("per 1 oct 2026 s/d 31 oct 2026",
         (dt.date(2026, 10, 1), dt.date(2026, 10, 31))),
        ("PER 28 SEPTEMBER 2026 S / D 04 OKTOBER 2026",
         (dt.date(2026, 9, 28), dt.date(2026, 10, 4))),
        ("PER 25 DESEMBER 2026 S/D 05 JANUARI 2027",
         (dt.date(2026, 12, 25), dt.date(2027, 1, 5))),
    ],
)
def test_periode_varian_bulan(teks: str, harap: tuple[dt.date, dt.date]) -> None:
    assert parse_periode_laporan(teks) == harap


def test_periode_mingguan() -> None:
    """Keputusan 4.2: unggah mingguan, jadi periode bisa hanya 7 hari."""
    assert parse_periode_laporan("PER 05 OKTOBER 2026 S/D 11 OKTOBER 2026") == (
        dt.date(2026, 10, 5),
        dt.date(2026, 10, 11),
    )


@pytest.mark.parametrize(
    "teks",
    [
        "",
        "TRANSAKSI PENJUALAN",
        "PER 01 OKOTBER 2026 S/D 31 OKOTBER 2026",   # salah tulis
        "PER 01 SEPTEMBER 2026",                      # tanpa akhir
        "PER 31 SEPTEMBER 2026 S/D 31 SEPTEMBER 2026",  # 31 Sept tidak ada
        "PER 01/09/2026 S/D 30/09/2026",              # bukan nama bulan
    ],
)
def test_periode_salah_ditolak(teks: str) -> None:
    with pytest.raises(TanggalTidakDikenal):
        parse_periode_laporan(teks)


def test_periode_terbalik_ditolak() -> None:
    with pytest.raises(TanggalTidakDikenal):
        parse_periode_laporan("PER 30 SEPTEMBER 2026 S/D 01 SEPTEMBER 2026")


# --------------------------------------------------------------------------
# format_periode_id: untuk laporan PDF
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("awal", "akhir", "harap"),
    [
        (dt.date(2026, 9, 1), dt.date(2026, 9, 30), "1-30 September 2026"),
        (dt.date(2026, 10, 5), dt.date(2026, 10, 11), "5-11 Oktober 2026"),
        (dt.date(2026, 9, 1), dt.date(2026, 9, 1), "1 September 2026"),
        (dt.date(2026, 9, 28), dt.date(2026, 10, 4),
         "28 September - 4 Oktober 2026"),
        (dt.date(2026, 12, 25), dt.date(2027, 1, 5),
         "25 Desember 2026 - 5 Januari 2027"),
    ],
)
def test_format_periode_id(awal: dt.date, akhir: dt.date, harap: str) -> None:
    assert format_periode_id(awal, akhir) == harap


def test_format_periode_id_tidak_pernah_berbahasa_inggris() -> None:
    for bulan in range(1, 13):
        hasil = format_periode_id(dt.date(2026, bulan, 1), dt.date(2026, bulan, 28))
        assert nama_bulan_id(bulan) in hasil
    semua = " ".join(
        format_periode_id(dt.date(2026, b, 1), dt.date(2026, b, 28))
        for b in range(1, 13)
    )
    for inggris in ["January", "March", "May", "August", "October", "December"]:
        assert inggris not in semua


def test_format_periode_id_terbalik_ditolak() -> None:
    with pytest.raises(TanggalTidakDikenal):
        format_periode_id(dt.date(2026, 9, 30), dt.date(2026, 9, 1))


# --------------------------------------------------------------------------
# Pemeriksaan kewajaran
# --------------------------------------------------------------------------


def test_dalam_periode_termasuk_ujungnya() -> None:
    awal, akhir = dt.date(2026, 9, 1), dt.date(2026, 9, 30)
    assert dalam_periode(awal, awal, akhir)
    assert dalam_periode(akhir, awal, akhir)
    assert dalam_periode(dt.date(2026, 9, 15), awal, akhir)
    assert not dalam_periode(dt.date(2026, 8, 31), awal, akhir)
    assert not dalam_periode(dt.date(2026, 10, 1), awal, akhir)


def test_deteksi_tanggal_mungkin_terbalik() -> None:
    # semua hari <= 12: urutan dd/mm vs mm/dd tidak bisa dipastikan
    assert tanggal_mungkin_terbalik(
        [dt.date(2026, 9, 1), dt.date(2026, 9, 5), dt.date(2026, 9, 12)]
    )
    # ada hari > 12: urutannya pasti dd/mm
    assert not tanggal_mungkin_terbalik(
        [dt.date(2026, 9, 1), dt.date(2026, 9, 30)]
    )
    assert not tanggal_mungkin_terbalik([])


def test_deteksi_terbalik_pada_laporan_contoh_nyata() -> None:
    """Laporan September penuh memuat tanggal 13-30, jadi tidak ambigu."""
    sebulan = [dt.date(2026, 9, h) for h in range(1, 31)]
    assert not tanggal_mungkin_terbalik(sebulan)


# --------------------------------------------------------------------------
# TANGGAL vs WAKTU TRANSAKSI
#
# Temuan dari laporan asli: 29 baris (21 Jemur, 8 Citraland) punya WAKTU
# TRANSAKSI di hari berikutnya, dua di antaranya +3 hari. TANGGAL = tanggal
# kunjungan, WAKTU TRANSAKSI = saat kasir mencatat pelunasan.
# --------------------------------------------------------------------------


def test_waktu_boleh_beda_hari_dengan_tanggal() -> None:
    """Kasus nyata baris 116 laporan Jemur: kunjungan 05/09, dilunasi 06/09."""
    tanggal = parse_tanggal("05/09/2026")
    waktu = parse_waktu("06/09/2026 14:08:58")
    assert waktu.date() != tanggal
    assert (waktu.date() - tanggal).days == 1


def test_kunci_urut_mengutamakan_tanggal_bukan_waktu() -> None:
    """Kunjungan 21/09 harus lebih baru dari kunjungan 20/09 yang telat dilunasi.

    Kasus nyata: baris 228-230 laporan Citraland, TANGGAL 20/09 dengan
    WAKTU TRANSAKSI 21/09.
    """
    telat = kunci_urut(parse_tanggal("20/09/2026"), parse_waktu("21/09/2026 14:07:09"))
    baru = kunci_urut(parse_tanggal("21/09/2026"), parse_waktu("21/09/2026 09:00:00"))
    assert telat < baru, "TANGGAL harus mendominasi WAKTU TRANSAKSI"

    # Dibandingkan: mengurutkan pakai WAKTU saja memberi jawaban yang salah.
    assert parse_waktu("21/09/2026 14:07:09") > parse_waktu("21/09/2026 09:00:00")


def test_kunci_urut_memutus_di_hari_sama() -> None:
    pagi = kunci_urut(parse_tanggal("12/09/2026"), parse_waktu("12/09/2026 09:15:00"))
    sore = kunci_urut(parse_tanggal("12/09/2026"), parse_waktu("12/09/2026 16:40:00"))
    assert pagi < sore
    assert max([pagi, sore]) == sore


def test_kunci_urut_tanpa_waktu() -> None:
    a = kunci_urut(parse_tanggal("12/09/2026"))
    b = kunci_urut(parse_tanggal("12/09/2026"), parse_waktu("12/09/2026 09:15:00"))
    assert a < b, "baris tanpa WAKTU TRANSAKSI diperlakukan paling awal di harinya"
    assert kunci_urut(parse_tanggal("11/09/2026")) < a


def test_kunci_urut_memilih_kunjungan_terakhir() -> None:
    """Meniru pemilihan faktur kunjungan terakhir satu pasien."""
    transaksi = [
        (parse_tanggal("05/09/2026"), parse_waktu("06/09/2026 14:08:58"), 26090148),
        (parse_tanggal("07/09/2026"), parse_waktu("07/09/2026 10:00:00"), 26090182),
        (parse_tanggal("12/09/2026"), parse_waktu("12/09/2026 16:40:00"), 26090311),
    ]
    terakhir = max(transaksi, key=lambda t: kunci_urut(t[0], t[1]))
    assert terakhir[2] == 26090311


@pytest.mark.parametrize("nilai", [None, "12/09/2026", 2026])
def test_kunci_urut_tipe_salah_ditolak(nilai: object) -> None:
    with pytest.raises(TanggalTidakDikenal):
        kunci_urut(nilai)  # type: ignore[arg-type]


def test_kunci_urut_waktu_tipe_salah_ditolak() -> None:
    with pytest.raises(TanggalTidakDikenal):
        kunci_urut(parse_tanggal("12/09/2026"), "12/09/2026 09:00:00")  # type: ignore[arg-type]
