"""Isi survei: pembacaan token, pertanyaan, dan penyimpanan jawaban.

Dipisah dari :mod:`web_survei` supaya seluruh aturan bisa diuji tanpa
menjalankan server.

**Inti rancangan privasi (keputusan 4.1).** Saat jawaban disimpan, identitas
pasien tidak ikut. Yang dibuat:

* ``sesi_jawaban`` berisi jawaban beserta **sifat kunjungannya** (cabang,
  layanan, dokter, unggahan) -- semuanya diperlukan untuk pembobotan dan
  laporan, dan tidak satu pun menunjuk orang tertentu.
* ``undangan.diisi_pada`` hanya diisi **tanggal**, cukup untuk aturan 365
  hari dan tidak cukup untuk mencocokkan jawaban dengan orang lewat waktu.
* ``izin_kontak`` dibuat **hanya bila** pasien menjawab boleh dihubungi.
  Itulah satu-satunya baris yang menghubungkan jawaban dengan nomor RM.

Batas yang tidak dijamin rancangan ini dicatat di docs/gaps.md butir G11.
"""

from __future__ import annotations

import datetime as _dt
import enum
import secrets
import sqlite3
from dataclasses import dataclass
from typing import Mapping, Sequence

from .tanggal import dari_iso, ke_iso

__all__ = [
    "StatusLink",
    "Pertanyaan",
    "Undangan",
    "JawabanTidakValid",
    "NILAI_SKALA_MIN",
    "NILAI_SKALA_MAKS",
    "AMBANG_NILAI_RENDAH",
    "periksa_token",
    "pertanyaan_untuk",
    "catat_dibuka",
    "perlu_tampil",
    "simpan_jawaban",
]

NILAI_SKALA_MIN: int = 1
NILAI_SKALA_MAKS: int = 5

#: Jawaban skala sampai nilai ini memunculkan pertanyaan lanjutan.
AMBANG_NILAI_RENDAH: int = 2

#: Panjang maksimal jawaban teks bebas. Cukup lapang untuk keluhan panjang,
#: tapi menolak kiriman yang jelas bukan jawaban survei.
PANJANG_TEKS_MAKS: int = 2000


class StatusLink(enum.StrEnum):
    SIAP = "siap"
    TIDAK_DIKENAL = "tidak_dikenal"
    SUDAH_DIISI = "sudah_diisi"
    KEDALUWARSA = "kedaluwarsa"
    DIBATALKAN = "dibatalkan"


class JawabanTidakValid(ValueError):
    """Kiriman jawaban tidak memenuhi syarat."""


@dataclass(frozen=True)
class Pertanyaan:
    id: int
    kode: str
    revisi: int
    teks: str
    jenis: str
    urutan: int
    wajib: bool
    peran: str
    tampil_bila: str | None

    @property
    def skala(self) -> bool:
        return self.jenis == "skala_1_5"

    @property
    def bersyarat(self) -> bool:
        return self.tampil_bila is not None

    @property
    def izin_kontak(self) -> bool:
        return self.peran == "izin_kontak"


@dataclass(frozen=True)
class Undangan:
    token: str
    rm: str
    nama: str
    cabang_kode: str
    no_faktur: int
    unggahan_id: int
    set_pertanyaan: str
    dibuat_pada: _dt.date
    kedaluwarsa_pada: _dt.date
    diisi_pada: _dt.date | None
    dibatalkan_pada: _dt.date | None


def periksa_token(
    conn: sqlite3.Connection, token: str, hari_ini: _dt.date | None = None
) -> tuple[StatusLink, Undangan | None]:
    """Cari undangan dari token dan tentukan apa yang boleh dilakukan.

    Mengembalikan statusnya supaya halaman publik bisa memberi pesan yang
    tepat (F8), bukan sekadar menolak.
    """
    hari_ini = hari_ini or _dt.date.today()
    if not isinstance(token, str) or not token.strip():
        return StatusLink.TIDAK_DIKENAL, None
    baris = conn.execute(
        "SELECT u.token, u.rm, u.cabang_kode, u.no_faktur, u.unggahan_id,"
        " u.set_pertanyaan, u.dibuat_pada, u.kedaluwarsa_pada, u.diisi_pada,"
        " u.dibatalkan_pada, p.nama_terakhir AS nama"
        " FROM undangan u JOIN pasien p ON p.rm = u.rm WHERE u.token = ?",
        (token,),
    ).fetchone()
    if baris is None:
        return StatusLink.TIDAK_DIKENAL, None

    undangan = Undangan(
        token=baris["token"],
        rm=baris["rm"],
        nama=baris["nama"],
        cabang_kode=baris["cabang_kode"],
        no_faktur=baris["no_faktur"],
        unggahan_id=baris["unggahan_id"],
        set_pertanyaan=baris["set_pertanyaan"],
        dibuat_pada=dari_iso(baris["dibuat_pada"]),
        kedaluwarsa_pada=dari_iso(baris["kedaluwarsa_pada"]),
        diisi_pada=dari_iso(baris["diisi_pada"]) if baris["diisi_pada"] else None,
        dibatalkan_pada=(
            dari_iso(baris["dibatalkan_pada"]) if baris["dibatalkan_pada"] else None
        ),
    )
    # Urutan pemeriksaan penting: link yang sudah diisi tetap berkata "sudah
    # diisi" walau masa berlakunya juga sudah lewat, karena itu pesan yang
    # lebih berguna bagi pasien.
    if undangan.diisi_pada is not None:
        return StatusLink.SUDAH_DIISI, undangan
    if undangan.dibatalkan_pada is not None:
        return StatusLink.DIBATALKAN, undangan
    if hari_ini >= undangan.kedaluwarsa_pada:
        return StatusLink.KEDALUWARSA, undangan
    return StatusLink.SIAP, undangan


