"""Pengaturan yang berbeda antar lingkungan.

Diambil dari peubah lingkungan supaya tidak ada alamat atau rahasia yang
tertulis di dalam kode.
"""

from __future__ import annotations

import os

__all__ = ["url_dasar_survei", "url_survei", "NAMA_KLINIK"]

NAMA_KLINIK: str = "JoDerma"

#: Halaman survei memakai subdomain sendiri, di luar kebijakan Cloudflare
#: Access, supaya pasien tidak diminta kode OTP (lihat PRD bagian Infrastruktur).
_BAWAAN_URL = "https://survey.joderma.id"


def url_dasar_survei() -> str:
    """Alamat dasar halaman survei publik."""
    return os.environ.get("JODERMA_URL_SURVEI", _BAWAAN_URL).rstrip("/")


def url_survei(token: str) -> str:
    """Alamat lengkap survei untuk satu token.

    >>> import os; os.environ["JODERMA_URL_SURVEI"] = "https://contoh.id"
    >>> url_survei("abc123")
    'https://contoh.id/s/abc123'
    >>> del os.environ["JODERMA_URL_SURVEI"]
    """
    return f"{url_dasar_survei()}/s/{token}"
