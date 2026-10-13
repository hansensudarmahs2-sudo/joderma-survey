"""Pengguna, sandi, dan hak akses (F14).

Sejak 13 Okt 2026 login web aplikasi admin memakai sesi aplikasi ops
(:mod:`joderma_survey.sesi_ops`). Yang tetap dipakai web dari modul ini hanya
:data:`IZIN` (peran -> kemampuan) dan :class:`Pengguna`. Tabel ``pengguna``
beserta fungsi sandi di bawah tinggal dipakai perintah CLI ``pengguna``.

Sandi disimpan sebagai turunan scrypt dari :mod:`hashlib` — pustaka standar,
jadi tidak perlu dependensi tambahan. Garam dibuat acak per pengguna, dan
pembandingan memakai :func:`secrets.compare_digest` supaya lamanya proses
tidak membocorkan berapa karakter yang sudah benar.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import secrets
import sqlite3
from dataclasses import dataclass
from typing import Final

from .tanggal import ke_iso

__all__ = [
    "PERAN",
    "KEMAMPUAN",
    "IZIN",
    "Pengguna",
    "SandiTidakValid",
    "hash_sandi",
    "periksa_sandi",
    "buat_pengguna",
    "cari_pengguna",
    "masuk",
    "boleh",
]

PERAN: Final[tuple[str, ...]] = ("owner", "direktur", "cs")

KEMAMPUAN: Final[tuple[str, ...]] = (
    "unggah_laporan",
    "lihat_daftar_kirim",
    "batalkan_undangan",
    "lihat_hasil",
    "kelola_pertanyaan",
    "kelola_pengguna",
)

#: Hak akses per peran (F14): unggah laporan dan hasil survei hanya untuk
#: owner dan direktur, CS hanya daftar kirim.
#:
#: Catatan: F14 menyebut owner boleh mengunggah laporan, sementara tabel peran
#: di PRD menggambarkan owner hanya membaca laporan. Yang dipakai di sini F14,
#: karena itu kebutuhan fungsional yang mengikat. Pengelolaan pengguna tetap
#: di direktur, yang di PRD disebut "mengelola sistem".
IZIN: Final[dict[str, frozenset[str]]] = {
    "owner": frozenset(
        {"unggah_laporan", "lihat_daftar_kirim", "batalkan_undangan",
         "lihat_hasil", "kelola_pertanyaan"}
    ),
    "direktur": frozenset(KEMAMPUAN),
    "cs": frozenset({"lihat_daftar_kirim", "batalkan_undangan"}),
}

_SCRYPT_N: Final[int] = 2**14
_SCRYPT_R: Final[int] = 8
_SCRYPT_P: Final[int] = 1
_PANJANG_KUNCI: Final[int] = 32
_PANJANG_GARAM: Final[int] = 16

#: Sandi terlalu pendek mudah ditebak walau di-hash dengan baik.
PANJANG_SANDI_MINIMUM: Final[int] = 10


class SandiTidakValid(ValueError):
    """Sandi tidak memenuhi syarat paling dasar."""


@dataclass(frozen=True)
class Pengguna:
    id: int
    nama: str
    peran: str
    aktif: bool

    def boleh(self, kemampuan: str) -> bool:
        return boleh(self.peran, kemampuan)


def boleh(peran: str, kemampuan: str) -> bool:
    """Apakah peran ini punya kemampuan tersebut.

    Kemampuan yang tidak dikenal selalu ditolak, supaya salah tulis nama
    kemampuan tidak diam-diam membuka akses.

    >>> boleh("cs", "lihat_daftar_kirim"), boleh("cs", "lihat_hasil")
    (True, False)
    >>> boleh("cs", "kemampuan_salah_tulis")
    False
    """
    if kemampuan not in KEMAMPUAN:
        return False
    return kemampuan in IZIN.get(peran, frozenset())


def hash_sandi(sandi: str, garam: bytes | None = None) -> str:
    """Ubah sandi menjadi bentuk simpan ``scrypt$n$r$p$garam$kunci``."""
    if not isinstance(sandi, str) or len(sandi) < PANJANG_SANDI_MINIMUM:
        raise SandiTidakValid(
            f"sandi harus teks minimal {PANJANG_SANDI_MINIMUM} karakter"
        )
    garam = garam or secrets.token_bytes(_PANJANG_GARAM)
    kunci = hashlib.scrypt(
        sandi.encode("utf-8"),
        salt=garam,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_PANJANG_KUNCI,
        maxmem=64 * 1024 * 1024,
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${garam.hex()}${kunci.hex()}"


def periksa_sandi(sandi: str, tersimpan: str) -> bool:
    """Bandingkan sandi dengan bentuk simpannya."""
    if not isinstance(sandi, str) or not isinstance(tersimpan, str):
        return False
    bagian = tersimpan.split("$")
    if len(bagian) != 6 or bagian[0] != "scrypt":
        return False
    try:
        n, r, p = int(bagian[1]), int(bagian[2]), int(bagian[3])
        garam = bytes.fromhex(bagian[4])
        kunci = bytes.fromhex(bagian[5])
    except ValueError:
        return False
    try:
        hitung = hashlib.scrypt(
            sandi.encode("utf-8"),
            salt=garam,
            n=n,
            r=r,
            p=p,
            dklen=len(kunci),
            maxmem=64 * 1024 * 1024,
        )
    except ValueError:
        return False
    return secrets.compare_digest(hitung, kunci)


def buat_pengguna(
    conn: sqlite3.Connection, nama: str, peran: str, sandi: str
) -> Pengguna:
    """Tambah pengguna baru."""
    if peran not in PERAN:
        raise ValueError(f"peran tidak dikenal: {peran!r}. Pilihan: {PERAN}")
    nama = nama.strip()
    if not nama:
        raise ValueError("nama pengguna kosong")
    cur = conn.execute(
        "INSERT INTO pengguna (nama, peran, hash_sandi, aktif, dibuat_pada)"
        " VALUES (?,?,?,1,?)",
        (nama, peran, hash_sandi(sandi), ke_iso(_dt.date.today())),
    )
    return Pengguna(id=int(cur.lastrowid or 0), nama=nama, peran=peran, aktif=True)


def cari_pengguna(conn: sqlite3.Connection, nama: str) -> Pengguna | None:
    baris = conn.execute(
        "SELECT id, nama, peran, aktif FROM pengguna WHERE nama = ?",
        (nama.strip(),),
    ).fetchone()
    if baris is None:
        return None
    return Pengguna(
        id=baris["id"],
        nama=baris["nama"],
        peran=baris["peran"],
        aktif=bool(baris["aktif"]),
    )


def masuk(conn: sqlite3.Connection, nama: str, sandi: str) -> Pengguna | None:
    """Periksa nama dan sandi. ``None`` bila gagal.

    Sandi tetap diperiksa walau penggunanya tidak ada, supaya lamanya proses
    tidak membocorkan nama pengguna mana yang terdaftar.
    """
    baris = conn.execute(
        "SELECT id, nama, peran, aktif, hash_sandi FROM pengguna WHERE nama = ?",
        (nama.strip(),),
    ).fetchone()
    palsu = (
        "scrypt$16384$8$1$" + "00" * _PANJANG_GARAM + "$" + "00" * _PANJANG_KUNCI
    )
    cocok = periksa_sandi(sandi, baris["hash_sandi"] if baris else palsu)
    if baris is None or not cocok or not baris["aktif"]:
        return None
    return Pengguna(
        id=baris["id"],
        nama=baris["nama"],
        peran=baris["peran"],
        aktif=True,
    )