def pertanyaan_untuk(
    conn: sqlite3.Connection, set_pertanyaan: str
) -> tuple[Pertanyaan, ...]:
    """Pertanyaan aktif untuk satu set, berurutan.

    Hanya revisi aktif yang diambil; revisi lama tetap tersimpan supaya
    jawaban lama menunjuk teks pertanyaan yang persis dijawab.
    """
    baris = conn.execute(
        "SELECT id, kode, revisi, teks, jenis, urutan, wajib, peran, tampil_bila"
        " FROM pertanyaan WHERE set_pertanyaan = ? AND aktif = 1"
        " ORDER BY urutan, revisi",
        (set_pertanyaan,),
    ).fetchall()
    return tuple(
        Pertanyaan(
            id=b["id"],
            kode=b["kode"],
            revisi=b["revisi"],
            teks=b["teks"],
            jenis=b["jenis"],
            urutan=b["urutan"],
            wajib=bool(b["wajib"]),
            peran=b["peran"],
            tampil_bila=b["tampil_bila"],
        )
        for b in baris
    )


def catat_dibuka(
    conn: sqlite3.Connection, token: str, pada: _dt.date | None = None
) -> bool:
    """Catat bahwa link pernah dibuka. Hanya pembukaan pertama yang dicatat."""
    pada = pada or _dt.date.today()
    cur = conn.execute(
        "UPDATE undangan SET dibuka_pada = ? WHERE token = ? AND dibuka_pada IS NULL",
        (ke_iso(pada), token),
    )
    return bool(cur.rowcount)


def perlu_tampil(
    pertanyaan: Pertanyaan, nilai_skala: Mapping[str, int]
) -> bool:
    """Apakah pertanyaan bersyarat ini seharusnya muncul.

    Kosakatanya sengaja hanya dua: selalu tampil, atau tampil bila ada
    jawaban skala rendah. Keputusan 4.5 hanya punya satu pertanyaan
    bersyarat, jadi penafsir ekspresi tidak akan terpakai.
    """
    if pertanyaan.tampil_bila is None:
        return True
    if pertanyaan.tampil_bila == "ada_nilai_rendah":
        return any(n <= AMBANG_NILAI_RENDAH for n in nilai_skala.values())
    return False


def _baca_skala(pertanyaan: Pertanyaan, mentah: str) -> int:
    try:
        nilai = int(mentah)
    except (TypeError, ValueError):
        raise JawabanTidakValid(
            f"jawaban {pertanyaan.kode!r} harus angka {NILAI_SKALA_MIN}"
            f"-{NILAI_SKALA_MAKS}, dapat {mentah!r}"
        ) from None
    if not NILAI_SKALA_MIN <= nilai <= NILAI_SKALA_MAKS:
        raise JawabanTidakValid(
            f"jawaban {pertanyaan.kode!r} di luar {NILAI_SKALA_MIN}"
            f"-{NILAI_SKALA_MAKS}: {nilai}"
        )
    return nilai


def _baca_ya_tidak(pertanyaan: Pertanyaan, mentah: str) -> int:
    bersih = mentah.strip().casefold()
    if bersih in ("ya", "1", "true", "on"):
        return 1
    if bersih in ("tidak", "0", "false", "off"):
        return 0
    raise JawabanTidakValid(
        f"jawaban {pertanyaan.kode!r} harus ya atau tidak, dapat {mentah!r}"
    )


