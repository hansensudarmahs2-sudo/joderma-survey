"""Akses basis data SQLite.

Pembagian tugas: modul ini hanya mengambil dan menyimpan. Aturan jeda
30/365 hari ada di :mod:`joderma_survey.aturan` sebagai fungsi murni, supaya
bisa diuji tanpa basis data dan supaya tidak ditulis dua kali dalam SQL.

Khususnya ``terblokir_sampai`` **tidak** dihitung di SQL. Selain lebih sulit
diuji, ``max()`` skalar SQLite menghasilkan NULL bila salah satu argumennya
NULL — tepat keadaan yang terjadi pada undangan yang belum diisi.
"""

from __future__ import annotations

import datetime as _dt
import json
import secrets
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from .aturan import RiwayatUndangan, kedaluwarsa_pada
from .cabang import aturan_untuk_rm
from .parser_omnicare import Laporan
from .skema import MIGRASI, VERSI_TERBARU
from .tanggal import dari_iso, ke_iso

__all__ = [
    "buka",
    "migrasi",
    "versi_skema",
    "HasilSimpan",
    "simpan_laporan",
    "riwayat",
    "riwayat_banyak",
    "buat_token",
    "catat_undangan",
    "batalkan_undangan",
    "PANJANG_TOKEN",
]

#: Panjang token dalam byte acak. 12 byte -> 16 karakter base64-url, sesuai
#: PRD ("sekitar 16 karakter"), dan 96 bit tidak bisa ditebak.
PANJANG_TOKEN: int = 12


def buka(path: str | Path) -> sqlite3.Connection:
    """Buka basis data dan pasang pengaturan yang diperlukan.

    ``foreign_keys`` wajib dinyalakan per sambungan: SQLite mematikannya
    secara bawaan, sehingga REFERENCES tidak ditegakkan tanpa ini.
    """
    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def versi_skema(conn: sqlite3.Connection) -> int:
    """Versi skema yang sudah diterapkan. 0 berarti basis data masih kosong."""
    ada = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='skema_versi'"
    ).fetchone()
    if ada is None:
        return 0
    baris = conn.execute("SELECT MAX(versi) AS v FROM skema_versi").fetchone()
    return int(baris["v"] or 0)


def migrasi(conn: sqlite3.Connection) -> list[int]:
    """Terapkan migrasi yang belum dijalankan. Aman dipanggil berulang.

    ``BEGIN`` dan ``COMMIT`` ditaruh **di dalam** skrip, bukan di sekelilingnya:
    ``executescript()`` melakukan COMMIT implisit sebelum menjalankan skripnya,
    sehingga transaksi yang dibuka dari luar langsung tertutup. Dengan begini
    satu migrasi tetap masuk utuh atau tidak sama sekali, termasuk baris
    penanda versinya.
    """
    conn.execute(
        "CREATE TABLE IF NOT EXISTS skema_versi ("
        " versi INTEGER PRIMARY KEY,"
        " diterapkan_pada TEXT NOT NULL) STRICT"
    )
    sekarang = versi_skema(conn)
    diterapkan: list[int] = []
    for versi, sql in MIGRASI:
        if versi <= sekarang:
            continue
        stempel = _dt.datetime.now().isoformat(timespec="seconds")
        skrip = (
            "BEGIN;\n"
            f"{sql}\n"
            "INSERT INTO skema_versi (versi, diterapkan_pada) VALUES "
            f"({int(versi)}, '{stempel}');\n"
            "COMMIT;\n"
        )
        try:
            conn.executescript(skrip)
        except Exception:
            # ROLLBACK lewat execute(), bukan executescript(), karena yang
            # kedua akan meng-COMMIT pekerjaan separuh jadi lebih dulu.
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        diterapkan.append(versi)
    return diterapkan


# --------------------------------------------------------------------------
# Menyimpan hasil unggahan
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class HasilSimpan:
    unggahan_id: int
    transaksi_baru: int
    transaksi_sudah_ada: int
    pasien_baru: int
    pasien_diperbarui: int

    @property
    def unggahan_ulang(self) -> bool:
        """Seluruh transaksi sudah dikenal: berkas ini sudah pernah diunggah."""
        return self.transaksi_baru == 0 and self.transaksi_sudah_ada > 0


