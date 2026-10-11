"""Pembersihan data kotor dari laporan Omnicare.

Semua kekotoran dirapikan di sini, tidak ditebak di tempat lain. Yang
ditangani (lihat docs/temuan-data.md butir T6):

* Spasi di ujung nomor RM dan huruf kecil
* Lebar angka RM yang tidak seragam
* Baris OTC anonim bernomor RM ``-`` dengan nama kosong
* Nama pasien yang seluruhnya huruf besar
* Akun yang patut diragukan sebagai pasien perorangan

**Dasar normalisasi lebar angka RM.** Omnicare memakai lebar tetap:
``J`` + 5 angka untuk Jemur, ``JC`` + 4 angka untuk Citraland. Buktinya nilai
kecil pun ditulis penuh (``J00001`` untuk nilai 1, ``JC0027`` untuk 27), jadi
**angkanya adalah identitas pasien dan nol di depan hanya kosmetik**. Karena
itu RM dinormalkan berdasarkan nilai angkanya, bukan berdasarkan teks apa
adanya.

Di laporan September 2026 aturan ini menyentuh 5 RM dari 736, semuanya jatuh
di dalam jangkauan nomor yang wajar dan tidak satu pun bertabrakan dengan RM
lain. Nilai tertinggi yang ditemukan, J08146 dan JC1099, cocok dengan jumlah
pasien yang dilaporkan klinik (Jemur ~8200, Citraland ~2000).
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass, field
from typing import Final

from .cabang import AturanRM, aturan_untuk_rm

__all__ = [
    "StatusRM",
    "HasilRM",
    "normalisasi_rm",
    "normalisasi_nama",
    "curiga_bukan_pasien",
    "TANPA_RM",
]

#: Nilai kolom NO. ID untuk baris OTC anonim.
TANPA_RM: Final[frozenset[str]] = frozenset({"-", "", "--", "N/A", "NA"})


class StatusRM(enum.StrEnum):
    """Hasil pemeriksaan satu nomor RM."""

    BAKU = "baku"
    """Sudah sesuai pola; paling banyak hanya spasi dan huruf yang dirapikan."""

    DINORMALISASI = "dinormalisasi"
    """Lebar angka diperbaiki ke pola baku. Perlu dilaporkan ke direktur."""

    TANPA_RM = "tanpa_rm"
    """Baris anonim. Tidak bisa disurvei karena tidak ada identitas."""

    TIDAK_DIKENAL = "tidak_dikenal"
    """Pola tidak dikenali. Tidak dipakai, dan dilaporkan."""


@dataclass(frozen=True)
class HasilRM:
    asli: str
    """Isi sel apa adanya, untuk jejak audit."""

    rm: str | None
    """Nomor RM baku. ``None`` bila tidak bisa dipakai."""

    status: StatusRM
    catatan: str = ""
    peringatan: tuple[str, ...] = field(default_factory=tuple)

    @property
    def bisa_dipakai(self) -> bool:
        return self.rm is not None

    @property
    def perlu_ditinjau(self) -> bool:
        """Perlu masuk ringkasan unggahan untuk dilihat direktur."""
        return self.status in (StatusRM.DINORMALISASI, StatusRM.TIDAK_DIKENAL) or bool(
            self.peringatan
        )


_SPASI = re.compile(r"\s+")


def normalisasi_rm(nilai: object) -> HasilRM:
    """Rapikan satu nomor RM dari kolom ``NO. ID``.

    Tiga tahap, dari yang paling aman ke yang perlu dilaporkan:

    1. Buang spasi, besarkan huruf. Selalu aman.
    2. Kenali baris anonim (``-``).
    3. Seragamkan lebar angka ke pola awalannya, berdasarkan nilai angka.

    >>> normalisasi_rm("J07536 ").rm
    'J07536'
    >>> normalisasi_rm("jc0308").rm
    'JC0308'
    >>> hasil = normalisasi_rm("J0635")
    >>> hasil.rm, hasil.status
    ('J00635', <StatusRM.DINORMALISASI: 'dinormalisasi'>)
    >>> normalisasi_rm("-").status
    <StatusRM.TANPA_RM: 'tanpa_rm'>
    """
    asli = nilai if isinstance(nilai, str) else ""
    if not isinstance(nilai, str):
        return HasilRM(
            asli=str(nilai),
            rm=None,
            status=StatusRM.TIDAK_DIKENAL,
            catatan=f"nilai NO. ID bukan teks: {nilai!r}",
        )

    bersih = _SPASI.sub("", nilai).upper()
    if bersih in TANPA_RM:
        return HasilRM(
            asli=asli,
            rm=None,
            status=StatusRM.TANPA_RM,
            catatan="baris anonim tanpa nomor RM",
        )

    aturan = aturan_untuk_rm(bersih)
    if aturan is None:
        return HasilRM(
            asli=asli,
            rm=None,
            status=StatusRM.TIDAK_DIKENAL,
            catatan=f"awalan nomor RM tidak dikenal: {bersih!r}",
        )

    angka = int(bersih[len(aturan.awalan) :])
    if angka == 0:
        return HasilRM(
            asli=asli,
            rm=None,
            status=StatusRM.TIDAK_DIKENAL,
            catatan=f"nomor RM bernilai nol: {bersih!r}",
        )
    if angka > aturan.maksimum_format:
        # Tidak muat di lebar baku, jadi tidak mungkin nomor RM yang sah.
        return HasilRM(
            asli=asli,
            rm=None,
            status=StatusRM.TIDAK_DIKENAL,
            catatan=(
                f"nomor RM {bersih!r} bernilai {angka}, melebihi batas format "
                f"{aturan.awalan} + {aturan.lebar_angka} angka "
                f"(maksimum {aturan.maksimum_format})"
            ),
        )

    baku = f"{aturan.awalan}{angka:0{aturan.lebar_angka}d}"
    peringatan = _peringatan_jangkauan(baku, angka, aturan)

    if baku == bersih:
        status, catatan = StatusRM.BAKU, ""
    else:
        status = StatusRM.DINORMALISASI
        catatan = (
            f"lebar angka disesuaikan ke pola {aturan.awalan} + "
            f"{aturan.lebar_angka} angka: {bersih!r} -> {baku!r}"
        )
    return HasilRM(
        asli=asli, rm=baku, status=status, catatan=catatan, peringatan=peringatan
    )


def _peringatan_jangkauan(
    baku: str, angka: int, aturan: AturanRM
) -> tuple[str, ...]:
    if angka > aturan.perkiraan_tertinggi:
        return (
            f"nomor RM {baku} ({angka}) di atas perkiraan tertinggi "
            f"{aturan.perkiraan_tertinggi} untuk awalan {aturan.awalan}. "
            f"Wajar bila jumlah pasien sudah bertambah; perbarui "
            f"perkiraan_tertinggi di cabang.py bila memang begitu.",
        )
    return ()


def normalisasi_nama(nilai: object) -> str:
    """Rapikan nama pasien untuk sapaan di teks siap salin.

    Spasi ganda dirapatkan dan spasi di ujung dibuang. Besar-kecil huruf
    **tidak** diubah, kecuali bila seluruhnya huruf besar — nama seperti itu
    terbaca seperti berteriak di pesan WhatsApp.

    >>> normalisasi_nama("  Ade   Wijaya ")
    'Ade Wijaya'
    >>> normalisasi_nama("BUDI SANTOSO")
    'Budi Santoso'
    >>> normalisasi_nama("Dr.berliana Kurniawati")
    'Dr.berliana Kurniawati'
    """
    if not isinstance(nilai, str):
        return ""
    nama = _SPASI.sub(" ", nilai).strip()
    if nama and nama.isupper():
        nama = nama.title()
    return nama


# Kata yang menandakan akun bukan pasien perorangan. Dicocokkan sebagai kata
# utuh, bukan potongan: tanpa batas kata, "Sutoko" ikut tertangkap oleh
# "toko" dan memunculkan peringatan palsu.
_KATA_LEMBAGA: Final[tuple[str, ...]] = (
    "klinik", "apotek", "apotik", "rs", "rsu", "rsud", "rsia",
    "pt", "cv", "ud", "toko", "lab", "laboratorium", "yayasan", "koperasi",
)
_POLA_LEMBAGA: Final[re.Pattern[str]] = re.compile(
    r"\b(?:" + "|".join(_KATA_LEMBAGA) + r")\b", re.IGNORECASE
)
# Gelar dokter di awal nama.
_POLA_GELAR: Final[re.Pattern[str]] = re.compile(
    r"^\s*(?:dr|drg|prof)\b\.?", re.IGNORECASE
)


def curiga_bukan_pasien(nama: str, rm: str | None = None) -> tuple[str, ...]:
    """Alasan untuk meragukan bahwa baris ini pasien perorangan.

    Mengembalikan tuple kosong bila tidak ada keraguan. Ini **hanya
    peringatan** di daftar kirim; penyaringan akhir ada di tangan CS
    (keputusan 2.7), jadi tidak pernah menghalangi pembuatan link.

    >>> curiga_bukan_pasien("Klinik Utama Dryn Dipo")
    ('nama memuat kata lembaga: "Klinik"',)
    >>> curiga_bukan_pasien("Dr. Muhlis Yusuf")
    ('nama berawalan gelar dokter: "Dr."',)
    >>> curiga_bukan_pasien("Bagus Sutoko S.pd")
    ()
    >>> curiga_bukan_pasien("Ade Wijaya")
    ()
    """
    alasan: list[str] = []
    nama = nama or ""

    cocok_lembaga = _POLA_LEMBAGA.search(nama)
    if cocok_lembaga is not None:
        alasan.append(f'nama memuat kata lembaga: "{cocok_lembaga.group(0)}"')

    cocok_gelar = _POLA_GELAR.match(nama)
    if cocok_gelar is not None:
        alasan.append(f'nama berawalan gelar dokter: "{cocok_gelar.group(0).strip()}"')

    if not nama.strip():
        alasan.append("nama pasien kosong")

    return tuple(alasan)
