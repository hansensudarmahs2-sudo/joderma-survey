"""Uji aturan jeda 30/365 hari.

Batas hari diuji tepat di hari ke-29/30 dan ke-364/365, karena kesalahan
satu hari di sini berarti pasien dikirimi survei di dalam masa jeda -- salah
satu ukuran keberhasilan di PRD.
"""

from __future__ import annotations

import datetime as dt

import pytest

from joderma_survey.aturan import (
    JEDA_BELUM_MENGISI,
    JEDA_SUDAH_MENGISI,
    MASA_BERLAKU_LINK,
    RiwayatUndangan,
    boleh_dikirim,
    kedaluwarsa_pada,
    link_masih_berlaku,
    terblokir_sampai,
)

HARI_H = dt.date(2026, 10, 11)


def hari(selisih: int) -> dt.date:
    """Tanggal berjarak ``selisih`` hari dari HARI_H."""
    return HARI_H + dt.timedelta(days=selisih)


def undangan(
    dibuat: int, diisi: int | None = None, dibatalkan: int | None = None
) -> RiwayatUndangan:
    return RiwayatUndangan(
        dibuat_pada=hari(dibuat),
        diisi_pada=hari(diisi) if diisi is not None else None,
        dibatalkan_pada=hari(dibatalkan) if dibatalkan is not None else None,
    )


# --------------------------------------------------------------------------
# Tetapan
# --------------------------------------------------------------------------


def test_nilai_jeda_sesuai_prd() -> None:
    assert JEDA_BELUM_MENGISI == 30
    assert JEDA_SUDAH_MENGISI == 365


def test_tidak_ada_rentang_mati() -> None:
    """Masa berlaku link harus sama dengan jeda belum-mengisi.

    Kalau masa berlaku lebih pendek dari jeda, muncul rentang waktu di mana
    pasien tidak bisa membuka link lamanya dan belum boleh dapat yang baru.
    Itulah kekeliruan yang diperbaiki di keputusan 2.1 (dulu 7 hari vs 30).
    """
    assert MASA_BERLAKU_LINK == JEDA_BELUM_MENGISI, (
        "mengubah salah satu tanpa yang lain memunculkan rentang mati; "
        "lihat docs/keputusan.md butir 2.1"
    )


# --------------------------------------------------------------------------
# Belum pernah dikirimi
# --------------------------------------------------------------------------


def test_belum_pernah_langsung_boleh() -> None:
    hasil = boleh_dikirim([], HARI_H)
    assert hasil.boleh
    assert hasil.terblokir_sampai is None
    assert "belum pernah" in hasil.alasan


def test_keputusan_bisa_dipakai_sebagai_boolean() -> None:
    assert boleh_dikirim([], HARI_H)
    assert not boleh_dikirim([undangan(dibuat=-1)], HARI_H)


def test_terblokir_sampai_kosong() -> None:
    assert terblokir_sampai([]) is None


# --------------------------------------------------------------------------
# Jeda 30 hari: sudah dikirimi, belum mengisi
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("umur_link", "harap_boleh"),
    [(0, False), (1, False), (15, False), (28, False), (29, False),
     (30, True), (31, True), (100, True)],
)
def test_batas_30_hari(umur_link: int, harap_boleh: bool) -> None:
    riwayat = [undangan(dibuat=-umur_link)]
    assert boleh_dikirim(riwayat, HARI_H).boleh is harap_boleh


def test_hari_ke_29_masih_terblokir() -> None:
    hasil = boleh_dikirim([undangan(dibuat=-29)], HARI_H)
    assert not hasil.boleh
    assert hasil.terblokir_sampai == hari(1)
    assert "link masih aktif" in hasil.alasan


def test_hari_ke_30_sudah_boleh() -> None:
    hasil = boleh_dikirim([undangan(dibuat=-30)], HARI_H)
    assert hasil.boleh
    assert hasil.terblokir_sampai == HARI_H


# --------------------------------------------------------------------------
# Jeda 365 hari: sudah mengisi
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("umur_isi", "harap_boleh"),
    [(0, False), (30, False), (180, False), (363, False), (364, False),
     (365, True), (366, True)],
)
def test_batas_365_hari(umur_isi: int, harap_boleh: bool) -> None:
    riwayat = [undangan(dibuat=-umur_isi - 2, diisi=-umur_isi)]
    assert boleh_dikirim(riwayat, HARI_H).boleh is harap_boleh


def test_hari_ke_364_masih_terblokir() -> None:
    hasil = boleh_dikirim([undangan(dibuat=-366, diisi=-364)], HARI_H)
    assert not hasil.boleh
    assert hasil.terblokir_sampai == hari(1)
    assert "sudah mengisi" in hasil.alasan


def test_hari_ke_365_sudah_boleh() -> None:
    hasil = boleh_dikirim([undangan(dibuat=-367, diisi=-365)], HARI_H)
    assert hasil.boleh


def test_mengisi_cepat_tetap_terblokir_365_hari() -> None:
    """Mengisi di hari ke-3 tidak membuat jeda jadi 30 hari."""
    riwayat = [undangan(dibuat=-3, diisi=0)]
    hasil = boleh_dikirim(riwayat, HARI_H)
    assert not hasil.boleh
    assert hasil.terblokir_sampai == hari(JEDA_SUDAH_MENGISI)


