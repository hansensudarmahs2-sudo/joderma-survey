"""Aplikasi web halaman survei publik.

**Aplikasi ini sama sekali terpisah dari admin** (:mod:`web_admin`). Tidak
ada rute admin di sini, tidak ada login, dan tidak ada pencarian pasien.
Subdomain survei menjalankan aplikasi ini saja, sehingga halaman admin
secara fisik tidak bisa dijangkau dari sana walau aturan proxy salah
dikonfigurasi (PRD bagian Infrastruktur).

Yang dijaga di sini:

* **Token tidak boleh bocor lewat Referer.** Alamat halaman memuat token,
  jadi ``Referrer-Policy: no-referrer`` dipasang dan tidak ada satu pun
  tautan keluar di halamannya.
* **Tidak diindeks mesin pencari**, lewat ``X-Robots-Tag`` dan meta robots.
* **Tidak ada CSRF token.** Di halaman ini tidak ada gunanya: token di
  alamatlah satu-satunya kredensial, dan penyerang yang sudah memilikinya
  bisa mengisi survei secara langsung.
* **Pesan ramah** untuk link terpakai, kedaluwarsa, dibatalkan, atau salah
  (F8), tanpa membocorkan apakah token itu pernah ada.
"""

from __future__ import annotations

import datetime as _dt
import time
from pathlib import Path
from typing import Any

from flask import Flask, abort, g, redirect, render_template, request, url_for

from . import db as basis
from .cabang import CABANG
from .konfigurasi import NAMA_KLINIK
from .survei import (
    AMBANG_NILAI_RENDAH,
    JawabanTidakValid,
    StatusLink,
    catat_dibuka,
    periksa_token,
    pertanyaan_untuk,
    simpan_jawaban,
)

__all__ = ["buat_app", "PESAN_STATUS"]

#: Pesan untuk tiap keadaan link (F8). Disusun agar tidak menyalahkan pasien
#: dan selalu memberi langkah berikutnya.
PESAN_STATUS: dict[str, tuple[str, str]] = {
    StatusLink.SUDAH_DIISI: (
        "Survei ini sudah terisi",
        "Terima kasih, masukan Anda sudah kami terima. Setiap link hanya bisa "
        "dipakai sekali.",
    ),
    StatusLink.KEDALUWARSA: (
        "Masa berlaku link sudah lewat",
        "Link survei berlaku 30 hari sejak dibuat. Bila Anda masih ingin "
        "menyampaikan masukan, silakan hubungi klinik dan kami akan "
        "mengirimkan link baru.",
    ),
    StatusLink.DIBATALKAN: (
        "Link tidak berlaku lagi",
        "Silakan hubungi klinik bila Anda masih ingin menyampaikan masukan.",
    ),
    StatusLink.TIDAK_DIKENAL: (
        "Link tidak dikenali",
        "Alamatnya mungkin terpotong saat disalin. Coba buka kembali link "
        "lengkap dari pesan yang Anda terima.",
    ),
}


def buat_app(path_basis: str | Path = "joderma.db") -> Flask:
    app = Flask(__name__, template_folder="templat")
    app.config["PATH_BASIS"] = str(path_basis)
    # Kiriman survei paling besar pun hanya beberapa kilobyte.
    app.config["MAX_CONTENT_LENGTH"] = 256 * 1024

    def sambungan() -> Any:
        if "basis" not in g:
            g.basis = basis.buka(app.config["PATH_BASIS"])
        return g.basis

    @app.teardown_appcontext
    def tutup(_exc: BaseException | None) -> None:
        conn = g.pop("basis", None)
        if conn is not None:
            conn.close()

    app.sambungan = sambungan  # type: ignore[attr-defined]

    @app.after_request
    def kepala_aman(jawab: Any) -> Any:
        # Token ada di alamat; tanpa ini alamat lengkap ikut terkirim ke
        # situs lain bila ada tautan keluar atau sumber daya eksternal.
        jawab.headers["Referrer-Policy"] = "no-referrer"
        jawab.headers["X-Robots-Tag"] = "noindex, nofollow"
        jawab.headers["X-Content-Type-Options"] = "nosniff"
        jawab.headers["Cache-Control"] = "no-store"
        return jawab

    def _pesan(status: StatusLink, kode: int = 200) -> Any:
        judul, keterangan = PESAN_STATUS[status]
        return (
            render_template(
                "survei_pesan.html", judul=judul, keterangan=keterangan,
                klinik=NAMA_KLINIK,
            ),
            kode,
        )

    @app.route("/s/<token>", methods=["GET"])
    def halaman_survei(token: str) -> Any:
        conn = sambungan()
        status, undangan = periksa_token(conn, token)
        if status is not StatusLink.SIAP or undangan is None:
            return _pesan(status, 410 if undangan is not None else 404)

        catat_dibuka(conn, token)
        daftar = pertanyaan_untuk(conn, undangan.set_pertanyaan)
        cabang = CABANG.get(undangan.cabang_kode)
        return render_template(
            "survei.html",
            undangan=undangan,
            pertanyaan=daftar,
            cabang_nama=cabang.nama if cabang else "",
            klinik=NAMA_KLINIK,
            ambang_rendah=AMBANG_NILAI_RENDAH,
            mulai=int(time.time()),
        )

    @app.route("/s/<token>", methods=["POST"])
    def kirim_survei(token: str) -> Any:
        conn = sambungan()
        status, undangan = periksa_token(conn, token)
        if status is not StatusLink.SIAP or undangan is None:
            return _pesan(status, 410 if undangan is not None else 404)

        try:
            mulai = int(request.form.get("mulai", "") or 0)
        except ValueError:
            mulai = 0
        durasi = max(0, int(time.time()) - mulai) if mulai else None
        if durasi is not None and durasi > 24 * 3600:
            durasi = None

        try:
            simpan_jawaban(
                conn, undangan, request.form, durasi_detik=durasi
            )
        except JawabanTidakValid as galat:
            daftar = pertanyaan_untuk(conn, undangan.set_pertanyaan)
            cabang = CABANG.get(undangan.cabang_kode)
            return (
                render_template(
                    "survei.html",
                    undangan=undangan,
                    pertanyaan=daftar,
                    cabang_nama=cabang.nama if cabang else "",
                    klinik=NAMA_KLINIK,
                    ambang_rendah=AMBANG_NILAI_RENDAH,
                    mulai=mulai or int(time.time()),
                    galat=str(galat),
                    terkirim=request.form,
                ),
                400,
            )
        return redirect(url_for("halaman_terima_kasih"))

    @app.route("/terima-kasih")
    def halaman_terima_kasih() -> Any:
        return render_template("survei_selesai.html", klinik=NAMA_KLINIK)

    @app.route("/")
    def akar() -> Any:
        # Tanpa token tidak ada apa pun yang bisa ditampilkan. Sengaja tidak
        # ada daftar maupun pencarian pasien di aplikasi ini.
        abort(404)

    @app.errorhandler(404)
    def tidak_ketemu(_galat: Any) -> Any:
        return _pesan(StatusLink.TIDAK_DIKENAL, 404)

    @app.errorhandler(405)
    def metode_salah(_galat: Any) -> Any:
        return _pesan(StatusLink.TIDAK_DIKENAL, 404)

    return app
