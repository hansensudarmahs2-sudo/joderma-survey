"""Definisi cabang dan aturan nomor RM.

Dua hal yang mudah tertukar dan sengaja dipisah di sini:

* **Cabang kunjungan** diambil dari kode di nama berkas yang diunggah
  (30376 / 31281). Itulah cabang tempat transaksi terjadi.
* **Cabang pendaftaran** tercermin di awalan nomor RM (``J`` / ``JC``).
  Itu tempat pasien pertama kali mendaftar, **bukan** tempat ia berkunjung.

Di laporan contoh September 2026 ada 33 baris pasien yang berobat di cabang
lain dari tempat ia mendaftar, jadi awalan RM tidak boleh dipakai untuk
menebak cabang kunjungan. Lihat docs/temuan-data.md butir T7.

Aturan lebar angka RM dikunci ke **awalan**, bukan ke berkas, supaya RM
berawalan ``J`` yang muncul di berkas Citraland tetap dinormalkan dengan
aturan Jemur.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

__all__ = ["Cabang", "AturanRM", "CABANG", "ATURAN_RM", "cabang_dari_kode", "aturan_untuk_rm"]


@dataclass(frozen=True)
class Cabang:
    kode: str
    nama: str


@dataclass(frozen=True)
class AturanRM:
    """Pola nomor RM untuk satu awalan."""

    awalan: str
    lebar_angka: int
    kode_cabang: str
    #: Perkiraan nomor tertinggi yang masuk akal saat ini. Dipakai hanya untuk
    #: memberi peringatan, tidak untuk menolak, karena jumlah pasien terus
    #: bertambah. Per Oktober 2026: Jemur ~8200 pasien (berdiri 3 tahun),
    #: Citraland ~2000 pasien (berdiri 10 bulan). Nilai tertinggi yang benar
    #: ada di laporan September: J08146 dan JC1099.
    perkiraan_tertinggi: int

    @property
    def maksimum_format(self) -> int:
        """Nilai terbesar yang masih muat di lebar angka ini."""
        return 10**self.lebar_angka - 1


CABANG: Final[dict[str, Cabang]] = {
    "30376": Cabang(kode="30376", nama="Jemur Andayani"),
    "31281": Cabang(kode="31281", nama="Citraland"),
}

# Urutan penting: awalan terpanjang diperiksa lebih dulu, karena "JC" juga
# berawalan "J".
ATURAN_RM: Final[tuple[AturanRM, ...]] = (
    AturanRM(awalan="JC", lebar_angka=4, kode_cabang="31281", perkiraan_tertinggi=2_000),
    AturanRM(awalan="J", lebar_angka=5, kode_cabang="30376", perkiraan_tertinggi=8_200),
)


def cabang_dari_kode(kode: str) -> Cabang:
    """Cari cabang dari kode di nama berkas."""
    try:
        return CABANG[str(kode).strip()]
    except KeyError:
        raise KeyError(
            f"kode cabang tidak dikenal: {kode!r}. "
            f"Yang dikenal: {', '.join(sorted(CABANG))}"
        ) from None


def aturan_untuk_rm(rm_bersih: str) -> AturanRM | None:
    """Aturan yang cocok untuk satu nomor RM yang sudah dirapikan hurufnya.

    Mengembalikan ``None`` bila awalannya tidak dikenal, misalnya karena ada
    cabang baru yang aturannya belum ditambahkan di modul ini.
    """
    for aturan in ATURAN_RM:
        sisa = rm_bersih[len(aturan.awalan) :]
        if rm_bersih.startswith(aturan.awalan) and sisa.isdigit():
            return aturan
    return None