def test_aturan_365_tidak_hilang_karena_link_kedaluwarsa() -> None:
    """Lubang yang paling berbahaya: link yang sudah diisi juga kedaluwarsa.

    Kalau hanya masa berlaku link yang diperiksa, pasien yang rajin mengisi
    akan disurvei 12 kali setahun.
    """
    riwayat = [undangan(dibuat=-40, diisi=-38)]
    hasil = boleh_dikirim(riwayat, HARI_H)
    assert not hasil.boleh, "link memang sudah kedaluwarsa, tapi jeda 365 berlaku"
    assert hasil.terblokir_sampai == hari(-38 + JEDA_SUDAH_MENGISI)


# --------------------------------------------------------------------------
# Gabungan: yang memblokir adalah yang paling akhir
# --------------------------------------------------------------------------


def test_mengisi_lama_lalu_tapi_baru_dapat_link() -> None:
    """Sudah mengisi 400 hari lalu (lewat), link 10 hari lalu (belum lewat)."""
    riwayat = [undangan(dibuat=-402, diisi=-400), undangan(dibuat=-10)]
    hasil = boleh_dikirim(riwayat, HARI_H)
    assert not hasil.boleh, "terkena jeda 30 hari dari link terbaru"
    assert hasil.terblokir_sampai == hari(20)


def test_memakai_riwayat_terakhir_bukan_yang_pertama() -> None:
    riwayat = [undangan(dibuat=-200), undangan(dibuat=-100), undangan(dibuat=-5)]
    hasil = boleh_dikirim(riwayat, HARI_H)
    assert not hasil.boleh
    assert hasil.terblokir_sampai == hari(25)


def test_urutan_riwayat_tidak_memengaruhi_hasil() -> None:
    maju = [undangan(dibuat=-200), undangan(dibuat=-5)]
    balik = list(reversed(maju))
    assert terblokir_sampai(maju) == terblokir_sampai(balik)


def test_banyak_pengisian_memakai_yang_terbaru() -> None:
    riwayat = [undangan(dibuat=-800, diisi=-798), undangan(dibuat=-400, diisi=-398)]
    assert terblokir_sampai(riwayat) == hari(-398 + JEDA_SUDAH_MENGISI)


# --------------------------------------------------------------------------
# Pembatalan (keputusan 4.4)
# --------------------------------------------------------------------------


def test_undangan_dibatalkan_tidak_memblokir() -> None:
    """CS tidak menemukan kontak: pasien tidak pernah menerima apa pun."""
    riwayat = [undangan(dibuat=-5, dibatalkan=-4)]
    hasil = boleh_dikirim(riwayat, HARI_H)
    assert hasil.boleh
    assert hasil.terblokir_sampai is None


def test_pembatalan_tidak_menghapus_jeda_365() -> None:
    """Pengisian tidak bisa ditarik kembali, jadi jeda 365 tetap berlaku."""
    riwayat = [undangan(dibuat=-40, diisi=-38, dibatalkan=-10)]
    hasil = boleh_dikirim(riwayat, HARI_H)
    assert not hasil.boleh
    assert hasil.terblokir_sampai == hari(-38 + JEDA_SUDAH_MENGISI)


def test_satu_dibatalkan_satu_aktif() -> None:
    riwayat = [undangan(dibuat=-20, dibatalkan=-19), undangan(dibuat=-5)]
    hasil = boleh_dikirim(riwayat, HARI_H)
    assert not hasil.boleh
    assert hasil.terblokir_sampai == hari(25)


def test_sifat_dibatalkan() -> None:
    assert undangan(dibuat=-5, dibatalkan=-4).dibatalkan
    assert not undangan(dibuat=-5, diisi=-4, dibatalkan=-3).dibatalkan
    assert not undangan(dibuat=-5).dibatalkan


# --------------------------------------------------------------------------
# Masa berlaku link
# --------------------------------------------------------------------------


def test_kedaluwarsa_pada() -> None:
    assert kedaluwarsa_pada(dt.date(2026, 10, 11)) == dt.date(2026, 11, 10)
    assert kedaluwarsa_pada(dt.date(2026, 2, 1)) == dt.date(2026, 3, 3)
    assert kedaluwarsa_pada(dt.date(2024, 2, 1)) == dt.date(2024, 3, 2)  # kabisat


@pytest.mark.parametrize(
    ("umur", "harap"),
    [(0, True), (29, True), (30, False), (31, False)],
)
def test_link_masih_berlaku(umur: int, harap: bool) -> None:
    assert link_masih_berlaku(undangan(dibuat=-umur), HARI_H) is harap


def test_link_sekali_pakai() -> None:
    assert not link_masih_berlaku(undangan(dibuat=-1, diisi=0), HARI_H)


def test_link_dibatalkan_tidak_berlaku() -> None:
    assert not link_masih_berlaku(undangan(dibuat=-1, dibatalkan=0), HARI_H)


def test_kedaluwarsa_dan_jeda_habis_di_hari_yang_sama() -> None:
    """Sifat yang membuat rancangan ini sederhana: satu peristiwa, bukan dua."""
    u = undangan(dibuat=-30)
    assert not link_masih_berlaku(u, HARI_H)
    assert boleh_dikirim([u], HARI_H).boleh
    sehari_sebelum = HARI_H - dt.timedelta(days=1)
    assert link_masih_berlaku(u, sehari_sebelum)
    assert not boleh_dikirim([u], sehari_sebelum).boleh
