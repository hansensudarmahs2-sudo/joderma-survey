"""Uji pembacaan laporan Omnicare.

Memakai lembar palsu, bukan berkas .xls asli, karena berkas asli memuat data
pasien dan tidak boleh masuk git. Tes integrasi terhadap berkas asli ada di
bagian paling bawah dan dilewati bila berkasnya tidak ada.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from joderma_survey.parser_omnicare import (
    KOLOM_WAJIB,
    LaporanTidakValid,
    baca_lembar,
    kode_cabang_dari_nama_berkas,
)

JUDUL = "TRANSAKSI PENJUALAN PER 01 SEPTEMBER 2026 S/D 30 SEPTEMBER 2026"
BARIS_FILTER = ["STATUS:", "SEMUA", "PENGGUNA:", "SEMUA", "ASURANSI:", "SEMUA",
                "PELAYANAN:", "SEMUA"]
# Baris TOTAL asli bergeser satu kolom: label di kolom HARGA, angka mulai
# LAIN-LAIN (docs/temuan-data.md T2).
BARIS_TOTAL = ["", "", "", "", "", "", "", "TOTAL", 1153500.0, 0.0, 0.0, 0.0, 0.0, 0.0]
BARIS_LEGENDA = ["RJ: Rawat Jalan; RI: Rawat Inap; MCU: Pemeriksaan Kesehatan; "
                 "OTC: Tanpa Pemeriksaan"]


class LembarPalsu:
    """Lembar kerja sederhana dari daftar baris."""

    def __init__(self, baris: list[list[object]]) -> None:
        self._baris = baris
        self._ncols = max((len(b) for b in baris), default=0)

    @property
    def nrows(self) -> int:
        return len(self._baris)

    @property
    def ncols(self) -> int:
        return self._ncols

    def cell_value(self, row: int, col: int) -> object:
        baris = self._baris[row]
        return baris[col] if col < len(baris) else ""


def transaksi(
    tanggal: str = "01/09/2026",
    faktur: float = 26090001.0,
    layanan: str = "RJ",
    no_id: str = "J00143",
    pasien: str = "Tatik Mindari",
    dokter: str = "dr. Yohanes Widjaja Sp.DVE",
    harga: float = 550000.0,
    status: str = "LUNAS",
    waktu: str = "01/09/2026 14:45:02",
) -> list[object]:
    return [tanggal, faktur, layanan, no_id, pasien, dokter, "-", harga,
            0.0, 0.0, 0.0, 0.0, 0.0, "", status, "APJ", waktu]


def lembar(
    *baris_data: list[object],
    judul: str = JUDUL,
    header: list[str] | None = None,
    catatan_kaki: bool = True,
) -> LembarPalsu:
    isi: list[list[object]] = [[judul], list(BARIS_FILTER), [""],
                               list(header if header is not None else KOLOM_WAJIB)]
    isi.extend(list(b) for b in baris_data)
    if catatan_kaki:
        isi.append(list(BARIS_TOTAL))
        isi.append(list(BARIS_LEGENDA))
    return LembarPalsu(isi)


def baca(*baris_data: list[object], **kw: object) -> object:
    return baca_lembar(lembar(*baris_data, **kw), "uji_30376.xls", "30376")  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Kode cabang dari nama berkas
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("nama", "harap"),
    [
        ("sales_transactions_11_10_2026_30376.xls", "30376"),
        ("sales_transactions_11_10_2026_31281.xls", "31281"),
        ("/data/unggahan/sales_transactions_01_11_2026_31281.xls", "31281"),
        ("30376.xls", "30376"),
    ],
)
def test_kode_cabang_dari_nama_berkas(nama: str, harap: str) -> None:
    assert kode_cabang_dari_nama_berkas(nama) == harap


def test_tanggal_di_nama_berkas_bukan_kode_cabang() -> None:
    """11_10_2026 adalah tanggal ekspor, tidak boleh dianggap kode cabang."""
    assert kode_cabang_dari_nama_berkas("sales_transactions_11_10_2026_30376.xls") == "30376"


@pytest.mark.parametrize(
    "nama",
    ["laporan.xls", "sales_transactions_11_10_2026.xls", "sales_99999.xls"],
)
def test_nama_berkas_tanpa_kode_cabang_ditolak(nama: str) -> None:
    with pytest.raises(LaporanTidakValid, match="kode cabang tidak ditemukan"):
        kode_cabang_dari_nama_berkas(nama)


def test_nama_berkas_dua_kode_cabang_ditolak() -> None:
    with pytest.raises(LaporanTidakValid, match="lebih dari satu kode"):
        kode_cabang_dari_nama_berkas("sales_30376_31281.xls")


# --------------------------------------------------------------------------
# Judul kolom (F2)
# --------------------------------------------------------------------------


def test_laporan_baku_terbaca() -> None:
    lap = baca(transaksi())
    assert lap.ringkasan.baris_data == 1
    assert lap.ringkasan.baris_dipakai == 1
    assert lap.baris[0].rm == "J00143"
    assert lap.baris[0].nomor_baris == 5, "baris ke-5 di berkas (header di baris 4)"


def test_judul_kolom_tidak_peduli_besar_kecil() -> None:
    """Omnicare menulis 'HARGA (Rp)' dengan p kecil."""
    header = [k.upper() for k in KOLOM_WAJIB]
    lap = baca(transaksi(), header=header)
    assert lap.ringkasan.baris_dipakai == 1


def test_judul_kolom_kurang_ditolak_dengan_pesan_jelas() -> None:
    header = [k for k in KOLOM_WAJIB if k != "NO. ID"]
    with pytest.raises(LaporanTidakValid) as galat:
        baca(transaksi(), header=header)
    pesan = str(galat.value)
    assert "NO. ID" in pesan
    assert "Pemeriksaan Tenaga Medis" in pesan, "harus menyarankan penyebab paling mungkin"


def test_laporan_lain_ditolak() -> None:
    """Laporan Pemeriksaan Tenaga Medis punya judul kolom berbeda."""
    header = ["TANGGAL", "NO. RM", "NIK", "DIAGNOSA", "PASIEN"]
    with pytest.raises(LaporanTidakValid, match="judul kolom tidak sesuai"):
        baca(transaksi(), header=header)


def test_baris_header_dicari_bukan_dipaku() -> None:
    isi: list[list[object]] = [[JUDUL], [""], [""], [""], [""],
                               list(KOLOM_WAJIB), transaksi()]
    lap = baca_lembar(LembarPalsu(isi), "uji_30376.xls", "30376")
    assert lap.ringkasan.baris_dipakai == 1


def test_tanpa_baris_header_ditolak() -> None:
    isi: list[list[object]] = [[JUDUL], [""], [""], ["bukan", "header"]]
    with pytest.raises(LaporanTidakValid, match="baris judul kolom tidak ditemukan"):
        baca_lembar(LembarPalsu(isi), "uji_30376.xls", "30376")


# --------------------------------------------------------------------------
# Catatan kaki (F2)
# --------------------------------------------------------------------------


def test_catatan_kaki_dilewati() -> None:
    lap = baca(transaksi(), transaksi(faktur=26090002.0, no_id="J00813"))
    assert lap.ringkasan.baris_catatan_kaki == 2
    assert lap.ringkasan.baris_data == 2
    assert lap.ringkasan.baris_dipakai == 2


def test_baris_total_tidak_dianggap_data_walau_bergeser_kolom() -> None:
    """Deteksi lewat kolom TANGGAL, bukan posisi kolom."""
    lap = baca(transaksi())
    assert all(b.no_faktur != 1153500 for b in lap.baris)
    assert lap.ringkasan.baris_data == 1


# --------------------------------------------------------------------------
# Periode laporan
# --------------------------------------------------------------------------


def test_periode_dibaca_dari_baris_judul() -> None:
    lap = baca(transaksi())
    assert lap.ringkasan.periode_awal == dt.date(2026, 9, 1)
    assert lap.ringkasan.periode_akhir == dt.date(2026, 9, 30)


def test_periode_tidak_terbaca_ditolak() -> None:
    with pytest.raises(LaporanTidakValid, match="periode laporan tidak bisa dibaca"):
        baca(transaksi(), judul="LAPORAN PENJUALAN")


def test_tanggal_di_luar_periode_memicu_peringatan() -> None:
    lap = baca(transaksi(tanggal="15/08/2026", waktu="15/08/2026 10:00:00"))
    assert any("di luar periode" in p for p in lap.ringkasan.peringatan)
    assert lap.ringkasan.baris_dipakai == 1, "diperingatkan, bukan dibuang"


# --------------------------------------------------------------------------
# Penyaringan baris
# --------------------------------------------------------------------------


def test_status_bukan_lunas_dilewati() -> None:
    lap = baca(transaksi(), transaksi(faktur=26090002.0, status="BELUM LUNAS"))
    assert lap.ringkasan.baris_dipakai == 1
    assert any("bukan LUNAS" in k for k in lap.ringkasan.dilewati)


def test_baris_anonim_dilewati() -> None:
    lap = baca(transaksi(), transaksi(faktur=26090002.0, no_id="-", pasien="",
                                      layanan="OTC", dokter="-"))
    assert lap.ringkasan.baris_dipakai == 1
    assert lap.ringkasan.dilewati["baris anonim tanpa nomor RM"] == 1


def test_rm_tidak_dikenal_dilewati_dan_dilaporkan() -> None:
    lap = baca(transaksi(), transaksi(faktur=26090002.0, no_id="X9999"))
    assert lap.ringkasan.baris_dipakai == 1
    assert lap.ringkasan.dilewati["nomor RM tidak dikenal"] == 1
    assert len(lap.ringkasan.rm_tidak_dikenal) == 1


def test_faktur_tidak_terbaca_dilewati() -> None:
    lap = baca(transaksi(faktur="bukan angka"))  # type: ignore[arg-type]
    assert lap.ringkasan.baris_dipakai == 0
    assert lap.ringkasan.dilewati["nomor faktur tidak terbaca"] == 1


def test_faktur_float_jadi_bilangan_bulat() -> None:
    """Omnicare menyimpan nomor faktur sebagai angka, bukan teks."""
    lap = baca(transaksi(faktur=26090841.0))
    assert lap.baris[0].no_faktur == 26090841
    assert isinstance(lap.baris[0].no_faktur, int)


# --------------------------------------------------------------------------
# Normalisasi RM dilaporkan
# --------------------------------------------------------------------------


def test_rm_dinormalisasi_dilaporkan() -> None:
    lap = baca(transaksi(no_id="J0635", pasien="Ade Wijaya"))
    assert lap.baris[0].rm == "J00635"
    assert lap.ringkasan.rm_dinormalisasi == [(5, "J0635", "J00635")]


def test_rm_berspasi_tidak_dilaporkan_sebagai_perubahan() -> None:
    """Spasi dan huruf itu perapian biasa, tidak perlu ditinjau direktur."""
    lap = baca(transaksi(no_id="J07536 "))
    assert lap.baris[0].rm == "J07536"
    assert lap.ringkasan.rm_dinormalisasi == []


def test_rm_awalan_lain_tetap_diterima() -> None:
    """RM berawalan J boleh muncul di berkas Citraland dan sebaliknya."""
    lap = baca_lembar(lembar(transaksi(no_id="J05772")), "uji_31281.xls", "31281")
    assert lap.baris[0].rm == "J05772"
    assert lap.ringkasan.cabang.nama == "Citraland"


# --------------------------------------------------------------------------
# Deteksi penggabungan pasien yang salah
# --------------------------------------------------------------------------


def test_rm_sama_dari_bentuk_berbeda_dengan_nama_berbeda_diperingatkan() -> None:
    """Pengaman: kalau normalisasi menggabungkan dua orang, harus terlihat."""
    lap = baca(
        transaksi(no_id="J0635", pasien="Ade Wijaya"),
        transaksi(faktur=26090002.0, no_id="J00635", pasien="Orang Lain"),
    )
    assert any("mungkin menggabungkan dua pasien" in p for p in lap.ringkasan.peringatan)


def test_rm_sama_dari_bentuk_berbeda_dengan_nama_sama_tidak_diperingatkan() -> None:
    lap = baca(
        transaksi(no_id="J0635", pasien="Ade Wijaya"),
        transaksi(faktur=26090002.0, no_id="J00635", pasien="Ade Wijaya"),
    )
    assert not any("menggabungkan" in p for p in lap.ringkasan.peringatan)


def test_rm_satu_bentuk_dua_nama_diperingatkan() -> None:
    lap = baca(
        transaksi(no_id="J00143", pasien="Tatik Mindari"),
        transaksi(faktur=26090002.0, no_id="J00143", pasien="Nama Beda"),
    )
    assert any("lebih dari satu nama" in p for p in lap.ringkasan.peringatan)


# --------------------------------------------------------------------------
# Kunjungan terakhir per pasien
# --------------------------------------------------------------------------


def test_satu_pasien_satu_kunjungan_terakhir() -> None:
    lap = baca(
        transaksi(tanggal="05/09/2026", faktur=26090148.0, waktu="06/09/2026 14:08:58"),
        transaksi(tanggal="07/09/2026", faktur=26090182.0, waktu="07/09/2026 10:00:00"),
        transaksi(tanggal="12/09/2026", faktur=26090311.0, waktu="12/09/2026 16:40:00"),
    )
    terakhir = lap.terakhir_per_pasien()
    assert len(terakhir) == 1
    assert terakhir["J00143"].no_faktur == 26090311


def test_kunjungan_terakhir_pakai_tanggal_bukan_waktu_pelunasan() -> None:
    """Kunjungan 20/09 yang dilunasi 21/09 bukan yang terbaru."""
    lap = baca(
        transaksi(tanggal="20/09/2026", faktur=26090250.0, waktu="21/09/2026 14:07:09"),
        transaksi(tanggal="21/09/2026", faktur=26090260.0, waktu="21/09/2026 09:00:00"),
    )
    assert lap.terakhir_per_pasien()["J00143"].no_faktur == 26090260


def test_kunjungan_terakhir_waktu_jadi_pemutus_di_hari_sama() -> None:
    lap = baca(
        transaksi(tanggal="12/09/2026", faktur=26090301.0, waktu="12/09/2026 09:15:00"),
        transaksi(tanggal="12/09/2026", faktur=26090302.0, waktu="12/09/2026 16:40:00"),
    )
    assert lap.terakhir_per_pasien()["J00143"].no_faktur == 26090302


def test_terakhir_per_pasien_memisahkan_pasien() -> None:
    lap = baca(
        transaksi(no_id="J00143", faktur=26090001.0),
        transaksi(no_id="J00813", faktur=26090002.0),
        transaksi(no_id="JC0308", faktur=26090003.0),
    )
    assert set(lap.terakhir_per_pasien()) == {"J00143", "J00813", "JC0308"}


# --------------------------------------------------------------------------
# Keraguan dan ringkasan
# --------------------------------------------------------------------------


def test_akun_lembaga_ditandai_tapi_tetap_dipakai() -> None:
    """Keputusan 2.7: diberi peringatan, penyaringan akhir di tangan CS."""
    lap = baca(transaksi(no_id="J00000002", pasien="Klinik Utama Dryn Dipo",
                         layanan="OTC", dokter="-"))
    assert lap.ringkasan.baris_dipakai == 1
    assert lap.baris[0].rm == "J00002"
    assert lap.baris[0].keraguan
    assert len(lap.ringkasan.keraguan) == 1


def test_hitungan_layanan() -> None:
    lap = baca(
        transaksi(layanan="RJ"),
        transaksi(faktur=26090002.0, layanan="OTC", dokter="-", no_id="J00813"),
        transaksi(faktur=26090003.0, layanan="OTC", dokter="-", no_id="J00814"),
    )
    assert lap.ringkasan.layanan == {"RJ": 1, "OTC": 2}


def test_pasien_unik_dihitung_setelah_normalisasi() -> None:
    lap = baca(
        transaksi(no_id="J0635", pasien="Ade Wijaya"),
        transaksi(faktur=26090002.0, no_id="J00635", pasien="Ade Wijaya"),
    )
    assert lap.ringkasan.pasien_unik == 1


def test_ringkas_memuat_keterangan_penting() -> None:
    lap = baca(transaksi(), transaksi(faktur=26090002.0, no_id="-", pasien=""))
    teks = lap.ringkasan.ringkas()
    assert "Jemur Andayani" in teks
    assert "2026-09-01" in teks
    assert "dilewati" in teks


def test_cabang_dari_kode_dipakai_di_ringkasan() -> None:
    lap = baca_lembar(lembar(transaksi()), "uji_31281.xls", "31281")
    assert lap.ringkasan.cabang.kode == "31281"
    assert lap.ringkasan.cabang.nama == "Citraland"


def test_deteksi_tanggal_mungkin_terbalik() -> None:
    lap = baca(
        transaksi(tanggal="01/09/2026", waktu="01/09/2026 10:00:00"),
        transaksi(tanggal="05/09/2026", faktur=26090002.0, waktu="05/09/2026 10:00:00"),
    )
    assert any("dd/mm tidak bisa" in p for p in lap.ringkasan.peringatan)


def test_tanggal_lewat_12_tidak_memicu_peringatan_terbalik() -> None:
    lap = baca(
        transaksi(tanggal="01/09/2026", waktu="01/09/2026 10:00:00"),
        transaksi(tanggal="30/09/2026", faktur=26090002.0, waktu="30/09/2026 10:00:00"),
    )
    assert not any("dd/mm tidak bisa" in p for p in lap.ringkasan.peringatan)


def test_waktu_transaksi_kosong_boleh() -> None:
    lap = baca(transaksi(waktu=""))
    assert lap.ringkasan.baris_dipakai == 1
    assert lap.baris[0].waktu is None


def test_waktu_transaksi_rusak_diperingatkan_bukan_dibuang() -> None:
    lap = baca(transaksi(waktu="bukan waktu"))
    assert lap.ringkasan.baris_dipakai == 1
    assert lap.baris[0].waktu is None
    assert any("WAKTU TRANSAKSI tidak terbaca" in p for p in lap.ringkasan.peringatan)


# --------------------------------------------------------------------------
# Integrasi dengan berkas asli (dilewati bila berkasnya tidak ada)
#
# Berkas asli memuat data pasien dan tidak masuk git, jadi tes ini hanya
# jalan di mesin yang punya salinannya. Ini satu-satunya tes yang menyentuh
# jalur .xls cacat (docs/gaps.md G8).
# --------------------------------------------------------------------------

CONTOH = Path(__file__).resolve().parent.parent / "contoh-xls-omnicare"
BERKAS_ASLI = [
    (CONTOH / "sales_transactions_11_10_2026_30376.xls", "30376", 827, 497),
    (CONTOH / "sales_transactions_11_10_2026_31281.xls", "31281", 351, 244),
]


@pytest.mark.parametrize(("path", "kode", "baris_data", "pasien"), BERKAS_ASLI)
def test_integrasi_berkas_omnicare_asli(
    path: Path, kode: str, baris_data: int, pasien: int
) -> None:
    pytest.importorskip("xlrd")
    if not path.exists():
        pytest.skip(f"berkas contoh tidak ada: {path.name}")
    from joderma_survey.parser_omnicare import baca_laporan

    lap = baca_laporan(path, kode_cabang=kode)
    assert lap.ringkasan.baris_data == baris_data
    assert lap.ringkasan.baris_catatan_kaki == 2
    assert lap.ringkasan.pasien_unik == pasien
    assert lap.ringkasan.periode_awal == dt.date(2026, 9, 1)
    assert lap.ringkasan.periode_akhir == dt.date(2026, 9, 30)
    assert all(b.status == "LUNAS" for b in lap.baris)
    assert all(b.rm for b in lap.baris)


def test_integrasi_salah_pilih_cabang_ditolak() -> None:
    path, _, _, _ = BERKAS_ASLI[0]
    if not path.exists():
        pytest.skip("berkas contoh tidak ada")
    from joderma_survey.parser_omnicare import baca_laporan

    with pytest.raises(LaporanTidakValid, match="tidak cocok"):
        baca_laporan(path, kode_cabang="31281")
