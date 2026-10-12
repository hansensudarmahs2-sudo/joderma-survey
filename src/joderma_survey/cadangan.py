"""Cadangan basis data dan dokumen (F16, gap G1).

**Basis data tidak boleh disalin dengan ``cp``.** Aplikasi berjalan dalam
mode WAL, sehingga isi berkas ``.db`` pada satu saat belum tentu lengkap:
sebagian transaksi masih berada di ``.db-wal`` dan belum dilipat masuk.
Menyalin ketiga berkas satu per satu pada basis data yang sedang dipakai
bisa menghasilkan salinan yang robek dan baru ketahuan saat dibutuhkan.

Karena itu dipakai ``VACUUM INTO``, yang membuat salinan **konsisten pada
satu titik waktu** tanpa menghentikan aplikasi, sekaligus memadatkan
berkasnya. Hasilnya lalu diperiksa dengan ``PRAGMA integrity_check``, supaya
cadangan yang rusak ketahuan saat dibuat, bukan saat dipulihkan.

Pemindahan ke desktop rumah **tidak** dilakukan modul ini. Yang paling masuk
akal untuk mini PC di belakang NAT adalah alat sinkronisasi seperti
Syncthing yang mengawasi folder cadangan; dengan begitu tidak ada kredensial
apa pun yang perlu disimpan di dalam kode ini. Lihat docs/operasional.md.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import shutil
import sqlite3
import tarfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

__all__ = [
    "AWALAN",
    "CadanganGagal",
    "HasilCadangan",
    "buat_cadangan",
    "pangkas",
    "sidik_jari",
]

#: Awalan nama berkas cadangan. Dipakai juga saat memangkas, supaya berkas
#: lain di folder yang sama tidak pernah ikut terhapus.
AWALAN: str = "joderma-"

_POLA_WAKTU = "%Y%m%d-%H%M%S"


class CadanganGagal(RuntimeError):
    """Cadangan tidak bisa dibuat atau hasilnya tidak lolos pemeriksaan."""


@dataclass
class HasilCadangan:
    berkas: Path
    ukuran: int
    sidik: str
    dibuat: _dt.datetime
    dokumen: list[str] = field(default_factory=list)
    dihapus: list[str] = field(default_factory=list)

    @property
    def ukuran_mb(self) -> float:
        return self.ukuran / 1_048_576

    def ringkas(self) -> str:
        baris = [
            f"Cadangan dibuat: {self.berkas}",
            f"  ukuran   : {self.ukuran_mb:.2f} MB",
            f"  sha256   : {self.sidik[:16]}...",
        ]
        if self.dokumen:
            baris.append(f"  dokumen  : {len(self.dokumen)} berkas ikut disertakan")
        if self.dihapus:
            baris.append(f"  dipangkas: {len(self.dihapus)} cadangan lama dihapus")
        return "\n".join(baris)


def sidik_jari(path: Path) -> str:
    """SHA-256 sebuah berkas, dibaca bertahap agar tidak memuat seluruhnya."""
    pencerna = hashlib.sha256()
    with path.open("rb") as f:
        for potong in iter(lambda: f.read(1024 * 1024), b""):
            pencerna.update(potong)
    return pencerna.hexdigest()


def _salin_konsisten(sumber: Path, tujuan: Path) -> None:
    """Salinan basis data yang konsisten, tanpa menghentikan aplikasi."""
    if not sumber.exists():
        raise CadanganGagal(f"basis data tidak ada: {sumber}")
    conn = sqlite3.connect(f"file:{sumber}?mode=ro", uri=True)
    try:
        # VACUUM INTO menolak menimpa berkas yang sudah ada.
        if tujuan.exists():
            tujuan.unlink()
        conn.execute("VACUUM INTO ?", (str(tujuan),))
    except sqlite3.Error as galat:
        raise CadanganGagal(f"gagal menyalin basis data: {galat}") from galat
    finally:
        conn.close()


def _periksa(path: Path) -> None:
    """Pastikan hasil salinannya utuh, sebelum dianggap cadangan yang sah."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        hasil = conn.execute("PRAGMA integrity_check").fetchone()
        if not hasil or hasil[0] != "ok":
            raise CadanganGagal(
                f"salinan tidak lolos integrity_check: {hasil[0] if hasil else '?'}"
            )
        jumlah = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
        ).fetchone()[0]
        if not jumlah:
            raise CadanganGagal("salinan tidak memuat satu tabel pun")
    finally:
        conn.close()


def buat_cadangan(
    basis: str | Path,
    tujuan: str | Path,
    *,
    dokumen: Iterable[str | Path] = (),
    simpan: int = 30,
    sekarang: _dt.datetime | None = None,
) -> HasilCadangan:
    """Buat satu berkas cadangan bertanggal di ``tujuan``.

    Hasilnya ``.tar.gz`` berisi salinan basis data yang konsisten, ditambah
    berkas dokumen yang diminta. Cadangan lama dipangkas, menyisakan
    ``simpan`` berkas terbaru.
    """
    basis, tujuan = Path(basis), Path(tujuan)
    sekarang = sekarang or _dt.datetime.now()
    tujuan.mkdir(parents=True, exist_ok=True)

    stempel = sekarang.strftime(_POLA_WAKTU)
    arsip = tujuan / f"{AWALAN}{stempel}.tar.gz"
    sementara = tujuan / f".{AWALAN}{stempel}.db"

    disertakan: list[str] = []
    try:
        _salin_konsisten(basis, sementara)
        _periksa(sementara)
        with tarfile.open(arsip, "w:gz") as tar:
            tar.add(sementara, arcname=f"{basis.stem}.db")
            for d in dokumen:
                d = Path(d)
                if not d.exists():
                    continue
                if d.is_dir():
                    for anak in sorted(d.rglob("*")):
                        if anak.is_file():
                            tar.add(anak, arcname=str(anak))
                            disertakan.append(str(anak))
                else:
                    tar.add(d, arcname=str(d))
                    disertakan.append(str(d))
    except Exception:
        arsip.unlink(missing_ok=True)
        raise
    finally:
        sementara.unlink(missing_ok=True)

    dihapus = pangkas(tujuan, simpan)
    return HasilCadangan(
        berkas=arsip,
        ukuran=arsip.stat().st_size,
        sidik=sidik_jari(arsip),
        dibuat=sekarang,
        dokumen=disertakan,
        dihapus=dihapus,
    )


def pangkas(folder: str | Path, simpan: int) -> list[str]:
    """Sisakan ``simpan`` cadangan terbaru, hapus selebihnya.

    Hanya berkas berawalan :data:`AWALAN` yang pernah disentuh, supaya isi
    folder lain tidak ikut terhapus kalau foldernya dipakai bersama.
    """
    folder = Path(folder)
    if simpan <= 0 or not folder.is_dir():
        return []
    arsip = sorted(
        (p for p in folder.glob(f"{AWALAN}*.tar.gz") if p.is_file()),
        key=lambda p: p.name,
        reverse=True,
    )
    dihapus: list[str] = []
    for lama in arsip[simpan:]:
        lama.unlink()
        dihapus.append(lama.name)
    return dihapus
