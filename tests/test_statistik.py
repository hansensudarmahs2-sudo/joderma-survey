"""Uji hitungan statistik."""

from __future__ import annotations

import math

import pytest

from joderma_survey.statistik import (
    Z_95,
    bobot_pasca_stratifikasi,
    koreksi_populasi,
    nilai_t,
    proporsi,
    rata_rata,
    ringkas_nilai,
    ukuran_efektif,
)


# --------------------------------------------------------------------------
# Nilai kritis
# --------------------------------------------------------------------------


def test_t_lebih_lebar_dari_z_pada_n_kecil() -> None:
    """Mengabaikan ini membuat beda tampak nyata padahal belum tentu."""
    assert nilai_t(5) > nilai_t(30) > Z_95
    assert nilai_t(30) == pytest.approx(2.042)


def test_t_mendekati_z_pada_n_besar() -> None:
    assert nilai_t(200) == Z_95
    assert nilai_t(10_000) == Z_95


def test_t_derajat_bebas_di_antara_memakai_yang_lebih_lebar() -> None:
    """Arah aman: selangnya sedikit lebih lebar, bukan lebih sempit."""
    assert nilai_t(35) == nilai_t(30)
    assert nilai_t(50) == nilai_t(40)


def test_t_derajat_bebas_tak_masuk_akal() -> None:
    assert nilai_t(0) == float("inf")
    assert nilai_t(-5) == float("inf")


# --------------------------------------------------------------------------
# Koreksi populasi terbatas
# --------------------------------------------------------------------------


def test_koreksi_populasi_tanpa_populasi() -> None:
    assert koreksi_populasi(50, None) == 1.0


def test_koreksi_populasi_mengecilkan_galat() -> None:
    """42 jawaban dari 210 pasien lebih tepat daripada dari populasi tak hingga."""
    assert koreksi_populasi(42, 210) < 1.0
    assert koreksi_populasi(100, 497) == pytest.approx(0.8947, abs=1e-4)


def test_koreksi_populasi_sensus_penuh() -> None:
    assert koreksi_populasi(100, 100) == 0.0
    assert koreksi_populasi(150, 100) == 0.0


# --------------------------------------------------------------------------
# Rata-rata
# --------------------------------------------------------------------------


def test_rata_rata_dasar() -> None:
    s = rata_rata([4, 4, 5, 5])
    assert s is not None
    assert s.nilai == 4.5
    assert s.bawah < 4.5 < s.atas


def test_rata_rata_kosong() -> None:
    assert rata_rata([]) is None


def test_rata_rata_satu_nilai_tanpa_selang() -> None:
    s = rata_rata([4])
    assert s is not None
    assert s.bawah == s.atas == 4.0


def test_selang_dipotong_ke_jangkauan_skala() -> None:
    """Rata-rata nilai 1-5 mustahil di luar 1-5; selang yang keluar menyesatkan."""
    s = rata_rata([4, 5], batas=(1.0, 5.0))
    assert s is not None
    assert s.nilai == 4.5
    assert s.bawah == 1.0 and s.atas == 5.0


def test_tanpa_batas_selang_bisa_keluar_jangkauan() -> None:
    s = rata_rata([4, 5])
    assert s is not None
    assert s.atas > 5.0, "tanpa batas memang bisa melewati skala"


def test_populasi_terbatas_mempersempit_selang() -> None:
    nilai = [4, 5, 3, 4, 5, 4, 3, 5, 4, 4]
    luas = rata_rata(nilai)
    sempit = rata_rata(nilai, populasi=12)
    assert luas is not None and sempit is not None
    assert sempit.lebar_setengah < luas.lebar_setengah


def test_bobot_mengubah_rata_rata() -> None:
    s = rata_rata([5, 1], bobot=[3, 1])
    assert s is not None
    assert s.nilai == pytest.approx(4.0)


def test_bobot_salah_jumlah_ditolak() -> None:
    with pytest.raises(ValueError, match="jumlah bobot"):
        rata_rata([1, 2, 3], bobot=[1, 1])


def test_pembobotan_tidak_mempersempit_selang_secara_palsu() -> None:
    """Pembobotan selalu mengurangi presisi efektif, tidak menambahnya."""
    nilai = [5, 4, 5, 4, 3, 5, 4, 4, 5, 3]
    rata = rata_rata(nilai)
    berbobot = rata_rata(nilai, bobot=[3, 1, 1, 1, 1, 1, 1, 1, 1, 1])
    assert rata is not None and berbobot is not None
    assert berbobot.lebar_setengah >= rata.lebar_setengah


# --------------------------------------------------------------------------
# Proporsi (Wilson)
# --------------------------------------------------------------------------


def test_proporsi_dasar() -> None:
    s = proporsi(85, 100)
    assert s is not None
    assert s.nilai == 0.85
    assert 0.76 < s.bawah < 0.78
    assert 0.90 < s.atas < 0.92


def test_wilson_tidak_pernah_melewati_nol_satu() -> None:
    """Hampiran normal gagal di dekat ujung; top-2-box sering ada di sana."""
    for berhasil, jumlah in [(0, 10), (10, 10), (1, 100), (99, 100), (0, 1), (1, 1)]:
        s = proporsi(berhasil, jumlah)
        assert s is not None
        assert 0.0 <= s.bawah <= s.atas <= 1.0, (berhasil, jumlah)


