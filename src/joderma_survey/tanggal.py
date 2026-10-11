"""Satu-satunya modul untuk membaca, menyimpan, dan menulis tanggal.

Aturan dari PRD, dan alasan modul ini berdiri sendiri:

1. Tanggal di laporan Omnicare **selalu angka dd/mm/yyyy**. Dibaca dengan
   format tetap itu, disimpan sebagai YYYY-MM-DD.
2. **Nama bulan tidak pernah di-parse dari teks bebas.** Satu-satunya jalan
   adalah tabel ``_ALIAS_BULAN`` di bawah, dan varian yang tidak dikenal
   **ditolak, bukan ditebak**.
3. Nama bulan berbahasa Indonesia untuk laporan PDF dibuat oleh satu fungsi:
   :func:`nama_bulan_id`.

Masalah serupa pernah menyebabkan bug di modul finance (Oktober/October/
Okt/Oct), jadi seluruh varian diuji di ``tests/test_tanggal.py``.

Di mana nama bulan sebenarnya muncul: **hanya di baris 0 laporan**, yang
memuat periode, contoh::

    TRANSAKSI PENJUALAN PER 01 SEPTEMBER 2026 S/D 30 SEPTEMBER 2026

Kolom TANGGAL sendiri 100% angka (1.178 dari 1.178 baris di laporan contoh),
jadi tabel bulan tidak pernah dipakai untuk membaca baris data.

**TANGGAL dan WAKTU TRANSAKSI bukan hal yang sama.** TANGGAL adalah tanggal
kunjungan; WAKTU TRANSAKSI adalah saat kasir mencatat pelunasan, yang bisa
jatuh di hari berikutnya. Di laporan contoh ada 29 baris (21 Jemur, 8
Citraland) dengan selisih +1 hari, dua di antaranya +3 hari. Laporan Omnicare
disaring berdasarkan **TANGGAL** (seluruh 1.178 TANGGAL ada di dalam periode,
sementara satu WAKTU TRANSAKSI jatuh di luar periode).

Akibatnya untuk menentukan "kunjungan terakhir" pasien: urutkan dengan
TANGGAL sebagai kunci utama dan WAKTU TRANSAKSI hanya sebagai pemutus di
dalam hari yang sama. Lihat :func:`kunci_urut`. Jangan pernah mengurutkan
dengan WAKTU TRANSAKSI saja, dan jangan pernah mengandaikan keduanya sehari.
"""

from __future__ import annotations

import datetime as _dt
import re
from typing import Final, Iterable

__all__ = [
    "TanggalTidakDikenal",
    "bulan_ke_angka",
    "nama_bulan_id",
    "parse_tanggal",
    "parse_waktu",
    "kunci_urut",
    "ke_iso",
    "dari_iso",
    "parse_periode_laporan",
    "format_periode_id",
    "dalam_periode",
    "tanggal_mungkin_terbalik",
]


class TanggalTidakDikenal(ValueError):
    """Teks tanggal atau nama bulan yang tidak dikenal.

    Sengaja berupa galat, bukan nilai None atau tebakan: PRD mensyaratkan
    format yang tidak dikenal ditolak.
    """


# --------------------------------------------------------------------------
# Nama bulan
# --------------------------------------------------------------------------

#: Nama bulan resmi untuk semua keluaran berbahasa Indonesia (laporan PDF).
NAMA_BULAN_ID: Final[tuple[str, ...]] = (
    "Januari",
    "Februari",
    "Maret",
    "April",
    "Mei",
    "Juni",
    "Juli",
    "Agustus",
    "September",
    "Oktober",
    "November",
    "Desember",
)

# Semua varian yang diterima, termasuk bahasa Inggris, singkatan, dan salah
# tulis yang umum di Indonesia (Pebruari, Nopember). Ditulis eksplisit supaya
# bisa diperiksa mata, bukan dihasilkan otomatis.
_VARIAN: Final[tuple[tuple[int, tuple[str, ...]], ...]] = (
    (1, ("januari", "january", "jan")),
    (2, ("februari", "february", "pebruari", "feb", "febr", "peb")),
    (3, ("maret", "march", "mar", "mrt")),
    (4, ("april", "apr")),
    (5, ("mei", "may")),
    (6, ("juni", "june", "jun")),
    (7, ("juli", "july", "jul")),
    (8, ("agustus", "august", "agu", "ags", "agt", "aug")),
    (9, ("september", "sep", "sept", "spt")),
    (10, ("oktober", "october", "okt", "oct")),
    (11, ("november", "nopember", "nov", "nop")),
    (12, ("desember", "december", "des", "dec", "dez")),
)


