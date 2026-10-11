"""Pembuatan link survei dan daftar kirim untuk CS (F4, F5, F6).

Alur satu unggahan::

    laporan -> pilih_calon() -> aturan jeda -> buat_undangan() -> daftar_kirim()

Dua hal yang perlu diketahui tentang pemilihan calon:

* **Hanya pasien dengan minimal satu kunjungan RJ** (keputusan 4.3). Pasien
  yang bulan itu hanya membeli produk diparkir sampai set pertanyaan OTC
  dibuat.
* **Link ditempel ke kunjungan RJ terakhir, bukan transaksi terakhir.**
  Set A menanyakan "kunjungan Anda" dan "penjelasan dokter", jadi menempelkan
  faktur pembelian produk akan membuat kolom dokter berisi "-" dan merusak
  skor per dokter. Di laporan contoh ada 59 pasien (41 Jemur, 18 Citraland)
  yang transaksi terakhirnya OTC padahal punya kunjungan RJ.

Pembuatan daftar kirim **aman diulang**: undangan yang baru dibuat hari ini
langsung memblokir pasiennya lewat jeda 30 hari, sehingga menjalankan ulang
pada unggahan yang sama menghasilkan 0 undangan baru.
"""

from __future__ import annotations

import datetime as _dt
import sqlite3
from dataclasses import dataclass
from typing import Sequence

from .aturan import boleh_dikirim, link_masih_berlaku
from .cabang import cabang_dari_kode
from .db import catat_undangan, riwayat_banyak
from .konfigurasi import NAMA_KLINIK, url_survei
from .parser_omnicare import BarisTransaksi, Laporan
from .pembersihan import curiga_bukan_pasien
from .tanggal import dari_iso, format_periode_id, kunci_urut

__all__ = [
    "SET_RJ",
    "Calon",
    "HasilPembuatan",
    "BarisKirim",
    "pilih_calon",
    "buat_undangan",
    "daftar_kirim",
    "teks_pencarian",
    "teks_pesan",
    "TEMPLAT_PESAN",
]

SET_RJ: str = "RJ"


@dataclass(frozen=True)
class Calon:
    """Pasien yang memenuhi syarat dari satu unggahan, sebelum aturan jeda."""

    rm: str
    nama: str
    cabang_kode: str
    no_faktur: int
    tanggal: _dt.date
    dokter: str
    keraguan: tuple[str, ...] = ()


def pilih_calon(laporan: Laporan) -> tuple[Calon, ...]:
    """Pasien yang boleh disurvei dari satu laporan, beserta kunjungan RJ terakhirnya.

    Urutannya tetap (menurut nomor RM) supaya hasilnya bisa diulang.
    """
    per_pasien: dict[str, list[BarisTransaksi]] = {}
    for baris in laporan.baris:
        if baris.layanan != SET_RJ:
            continue
        per_pasien.setdefault(baris.rm, []).append(baris)

    calon: list[Calon] = []
    for rm in sorted(per_pasien):
        terakhir = max(
            per_pasien[rm], key=lambda b: kunci_urut(b.tanggal, b.waktu)  # type: ignore[arg-type]
        )
        calon.append(
            Calon(
                rm=rm,
                nama=terakhir.nama,
                cabang_kode=laporan.ringkasan.cabang.kode,
                no_faktur=terakhir.no_faktur,
                tanggal=terakhir.tanggal,  # type: ignore[arg-type]
                dokter=terakhir.dokter,
                keraguan=terakhir.keraguan,
            )
        )
    return tuple(calon)


@dataclass
class HasilPembuatan:
    dibuat: list[str]
    """Nomor RM yang dibuatkan link."""

    dilewati: dict[str, int]
    """Alasan -> jumlah pasien."""

    rinci_dilewati: list[tuple[str, str, _dt.date | None]]
    """(rm, alasan, terblokir_sampai) untuk ditampilkan bila perlu."""

    calon: int = 0
    diparkir_otc: int = 0

    @property
    def jumlah_dibuat(self) -> int:
        return len(self.dibuat)

    def ringkas(self) -> str:
        baris = [
            f"{self.jumlah_dibuat} link dibuat dari {self.calon} calon",
        ]
        if self.diparkir_otc:
            baris.append(
                f"{self.diparkir_otc} pasien diparkir: hanya membeli produk, "
                f"set pertanyaan OTC belum ada"
            )
        for alasan, jumlah in sorted(self.dilewati.items()):
            baris.append(f"dilewati {jumlah} -> {alasan}")
        return "\n".join(baris)


def buat_undangan(
    conn: sqlite3.Connection,
    laporan: Laporan,
    unggahan_id: int,
    hari_ini: _dt.date | None = None,
) -> HasilPembuatan:
    """Terapkan aturan jeda lalu catat undangan untuk pasien yang lolos.

    Seluruh undangan dicatat dalam satu transaksi: kalau ada yang gagal,
    tidak ada link setengah jadi yang sudah memblokir pasien.
    """
    hari_ini = hari_ini or _dt.date.today()
    calon = pilih_calon(laporan)

    semua_rm = {b.rm for b in laporan.baris}
    diparkir = len(semua_rm) - len(calon)

    hasil = HasilPembuatan(
        dibuat=[], dilewati={}, rinci_dilewati=[], calon=len(calon),
        diparkir_otc=diparkir,
    )
    if not calon:
        return hasil

    riwayat = riwayat_banyak(conn, (c.rm for c in calon))

    conn.execute("BEGIN")
    try:
        for c in calon:
            keputusan = boleh_dikirim(riwayat[c.rm], hari_ini)
            if not keputusan.boleh:
                hasil.dilewati[keputusan.alasan] = (
                    hasil.dilewati.get(keputusan.alasan, 0) + 1
                )
                hasil.rinci_dilewati.append(
                    (c.rm, keputusan.alasan, keputusan.terblokir_sampai)
                )
                continue
            catat_undangan(
                conn,
                rm=c.rm,
                cabang_kode=c.cabang_kode,
                no_faktur=c.no_faktur,
                unggahan_id=unggahan_id,
                set_pertanyaan=SET_RJ,
                dibuat_pada=hari_ini,
            )
            hasil.dibuat.append(c.rm)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return hasil