def simpan_laporan(
    conn: sqlite3.Connection, laporan: Laporan, diunggah_pada: _dt.date | None = None
) -> HasilSimpan:
    """Simpan hasil pembacaan satu berkas laporan.

    Transaksi yang sudah dikenal dilewati, bukan menimbulkan galat, sehingga
    mengunggah ulang berkas yang sama aman dan menghasilkan laporan
    "0 transaksi baru". Penangkalnya ``UNIQUE(cabang_kode, no_faktur)``.
    """
    r = laporan.ringkasan
    diunggah_pada = diunggah_pada or _dt.date.today()

    conn.execute("BEGIN")
    try:
        cur = conn.execute(
            "INSERT INTO unggahan (nama_berkas, cabang_kode, periode_awal,"
            " periode_akhir, diunggah_pada, baris_data, baris_dipakai,"
            " pasien_unik, ringkasan) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                r.nama_berkas,
                r.cabang.kode,
                ke_iso(r.periode_awal),  # type: ignore[arg-type]
                ke_iso(r.periode_akhir),  # type: ignore[arg-type]
                ke_iso(diunggah_pada),
                r.baris_data,
                r.baris_dipakai,
                r.pasien_unik,
                json.dumps(
                    {
                        "dilewati": r.dilewati,
                        "layanan": r.layanan,
                        "rm_dinormalisasi": r.rm_dinormalisasi,
                        "rm_tidak_dikenal": r.rm_tidak_dikenal,
                        "keraguan": [
                            {"rm": rm, "nama": nama, "alasan": list(alasan)}
                            for rm, nama, alasan in r.keraguan
                        ],
                        "peringatan": r.peringatan,
                        "baris_catatan_kaki": r.baris_catatan_kaki,
                    },
                    ensure_ascii=False,
                ),
            ),
        )
        unggahan_id = int(cur.lastrowid or 0)

        pasien_baru = pasien_diperbarui = 0
        for rm, baris in _terakhir_per_rm(laporan).items():
            aturan = aturan_untuk_rm(rm)
            awalan = aturan.awalan if aturan else ""
            tgl = ke_iso(baris.tanggal)  # type: ignore[arg-type]
            lama = conn.execute(
                "SELECT rm FROM pasien WHERE rm = ?", (rm,)
            ).fetchone()
            if lama is None:
                conn.execute(
                    "INSERT INTO pasien (rm, nama_terakhir, awalan,"
                    " pertama_terlihat, terakhir_terlihat) VALUES (?,?,?,?,?)",
                    (rm, baris.nama, awalan, tgl, tgl),
                )
                pasien_baru += 1
            else:
                conn.execute(
                    "UPDATE pasien SET nama_terakhir = ?,"
                    " pertama_terlihat = MIN(pertama_terlihat, ?),"
                    " terakhir_terlihat = MAX(terakhir_terlihat, ?) WHERE rm = ?",
                    (baris.nama, tgl, tgl, rm),
                )
                pasien_diperbarui += 1

        baru = ada = 0
        for b in laporan.baris:
            cur = conn.execute(
                "INSERT OR IGNORE INTO transaksi (unggahan_id, cabang_kode,"
                " no_faktur, rm, tanggal, waktu, layanan, dokter, harga)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    unggahan_id,
                    r.cabang.kode,
                    b.no_faktur,
                    b.rm,
                    ke_iso(b.tanggal),  # type: ignore[arg-type]
                    b.waktu.isoformat(timespec="seconds") if b.waktu else None,  # type: ignore[union-attr]
                    b.layanan,
                    b.dokter,
                    b.harga,
                ),
            )
            if cur.rowcount:
                baru += 1
            else:
                ada += 1
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    return HasilSimpan(
        unggahan_id=unggahan_id,
        transaksi_baru=baru,
        transaksi_sudah_ada=ada,
        pasien_baru=pasien_baru,
        pasien_diperbarui=pasien_diperbarui,
    )


def _terakhir_per_rm(laporan: Laporan) -> dict[str, object]:
    return laporan.terakhir_per_pasien()  # type: ignore[return-value]


# --------------------------------------------------------------------------
# Riwayat undangan, untuk aturan jeda
# --------------------------------------------------------------------------


def _ke_riwayat(baris: sqlite3.Row) -> RiwayatUndangan:
    return RiwayatUndangan(
        dibuat_pada=dari_iso(baris["dibuat_pada"]),
        diisi_pada=dari_iso(baris["diisi_pada"]) if baris["diisi_pada"] else None,
        dibatalkan_pada=(
            dari_iso(baris["dibatalkan_pada"]) if baris["dibatalkan_pada"] else None
        ),
    )


