"""Pembantu untuk tes: lembar kerja palsu berbentuk laporan Omnicare.

Dipakai bersama oleh tes parser dan tes basis data, supaya tidak ada tes yang
bergantung pada berkas .xls asli yang memuat data pasien.
"""

from __future__ import annotations

from joderma_survey.parser_omnicare import KOLOM_WAJIB, Laporan, baca_lembar

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


def laporan(
    *baris_data: list[object],
    kode_cabang: str = "30376",
    nama_berkas: str | None = None,
    **kw: object,
) -> Laporan:
    """Laporan hasil parsing dari lembar palsu."""
    nama = nama_berkas or f"sales_transactions_11_10_2026_{kode_cabang}.xls"
    return baca_lembar(lembar(*baris_data, **kw), nama, kode_cabang)  # type: ignore[arg-type]
