"""Perintah baris perintah: siapkan basis data, tambah pengguna, jalankan web.

Contoh::

    uv run python -m joderma_survey siapkan --basis joderma.db
    uv run python -m joderma_survey pengguna --basis joderma.db \\
        --nama hansen --peran direktur
    uv run python -m joderma_survey jalankan --basis joderma.db --porta 8000
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

from . import db as basis
from .cabang import CABANG
from .pengguna import (
    PANJANG_SANDI_MINIMUM,
    PERAN,
    SandiTidakValid,
    buat_pengguna,
    cari_pengguna,
)
from .skema import VERSI_TERBARU


def _siapkan(args: argparse.Namespace) -> int:
    conn = basis.buka(args.basis)
    diterapkan = basis.migrasi(conn)
    if diterapkan:
        print(f"Migrasi diterapkan: {diterapkan}")
    print(f"Versi skema sekarang: {basis.versi_skema(conn)} (terbaru {VERSI_TERBARU})")
    jumlah = conn.execute("SELECT COUNT(*) AS n FROM pengguna").fetchone()["n"]
    if jumlah == 0:
        print(
            "Belum ada pengguna. Tambahkan dengan:\n"
            f"  python -m joderma_survey pengguna --basis {args.basis}"
            " --nama <nama> --peran direktur"
        )
    conn.close()
    return 0


def _pengguna(args: argparse.Namespace) -> int:
    conn = basis.buka(args.basis)
    basis.migrasi(conn)
    if cari_pengguna(conn, args.nama) is not None:
        print(f"Pengguna {args.nama!r} sudah ada.", file=sys.stderr)
        conn.close()
        return 1
    # Panjang diperiksa sebelum minta ulangan, supaya tidak perlu mengetik
    # dua kali hanya untuk ditolak.
    sandi = getpass.getpass(f"Sandi (minimal {PANJANG_SANDI_MINIMUM} karakter): ")
    if len(sandi) < PANJANG_SANDI_MINIMUM:
        print(
            f"Sandi ditolak: baru {len(sandi)} karakter, "
            f"minimal {PANJANG_SANDI_MINIMUM}.",
            file=sys.stderr,
        )
        conn.close()
        return 1
    if sandi != getpass.getpass("Ulangi sandi: "):
        print("Sandi tidak sama.", file=sys.stderr)
        conn.close()
        return 1
    try:
        orang = buat_pengguna(conn, args.nama, args.peran, sandi)
    except SandiTidakValid as galat:
        print(f"Sandi ditolak: {galat}", file=sys.stderr)
        conn.close()
        return 1
    print(f"Pengguna {orang.nama!r} dibuat dengan peran {orang.peran!r}.")
    conn.close()
    return 0


def _jalankan(args: argparse.Namespace) -> int:
    from .web_admin import buat_app

    conn = basis.buka(args.basis)
    basis.migrasi(conn)
    conn.close()
    app = buat_app(args.basis)
    # Hanya untuk pengembangan. Di mini PC dijalankan lewat server WSGI di
    # belakang Cloudflare Tunnel.
    app.run(host=args.alamat, port=args.porta, debug=args.debug)
    return 0


def _pertanyaan(args: argparse.Namespace) -> int:
    from .pertanyaan import (
        KonfigurasiTidakValid,
        bandingkan,
        muat_berkas,
        terapkan,
    )

    try:
        daftar = muat_berkas(args.berkas)
    except KonfigurasiTidakValid as galat:
        print(f"Berkas pertanyaan ditolak: {galat}", file=sys.stderr)
        return 1

    conn = basis.buka(args.basis)
    basis.migrasi(conn)
    try:
        if args.terapkan:
            rencana = terapkan(conn, daftar, ejaan=args.ejaan)
            print(f"Diterapkan dari {args.berkas}:")
        else:
            rencana = bandingkan(conn, daftar, ejaan=args.ejaan)
            print(f"Uji kering dari {args.berkas} (basis data tidak disentuh):")
    except KonfigurasiTidakValid as galat:
        print(f"Ditolak: {galat}", file=sys.stderr)
        return 1
    finally:
        conn.close()

    print(rencana.ringkas())
    if not args.terapkan and rencana.ada_perubahan:
        print()
        print("Jalankan ulang dengan --terapkan untuk menyimpannya.")
        makna = [k for k, _, m in rencana.berubah if m]
        if makna:
            print(
                "Perubahan teks dianggap MENGUBAH MAKNA, sehingga laporan "
                "memotong rangkaian datanya di titik itu."
            )
            print(
                "Bila itu hanya perbaikan ejaan, tambahkan: "
                + " ".join(f"--ejaan {k}" for k in makna)
            )
    return 0


def _cadangan(args: argparse.Namespace) -> int:
    from .cadangan import CadanganGagal, buat_cadangan

    dokumen = list(args.dokumen)
    if not args.tanpa_dokumen and not dokumen:
        # Berkas yang tidak masuk repo publik, jadi inilah satu-satunya
        # salinannya di luar mesin ini.
        for bawaan in ("docs", "config", "PRD Survei Pelanggan JoDerma.md"):
            if Path(bawaan).exists():
                dokumen.append(bawaan)
    try:
        hasil = buat_cadangan(
            args.basis, args.tujuan, dokumen=dokumen, simpan=args.simpan
        )
    except CadanganGagal as galat:
        print(f"Cadangan GAGAL: {galat}", file=sys.stderr)
        return 1
    print(hasil.ringkas())
    return 0


def _ekspor(args: argparse.Namespace) -> int:
    from .ekspor import ekspor
    from .perapian import Periode
    from .tanggal import TanggalTidakDikenal, dari_iso

    periode = None
    if args.awal or args.akhir:
        if not (args.awal and args.akhir):
            print("--awal dan --akhir harus diisi berdua.", file=sys.stderr)
            return 1
        try:
            periode = Periode(dari_iso(args.awal), dari_iso(args.akhir))
        except TanggalTidakDikenal as galat:
            print(f"Tanggal ditolak: {galat}", file=sys.stderr)
            return 1
        if periode.akhir < periode.awal:
            print("Periode berakhir sebelum dimulai.", file=sys.stderr)
            return 1

    conn = basis.buka(args.basis)
    basis.migrasi(conn)
    try:
        hasil = ekspor(
            conn,
            args.folder,
            periode=periode,
            cabang_kode=args.cabang,
            set_pertanyaan=args.set,
            sertakan_dokter=args.sertakan_dokter,
        )
    finally:
        conn.close()
    print(hasil.ringkas())
    print()
    print("Berikan folder itu ke Claude agent, dan minta ia membaca "
          "konteks.md lebih dulu.")
    return 0


def _jalankan_survei(args: argparse.Namespace) -> int:
    from .web_survei import buat_app

    conn = basis.buka(args.basis)
    basis.migrasi(conn)
    conn.close()
    # Aplikasi terpisah dari admin, dan di mini PC dijalankan di porta sendiri
    # yang dipetakan ke subdomain survei lewat Cloudflare Tunnel.
    app = buat_app(args.basis)
    app.run(host=args.alamat, port=args.porta, debug=args.debug)
    return 0


def utama(argv: list[str] | None = None) -> int:
    induk = argparse.ArgumentParser(
        prog="joderma_survey", description="Sistem survei pelanggan JoDerma"
    )
    induk.add_argument(
        "--basis", default="joderma.db", type=Path, help="berkas basis data SQLite"
    )
    anak = induk.add_subparsers(dest="perintah", required=True)

    p = anak.add_parser("siapkan", help="buat atau perbarui skema basis data")
    p.set_defaults(fungsi=_siapkan)

    p = anak.add_parser("pengguna", help="tambah pengguna")
    p.add_argument("--nama", required=True)
    p.add_argument("--peran", required=True, choices=PERAN)
    p.set_defaults(fungsi=_pengguna)

    p = anak.add_parser(
        "pertanyaan",
        help="terapkan isi survei dari berkas konfigurasi",
    )
    p.add_argument("--berkas", default=Path("config/pertanyaan.toml"), type=Path)
    p.add_argument(
        "--terapkan",
        action="store_true",
        help="simpan perubahan; tanpa ini hanya menampilkan uji kering",
    )
    p.add_argument(
        "--ejaan",
        action="append",
        default=[],
        metavar="KODE",
        help="tandai perubahan teks pertanyaan ini sebagai perbaikan ejaan "
        "saja, bukan perubahan makna (boleh diulang)",
    )
    p.set_defaults(fungsi=_pertanyaan)

    p = anak.add_parser("cadangan", help="buat cadangan basis data dan dokumen")
    p.add_argument("--tujuan", default=Path("cadangan"), type=Path)
    p.add_argument(
        "--simpan", default=30, type=int,
        help="jumlah cadangan terbaru yang disisakan (bawaan 30)",
    )
    p.add_argument(
        "--dokumen", action="append", default=[], metavar="JALUR",
        help="berkas atau folder tambahan yang ikut dicadangkan (boleh diulang)",
    )
    p.add_argument(
        "--tanpa-dokumen", action="store_true", dest="tanpa_dokumen",
        help="hanya basis data, tanpa docs/ dan config/",
    )
    p.set_defaults(fungsi=_cadangan)

    p = anak.add_parser("ekspor", help="tulis berkas analisis untuk Claude agent")
    p.add_argument("--folder", default=Path("ekspor"), type=Path)
    p.add_argument("--awal", help="tanggal awal periode, YYYY-MM-DD")
    p.add_argument("--akhir", help="tanggal akhir periode, YYYY-MM-DD")
    p.add_argument("--cabang", choices=sorted(CABANG), help="kode cabang")
    p.add_argument("--set", default="RJ", help="set pertanyaan")
    p.add_argument(
        "--sertakan-dokter",
        action="store_true",
        dest="sertakan_dokter",
        help="sertakan pemetaan kode dokter ke namanya",
    )
    p.set_defaults(fungsi=_ekspor)

    p = anak.add_parser("jalankan", help="jalankan aplikasi admin")
    p.add_argument("--alamat", default="127.0.0.1")
    p.add_argument("--porta", default=8000, type=int)
    p.add_argument("--debug", action="store_true")
    p.set_defaults(fungsi=_jalankan)

    p = anak.add_parser(
        "jalankan-survei",
        help="jalankan halaman survei publik (aplikasi terpisah dari admin)",
    )
    p.add_argument("--alamat", default="127.0.0.1")
    p.add_argument("--porta", default=8001, type=int)
    p.add_argument("--debug", action="store_true")
    p.set_defaults(fungsi=_jalankan_survei)

    args = induk.parse_args(argv)
    return int(args.fungsi(args))


if __name__ == "__main__":
    raise SystemExit(utama())
