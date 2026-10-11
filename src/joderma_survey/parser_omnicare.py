"""Pembacaan laporan Omnicare "Transaksi Penjualan" (.xls).

Memenuhi F1 dan F2: membaca hanya kolom yang diperlukan, menolak berkas yang
judul kolomnya tidak sesuai, merapikan nomor RM, serta melewati baris catatan
kaki dan baris tanpa nomor RM yang sah.

**Kolom yang dibaca** hanya sembilan dari tujuh belas: TANGGAL, NO. FAKTUR,
LAYANAN, NO. ID, PASIEN, TENAGA MEDIS, HARGA (Rp), STATUS, WAKTU TRANSAKSI.
Kolom CATATAN sengaja tidak dibaca karena berisi teks bebas yang bisa memuat
keterangan pribadi, dan tidak diperlukan sistem ini.

**Berkas .xls Omnicare punya struktur OLE2 cacat.** Pembacaan biasa gagal
dengan ``CompDocError: Workbook corruption``, jadi dipakai
``ignore_workbook_corruption=True``. Akibatnya ``pandas.read_excel()`` tidak
bisa dipakai sama sekali. Lihat docs/temuan-data.md butir T1 dan
docs/gaps.md butir G8.

Pembacaan berkas (:func:`baca_laporan`) dipisah dari penafsiran baris
(:func:`baca_lembar`) supaya seluruh logika bisa diuji tanpa berkas asli,
yang memuat data pasien dan tidak boleh masuk git.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, Sequence

from .cabang import CABANG, Cabang, cabang_dari_kode
from .pembersihan import HasilRM, StatusRM, curiga_bukan_pasien, normalisasi_nama, normalisasi_rm
from .tanggal import (
    TanggalTidakDikenal,
    dalam_periode,
    kunci_urut,
    parse_periode_laporan,
    parse_tanggal,
    parse_waktu,
    tanggal_mungkin_terbalik,
)

__all__ = [
    "LaporanTidakValid",
    "BarisTransaksi",
    "RingkasanUnggahan",
    "Laporan",
    "KOLOM_WAJIB",
    "STATUS_DIPAKAI",
    "kode_cabang_dari_nama_berkas",
    "baca_laporan",
    "baca_lembar",
]


class LaporanTidakValid(Exception):
    """Berkas tidak bisa diterima sebagai laporan Transaksi Penjualan."""


#: Judul kolom persis seperti yang ditulis Omnicare, dalam urutan aslinya.
#: Kolom RM bernama ``NO. ID``, bukan "NO. RM".
KOLOM_WAJIB: tuple[str, ...] = (
    "TANGGAL",
    "NO. FAKTUR",
    "LAYANAN",
    "NO. ID",
    "PASIEN",
    "TENAGA MEDIS",
    "ASURANSI",
    "HARGA (Rp)",
    "LAIN-LAIN",
    "TUSLAH (Rp)",
    "PAJAK (Rp)",
    "TANGGUNGAN (Rp)",
    "KURANG BAYAR (Rp)",
    "CATATAN",
    "STATUS",
    "PENGGUNA",
    "WAKTU TRANSAKSI",
)

#: Hanya baris lunas yang dipakai. Di laporan contoh seluruh baris LUNAS, tapi
#: baris filter berbunyi "STATUS: SEMUA", jadi ekspor lain bisa memuat baris
#: belum lunas. Filternya dibuat tersurat, bukan diandalkan pada kebetulan.
STATUS_DIPAKAI: frozenset[str] = frozenset({"LUNAS"})

_BARIS_HEADER_MAKS = 12


class Lembar(Protocol):
    """Antarmuka minimal sebuah lembar kerja, agar bisa diganti saat diuji."""

    @property
    def nrows(self) -> int: ...
    @property
    def ncols(self) -> int: ...
    def cell_value(self, row: int, col: int) -> object: ...


@dataclass(frozen=True)
class BarisTransaksi:
    """Satu baris transaksi yang sudah bersih dan siap dipakai."""

    nomor_baris: int
    """Nomor baris di berkas (mulai 1), untuk jejak audit."""

    tanggal: object  # datetime.date
    waktu: object | None  # datetime.datetime | None
    no_faktur: int
    layanan: str
    rm: str
    nama: str
    dokter: str
    harga: float
    status: str
    keraguan: tuple[str, ...] = ()
    """Alasan meragukan baris ini pasien perorangan. Peringatan saja."""

    @property
    def kunci_urut(self) -> tuple[object, object]:
        """Kunci untuk memilih kunjungan terakhir: TANGGAL utama, WAKTU pemutus."""
        return kunci_urut(self.tanggal, self.waktu)  # type: ignore[arg-type]


@dataclass
class RingkasanUnggahan:
    """Apa yang terjadi saat satu berkas dibaca. Ditampilkan ke direktur."""

    nama_berkas: str
    cabang: Cabang
    periode_awal: object
    periode_akhir: object
    baris_di_berkas: int = 0
    baris_catatan_kaki: int = 0
    baris_data: int = 0
    baris_dipakai: int = 0
    dilewati: dict[str, int] = field(default_factory=dict)
    pasien_unik: int = 0
    layanan: dict[str, int] = field(default_factory=dict)
    rm_dinormalisasi: list[tuple[int, str, str]] = field(default_factory=list)
    rm_tidak_dikenal: list[tuple[int, str, str]] = field(default_factory=list)
    keraguan: list[tuple[str, str, tuple[str, ...]]] = field(default_factory=list)
    peringatan: list[str] = field(default_factory=list)

    def _lewati(self, alasan: str) -> None:
        self.dilewati[alasan] = self.dilewati.get(alasan, 0) + 1

    @property
    def total_dilewati(self) -> int:
        return sum(self.dilewati.values())

    def ringkas(self) -> str:
        """Teks ringkas untuk ditampilkan setelah unggah."""
        baris = [
            f"{self.nama_berkas} -> {self.cabang.nama}",
            f"periode {self.periode_awal} s/d {self.periode_akhir}",
            f"{self.baris_dipakai} baris dipakai dari {self.baris_data} baris data "
            f"({self.pasien_unik} pasien unik)",
        ]
        if self.dilewati:
            rinci = ", ".join(f"{k}: {v}" for k, v in sorted(self.dilewati.items()))
            baris.append(f"dilewati {self.total_dilewati} -> {rinci}")
        if self.rm_dinormalisasi:
            baris.append(f"nomor RM dinormalisasi: {len(self.rm_dinormalisasi)} baris")
        if self.rm_tidak_dikenal:
            baris.append(f"nomor RM tidak dikenal: {len(self.rm_tidak_dikenal)} baris")
        if self.keraguan:
            baris.append(f"baris patut diragukan sebagai pasien: {len(self.keraguan)}")
        for p in self.peringatan:
            baris.append(f"PERINGATAN: {p}")
        return "\n".join(baris)


@dataclass(frozen=True)
class Laporan:
    baris: tuple[BarisTransaksi, ...]
    ringkasan: RingkasanUnggahan

    def terakhir_per_pasien(self) -> dict[str, BarisTransaksi]:
        """Kunjungan terakhir setiap pasien: satu link per pasien per unggahan.

        TANGGAL mendominasi, WAKTU TRANSAKSI hanya memutus di hari yang sama.
        """
        hasil: dict[str, BarisTransaksi] = {}
        for b in self.baris:
            lama = hasil.get(b.rm)
            if lama is None or b.kunci_urut > lama.kunci_urut:
                hasil[b.rm] = b
        return hasil


def kode_cabang_dari_nama_berkas(nama: str | Path) -> str:
    """Ambil kode cabang dari nama berkas Omnicare.

    Contoh nama: ``sales_transactions_11_10_2026_30376.xls``. Tanggal di nama
    berkas adalah tanggal ekspor, bukan periode laporan, jadi tidak dipakai.

    >>> kode_cabang_dari_nama_berkas("sales_transactions_11_10_2026_30376.xls")
    '30376'
    """
    teks = Path(nama).name
    ketemu = sorted({k for k in CABANG if re.search(rf"(?<!\d){k}(?!\d)", teks)})
    if not ketemu:
        raise LaporanTidakValid(
            f"kode cabang tidak ditemukan di nama berkas {teks!r}. "
            f"Yang dikenal: {', '.join(sorted(CABANG))}"
        )
    if len(ketemu) > 1:
        raise LaporanTidakValid(
            f"nama berkas {teks!r} memuat lebih dari satu kode cabang: {ketemu}"
        )
    return ketemu[0]


def baca_laporan(path: str | Path, kode_cabang: str | None = None) -> Laporan:
    """Baca berkas .xls Omnicare dari disk.

    Cabang diambil dari kode di nama berkas. Bila ``kode_cabang`` diisi, kode
    itu harus cocok dengan nama berkas; kalau tidak, berkas ditolak. Ini
    mencegah laporan Jemur tercatat sebagai Citraland karena salah pilih.
    """
    import xlrd  # diimpor di dalam fungsi: logika baris bisa diuji tanpa xlrd

    path = Path(path)
    kode_berkas = kode_cabang_dari_nama_berkas(path)
    if kode_cabang is not None and str(kode_cabang).strip() != kode_berkas:
        raise LaporanTidakValid(
            f"cabang yang dipilih ({cabang_dari_kode(kode_cabang).nama}) tidak cocok "
            f"dengan kode di nama berkas ({kode_berkas} = "
            f"{cabang_dari_kode(kode_berkas).nama}). Berkas tidak diproses."
        )
    try:
        buku = xlrd.open_workbook(path, ignore_workbook_corruption=True)
    except Exception as exc:  # pragma: no cover - bergantung berkas nyata
        raise LaporanTidakValid(f"berkas {path.name!r} tidak bisa dibuka: {exc}") from exc
    return baca_lembar(buku.sheet_by_index(0), path.name, kode_berkas)


def _teks(lembar: Lembar, row: int, col: int) -> str:
    try:
        nilai = lembar.cell_value(row, col)
    except IndexError:
        return ""
    return "" if nilai is None else str(nilai).strip()


def _cari_baris_header(lembar: Lembar) -> int:
    """Cari baris judul kolom. Omnicare menaruhnya di baris ke-4 (indeks 3)."""
    batas = min(lembar.nrows, _BARIS_HEADER_MAKS)
    for row in range(batas):
        if _teks(lembar, row, 0).upper() == KOLOM_WAJIB[0]:
            return row
    raise LaporanTidakValid(
        f"baris judul kolom tidak ditemukan di {batas} baris pertama. "
        f"Kolom pertama seharusnya {KOLOM_WAJIB[0]!r}."
    )


def _periksa_header(lembar: Lembar, baris_header: int) -> dict[str, int]:
    """Cocokkan judul kolom tanpa peduli besar-kecil huruf.

    Omnicare menulis "HARGA (Rp)" dengan p kecil, jadi perbandingan harus
    tidak peduli besar-kecil di kedua sisi. Kunci yang dikembalikan selalu
    memakai ejaan baku di KOLOM_WAJIB.
    """
    ada = [_teks(lembar, baris_header, c) for c in range(lembar.ncols)]
    posisi = {nama.upper(): i for i, nama in enumerate(ada)}
    indeks: dict[str, int] = {}
    hilang: list[str] = []
    for k in KOLOM_WAJIB:
        i = posisi.get(k.upper())
        if i is None:
            hilang.append(k)
        else:
            indeks[k] = i
    if hilang:
        raise LaporanTidakValid(
            "judul kolom tidak sesuai laporan Transaksi Penjualan.\n"
            f"  kolom hilang : {hilang}\n"
            f"  yang ditemukan: {ada}\n"
            "Pastikan yang diunggah laporan Transaksi Penjualan, bukan "
            "Pemeriksaan Tenaga Medis."
        )
    return indeks


def _angka(teks: str) -> float:
    try:
        return float(teks)
    except (TypeError, ValueError):
        return 0.0


def baca_lembar(lembar: Lembar, nama_berkas: str, kode_cabang: str) -> Laporan:
    """Tafsirkan satu lembar kerja menjadi baris transaksi yang bersih.

    Dipisah dari :func:`baca_laporan` supaya bisa diuji dengan lembar palsu,
    tanpa berkas .xls dan tanpa data pasien asli.
    """
    cabang = cabang_dari_kode(kode_cabang)
    baris_header = _cari_baris_header(lembar)
    kolom = _periksa_header(lembar, baris_header)

    judul = _teks(lembar, 0, 0)
    try:
        awal, akhir = parse_periode_laporan(judul)
    except TanggalTidakDikenal as exc:
        raise LaporanTidakValid(
            f"periode laporan tidak bisa dibaca dari baris pertama: {exc}"
        ) from None

    ringkasan = RingkasanUnggahan(
        nama_berkas=nama_berkas,
        cabang=cabang,
        periode_awal=awal,
        periode_akhir=akhir,
        baris_di_berkas=lembar.nrows,
    )

    terpakai: list[BarisTransaksi] = []
    tanggals: list[object] = []
    asal_rm: dict[str, set[str]] = {}
    nama_per_rm: dict[str, set[str]] = {}

    for row in range(baris_header + 1, lembar.nrows):
        nomor_baris = row + 1
        teks_tanggal = _teks(lembar, row, kolom["TANGGAL"])
        try:
            tanggal = parse_tanggal(teks_tanggal)
        except TanggalTidakDikenal:
            # Baris TOTAL dan baris legenda layanan jatuh ke sini. Deteksinya
            # lewat kolom TANGGAL, bukan posisi kolom, karena baris TOTAL
            # bergeser satu kolom (lihat docs/temuan-data.md butir T2).
            ringkasan.baris_catatan_kaki += 1
            continue

        ringkasan.baris_data += 1
        tanggals.append(tanggal)

        layanan = _teks(lembar, row, kolom["LAYANAN"]).upper()
        ringkasan.layanan[layanan] = ringkasan.layanan.get(layanan, 0) + 1

        status = _teks(lembar, row, kolom["STATUS"]).upper()
        if status not in STATUS_DIPAKAI:
            ringkasan._lewati(f"status bukan LUNAS ({status or 'kosong'})")
            continue

        hasil_rm: HasilRM = normalisasi_rm(lembar.cell_value(row, kolom["NO. ID"]))
        if hasil_rm.status is StatusRM.DINORMALISASI:
            ringkasan.rm_dinormalisasi.append(
                (nomor_baris, hasil_rm.asli.strip(), hasil_rm.rm or "")
            )
        elif hasil_rm.status is StatusRM.TIDAK_DIKENAL:
            ringkasan.rm_tidak_dikenal.append(
                (nomor_baris, hasil_rm.asli.strip(), hasil_rm.catatan)
            )
        for p in hasil_rm.peringatan:
            if p not in ringkasan.peringatan:
                ringkasan.peringatan.append(p)

        if not hasil_rm.bisa_dipakai:
            alasan = (
                "baris anonim tanpa nomor RM"
                if hasil_rm.status is StatusRM.TANPA_RM
                else "nomor RM tidak dikenal"
            )
            ringkasan._lewati(alasan)
            continue

        rm = hasil_rm.rm
        assert rm is not None
        nama = normalisasi_nama(lembar.cell_value(row, kolom["PASIEN"]))

        teks_waktu = _teks(lembar, row, kolom["WAKTU TRANSAKSI"])
        try:
            waktu = parse_waktu(teks_waktu) if teks_waktu else None
        except TanggalTidakDikenal:
            waktu = None
            ringkasan.peringatan.append(
                f"baris {nomor_baris}: WAKTU TRANSAKSI tidak terbaca "
                f"({teks_waktu!r}), pengurutan memakai TANGGAL saja"
            )

        teks_faktur = _teks(lembar, row, kolom["NO. FAKTUR"])
        try:
            no_faktur = int(float(teks_faktur))
        except (TypeError, ValueError):
            ringkasan._lewati("nomor faktur tidak terbaca")
            continue

        keraguan = curiga_bukan_pasien(nama, rm)
        if keraguan:
            ringkasan.keraguan.append((rm, nama, keraguan))

        asal_rm.setdefault(rm, set()).add(hasil_rm.asli.strip().upper())
        nama_per_rm.setdefault(rm, set()).add(nama)

        if not dalam_periode(tanggal, awal, akhir):
            ringkasan.peringatan.append(
                f"baris {nomor_baris}: TANGGAL {tanggal} di luar periode laporan "
                f"{awal} s/d {akhir}"
            )

        terpakai.append(
            BarisTransaksi(
                nomor_baris=nomor_baris,
                tanggal=tanggal,
                waktu=waktu,
                no_faktur=no_faktur,
                layanan=layanan,
                rm=rm,
                nama=nama,
                dokter=_teks(lembar, row, kolom["TENAGA MEDIS"]),
                harga=_angka(_teks(lembar, row, kolom["HARGA (Rp)"])),
                status=status,
                keraguan=keraguan,
            )
        )

    ringkasan.baris_dipakai = len(terpakai)
    ringkasan.pasien_unik = len({b.rm for b in terpakai})

    # Satu nomor RM baku yang berasal dari beberapa bentuk asli sekaligus
    # DAN memuat nama berbeda berarti normalisasi menggabungkan dua orang.
    # Di laporan September tidak ada satu pun, tapi diperiksa supaya tidak
    # lolos diam-diam kalau suatu saat terjadi.
    for rm, bentuk in sorted(asal_rm.items()):
        nama_set = nama_per_rm.get(rm, set())
        if len(bentuk) > 1 and len(nama_set) > 1:
            ringkasan.peringatan.append(
                f"nomor RM {rm} berasal dari bentuk berbeda {sorted(bentuk)} "
                f"dengan nama berbeda {sorted(nama_set)}. Normalisasi mungkin "
                f"menggabungkan dua pasien. Periksa di Omnicare sebelum kirim."
            )
        elif len(nama_set) > 1:
            ringkasan.peringatan.append(
                f"nomor RM {rm} memuat lebih dari satu nama: {sorted(nama_set)}"
            )

    if tanggal_mungkin_terbalik(tanggals):  # type: ignore[arg-type]
        ringkasan.peringatan.append(
            "semua tanggal berhari <= 12, sehingga urutan dd/mm tidak bisa "
            "dipastikan dari isinya. Wajar untuk laporan rentang pendek; "
            "periksa bila ini laporan sebulan penuh."
        )

    return Laporan(baris=tuple(terpakai), ringkasan=ringkasan)
