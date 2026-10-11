"""Pertanyaan survei dari berkas konfigurasi (F10).

Memenuhi F10 "pertanyaan survei dapat diganti tanpa mengubah kode" tanpa
membuat editor di web. Keputusan 2.13 (editor) dibatalkan karena pertanyaan
yang bisa diubah satu klik mengundang perubahan tak sengaja di tengah
periode, dan itu merusak perbandingan antar periode.

Memakai ``tomllib`` dari pustaka standar, jadi tidak ada dependensi baru.

**Pertanyaan tidak pernah diubah di tempat** (keputusan 2.14). Menyunting
teks membuat **revisi baru** dengan kode yang tetap, dan revisi lama
dinonaktifkan tapi tidak dihapus -- jawaban lama tetap menunjuk teks yang
persis dijawab.

**Perubahan teks dianggap mengubah makna secara bawaan.** Arah itu yang
aman: laporan akan memotong rangkaian datanya, sehingga dua pertanyaan
berbeda tidak pernah diam-diam dibandingkan. Perbaikan ejaan yang benar-benar
tidak mengubah makna ditandai lewat parameter ``ejaan``.
"""

from __future__ import annotations

import datetime as _dt
import sqlite3
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

from .tanggal import ke_iso

__all__ = [
    "JENIS_SAH",
    "PERAN_SAH",
    "TAMPIL_BILA_SAH",
    "BERKAS_BAWAAN",
    "KonfigurasiTidakValid",
    "PertanyaanBerkas",
    "Perubahan",
    "muat_berkas",
    "bandingkan",
    "terapkan",
]

JENIS_SAH: frozenset[str] = frozenset({"skala_1_5", "teks", "ya_tidak"})
PERAN_SAH: frozenset[str] = frozenset({"biasa", "izin_kontak"})
TAMPIL_BILA_SAH: frozenset[str] = frozenset({"ada_nilai_rendah"})

BERKAS_BAWAAN: Path = Path("config/pertanyaan.toml")


class KonfigurasiTidakValid(ValueError):
    """Isi berkas pertanyaan tidak memenuhi syarat."""


@dataclass(frozen=True)
class PertanyaanBerkas:
    set_pertanyaan: str
    kode: str
    teks: str
    jenis: str
    urutan: int
    wajib: bool = False
    peran: str = "biasa"
    tampil_bila: str | None = None

    def sama_isinya(self, baris: sqlite3.Row) -> bool:
        """Apakah isinya sama persis dengan satu baris pertanyaan di basis data."""
        return (
            self.teks == baris["teks"]
            and self.jenis == baris["jenis"]
            and self.urutan == baris["urutan"]
            and self.wajib == bool(baris["wajib"])
            and self.peran == baris["peran"]
            and self.tampil_bila == baris["tampil_bila"]
            and self.set_pertanyaan == baris["set_pertanyaan"]
        )


def muat_berkas(path: str | Path = BERKAS_BAWAAN) -> tuple[PertanyaanBerkas, ...]:
    """Baca dan periksa berkas pertanyaan.

    Urutan pertanyaan mengikuti urutannya di berkas, jadi tidak perlu
    menomori sendiri.
    """
    path = Path(path)
    try:
        isi = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise KonfigurasiTidakValid(f"berkas pertanyaan tidak ada: {path}") from None
    except tomllib.TOMLDecodeError as galat:
        raise KonfigurasiTidakValid(f"{path} bukan TOML yang sah: {galat}") from None

    mentah = isi.get("pertanyaan")
    if not isinstance(mentah, list) or not mentah:
        raise KonfigurasiTidakValid(
            f"{path} harus memuat minimal satu blok [[pertanyaan]]"
        )

    hasil: list[PertanyaanBerkas] = []
    urutan_per_set: dict[str, int] = {}
    for i, baris in enumerate(mentah, start=1):
        if not isinstance(baris, dict):
            raise KonfigurasiTidakValid(f"blok pertanyaan ke-{i} bukan tabel")
        p = _rakit(baris, i, urutan_per_set)
        hasil.append(p)
    _periksa_keseluruhan(hasil, path)
    return tuple(hasil)