# --------------------------------------------------------------------------
# Teks siap salin
# --------------------------------------------------------------------------

#: Templat pesan WhatsApp. Sengaja satu tempat supaya mudah disunting.
#:
#: Rumusannya mengikuti metodologi bagian 8: menyebut lamanya pengisian dan
#: tujuannya, tanpa imbalan apa pun. Janji soal anonimitas ditulis persis
#: sesuai kenyataan rancangan basis data (keputusan 4.1) -- jawaban memang
#: tidak disimpan bersama nama, dan penautan hanya terjadi bila pasien
#: mengizinkannya di akhir survei.
TEMPLAT_PESAN: str = """Halo {nama}, terima kasih sudah berkunjung ke {klinik} {cabang}.

Boleh kami minta waktu sekitar 1 menit untuk mengisi survei singkat? Masukan Anda kami pakai untuk memperbaiki layanan. Jawaban Anda tidak kami simpan bersama nama Anda.

{url}

Link ini khusus untuk Anda dan berlaku sampai {kedaluwarsa}."""


def teks_pencarian(nama: str, rm: str) -> str:
    """Teks untuk dicari CS di kotak pencarian WhatsApp (keputusan 2.11).

    >>> teks_pencarian("Ade Wijaya", "J00635")
    'Ade Wijaya - J00635'
    """
    return f"{nama} - {rm}"


def teks_pesan(
    nama: str, cabang_nama: str, url: str, kedaluwarsa: _dt.date
) -> str:
    """Isi pesan siap salin untuk ditempel ke WhatsApp."""
    return TEMPLAT_PESAN.format(
        nama=nama,
        klinik=NAMA_KLINIK,
        cabang=cabang_nama,
        url=url,
        kedaluwarsa=format_periode_id(kedaluwarsa, kedaluwarsa),
    )


@dataclass(frozen=True)
class BarisKirim:
    """Satu baris di daftar kirim CS."""

    rm: str
    nama: str
    cabang_nama: str
    token: str
    url: str
    teks_pencarian: str
    teks_pesan: str
    dibuat_pada: _dt.date
    kedaluwarsa_pada: _dt.date
    keraguan: tuple[str, ...] = ()

    def sisa_hari(self, hari_ini: _dt.date | None = None) -> int:
        """Berapa hari lagi link ini bisa dibuka pasien."""
        hari_ini = hari_ini or _dt.date.today()
        return (self.kedaluwarsa_pada - hari_ini).days


def daftar_kirim(
    conn: sqlite3.Connection,
    *,
    unggahan_id: int | None = None,
    cabang_kode: str | None = None,
    hari_ini: _dt.date | None = None,
) -> tuple[BarisKirim, ...]:
    """Undangan yang masih perlu dikirim CS.

    Hanya yang belum diisi, belum dibatalkan, dan belum kedaluwarsa. Diambil
    dari basis data, bukan dibuat ulang, supaya CS bisa membuka daftar yang
    sama berulang kali dan menyalin link yang persis sama.
    """
    hari_ini = hari_ini or _dt.date.today()
    syarat = ["u.diisi_pada IS NULL", "u.dibatalkan_pada IS NULL"]
    nilai: list[object] = []
    if unggahan_id is not None:
        syarat.append("u.unggahan_id = ?")
        nilai.append(unggahan_id)
    if cabang_kode is not None:
        syarat.append("u.cabang_kode = ?")
        nilai.append(cabang_kode)

    baris = conn.execute(
        "SELECT u.token, u.rm, u.cabang_kode, u.dibuat_pada, u.kedaluwarsa_pada,"
        " p.nama_terakhir AS nama"
        " FROM undangan u JOIN pasien p ON p.rm = u.rm"
        f" WHERE {' AND '.join(syarat)}"
        " ORDER BY p.nama_terakhir, u.rm",
        nilai,
    ).fetchall()

    hasil: list[BarisKirim] = []
    for b in baris:
        dibuat = dari_iso(b["dibuat_pada"])
        kedaluwarsa = dari_iso(b["kedaluwarsa_pada"])
        if hari_ini >= kedaluwarsa:
            continue
        cabang = cabang_dari_kode(b["cabang_kode"])
        url = url_survei(b["token"])
        hasil.append(
            BarisKirim(
                rm=b["rm"],
                nama=b["nama"],
                cabang_nama=cabang.nama,
                token=b["token"],
                url=url,
                teks_pencarian=teks_pencarian(b["nama"], b["rm"]),
                teks_pesan=teks_pesan(b["nama"], cabang.nama, url, kedaluwarsa),
                dibuat_pada=dibuat,
                kedaluwarsa_pada=kedaluwarsa,
                # Dihitung ulang dari nama yang tersimpan, bukan diambil dari
                # ringkasan unggahan, supaya daftar kirim selalu mengikuti
                # heuristik yang berlaku sekarang.
                keraguan=curiga_bukan_pasien(b["nama"], b["rm"]),
            )
        )
    return tuple(hasil)
