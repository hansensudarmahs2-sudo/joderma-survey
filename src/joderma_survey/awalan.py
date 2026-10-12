"""Memasang aplikasi admin di bawah awalan jalur, misalnya ``/survei``.

Dipakai saat aplikasi admin berbagi hostname dengan sistem lain, supaya ia
ikut terlindungi kebijakan Cloudflare Access yang sudah ada di hostname itu
dan staf tidak perlu login dua kali.

**Kenapa perlu lapisan ini.** Flask membuat tautan dan pengalihan dari akar
aplikasi: ``/masuk``, ``/kirim``, ``/hasil``. Bila dipasang di bawah
``/survei`` tanpa penyesuaian, semua tautan itu menunjuk ke akar hostname --
yang di sana justru aplikasi lain. Gejalanya membingungkan: halaman masuk
muncul, tapi sesudah login malah terlempar ke aplikasi tetangga.

WSGI sudah menyediakan jawabannya lewat ``SCRIPT_NAME``: bagian jalur yang
merupakan "tempat aplikasi dipasang" dipindahkan ke sana, dan ``PATH_INFO``
hanya menyisakan jalur di dalam aplikasi. Flask membaca keduanya, sehingga
``url_for`` otomatis menghasilkan ``/survei/masuk``.

Lapisan ini **longgar**: permintaan yang tidak berawalan diteruskan apa
adanya. Dengan begitu pemeriksaan langsung ke ``127.0.0.1:8002/masuk`` --
yang dipakai skrip pemasangan dan saat menelusuri masalah -- tetap bekerja,
sementara permintaan dari Cloudflare yang berawalan ``/survei`` juga bekerja.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable

__all__ = ["AwalanJalur", "rapikan_awalan"]


def rapikan_awalan(awalan: str) -> str:
    """Normalkan awalan menjadi bentuk ``/survei`` atau kosong.

    >>> rapikan_awalan("survei"), rapikan_awalan("/survei/"), rapikan_awalan("")
    ('/survei', '/survei', '')
    >>> rapikan_awalan("  /a/b/  ")
    '/a/b'
    """
    bersih = (awalan or "").strip().strip("/")
    return f"/{bersih}" if bersih else ""


class AwalanJalur:
    """Pindahkan awalan jalur dari ``PATH_INFO`` ke ``SCRIPT_NAME``."""

    def __init__(self, app: Any, awalan: str) -> None:
        self.app = app
        self.awalan = rapikan_awalan(awalan)

    def __call__(
        self,
        environ: dict[str, Any],
        start_response: Callable[..., Any],
    ) -> Iterable[bytes]:
        jalur = environ.get("PATH_INFO", "")
        if self.awalan and (
            jalur == self.awalan or jalur.startswith(self.awalan + "/")
        ):
            environ["SCRIPT_NAME"] = environ.get("SCRIPT_NAME", "") + self.awalan
            # Sisanya minimal "/", karena PATH_INFO kosong membuat Flask
            # mengira permintaannya ke jalur yang tidak ada.
            environ["PATH_INFO"] = jalur[len(self.awalan) :] or "/"
        return self.app(environ, start_response)