def _rakit(
    baris: dict[str, object], nomor: int, urutan_per_set: dict[str, int]
) -> PertanyaanBerkas:
    def wajib_ada(kunci: str) -> str:
        nilai = baris.get(kunci)
        if not isinstance(nilai, str) or not nilai.strip():
            raise KonfigurasiTidakValid(
                f"pertanyaan ke-{nomor}: {kunci!r} wajib diisi dan harus teks"
            )
        return nilai.strip()

    set_p = wajib_ada("set")
    kode = wajib_ada("kode")
    teks = wajib_ada("teks")
    jenis = wajib_ada("jenis")
    if jenis not in JENIS_SAH:
        raise KonfigurasiTidakValid(
            f"pertanyaan {kode!r}: jenis {jenis!r} tidak dikenal. "
            f"Pilihan: {', '.join(sorted(JENIS_SAH))}"
        )

    peran = str(baris.get("peran", "biasa")).strip()
    if peran not in PERAN_SAH:
        raise KonfigurasiTidakValid(
            f"pertanyaan {kode!r}: peran {peran!r} tidak dikenal. "
            f"Pilihan: {', '.join(sorted(PERAN_SAH))}"
        )

    tampil = baris.get("tampil_bila")
    if tampil is not None:
        tampil = str(tampil).strip() or None
    if tampil is not None and tampil not in TAMPIL_BILA_SAH:
        raise KonfigurasiTidakValid(
            f"pertanyaan {kode!r}: tampil_bila {tampil!r} tidak dikenal. "
            f"Pilihan: {', '.join(sorted(TAMPIL_BILA_SAH))}"
        )

    wajib = baris.get("wajib", False)
    if not isinstance(wajib, bool):
        raise KonfigurasiTidakValid(f"pertanyaan {kode!r}: wajib harus true/false")

    asing = set(baris) - {"set", "kode", "teks", "jenis", "wajib", "peran", "tampil_bila"}
    if asing:
        raise KonfigurasiTidakValid(
            f"pertanyaan {kode!r}: kunci tidak dikenal {sorted(asing)}"
        )

    urutan_per_set[set_p] = urutan_per_set.get(set_p, 0) + 1
    return PertanyaanBerkas(
        set_pertanyaan=set_p,
        kode=kode,
        teks=teks,
        jenis=jenis,
        urutan=urutan_per_set[set_p],
        wajib=wajib,
        peran=peran,
        tampil_bila=tampil,
    )


def _periksa_keseluruhan(daftar: Sequence[PertanyaanBerkas], path: Path) -> None:
    kode = [p.kode for p in daftar]
    ganda = sorted({k for k in kode if kode.count(k) > 1})
    if ganda:
        raise KonfigurasiTidakValid(f"{path}: kode pertanyaan berulang: {ganda}")

    for set_p in {p.set_pertanyaan for p in daftar}:
        anggota = [p for p in daftar if p.set_pertanyaan == set_p]
        izin = [p for p in anggota if p.peran == "izin_kontak"]
        if len(izin) > 1:
            raise KonfigurasiTidakValid(
                f"set {set_p!r}: hanya boleh ada satu pertanyaan izin_kontak, "
                f"ada {len(izin)}"
            )
        if izin and izin[0].jenis != "ya_tidak":
            raise KonfigurasiTidakValid(
                f"set {set_p!r}: pertanyaan izin_kontak harus berjenis ya_tidak"
            )
        if not any(p.wajib for p in anggota):
            raise KonfigurasiTidakValid(
                f"set {set_p!r}: minimal satu pertanyaan harus wajib, "
                "kalau tidak ada jawaban yang pasti terkumpul"
            )
        syarat = [p for p in anggota if p.tampil_bila == "ada_nilai_rendah"]
        if syarat and not any(p.jenis == "skala_1_5" for p in anggota):
            raise KonfigurasiTidakValid(
                f"set {set_p!r}: ada pertanyaan bersyarat 'ada_nilai_rendah' "
                "tapi tidak ada pertanyaan skala yang bisa memicunya"
            )


