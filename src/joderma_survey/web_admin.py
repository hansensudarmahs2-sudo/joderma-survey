"""Aplikasi web sisi admin: unggah laporan dan daftar kirim CS.

**Aplikasi ini terpisah dari halaman survei publik** (:mod:`web_survei`,
tahap 4). Pemisahannya di tingkat aplikasi, bukan di tingkat rute, sehingga
subdomain survei secara fisik tidak punya kode admin untuk dijangkau. Itu
memenuhi syarat PRD "halaman admin tetap tertutup dan tidak ikut tampil di
subdomain survei" tanpa bergantung pada konfigurasi yang bisa salah.

Hak akses (F14) ditegakkan oleh :func:`perlu` yang membaca
:data:`joderma_survey.pengguna.IZIN`. CS hanya bisa membuka daftar kirim dan
membatalkan undangan; unggah laporan dan hasil survei tertutup untuknya.
"""

from __future__ import annotations

import datetime as _dt
import os
import secrets
import sqlite3
import tempfile
from functools import wraps
from pathlib import Path
from typing import Any, Callable

from flask import (
    Flask,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from . import db as basis
from .awalan import AwalanJalur, rapikan_awalan
from .cabang import CABANG
from .daftar_kirim import buat_undangan, daftar_kirim
from .parser_omnicare import LaporanTidakValid, baca_laporan
from .pengguna import Pengguna, cari_pengguna, masuk
from .perapian import Periode, banding, periode_sebelumnya, rapikan
from .tanggal import TanggalTidakDikenal, dari_iso, format_periode_id

__all__ = ["buat_app"]

#: Batas ukuran berkas unggahan. Laporan sebulan penuh ~300 KB, jadi 16 MB
#: sudah sangat lapang dan tetap menolak berkas yang jelas bukan laporan.
BATAS_UNGGAHAN: int = 16 * 1024 * 1024


def buat_app(
    path_basis: str | Path = "joderma.db", kunci_rahasia: str | None = None
) -> Flask:
    app = Flask(__name__, template_folder="templat")
    app.config["MAX_CONTENT_LENGTH"] = BATAS_UNGGAHAN
    app.config["PATH_BASIS"] = str(path_basis)
    app.secret_key = (
        kunci_rahasia
        or os.environ.get("JODERMA_KUNCI_RAHASIA")
        or secrets.token_hex(32)
    )
    # Kuki sesi hanya untuk jalur admin, yang selalu di balik HTTPS lewat
    # Cloudflare Tunnel.
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("JODERMA_KUKI_AMAN", "1") == "1",
        # Nama kuki dibuat khas, bukan "session" bawaan Flask: aplikasi ini
        # bisa berbagi hostname dengan sistem lain, dan dua aplikasi yang
        # memakai nama kuki sama akan saling menimpa sesi.
        SESSION_COOKIE_NAME="joderma_survei_sesi",
    )

    # Dipasang di bawah awalan jalur bila diminta, supaya bisa berbagi
    # hostname dengan sistem lain dan ikut memakai kebijakan Cloudflare
    # Access yang sudah ada di sana.
    awalan = rapikan_awalan(os.environ.get("JODERMA_AWALAN_ADMIN", ""))
    if awalan:
        # Kuki dibatasi ke awalan ini saja, supaya tidak ikut terkirim ke
        # aplikasi tetangga di hostname yang sama.
        app.config["SESSION_COOKIE_PATH"] = awalan
        # APPLICATION_ROOT sengaja TIDAK diisi. Flask membangun URL dari
        # SCRIPT_NAME yang sudah dipasang lapisan di bawah; mengisi keduanya
        # membuat awalannya terpasang dua kali (/survei/survei/kirim).
        app.wsgi_app = AwalanJalur(app.wsgi_app, awalan)

    # ------------------------------------------------------------------ basis
    def sambungan() -> sqlite3.Connection:
        if "basis" not in g:
            g.basis = basis.buka(app.config["PATH_BASIS"])
        return g.basis

    @app.teardown_appcontext
    def tutup(_exc: BaseException | None) -> None:
        conn = g.pop("basis", None)
        if conn is not None:
            conn.close()

    app.sambungan = sambungan  # type: ignore[attr-defined]

    # ------------------------------------------------------------- pengguna
    def pengguna_aktif() -> Pengguna | None:
        nama = session.get("pengguna")
        if not nama:
            return None
        return cari_pengguna(sambungan(), nama)

    @app.context_processor
    def suntik() -> dict[str, Any]:
        return {"pengguna": pengguna_aktif(), "token_csrf": session.get("csrf", "")}

    # ------------------------------------------------------------------ csrf
    def periksa_csrf() -> None:
        dikirim = request.form.get("csrf", "")
        disimpan = session.get("csrf", "")
        if not disimpan or not secrets.compare_digest(dikirim, disimpan):
            abort(400, "token formulir tidak sah, coba muat ulang halaman")

    @app.before_request
    def jaga_csrf() -> None:
        if request.method == "POST" and request.endpoint != "halaman_masuk":
            periksa_csrf()

    # -------------------------------------------------------------- penjaga
    def perlu(kemampuan: str) -> Callable[..., Any]:
        """Hanya pengguna dengan kemampuan ini yang boleh masuk rute."""

        def pembungkus(fungsi: Callable[..., Any]) -> Callable[..., Any]:
            @wraps(fungsi)
            def dalam(*args: Any, **kw: Any) -> Any:
                orang = pengguna_aktif()
                if orang is None:
                    return redirect(url_for("halaman_masuk", lanjut=request.path))
                if not orang.boleh(kemampuan):
                    abort(403)
                return fungsi(*args, **kw)

            return dalam

        return pembungkus

    # ----------------------------------------------------------------- rute
    @app.route("/masuk", methods=["GET", "POST"])
    def halaman_masuk() -> Any:
        if request.method == "POST":
            orang = masuk(
                sambungan(),
                request.form.get("nama", ""),
                request.form.get("sandi", ""),
            )
            if orang is None:
                # Pesan sengaja tidak menyebut mana yang salah.
                flash("Nama pengguna atau sandi salah.", "galat")
                return render_template("masuk.html"), 401
            session.clear()
            session["pengguna"] = orang.nama
            session["csrf"] = secrets.token_urlsafe(32)
            lanjut = request.args.get("lanjut", "")
            # Hanya jalur internal, supaya tidak bisa dipakai mengarahkan keluar.
            if lanjut.startswith("/") and not lanjut.startswith("//"):
                return redirect(lanjut)
            return redirect(url_for("beranda"))
        return render_template("masuk.html")

    @app.post("/keluar")
    def halaman_keluar() -> Any:
        session.clear()
        return redirect(url_for("halaman_masuk"))

    @app.route("/")
    def beranda() -> Any:
        orang = pengguna_aktif()
        if orang is None:
            return redirect(url_for("halaman_masuk"))
        if orang.boleh("unggah_laporan"):
            return redirect(url_for("halaman_unggah"))
        return redirect(url_for("halaman_kirim"))

    @app.route("/unggah", methods=["GET", "POST"])
    @perlu("unggah_laporan")
    def halaman_unggah() -> Any:
        if request.method == "GET":
            return render_template("unggah.html", cabang=CABANG, riwayat=_riwayat_unggahan(sambungan()))

        berkas = request.files.get("laporan")
        if berkas is None or not berkas.filename:
            flash("Pilih berkas laporan .xls lebih dulu.", "galat")
            return redirect(url_for("halaman_unggah"))

        # Berkas laporan tidak disimpan permanen (PRD bagian Privasi): ditulis
        # ke berkas sementara, dibaca, lalu dihapus.
        suf = Path(berkas.filename).suffix or ".xls"
        fd, sementara = tempfile.mkstemp(prefix="omnicare-", suffix=suf)
        os.close(fd)
        tujuan = Path(sementara).with_name(Path(berkas.filename).name)
        try:
            berkas.save(tujuan)
            Path(sementara).unlink(missing_ok=True)
            try:
                laporan = baca_laporan(tujuan)
            except LaporanTidakValid as galat:
                flash(str(galat), "galat")
                return redirect(url_for("halaman_unggah"))

            conn = sambungan()
            simpan = basis.simpan_laporan(conn, laporan)
            buat = buat_undangan(conn, laporan, simpan.unggahan_id)
        finally:
            tujuan.unlink(missing_ok=True)
            Path(sementara).unlink(missing_ok=True)

        return render_template(
            "hasil_unggah.html",
            ringkasan=laporan.ringkasan,
            simpan=simpan,
            buat=buat,
        )

    @app.route("/kirim")
    @perlu("lihat_daftar_kirim")
    def halaman_kirim() -> Any:
        kode = request.args.get("cabang") or None
        if kode is not None and kode not in CABANG:
            kode = None
        baris = daftar_kirim(sambungan(), cabang_kode=kode)
        return render_template(
            "kirim.html", baris=baris, cabang=CABANG, dipilih=kode,
            hari_ini=_dt.date.today(),
        )

    @app.post("/kirim/<token>/batal")
    @perlu("batalkan_undangan")
    def batalkan(token: str) -> Any:
        if basis.batalkan_undangan(sambungan(), token):
            flash(
                "Undangan dibatalkan. Pasien akan muncul lagi di unggahan "
                "berikutnya.",
                "berhasil",
            )
        else:
            flash("Undangan tidak ditemukan, sudah diisi, atau sudah dibatalkan.", "galat")
        return redirect(url_for("halaman_kirim", cabang=request.args.get("cabang")))

    @app.route("/hasil")
    @perlu("lihat_hasil")
    def halaman_hasil() -> Any:
        """Laporan periode, dirancang untuk dicetak ke PDF dari peramban."""
        conn = sambungan()
        hari_ini = _dt.date.today()
        awal_bawaan = hari_ini.replace(day=1)
        akhir_bawaan = _akhir_bulan(awal_bawaan)
        try:
            awal = dari_iso(request.args["awal"]) if request.args.get("awal") else awal_bawaan
            akhir = dari_iso(request.args["akhir"]) if request.args.get("akhir") else akhir_bawaan
        except TanggalTidakDikenal:
            flash("Tanggal tidak dikenali, memakai bulan berjalan.", "galat")
            awal, akhir = awal_bawaan, akhir_bawaan
        if akhir < awal:
            awal, akhir = akhir, awal

        kode = request.args.get("cabang") or None
        if kode is not None and kode not in CABANG:
            kode = None

        periode = Periode(awal, akhir)
        sekarang = rapikan(conn, periode=periode, cabang_kode=kode)
        lalu = periode_sebelumnya(periode)
        sebelum = rapikan(conn, periode=lalu, cabang_kode=kode)
        if sebelum.terisi == 0:
            sebelum = None

        return render_template(
            "hasil.html",
            r=sekarang,
            sebelum=sebelum,
            perbandingan=banding(sekarang, sebelum),
            periode=periode,
            periode_lalu=lalu,
            sebutan=format_periode_id(awal, akhir),
            sebutan_lalu=format_periode_id(lalu.awal, lalu.akhir),
            cabang=CABANG,
            dipilih=kode,
            dicetak=hari_ini,
        )

    @app.errorhandler(403)
    def tanpa_hak(_galat: Any) -> Any:
        return render_template("galat.html", kode=403,
                               pesan="Halaman ini tidak terbuka untuk peran Anda."), 403

    @app.errorhandler(413)
    def terlalu_besar(_galat: Any) -> Any:
        return render_template("galat.html", kode=413,
                               pesan="Berkas terlalu besar untuk laporan Omnicare."), 413

    return app


def _akhir_bulan(awal: _dt.date) -> _dt.date:
    if awal.month == 12:
        return awal.replace(day=31)
    return awal.replace(month=awal.month + 1, day=1) - _dt.timedelta(days=1)


def _riwayat_unggahan(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT id, nama_berkas, cabang_kode, periode_awal, periode_akhir,"
        " diunggah_pada, baris_dipakai, pasien_unik FROM unggahan"
        " ORDER BY id DESC LIMIT 10"
    ).fetchall()
