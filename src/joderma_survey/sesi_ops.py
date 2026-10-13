"""Menanyakan sesi login ke aplikasi ops (keputusan 13 Okt 2026).

Aplikasi admin survei dipasang di ``ops.joderma.id/survei``, satu hostname
dengan aplikasi ops (Django). Login survei sendiri sudah dihapus: siapa yang
sedang memakai aplikasi ditentukan dengan **menanyakannya ke ops pada setiap
permintaan**, dengan meneruskan kuki sesi ops (``sessionid``) yang dibawa
peramban. Karena tidak ada status login yang disimpan di sisi survei, logout
di ops atau peran yang dicabut langsung berlaku pada permintaan berikutnya.

Kontrak ops: ``GET /akun/sesi-survei/``

* ``200`` ``{"username", "nama", "peran"}`` dengan peran direktur/owner/cs
* ``403`` -- sudah login ops tetapi tidak berhak membuka Survei
* ``401`` -- belum login ops
* apa pun selain itu (302 sesi kedaluwarsa, 5xx, timeout, ops mati, isi
  yang tidak sah) dianggap **belum login**. Tidak pernah dianggap berhak.

Hanya kuki ``sessionid`` yang diteruskan -- tidak pernah kuki sesi survei
atau kuki lain milik peramban. Pengalihan dari ops tidak diikuti.

Dipakai ``urllib`` dari pustaka standar supaya tidak menambah dependensi.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Final
from urllib.parse import quote

from .pengguna import PERAN

__all__ = [
    "BERHAK",
    "TANPA_HAK",
    "BELUM_MASUK",
    "HasilSesi",
    "PemeriksaSesi",
    "periksa_sesi_ops",
    "jalur_lanjut",
    "url_login_ops",
    "OPS_INTERNAL_BAWAAN",
    "OPS_HOST_BAWAAN",
    "TENGGAT_OPS",
    "NAMA_KUKI_OPS",
]

BERHAK: Final[str] = "berhak"
TANPA_HAK: Final[str] = "tanpa_hak"
BELUM_MASUK: Final[str] = "belum_masuk"

OPS_INTERNAL_BAWAAN: Final[str] = "http://127.0.0.1:8731"
OPS_HOST_BAWAAN: Final[str] = "ops.joderma.id"
#: Pendek, supaya ops yang macet tidak menahan alur waitress lama-lama.
TENGGAT_OPS: Final[float] = 3.0
NAMA_KUKI_OPS: Final[str] = "sessionid"
JALUR_SESI: Final[str] = "/akun/sesi-survei/"

#: Kunci sesi Django hanya huruf kecil dan angka (32 karakter). Diperiksa
#: longgar, tetapi cukup ketat untuk menolak titik koma, spasi, dan CR/LF
#: yang bisa menyisipkan kuki atau header lain.
_POLA_KUKI: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9]{1,128}")
#: Jawaban ops kecil; apa pun yang jauh lebih besar jelas bukan jawaban sah.
_BATAS_ISI: Final[int] = 64 * 1024


@dataclass(frozen=True)
class HasilSesi:
    """Jawaban ops yang sudah ditafsirkan."""

    status: str
    username: str = ""
    nama: str = ""
    peran: str | None = None


#: Bentuk fungsi yang bisa disuntikkan ke ``buat_app`` (dipakai tes agar
#: tidak memanggil jaringan): nilai kuki ``sessionid`` (atau None) -> hasil.
PemeriksaSesi = Callable[[str | None], HasilSesi]


class _TolakPengalihan(urllib.request.HTTPRedirectHandler):
    """Jangan pernah mengikuti pengalihan dari ops; 3xx jadi HTTPError."""

    def redirect_request(self, *_args: Any, **_kw: Any) -> None:
        return None


#: Tanpa proksi: ops selalu di mesin yang sama, dan peubah http_proxy milik
#: lingkungan tidak boleh membelokkan kuki sesi ke tempat lain.
_PEMBUKA = urllib.request.build_opener(urllib.request.ProxyHandler({}), _TolakPengalihan)


def _teks(nilai: Any) -> str:
    return nilai if isinstance(nilai, str) else ""


def _tafsirkan(kode: int, isi: bytes) -> HasilSesi:
    if kode == 403:
        # Sudah login tetapi tidak berhak. Isi yang janggal pun tetap hanya
        # berarti "tanpa hak" -- tidak pernah membuka apa pun.
        try:
            data = json.loads(isi.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        return HasilSesi(TANPA_HAK, _teks(data.get("username")), _teks(data.get("nama")))
    if kode != 200:
        return HasilSesi(BELUM_MASUK)
    try:
        data = json.loads(isi.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return HasilSesi(BELUM_MASUK)
    if not isinstance(data, dict):
        return HasilSesi(BELUM_MASUK)
    username = data.get("username")
    peran = data.get("peran")
    if not isinstance(username, str) or not username.strip():
        return HasilSesi(BELUM_MASUK)
    if not isinstance(peran, str) or peran not in PERAN:
        return HasilSesi(BELUM_MASUK)
    return HasilSesi(BERHAK, username.strip(), _teks(data.get("nama")).strip(), peran)


def periksa_sesi_ops(
    kuki: str | None,
    *,
    url_internal: str = OPS_INTERNAL_BAWAAN,
    host: str = OPS_HOST_BAWAAN,
    tenggat: float = TENGGAT_OPS,
) -> HasilSesi:
    """Tanyakan ke ops siapa pemilik kuki ``sessionid`` ini."""
    if not kuki or not _POLA_KUKI.fullmatch(kuki):
        return HasilSesi(BELUM_MASUK)
    permintaan = urllib.request.Request(
        url_internal.rstrip("/") + JALUR_SESI,
        method="GET",
        headers={
            # Hanya kuki sesi ops. Kuki lain milik peramban (termasuk kuki
            # sesi survei) sengaja tidak ikut.
            "Cookie": f"{NAMA_KUKI_OPS}={kuki}",
            # ALLOWED_HOSTS Django; tanpa X-Forwarded-Proto, ops mengalihkan
            # ke https dengan 301.
            "Host": host,
            "X-Forwarded-Proto": "https",
            "Accept": "application/json",
        },
    )
    try:
        with _PEMBUKA.open(permintaan, timeout=tenggat) as jawab:
            return _tafsirkan(jawab.status, jawab.read(_BATAS_ISI + 1)[:_BATAS_ISI])
    except urllib.error.HTTPError as galat:
        try:
            isi = galat.read(_BATAS_ISI)
        except Exception:  # noqa: BLE001 - isi galat hanya pelengkap
            isi = b""
        finally:
            galat.close()
        return _tafsirkan(galat.code, isi)
    except Exception:  # noqa: BLE001 - timeout, ops mati, apa pun: belum login
        return HasilSesi(BELUM_MASUK)


def jalur_lanjut(awalan: str, jalur: str, kueri: str = "") -> str:
    """Jalur internal tujuan kembali sesudah login ops.

    Garis miring dan garis miring terbalik di depan dirapikan menjadi satu
    ``/``, supaya hasilnya tidak pernah berbentuk ``//host`` yang oleh
    peramban dibaca sebagai alamat situs lain.

    >>> jalur_lanjut("/survei", "/kirim", "cabang=1")
    '/survei/kirim?cabang=1'
    >>> jalur_lanjut("", "//jahat.example")
    '/jahat.example'
    """
    hasil = (awalan or "") + "/" + (jalur or "").lstrip("/\\")
    hasil = "/" + hasil.lstrip("/\\")
    if kueri:
        hasil += "?" + kueri
    return hasil


def url_login_ops(host: str, lanjut: str) -> str:
    """URL halaman login ops; ``next`` dikodekan utuh sebagai satu nilai.

    >>> url_login_ops("ops.joderma.id", "/survei/kirim")
    'https://ops.joderma.id/akun/login/?next=/survei/kirim'
    """
    return f"https://{host}/akun/login/?next={quote(lanjut, safe='/')}"