def test_wilson_semua_berhasil_tetap_punya_batas_bawah() -> None:
    """10 dari 10 bukan berarti 100% pasti; batas bawahnya harus di bawah 1."""
    s = proporsi(10, 10)
    assert s is not None
    assert s.bawah < 1.0
    assert s.atas == 1.0


def test_proporsi_kosong() -> None:
    assert proporsi(0, 0) is None


def test_proporsi_populasi_terbatas() -> None:
    luas = proporsi(42, 100)
    sempit = proporsi(42, 100, populasi=120)
    assert luas is not None and sempit is not None
    assert sempit.lebar_setengah < luas.lebar_setengah


# --------------------------------------------------------------------------
# Ukuran efektif dan pembobotan
# --------------------------------------------------------------------------


def test_ukuran_efektif_bobot_seragam() -> None:
    assert ukuran_efektif([1, 1, 1, 1]) == 4.0
    assert ukuran_efektif([2, 2, 2, 2]) == 4.0


def test_ukuran_efektif_turun_saat_bobot_timpang() -> None:
    assert ukuran_efektif([5, 1, 1, 1]) < 4.0


def test_ukuran_efektif_kosong() -> None:
    assert ukuran_efektif([]) == 0.0


def test_bobot_mengembalikan_komposisi_populasi() -> None:
    """Sel yang kurang terwakili diberi bobot lebih besar."""
    bobot = bobot_pasca_stratifikasi({"a": 50, "b": 10}, {"a": 100, "b": 100})
    assert bobot["b"] > 1.0 > bobot["a"]


def test_bobot_dibatasi() -> None:
    """Bobot ekstrem membuat beberapa responden mendominasi."""
    bobot = bobot_pasca_stratifikasi({"a": 100, "b": 1}, {"a": 10, "b": 1000})
    assert max(bobot.values()) <= 3.0


def test_bobot_batas_bisa_diubah() -> None:
    bobot = bobot_pasca_stratifikasi({"a": 100, "b": 1}, {"a": 10, "b": 1000},
                                     batas=10.0)
    assert max(bobot.values()) <= 10.0


def test_sel_tanpa_responden_diabaikan() -> None:
    """Sel tanpa responden tidak bisa diwakili oleh siapa pun."""
    bobot = bobot_pasca_stratifikasi({"a": 10, "b": 0}, {"a": 100, "b": 100})
    assert "b" not in bobot
    assert set(bobot) == {"a"}


def test_bobot_semua_sel_kosong() -> None:
    assert bobot_pasca_stratifikasi({"a": 0}, {"a": 100}) == {}


def test_bobot_komposisi_sudah_sama() -> None:
    bobot = bobot_pasca_stratifikasi({"a": 50, "b": 50}, {"a": 100, "b": 100})
    assert bobot["a"] == pytest.approx(1.0)
    assert bobot["b"] == pytest.approx(1.0)


# --------------------------------------------------------------------------
# Ringkasan satu pertanyaan
# --------------------------------------------------------------------------


def test_ringkas_nilai() -> None:
    r = ringkas_nilai([5, 4, 4, 3, 5, 5, 2, 4, 4, 5])
    assert r.n == 10
    assert r.sebaran == {1: 0, 2: 1, 3: 1, 4: 4, 5: 4}
    assert r.rata_rata is not None
    assert r.top2 is not None
    assert r.top2.nilai == pytest.approx(0.8), "8 dari 10 menjawab 4 atau 5"


def test_ringkas_nilai_kosong() -> None:
    r = ringkas_nilai([])
    assert r.n == 0
    assert r.rata_rata is None and r.top2 is None


def test_ringkas_selang_dipotong_ke_skala() -> None:
    r = ringkas_nilai([5, 5])
    assert r.rata_rata is not None
    assert r.rata_rata.atas <= 5.0
    assert r.rata_rata.bawah >= 1.0


def test_nilai_di_luar_skala_tidak_masuk_sebaran() -> None:
    r = ringkas_nilai([4, 9, 0])
    assert sum(r.sebaran.values()) == 1


# --------------------------------------------------------------------------
# Aturan baca
# --------------------------------------------------------------------------


def test_selang_tumpang_tindih() -> None:
    a = ringkas_nilai([4, 4, 4, 4, 4, 4, 4, 4, 4, 4]).rata_rata
    b = ringkas_nilai([4, 4, 4, 5, 4, 4, 4, 4, 4, 4]).rata_rata
    assert a is not None and b is not None
    assert a.tumpang_tindih(b), "beda 0,1 poin pada n=10 bukan beda nyata"


def test_selang_tidak_tumpang_tindih_saat_beda_besar() -> None:
    a = ringkas_nilai([2] * 20).rata_rata
    b = ringkas_nilai([5] * 20).rata_rata
    assert a is not None and b is not None
    assert not a.tumpang_tindih(b)


def test_moe_mengecil_saat_n_bertambah() -> None:
    kecil = ringkas_nilai([5, 4, 3, 4, 5] * 2).rata_rata
    besar = ringkas_nilai([5, 4, 3, 4, 5] * 40).rata_rata
    assert kecil is not None and besar is not None
    assert besar.lebar_setengah < kecil.lebar_setengah
