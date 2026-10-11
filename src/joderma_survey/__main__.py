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
