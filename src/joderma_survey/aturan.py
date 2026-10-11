"""Aturan kelayakan pengiriman survei.

Fungsi murni tanpa basis data, supaya bisa diuji tanpa menyiapkan apa pun.
Pengambilan riwayat dari basis data ada di :mod:`joderma_survey.db`.

Aturan (keputusan 3 di docs/keputusan.md)::

    Pasien boleh dibuatkan link baru bila:  hari_ini >= terblokir_sampai

    terblokir_sampai = yang paling akhir dari:
        diisi_pada_terakhir  + 365 hari     (bila pernah mengisi)
        dibuat_pada_terakhir +  30 hari     (bila pernah dibuatkan link)

    Tanpa riwayat sama sekali -> langsung boleh.

Dua sifat yang dijaga di sini:

1. **Dihitung saat ditanya, tidak disimpan.** Tidak ada kolom yang harus
   dibalik setiap hari, jadi tidak ada penjadwal yang bisa mati tanpa
   ketahuan.
2. **Masa berlaku link dan jeda belum-mengisi adalah peristiwa yang sama
   persis** (keputusan 2.1). "Link kedaluwarsa" dan "jeda habis" terjadi di
   hari yang sama, sehingga tidak ada rentang waktu di mana pasien tidak
   punya link yang bisa dibuka **dan** belum boleh dibuatkan yang baru.
   Dijaga oleh ``test_tidak_ada_rentang_mati``.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from typing import Iterable, Sequence

__all__ = [
    "JEDA_BELUM_MENGISI",
    "JEDA_SUDAH_MENGISI",
    "MASA_BERLAKU_LINK",
    "RiwayatUndangan",
    "Keputusan",
    "kedaluwarsa_pada",
    "link_masih_berlaku",
    "terblokir_sampai",
    "boleh_dikirim",
]

#: Jeda bila sudah dikirimi tapi belum mengisi.
JEDA_BELUM_MENGISI: int = 30

#: Jeda bila sudah mengisi.
JEDA_SUDAH_MENGISI: int = 365

#: Masa berlaku link. Sengaja sama dengan JEDA_BELUM_MENGISI — lihat docstring
#: modul. Kalau salah satu diubah tanpa yang lain, akan muncul rentang waktu
#: di mana pasien tidak bisa membuka link lamanya dan belum boleh dapat yang
#: baru. Itulah kekeliruan yang diperbaiki di keputusan 2.1.
MASA_BERLAKU_LINK: int = 30


@dataclass(frozen=True)
class RiwayatUndangan:
    """Satu baris riwayat undangan, secukupnya untuk menerapkan aturan."""

    dibuat_pada: _dt.date
    diisi_pada: _dt.date | None = None
    dibatalkan_pada: _dt.date | None = None

    @property
    def sudah_diisi(self) -> bool:
        return self.diisi_pada is not None

    @property
    def dibatalkan(self) -> bool:
        """Dibatalkan dan belum diisi.

        Undangan yang sudah diisi tidak bisa dianggap batal: pengisian tidak
        bisa ditarik kembali, jadi jeda 365 hari tetap berlaku.
        """
        return self.dibatalkan_pada is not None and not self.sudah_diisi


@dataclass(frozen=True)
class Keputusan:
    boleh: bool
    alasan: str
    terblokir_sampai: _dt.date | None = None

    def __bool__(self) -> bool:
        return self.boleh


def kedaluwarsa_pada(dibuat_pada: _dt.date) -> _dt.date:
    """Tanggal link berhenti bisa dibuka.

    >>> kedaluwarsa_pada(_dt.date(2026, 10, 11))
    datetime.date(2026, 11, 10)
    """
    return dibuat_pada + _dt.timedelta(days=MASA_BERLAKU_LINK)


def link_masih_berlaku(undangan: RiwayatUndangan, hari_ini: _dt.date) -> bool:
    """Apakah link masih bisa dibuka pasien hari ini.

    Link sekali pakai: yang sudah diisi tidak berlaku lagi. Yang dibatalkan
    juga tidak.
    """
    if undangan.sudah_diisi or undangan.dibatalkan_pada is not None:
        return False
    return hari_ini < kedaluwarsa_pada(undangan.dibuat_pada)


def _batas_blokir(undangan: RiwayatUndangan) -> list[_dt.date]:
    if undangan.diisi_pada is not None:
        return [
            undangan.diisi_pada + _dt.timedelta(days=JEDA_SUDAH_MENGISI),
            undangan.dibuat_pada + _dt.timedelta(days=JEDA_BELUM_MENGISI),
        ]
    if undangan.dibatalkan_pada is not None:
        # Link dibatalkan sebelum terkirim (keputusan 4.4): pasien tidak
        # pernah menerima apa pun, jadi tidak perlu diblokir.
        return []
    return [undangan.dibuat_pada + _dt.timedelta(days=JEDA_BELUM_MENGISI)]


def terblokir_sampai(riwayat: Iterable[RiwayatUndangan]) -> _dt.date | None:
    """Tanggal paling awal pasien boleh dibuatkan link lagi.

    ``None`` berarti tidak ada yang memblokir.

    >>> terblokir_sampai([])  # belum pernah
    >>> terblokir_sampai([RiwayatUndangan(dibuat_pada=_dt.date(2026, 10, 1))])
    datetime.date(2026, 10, 31)
    """
    batas: list[_dt.date] = []
    for undangan in riwayat:
        batas.extend(_batas_blokir(undangan))
    return max(batas) if batas else None


def _alasan_blokir(
    riwayat: Sequence[RiwayatUndangan], batas: _dt.date
) -> str:
    """Jelaskan apa yang memblokir, untuk ringkasan daftar kirim."""
    pengisian = [u.diisi_pada for u in riwayat if u.diisi_pada is not None]
    if pengisian:
        terakhir = max(pengisian)
        if terakhir + _dt.timedelta(days=JEDA_SUDAH_MENGISI) == batas:
            return f"sudah mengisi pada {terakhir.isoformat()}"
    aktif = [u.dibuat_pada for u in riwayat if not u.dibatalkan]
    if aktif:
        return f"link masih aktif, dibuat {max(aktif).isoformat()}"
    return "masih dalam masa jeda"


def boleh_dikirim(
    riwayat: Sequence[RiwayatUndangan], hari_ini: _dt.date
) -> Keputusan:
    """Apakah pasien ini boleh dibuatkan link survei hari ini.

    >>> boleh_dikirim([], _dt.date(2026, 10, 11)).boleh
    True
    >>> riwayat = [RiwayatUndangan(dibuat_pada=_dt.date(2026, 10, 1))]
    >>> boleh_dikirim(riwayat, _dt.date(2026, 10, 30)).boleh
    False
    >>> boleh_dikirim(riwayat, _dt.date(2026, 10, 31)).boleh
    True
    """
    batas = terblokir_sampai(riwayat)
    if batas is None:
        return Keputusan(True, "belum pernah dibuatkan link")
    if hari_ini >= batas:
        return Keputusan(True, "masa jeda sudah lewat", batas)
    return Keputusan(False, _alasan_blokir(riwayat, batas), batas)
