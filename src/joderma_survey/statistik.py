"""Hitungan statistik untuk ringkasan survei.

Fungsi murni tanpa dependensi luar; cukup ``math`` dari pustaka standar.

Tiga pilihan yang disengaja, karena ukuran sampel di sini kecil (metodologi
bagian 3: Jemur ~76 jawaban/bulan, Citraland ~42):

1. **Selang kepercayaan proporsi memakai metode Wilson**, bukan hampiran
   normal. Top-2-box biasanya berada di 0,85-0,95, dan di dekat ujung itu
   hampiran normal menghasilkan selang yang terlalu sempit dan bisa melewati
   100%.
2. **Rata-rata memakai sebaran t**, bukan z, dengan tabel nilai kritis
   sampai derajat bebas 30. Pada n=30 bedanya 2,042 vs 1,960 -- sekitar 4%
   lebih lebar, dan mengabaikannya membuat perbedaan tampak nyata padahal
   bukan.
3. **Koreksi populasi terbatas** selalu dipakai, karena survei ini sensus
   yang bocor: 42 jawaban dari 210 pasien jauh lebih tepat daripada 42
   jawaban dari populasi tak terhingga.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final, Sequence

__all__ = [
    "Z_95",
    "Selang",
    "Ringkasan",
    "nilai_t",
    "koreksi_populasi",
    "rata_rata",
    "proporsi",
    "ukuran_efektif",
    "bobot_pasca_stratifikasi",
    "ringkas_nilai",
]

Z_95: Final[float] = 1.959963985

# Nilai kritis t dua sisi untuk taraf 95%. Derajat bebas di antaranya memakai
# nilai derajat bebas terdekat yang lebih kecil, sehingga selangnya sedikit
# lebih lebar -- arah yang aman.
_TABEL_T: Final[dict[int, float]] = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365,
    8: 2.306, 9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145,
    15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086,
    21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064, 25: 2.060, 26: 2.056,
    27: 2.052, 28: 2.048, 29: 2.045, 30: 2.042, 40: 2.021, 60: 2.000,
    120: 1.980,
}


def nilai_t(derajat_bebas: int) -> float:
    """Nilai kritis t dua sisi untuk taraf 95%.

    >>> nilai_t(10)
    2.228
    >>> nilai_t(10_000) == Z_95
    True
    """
    if derajat_bebas < 1:
        return float("inf")
    if derajat_bebas in _TABEL_T:
        return _TABEL_T[derajat_bebas]
    kandidat = [d for d in _TABEL_T if d <= derajat_bebas]
    if not kandidat:
        return _TABEL_T[1]
    if derajat_bebas > 120:
        return Z_95
    return _TABEL_T[max(kandidat)]


def koreksi_populasi(n: int, populasi: int | None) -> float:
    """Faktor koreksi populasi terbatas.

    Mengembalikan 1,0 bila populasinya tidak diketahui. Mengembalikan 0,0
    bila seluruh populasi menjawab -- tidak ada kesalahan pengambilan sampel
    sama sekali saat itu.

    >>> koreksi_populasi(50, None)
    1.0
    >>> round(koreksi_populasi(100, 497), 4)
    0.8947
    """
    if populasi is None or populasi <= 1 or n >= populasi:
        return 1.0 if populasi is None else (0.0 if n >= populasi else 1.0)
    return math.sqrt((populasi - n) / (populasi - 1))


@dataclass(frozen=True)
class Selang:
    """Nilai titik beserta selang kepercayaannya."""

    nilai: float
    bawah: float
    atas: float
    n: int
    populasi: int | None = None

    @property
    def lebar_setengah(self) -> float:
        return (self.atas - self.bawah) / 2

    def tumpang_tindih(self, lain: "Selang") -> bool:
        """Apakah dua selang bertumpang tindih.

        Dipakai sebagai aturan baca sederhana: selang yang bertumpang tindih
        berarti bedanya belum tentu nyata. Catatan: tidak bertumpang tindih
        adalah bukti yang lebih kuat daripada sekadar berbeda nyata, jadi uji
        ini bersifat berhati-hati.
        """
        return not (self.atas < lain.bawah or lain.atas < self.bawah)

    def __str__(self) -> str:
        return f"{self.nilai:.2f} ({self.bawah:.2f}-{self.atas:.2f}, n={self.n})"


def rata_rata(
    nilai: Sequence[float],
    populasi: int | None = None,
    bobot: Sequence[float] | None = None,
    batas: tuple[float, float] | None = None,
) -> Selang | None:
    """Rata-rata beserta selang kepercayaan 95%.

    ``None`` bila datanya kosong.

    ``batas`` memotong selang ke jangkauan skalanya. Untuk skala 1-5,
    rata-rata mustahil berada di luar 1 sampai 5, sehingga selang yang
    melewatinya -- hal biasa pada n sangat kecil -- hanya menyesatkan
    pembaca. Yang dipotong hanya ujung selangnya; nilai titiknya tidak
    pernah diubah.

    >>> s = rata_rata([4, 5], batas=(1.0, 5.0))
    >>> s.nilai, s.bawah, s.atas
    (4.5, 1.0, 5.0)
    """
    n = len(nilai)
    if n == 0:
        return None
    if bobot is None:
        bobot = [1.0] * n
    if len(bobot) != n:
        raise ValueError("jumlah bobot harus sama dengan jumlah nilai")
    jumlah_bobot = sum(bobot)
    if jumlah_bobot <= 0:
        return None
    rerata = sum(b * x for b, x in zip(bobot, nilai)) / jumlah_bobot
    if n < 2:
        return Selang(rerata, rerata, rerata, n, populasi)

    # Ragam berbobot, lalu diperlakukan memakai ukuran efektif sampel supaya
    # pembobotan tidak membuat selang tampak lebih sempit dari seharusnya.
    ragam = sum(b * (x - rerata) ** 2 for b, x in zip(bobot, nilai)) / jumlah_bobot
    n_efektif = ukuran_efektif(bobot)
    if n_efektif < 2:
        return Selang(rerata, rerata, rerata, n, populasi)
    galat = math.sqrt(ragam * n_efektif / (n_efektif - 1) / n_efektif)
    galat *= koreksi_populasi(round(n_efektif), populasi)
    lebar = nilai_t(round(n_efektif) - 1) * galat
    bawah, atas = rerata - lebar, rerata + lebar
    if batas is not None:
        bawah = max(batas[0], bawah)
        atas = min(batas[1], atas)
    return Selang(rerata, bawah, atas, n, populasi)


def proporsi(
    berhasil: float, jumlah: int, populasi: int | None = None
) -> Selang | None:
    """Proporsi beserta selang Wilson 95%.

    Dipakai untuk top-2-box dan tingkat pengisian. Metode Wilson dipilih
    karena nilainya sering dekat 1, tempat hampiran normal gagal.

    >>> s = proporsi(85, 100)
    >>> round(s.nilai, 2), round(s.bawah, 2), round(s.atas, 2)
    (0.85, 0.77, 0.91)
    """
    if jumlah <= 0:
        return None
    p = berhasil / jumlah
    z = Z_95
    fpc = koreksi_populasi(jumlah, populasi)
    z2 = z * z
    penyebut = 1 + z2 / jumlah
    tengah = (p + z2 / (2 * jumlah)) / penyebut
    dalam = p * (1 - p) / jumlah * (fpc**2) + z2 / (4 * jumlah * jumlah)
    lebar = z / penyebut * math.sqrt(max(dalam, 0.0))
    return Selang(p, max(0.0, tengah - lebar), min(1.0, tengah + lebar),
                  jumlah, populasi)


def ukuran_efektif(bobot: Sequence[float]) -> float:
    """Ukuran efektif sampel menurut rumus Kish.

    Pembobotan selalu mengurangi presisi. Angka inilah yang harus dilaporkan,
    bukan jumlah jawaban mentah (metodologi bagian 7).

    >>> ukuran_efektif([1, 1, 1, 1])
    4.0
    >>> ukuran_efektif([3, 1, 1, 1])
    3.0
    >>> round(ukuran_efektif([3, 1, 1, 1, 1, 1]), 2)
    4.57
    """
    if not bobot:
        return 0.0
    jumlah = sum(bobot)
    kuadrat = sum(b * b for b in bobot)
    if kuadrat <= 0:
        return 0.0
    return jumlah * jumlah / kuadrat


def bobot_pasca_stratifikasi(
    responden_per_sel: dict[str, int],
    populasi_per_sel: dict[str, int],
    batas: float = 3.0,
) -> dict[str, float]:
    """Bobot agar komposisi responden menyerupai komposisi populasi.

    Sel yang tidak punya responden tidak bisa diwakili dan diabaikan; bagian
    populasinya hilang dari hitungan, dan itu harus dilaporkan.

    Bobot dibatasi ``batas`` kali (bawaan 3) karena bobot ekstrem membuat
    beberapa responden mendominasi dan justru memperbesar ragam
    (metodologi bagian 7).

    >>> bobot_pasca_stratifikasi({"a": 50, "b": 10}, {"a": 100, "b": 100})
    {'a': 0.6, 'b': 3.0}
    """
    terwakili = {k: v for k, v in responden_per_sel.items() if v > 0}
    if not terwakili:
        return {}
    total_responden = sum(terwakili.values())
    total_populasi = sum(populasi_per_sel.get(k, 0) for k in terwakili)
    if total_populasi <= 0:
        return {k: 1.0 for k in terwakili}

    bobot: dict[str, float] = {}
    for sel, jumlah in terwakili.items():
        bagian_populasi = populasi_per_sel.get(sel, 0) / total_populasi
        bagian_responden = jumlah / total_responden
        w = bagian_populasi / bagian_responden if bagian_responden else 1.0
        bobot[sel] = round(min(w, batas), 6)
    return bobot


@dataclass(frozen=True)
class Ringkasan:
    """Ringkasan satu pertanyaan skala."""

    n: int
    rata_rata: Selang | None
    top2: Selang | None
    sebaran: dict[int, int]

    @property
    def n_efektif(self) -> float:
        return float(self.n)


def ringkas_nilai(
    nilai: Sequence[int],
    populasi: int | None = None,
    bobot: Sequence[float] | None = None,
) -> Ringkasan:
    """Ringkas jawaban satu pertanyaan skala 1-5.

    Metrik utamanya rata-rata dan persentase menjawab 4 atau 5 (top-2-box),
    sesuai keputusan 4.4.
    """
    sebaran = {n: 0 for n in range(1, 6)}
    for v in nilai:
        if v in sebaran:
            sebaran[v] += 1
    if not nilai:
        return Ringkasan(0, None, None, sebaran)
    if bobot is None:
        bobot = [1.0] * len(nilai)
    atas = sum(b for b, v in zip(bobot, nilai) if v >= 4)
    jumlah_bobot = sum(bobot)
    # Dinyatakan ulang ke ukuran sampel sebenarnya supaya selangnya memakai n
    # yang benar, bukan jumlah bobot.
    berhasil = atas / jumlah_bobot * len(nilai) if jumlah_bobot else 0.0
    return Ringkasan(
        n=len(nilai),
        rata_rata=rata_rata(nilai, populasi, bobot, batas=(1.0, 5.0)),
        top2=proporsi(berhasil, len(nilai), populasi),
        sebaran=sebaran,
    )