def riwayat(conn: sqlite3.Connection, rm: str) -> tuple[RiwayatUndangan, ...]:
    """Seluruh riwayat undangan satu pasien, lintas cabang.

    Aturan jeda berlaku gabungan (keputusan 2.5), jadi tidak disaring cabang.
    """
    baris = conn.execute(
        "SELECT dibuat_pada, diisi_pada, dibatalkan_pada FROM undangan"
        " WHERE rm = ? ORDER BY dibuat_pada",
        (rm,),
    ).fetchall()
    return tuple(_ke_riwayat(b) for b in baris)


def riwayat_banyak(
    conn: sqlite3.Connection, rms: Iterable[str]
) -> dict[str, tuple[RiwayatUndangan, ...]]:
    """Riwayat banyak pasien sekaligus.

    Dipakai saat menyusun daftar kirim untuk ratusan pasien, agar tidak
    menembak satu kueri per pasien.
    """
    daftar = list(dict.fromkeys(rms))
    hasil: dict[str, tuple[RiwayatUndangan, ...]] = {rm: () for rm in daftar}
    if not daftar:
        return hasil
    kumpul: dict[str, list[RiwayatUndangan]] = {}
    # Dipecah agar tidak melewati batas jumlah parameter SQLite.
    for i in range(0, len(daftar), 500):
        potong = daftar[i : i + 500]
        tanda = ",".join("?" * len(potong))
        for b in conn.execute(
            f"SELECT rm, dibuat_pada, diisi_pada, dibatalkan_pada FROM undangan"
            f" WHERE rm IN ({tanda}) ORDER BY dibuat_pada",
            potong,
        ):
            kumpul.setdefault(b["rm"], []).append(_ke_riwayat(b))
    for rm, daftar_riwayat in kumpul.items():
        hasil[rm] = tuple(daftar_riwayat)
    return hasil


# --------------------------------------------------------------------------
# Undangan
# --------------------------------------------------------------------------


def buat_token() -> str:
    """Token acak untuk link survei.

    Memakai :mod:`secrets`, bukan :mod:`random`: token harus tidak bisa
    ditebak walau beberapa token lain sudah diketahui.
    """
    return secrets.token_urlsafe(PANJANG_TOKEN)


def catat_undangan(
    conn: sqlite3.Connection,
    *,
    rm: str,
    cabang_kode: str,
    no_faktur: int,
    unggahan_id: int,
    set_pertanyaan: str = "RJ",
    dibuat_pada: _dt.date | None = None,
    token: str | None = None,
) -> str:
    """Catat satu undangan baru dan kembalikan tokennya.

    ``kedaluwarsa_pada`` disimpan, bukan dihitung saat dibaca, supaya
    undangan lama tetap memakai masa berlaku yang berlaku saat ia dibuat.
    """
    dibuat_pada = dibuat_pada or _dt.date.today()
    token = token or buat_token()
    conn.execute(
        "INSERT INTO undangan (token, rm, cabang_kode, no_faktur, unggahan_id,"
        " set_pertanyaan, dibuat_pada, kedaluwarsa_pada)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (
            token,
            rm,
            cabang_kode,
            no_faktur,
            unggahan_id,
            set_pertanyaan,
            ke_iso(dibuat_pada),
            ke_iso(kedaluwarsa_pada(dibuat_pada)),
        ),
    )
    return token


def batalkan_undangan(
    conn: sqlite3.Connection, token: str, pada: _dt.date | None = None
) -> bool:
    """Batalkan undangan yang belum diisi (keputusan 4.4).

    Dipakai saat CS tidak menemukan kontak pasien di WhatsApp. Pasien kembali
    memenuhi syarat di unggahan berikutnya, karena ia tidak pernah menerima
    apa pun. Undangan yang sudah diisi tidak bisa dibatalkan.
    """
    pada = pada or _dt.date.today()
    cur = conn.execute(
        "UPDATE undangan SET dibatalkan_pada = ?"
        " WHERE token = ? AND diisi_pada IS NULL AND dibatalkan_pada IS NULL",
        (ke_iso(pada), token),
    )
    return bool(cur.rowcount)