def _bangun_alias() -> dict[str, int]:
    tabel: dict[str, int] = {}
    for angka, varian in _VARIAN:
        for v in varian:
            kunci = v.casefold()
            lama = tabel.get(kunci)
            if lama is not None and lama != angka:
                # Dijaga saat impor: satu singkatan tidak boleh menunjuk dua
                # bulan, karena itu justru sumber bug yang ingin dihindari.
                raise AssertionError(
                    f"varian bulan {kunci!r} bentrok: {lama} vs {angka}"
                )
            tabel[kunci] = angka
    return tabel


_ALIAS_BULAN: Final[dict[str, int]] = _bangun_alias()


def bulan_ke_angka(teks: str) -> int:
    """Ubah nama bulan menjadi angka 1-12.

    Menerima bahasa Indonesia dan Inggris, nama penuh dan singkatan, huruf
    besar-kecil apa pun, serta titik di ujung (``Okt.``). Varian yang tidak
    ada di tabel **ditolak**.

    >>> bulan_ke_angka("Oktober"), bulan_ke_angka("OCT"), bulan_ke_angka("okt.")
    (10, 10, 10)
    """
    if not isinstance(teks, str):
        raise TanggalTidakDikenal(f"nama bulan bukan teks: {teks!r}")
    kunci = teks.strip().rstrip(".").casefold()
    if not kunci:
        raise TanggalTidakDikenal("nama bulan kosong")
    try:
        return _ALIAS_BULAN[kunci]
    except KeyError:
        raise TanggalTidakDikenal(f"nama bulan tidak dikenal: {teks!r}") from None


def nama_bulan_id(bulan: int) -> str:
    """Angka 1-12 menjadi nama bulan Indonesia.

    Satu-satunya sumber nama bulan untuk laporan PDF.

    >>> nama_bulan_id(10)
    'Oktober'
    """
    if not isinstance(bulan, int) or isinstance(bulan, bool):
        raise TanggalTidakDikenal(f"nomor bulan bukan bilangan bulat: {bulan!r}")
    if not 1 <= bulan <= 12:
        raise TanggalTidakDikenal(f"nomor bulan di luar 1-12: {bulan!r}")
    return NAMA_BULAN_ID[bulan - 1]


# --------------------------------------------------------------------------
# Tanggal dan waktu dari laporan
# --------------------------------------------------------------------------

# Nol di depan boleh tidak ada (1/9/2026). Itu aman karena urutannya sudah
# dipaku hari/bulan/tahun, jadi tidak ada kerancuan. Bentuk lain ditolak.
_POLA_TANGGAL: Final[re.Pattern[str]] = re.compile(r"\A(\d{1,2})/(\d{1,2})/(\d{4})\Z")
_POLA_WAKTU: Final[re.Pattern[str]] = re.compile(
    r"\A(\d{1,2})/(\d{1,2})/(\d{4})[ \t]+(\d{1,2}):(\d{2})(?::(\d{2}))?\Z"
)


def parse_tanggal(teks: str) -> _dt.date:
    """Baca tanggal laporan Omnicare dengan format tetap dd/mm/yyyy.

    Selalu ditafsirkan hari/bulan/tahun. Nama bulan, pemisah selain ``/``,
    tahun dua angka, dan tanggal bertanggal waktu **ditolak**.

    >>> parse_tanggal("01/09/2026")
    datetime.date(2026, 9, 1)
    """
    if not isinstance(teks, str):
        raise TanggalTidakDikenal(f"tanggal bukan teks: {teks!r}")
    cocok = _POLA_TANGGAL.match(teks.strip())
    if cocok is None:
        raise TanggalTidakDikenal(
            f"tanggal harus berformat dd/mm/yyyy, dapat: {teks!r}"
        )
    hari, bulan, tahun = (int(g) for g in cocok.groups())
    try:
        return _dt.date(tahun, bulan, hari)
    except ValueError as exc:
        raise TanggalTidakDikenal(f"tanggal tidak sah: {teks!r} ({exc})") from None


