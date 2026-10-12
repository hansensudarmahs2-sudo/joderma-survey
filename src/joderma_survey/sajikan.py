"""Menjalankan aplikasi web dengan server yang pantas dipakai sungguhan.

``app.run()`` bawaan Flask adalah server pengembangan Werkzeug: satu alur,
tidak dirancang menghadapi lalu lintas sungguhan, dan Flask sendiri
memperingatkannya setiap kali dijalankan.

Dipakai `waitress` karena **murni Python**: tidak ada pustaka sistem yang
perlu dipasang di mini PC, berbeda dengan gunicorn (hanya Unix, butuh
penyetelan pekerja) atau uWSGI (butuh kompilasi). Beban di sini ringan --
sekitar 150 pasien per pekan, tidak serentak -- jadi yang dibutuhkan bukan
kecepatan, melainkan server yang tidak tumbang oleh sambungan yang
menggantung.

Dua setelan yang sengaja tidak memakai nilai bawaan, karena pembatasan laju
Cloudflare dicabut (keputusan 2.43) sehingga tidak ada lagi lapisan di
depannya:

``channel_timeout``
    Memutus sambungan yang diam. Bawaan waitress 120 detik; di sini 60.
    Tanpa ini, sambungan yang sengaja dibuka lambat bisa menahan alur kerja.

``connection_limit``
    Batas sambungan serentak. Saat tercapai, sambungan baru ditolak cepat
    alih-alih menumpuk sampai mini PC kehabisan memori.
"""

from __future__ import annotations

from typing import Any

__all__ = ["sajikan", "ALUR", "BATAS_SAMBUNGAN", "TENGGAT_SALURAN"]

#: Jumlah alur pekerja. Empat sudah lapang untuk beban klinik ini, dan
#: menjaga pemakaian memori mini PC tetap kecil.
ALUR: int = 4

BATAS_SAMBUNGAN: int = 100
TENGGAT_SALURAN: int = 60


def sajikan(
    app: Any,
    alamat: str,
    porta: int,
    *,
    debug: bool = False,
    nama: str = "aplikasi",
) -> None:
    """Jalankan ``app``.

    Dengan ``debug`` dipakai server pengembangan Flask, yang punya pemuatan
    ulang otomatis dan halaman galat. Tanpa itu dipakai waitress.
    """
    if debug:
        print(
            f"[{nama}] MODE PENGEMBANGAN di http://{alamat}:{porta} "
            f"-- jangan dipakai untuk melayani pasien",
            flush=True,
        )
        app.run(host=alamat, port=porta, debug=True)
        return

    from waitress import serve

    # flush wajib: stdout tidak terhubung terminal saat dijalankan systemd,
    # jadi tanpa ini pesannya tertahan di penyangga dan journalctl kosong.
    print(
        f"[{nama}] waitress di http://{alamat}:{porta} "
        f"({ALUR} alur, batas {BATAS_SAMBUNGAN} sambungan, "
        f"tenggat {TENGGAT_SALURAN} detik)",
        flush=True,
    )
    serve(
        app,
        host=alamat,
        port=porta,
        threads=ALUR,
        connection_limit=BATAS_SAMBUNGAN,
        channel_timeout=TENGGAT_SALURAN,
        # Tidak mengumumkan nama dan versi server di kepala tanggapan.
        ident=None,
    )