def simpan_jawaban(
    conn: sqlite3.Connection,
    undangan: Undangan,
    kiriman: Mapping[str, str],
    *,
    hari_ini: _dt.date | None = None,
    durasi_detik: int | None = None,
) -> str:
    """Simpan satu pengisian survei dan tandai undangannya terisi.

    Seluruhnya dalam satu transaksi: kalau ada yang gagal, undangan tidak
    ikut tertandai terisi dan pasien masih bisa mengulang.

    Mengembalikan id sesi jawaban. Id itu **tidak** bisa dipakai menelusuri
    balik ke pasien, kecuali bila pasien mengizinkan lewat pertanyaan izin.
    """
    hari_ini = hari_ini or _dt.date.today()
    daftar = pertanyaan_untuk(conn, undangan.set_pertanyaan)
    if not daftar:
        raise JawabanTidakValid(
            f"tidak ada pertanyaan aktif untuk set {undangan.set_pertanyaan!r}"
        )

    # Dibaca dua lewatan: skala dulu, karena pertanyaan bersyarat bergantung
    # pada nilainya.
    nilai_skala: dict[str, int] = {}
    for p in daftar:
        if not p.skala:
            continue
        mentah = (kiriman.get(p.kode) or "").strip()
        if not mentah:
            if p.wajib:
                raise JawabanTidakValid(f"pertanyaan {p.kode!r} wajib diisi")
            continue
        nilai_skala[p.kode] = _baca_skala(p, mentah)

    tersimpan: list[tuple[int, int | None, str | None]] = []
    izin = False
    for p in daftar:
        mentah = (kiriman.get(p.kode) or "").strip()
        if p.skala:
            if p.kode in nilai_skala:
                tersimpan.append((p.id, nilai_skala[p.kode], None))
            continue
        if not perlu_tampil(p, nilai_skala):
            # Jawaban untuk pertanyaan yang tidak seharusnya muncul diabaikan,
            # bukan ditolak: peramban bisa saja mengirimkannya.
            continue
        if not mentah:
            if p.wajib:
                raise JawabanTidakValid(f"pertanyaan {p.kode!r} wajib diisi")
            continue
        if p.jenis == "ya_tidak":
            nilai = _baca_ya_tidak(p, mentah)
            tersimpan.append((p.id, nilai, None))
            if p.izin_kontak and nilai == 1:
                izin = True
        else:
            if len(mentah) > PANJANG_TEKS_MAKS:
                raise JawabanTidakValid(
                    f"jawaban {p.kode!r} melebihi {PANJANG_TEKS_MAKS} karakter"
                )
            tersimpan.append((p.id, None, mentah))

    sesi_id = secrets.token_urlsafe(16)
    conn.execute("BEGIN")
    try:
        # Dikunci di sini juga, bukan hanya di halaman: dua kiriman yang
        # datang bersamaan tidak boleh keduanya tersimpan.
        cur = conn.execute(
            "UPDATE undangan SET diisi_pada = ? WHERE token = ?"
            " AND diisi_pada IS NULL AND dibatalkan_pada IS NULL",
            (ke_iso(hari_ini), undangan.token),
        )
        if not cur.rowcount:
            raise JawabanTidakValid("link sudah terpakai atau dibatalkan")

        conn.execute(
            "INSERT INTO sesi_jawaban (id, diisi_pada, set_pertanyaan,"
            " cabang_kode, layanan, dokter, unggahan_id, selesai,"
            " berhenti_di_kode, durasi_detik) VALUES (?,?,?,?,?,?,?,1,NULL,?)",
            (
                sesi_id,
                ke_iso(hari_ini),
                undangan.set_pertanyaan,
                undangan.cabang_kode,
                *_sifat_kunjungan(conn, undangan),
                undangan.unggahan_id,
                durasi_detik,
            ),
        )
        conn.executemany(
            "INSERT INTO jawaban (sesi_id, pertanyaan_id, nilai_angka, nilai_teks)"
            " VALUES (?,?,?,?)",
            [(sesi_id, pid, angka, teks) for pid, angka, teks in tersimpan],
        )
        if izin:
            conn.execute(
                "INSERT INTO izin_kontak (sesi_id, rm, dibuat_pada) VALUES (?,?,?)",
                (sesi_id, undangan.rm, ke_iso(hari_ini)),
            )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return sesi_id


def _sifat_kunjungan(
    conn: sqlite3.Connection, undangan: Undangan
) -> tuple[str, str]:
    """Layanan dan dokter kunjungan yang disurvei.

    Disalin ke sesi jawaban karena diperlukan pembobotan dan skor per dokter,
    dan keduanya sifat kunjungan, bukan sifat orang.
    """
    baris = conn.execute(
        "SELECT layanan, dokter FROM transaksi"
        " WHERE cabang_kode = ? AND no_faktur = ?",
        (undangan.cabang_kode, undangan.no_faktur),
    ).fetchone()
    if baris is None:
        return ("", "")
    return (baris["layanan"], baris["dokter"])