def parse_waktu(teks: str) -> _dt.datetime:
    """Baca kolom WAKTU TRANSAKSI: ``dd/mm/yyyy HH:MM:SS``.

    Detik boleh tidak ada. Dipakai sebagai pemutus ketika satu pasien punya
    lebih dari satu transaksi di hari yang sama.

    >>> parse_waktu("30/09/2026 22:29:48")
    datetime.datetime(2026, 9, 30, 22, 29, 48)
    """
    if not isinstance(teks, str):
        raise TanggalTidakDikenal(f"waktu bukan teks: {teks!r}")
    cocok = _POLA_WAKTU.match(teks.strip())
    if cocok is None:
        raise TanggalTidakDikenal(
            f"waktu harus berformat dd/mm/yyyy HH:MM:SS, dapat: {teks!r}"
        )
    hari, bulan, tahun, jam, menit = (int(g) for g in cocok.groups()[:5])
    detik = int(cocok.group(6) or 0)
    try:
        return _dt.datetime(tahun, bulan, hari, jam, menit, detik)
    except ValueError as exc:
        raise TanggalTidakDikenal(f"waktu tidak sah: {teks!r} ({exc})") from None


_AWAL_MULA: Final[_dt.datetime] = _dt.datetime(1900, 1, 1)


def kunci_urut(
    tanggal: _dt.date, waktu: _dt.datetime | None = None
) -> tuple[_dt.date, _dt.datetime]:
    """Kunci pengurutan transaksi: TANGGAL utama, WAKTU TRANSAKSI pemutus.

    Dipakai untuk memilih **kunjungan terakhir** pasien dalam satu unggahan.
    TANGGAL mendominasi karena itulah tanggal kunjungan; WAKTU TRANSAKSI
    hanya memutus bila dua transaksi jatuh di TANGGAL yang sama.

    Mengurutkan dengan WAKTU TRANSAKSI saja salah, karena pelunasan bisa
    dicatat di hari berikutnya: kunjungan 20/09 yang dilunasi 21/09 akan
    terlihat lebih baru daripada kunjungan 21/09 yang dilunasi 21/09.

    >>> kunci_urut(_dt.date(2026, 9, 20)) < kunci_urut(_dt.date(2026, 9, 21))
    True
    """
    if isinstance(tanggal, _dt.datetime):
        tanggal = tanggal.date()
    if not isinstance(tanggal, _dt.date):
        raise TanggalTidakDikenal(f"bukan tanggal: {tanggal!r}")
    if waktu is None:
        return (tanggal, _AWAL_MULA)
    if not isinstance(waktu, _dt.datetime):
        raise TanggalTidakDikenal(f"waktu bukan datetime: {waktu!r}")
    return (tanggal, waktu)


def ke_iso(tanggal: _dt.date) -> str:
    """Bentuk simpan di basis data: YYYY-MM-DD.

    >>> ke_iso(_dt.date(2026, 9, 1))
    '2026-09-01'
    """
    if isinstance(tanggal, _dt.datetime):
        tanggal = tanggal.date()
    if not isinstance(tanggal, _dt.date):
        raise TanggalTidakDikenal(f"bukan tanggal: {tanggal!r}")
    return tanggal.isoformat()


def dari_iso(teks: str) -> _dt.date:
    """Baca kembali YYYY-MM-DD dari basis data."""
    if not isinstance(teks, str):
        raise TanggalTidakDikenal(f"tanggal ISO bukan teks: {teks!r}")
    try:
        return _dt.date.fromisoformat(teks.strip())
    except ValueError as exc:
        raise TanggalTidakDikenal(f"tanggal ISO tidak sah: {teks!r} ({exc})") from None


# --------------------------------------------------------------------------
# Periode laporan (baris 0) -- satu-satunya tempat nama bulan muncul
# --------------------------------------------------------------------------

_POLA_PERIODE: Final[re.Pattern[str]] = re.compile(
    r"PER\s+(\d{1,2})\s+([A-Za-z]+)\.?\s+(\d{4})"
    r"\s+S\s*/\s*D\s+(\d{1,2})\s+([A-Za-z]+)\.?\s+(\d{4})",
    re.IGNORECASE,
)