@dataclass
class Perubahan:
    baru: list[str] = field(default_factory=list)
    berubah: list[tuple[str, int, bool]] = field(default_factory=list)
    """(kode, revisi baru, mengubah_makna)"""
    dinonaktifkan: list[str] = field(default_factory=list)
    tetap: list[str] = field(default_factory=list)

    @property
    def ada_perubahan(self) -> bool:
        return bool(self.baru or self.berubah or self.dinonaktifkan)

    def ringkas(self) -> str:
        if not self.ada_perubahan:
            return f"Tidak ada perubahan. {len(self.tetap)} pertanyaan sudah sesuai."
        baris: list[str] = []
        for kode in self.baru:
            baris.append(f"  BARU         {kode}")
        for kode, revisi, makna in self.berubah:
            tanda = "mengubah makna" if makna else "perbaikan ejaan"
            baris.append(f"  REVISI {revisi:<2}    {kode}  ({tanda})")
        for kode in self.dinonaktifkan:
            baris.append(f"  NONAKTIF     {kode}  (jawaban lama tetap tersimpan)")
        if self.tetap:
            baris.append(f"  tetap        {len(self.tetap)} pertanyaan")
        return "\n".join(baris)


def _aktif(conn: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    return {
        b["kode"]: b
        for b in conn.execute("SELECT * FROM pertanyaan WHERE aktif = 1")
    }


def bandingkan(
    conn: sqlite3.Connection,
    daftar: Sequence[PertanyaanBerkas],
    ejaan: Iterable[str] = (),
) -> Perubahan:
    """Bandingkan berkas dengan isi basis data, tanpa mengubah apa pun."""
    hanya_ejaan = set(ejaan)
    aktif = _aktif(conn)
    hasil = Perubahan()
    for p in daftar:
        lama = aktif.get(p.kode)
        if lama is None:
            hasil.baru.append(p.kode)
        elif p.sama_isinya(lama):
            hasil.tetap.append(p.kode)
        else:
            revisi = int(lama["revisi"]) + 1
            makna = p.teks != lama["teks"] and p.kode not in hanya_ejaan
            hasil.berubah.append((p.kode, revisi, makna))
    kode_berkas = {p.kode for p in daftar}
    hasil.dinonaktifkan = sorted(k for k in aktif if k not in kode_berkas)
    return hasil


def terapkan(
    conn: sqlite3.Connection,
    daftar: Sequence[PertanyaanBerkas],
    ejaan: Iterable[str] = (),
    pada: _dt.date | None = None,
) -> Perubahan:
    """Terapkan isi berkas ke basis data.

    Revisi lama dinonaktifkan, tidak dihapus, sehingga jawaban lama tetap
    menunjuk teks pertanyaan yang persis dijawab. Seluruhnya dalam satu
    transaksi.
    """
    pada = pada or _dt.date.today()
    hanya_ejaan = set(ejaan)
    tak_dikenal = hanya_ejaan - {p.kode for p in daftar}
    if tak_dikenal:
        raise KonfigurasiTidakValid(
            f"--ejaan menyebut kode yang tidak ada di berkas: {sorted(tak_dikenal)}"
        )

    rencana = bandingkan(conn, daftar, ejaan)
    if not rencana.ada_perubahan:
        return rencana

    aktif = _aktif(conn)
    conn.execute("BEGIN")
    try:
        for p in daftar:
            lama = aktif.get(p.kode)
            if lama is not None and p.sama_isinya(lama):
                continue
            if lama is not None:
                conn.execute(
                    "UPDATE pertanyaan SET aktif = 0 WHERE id = ?", (lama["id"],)
                )
                revisi = int(lama["revisi"]) + 1
                makna = p.teks != lama["teks"] and p.kode not in hanya_ejaan
            else:
                revisi, makna = 1, False
            conn.execute(
                "INSERT INTO pertanyaan (kode, revisi, set_pertanyaan, teks,"
                " jenis, urutan, wajib, peran, tampil_bila, mengubah_makna,"
                " aktif, dibuat_pada) VALUES (?,?,?,?,?,?,?,?,?,?,1,?)",
                (
                    p.kode, revisi, p.set_pertanyaan, p.teks, p.jenis, p.urutan,
                    int(p.wajib), p.peran, p.tampil_bila, int(makna), ke_iso(pada),
                ),
            )
        for kode in rencana.dinonaktifkan:
            conn.execute(
                "UPDATE pertanyaan SET aktif = 0 WHERE kode = ? AND aktif = 1",
                (kode,),
            )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return rencana