def parse_periode_laporan(teks: str) -> tuple[_dt.date, _dt.date]:
    """Ambil periode dari baris judul laporan Omnicare.

    Ini **satu-satunya** tempat nama bulan dibaca dari laporan. Tanggal di
    nama berkas adalah tanggal ekspor, bukan periode, jadi jangan dipakai.

    >>> parse_periode_laporan(
    ...     "TRANSAKSI PENJUALAN PER 01 SEPTEMBER 2026 S/D 30 SEPTEMBER 2026")
    (datetime.date(2026, 9, 1), datetime.date(2026, 9, 30))
    """
    if not isinstance(teks, str):
        raise TanggalTidakDikenal(f"baris periode bukan teks: {teks!r}")
    cocok = _POLA_PERIODE.search(teks)
    if cocok is None:
        raise TanggalTidakDikenal(f"baris periode tidak dikenali: {teks!r}")
    h1, b1, t1, h2, b2, t2 = cocok.groups()
    awal = _rakit(int(h1), bulan_ke_angka(b1), int(t1), teks)
    akhir = _rakit(int(h2), bulan_ke_angka(b2), int(t2), teks)
    if akhir < awal:
        raise TanggalTidakDikenal(
            f"periode berakhir sebelum dimulai: {awal} .. {akhir} dari {teks!r}"
        )
    return awal, akhir


def _rakit(hari: int, bulan: int, tahun: int, asal: str) -> _dt.date:
    try:
        return _dt.date(tahun, bulan, hari)
    except ValueError as exc:
        raise TanggalTidakDikenal(
            f"tanggal periode tidak sah ({hari}/{bulan}/{tahun}) dari {asal!r}: {exc}"
        ) from None


def format_periode_id(awal: _dt.date, akhir: _dt.date) -> str:
    """Tulis periode dalam bahasa Indonesia untuk laporan PDF.

    >>> format_periode_id(_dt.date(2026, 9, 1), _dt.date(2026, 9, 30))
    '1-30 September 2026'
    >>> format_periode_id(_dt.date(2026, 9, 28), _dt.date(2026, 10, 4))
    '28 September - 4 Oktober 2026'
    """
    if awal > akhir:
        raise TanggalTidakDikenal(f"periode terbalik: {awal} .. {akhir}")
    if (awal.year, awal.month) == (akhir.year, akhir.month):
        if awal.day == akhir.day:
            return f"{awal.day} {nama_bulan_id(awal.month)} {awal.year}"
        return f"{awal.day}-{akhir.day} {nama_bulan_id(awal.month)} {awal.year}"
    if awal.year == akhir.year:
        return (
            f"{awal.day} {nama_bulan_id(awal.month)} - "
            f"{akhir.day} {nama_bulan_id(akhir.month)} {awal.year}"
        )
    return (
        f"{awal.day} {nama_bulan_id(awal.month)} {awal.year} - "
        f"{akhir.day} {nama_bulan_id(akhir.month)} {akhir.year}"
    )


# --------------------------------------------------------------------------
# Pemeriksaan kewajaran, dipakai tahap 1
# --------------------------------------------------------------------------


def dalam_periode(tanggal: _dt.date, awal: _dt.date, akhir: _dt.date) -> bool:
    """Apakah tanggal berada di dalam periode laporan (termasuk ujungnya)."""
    return awal <= tanggal <= akhir


def tanggal_mungkin_terbalik(tanggals: Iterable[_dt.date]) -> bool:
    """Deteksi kemungkinan laporan memakai mm/dd/yyyy, bukan dd/mm/yyyy.

    Satu nilai tunggal tidak bisa membuktikan urutannya: ``09/01/2026`` sah
    dibaca 1 September maupun 9 Januari. Yang bisa diperiksa adalah
    sekumpulan tanggal — bila **tidak satu pun** harinya melebihi 12,
    urutannya tidak bisa dipastikan dan laporan patut dicurigai.

    Dipakai tahap 1 sebagai peringatan saat mengunggah, bukan sebagai
    penolakan, karena laporan satu-dua hari bisa saja memang begitu.
    """
    hari = [t.day for t in tanggals]
    if not hari:
        return False
    return max(hari) <= 12
