"""Perapian data jawaban survei (F11).

Mengubah baris mentah di basis data menjadi kumpulan angka yang siap
dianalisis, lengkap dengan hal-hal yang diwajibkan metodologi bagian 9:
tingkat pengisian per sel, perbandingan responden terhadap seluruh yang
dikirimi, ukuran efektif sampel, dan selang kepercayaan di setiap skor.

**Tiga hal yang dijaga di sini**

1. *Nonresponse bias adalah kesalahan utama*, bukan kesalahan pengambilan
   sampel. Karena itu tingkat pengisian per sel dan perbandingan komposisi
   selalu ikut dihitung, bukan sekadar skornya.
2. *Pembobotan hanya memperbaiki bias pada variabel yang dipakai membobot.*
   Keterbatasan itu ditulis di berkas konteks ekspor supaya tidak terlupa.
3. *Teks bebas bisa membongkar anonimitas sendiri* (gap G16), jadi disaring
   sebelum keluar dari basis data.
"""

from __future__ import annotations

import datetime as _dt
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Final, Iterable, Sequence

from .cabang import CABANG
from .statistik import (
    Ringkasan,
    Selang,
    bobot_pasca_stratifikasi,
    proporsi,
    ringkas_nilai,
    ukuran_efektif,
)
from .tanggal import dari_iso, ke_iso

#: Di bawah jumlah ini, selang kepercayaannya terlalu lebar untuk
#: menyimpulkan apa pun. Bukan ambang statistik baku, hanya pengingat.
MINIMAL_UNTUK_DISIMPULKAN: Final[int] = 10

__all__ = [
    "MINIMAL_UNTUK_DISIMPULKAN",
    "Perbandingan",
    "Periode",
    "banding",
    "periode_sebelumnya",
    "Sel",
    "RingkasanPertanyaan",
    "RingkasanPeriode",
    "saring_teks",
    "sel_dari",
    "rapikan",
]


@dataclass(frozen=True)
class Periode:
    awal: _dt.date
    akhir: _dt.date

    def memuat(self, tanggal: _dt.date) -> bool:
        return self.awal <= tanggal <= self.akhir

    def __str__(self) -> str:
        return f"{ke_iso(self.awal)}..{ke_iso(self.akhir)}"


# --------------------------------------------------------------------------
# Penyaringan teks bebas (gap G16)
# --------------------------------------------------------------------------

_POLA_SENSOR: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    # Nomor telepon Indonesia: 08xx, +62xx, 62xx, boleh berspasi atau berstrip.
    ("TELEPON", re.compile(r"(?:\+?62|0)[\s.-]?8\d(?:[\s.-]?\d){6,11}")),
    ("SUREL", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    # Nomor RM: J + 4-8 angka, atau JC + 3-6 angka.
    ("NOMOR_RM", re.compile(r"\bJC?\s?\d{3,8}\b", re.IGNORECASE)),
    # Rentetan angka panjang: NIK, nomor kartu, nomor rekening.
    ("ANGKA_PANJANG", re.compile(r"\b\d{9,}\b")),
)


def saring_teks(
    teks: str, nama_pasien: Iterable[str] = ()
) -> tuple[str, tuple[str, ...]]:
    """Sensor keterangan yang bisa mengenali orang dari teks bebas.

    Mengembalikan teks tersaring beserta daftar jenis yang disensor.

    Nama pasien disensor hanya bila **nama lengkapnya** (dua kata atau lebih)
    muncul utuh. Nama satu kata sengaja tidak disensor karena banyak nama
    depan Indonesia juga kata biasa, dan menyensornya akan merusak makna
    kalimat lebih sering daripada melindungi siapa pun.

    >>> saring_teks("Hubungi saya di 081234567890")
    ('Hubungi saya di [TELEPON]', ('TELEPON',))
    >>> saring_teks("Nomor RM saya J00635 ya")
    ('Nomor RM saya [NOMOR_RM] ya', ('NOMOR_RM',))
    >>> saring_teks("Pelayanan bagus sekali")
    ('Pelayanan bagus sekali', ())
    """
    if not isinstance(teks, str) or not teks.strip():
        return ("", ())
    hasil = teks
    ditemukan: list[str] = []

    for nama in nama_pasien:
        nama = (nama or "").strip()
        if len(nama.split()) < 2:
            continue
        pola = re.compile(re.escape(nama), re.IGNORECASE)
        if pola.search(hasil):
            hasil = pola.sub("[NAMA]", hasil)
            ditemukan.append("NAMA")

    for label, pola in _POLA_SENSOR:
        if pola.search(hasil):
            hasil = pola.sub(f"[{label}]", hasil)
            ditemukan.append(label)

    return (hasil.strip(), tuple(dict.fromkeys(ditemukan)))


# --------------------------------------------------------------------------
# Sel pembobotan
# --------------------------------------------------------------------------


def sel_dari(cabang_kode: str, layanan: str) -> str:
    """Nama sel pembobotan: cabang x jenis layanan (metodologi bagian 7)."""
    return f"{cabang_kode}/{layanan or '-'}"


@dataclass(frozen=True)
class Sel:
    nama: str
    cabang_kode: str
    layanan: str
    populasi: int
    responden: int
    bobot: float

    @property
    def tingkat_pengisian(self) -> float:
        return self.responden / self.populasi if self.populasi else 0.0


# --------------------------------------------------------------------------
# Ringkasan
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class RingkasanPertanyaan:
    kode: str
    teks: str
    revisi_terpakai: tuple[int, ...]
    mengubah_makna: bool
    jenis: str
    ringkasan: Ringkasan | None
    dijawab: int
    dikosongkan: int

    @property
    def tingkat_pengisian_butir(self) -> float:
        total = self.dijawab + self.dikosongkan
        return self.dijawab / total if total else 0.0


@dataclass
class RingkasanPeriode:
    periode: Periode
    cabang_kode: str | None
    undangan: int = 0
    dibuka: int = 0
    terisi: int = 0
    dibatalkan: int = 0
    kedaluwarsa_belum_diisi: int = 0
    sel: list[Sel] = field(default_factory=list)
    pertanyaan: list[RingkasanPertanyaan] = field(default_factory=list)
    teks_bebas: list[dict[str, object]] = field(default_factory=list)
    n_efektif: float = 0.0
    izin_kontak: int = 0
    peringatan: list[str] = field(default_factory=list)

    @property
    def tingkat_pengisian(self) -> Selang | None:
        return proporsi(self.terisi, self.undangan) if self.undangan else None

    @property
    def tingkat_pembukaan(self) -> Selang | None:
        return proporsi(self.dibuka, self.undangan) if self.undangan else None

    @property
    def terisi_dari_yang_dibuka(self) -> Selang | None:
        return proporsi(self.terisi, self.dibuka) if self.dibuka else None


def _periode_dari(conn: sqlite3.Connection) -> Periode:
    baris = conn.execute(
        "SELECT MIN(diisi_pada) a, MAX(diisi_pada) b FROM sesi_jawaban"
    ).fetchone()
    if baris is None or baris["a"] is None:
        hari = _dt.date.today()
        return Periode(hari, hari)
    return Periode(dari_iso(baris["a"]), dari_iso(baris["b"]))


def rapikan(
    conn: sqlite3.Connection,
    *,
    periode: Periode | None = None,
    cabang_kode: str | None = None,
    set_pertanyaan: str = "RJ",
) -> RingkasanPeriode:
    """Rapikan jawaban satu periode menjadi ringkasan siap analisis."""
    periode = periode or _periode_dari(conn)
    hasil = RingkasanPeriode(periode=periode, cabang_kode=cabang_kode)
    awal, akhir = ke_iso(periode.awal), ke_iso(periode.akhir)

    syarat_cabang = " AND cabang_kode = ?" if cabang_kode else ""
    nilai_cabang: list[object] = [cabang_kode] if cabang_kode else []

    # ---- sisi identitas: berapa yang dikirimi, dibuka, terisi -------------
    baris = conn.execute(
        "SELECT COUNT(*) AS undangan,"
        " SUM(dibuka_pada IS NOT NULL) AS dibuka,"
        " SUM(diisi_pada IS NOT NULL) AS terisi,"
        " SUM(dibatalkan_pada IS NOT NULL AND diisi_pada IS NULL) AS batal,"
        " SUM(diisi_pada IS NULL AND dibatalkan_pada IS NULL"
        "     AND kedaluwarsa_pada <= ?) AS lewat"
        f" FROM undangan WHERE dibuat_pada BETWEEN ? AND ?{syarat_cabang}",
        [akhir, awal, akhir, *nilai_cabang],
    ).fetchone()
    hasil.undangan = baris["undangan"] or 0
    hasil.dibuka = baris["dibuka"] or 0
    hasil.terisi = baris["terisi"] or 0
    hasil.dibatalkan = baris["batal"] or 0
    hasil.kedaluwarsa_belum_diisi = baris["lewat"] or 0

    # ---- sel pembobotan: populasi dari undangan, responden dari jawaban ---
    populasi_sel: dict[str, tuple[str, str, int]] = {}
    for b in conn.execute(
        "SELECT u.cabang_kode, t.layanan, COUNT(*) AS n FROM undangan u"
        " LEFT JOIN transaksi t ON t.cabang_kode = u.cabang_kode"
        "   AND t.no_faktur = u.no_faktur"
        f" WHERE u.dibuat_pada BETWEEN ? AND ?"
        + (" AND u.cabang_kode = ?" if cabang_kode else "")
        + " GROUP BY u.cabang_kode, t.layanan",
        [awal, akhir, *nilai_cabang],
    ):
        nama = sel_dari(b["cabang_kode"], b["layanan"] or "")
        populasi_sel[nama] = (b["cabang_kode"], b["layanan"] or "", b["n"])

    sesi = conn.execute(
        "SELECT id, cabang_kode, layanan, dokter FROM sesi_jawaban"
        f" WHERE diisi_pada BETWEEN ? AND ? AND set_pertanyaan = ?{syarat_cabang}",
        [awal, akhir, set_pertanyaan, *nilai_cabang],
    ).fetchall()

    responden_sel: dict[str, int] = {}
    sel_per_sesi: dict[str, str] = {}
    for s in sesi:
        nama = sel_dari(s["cabang_kode"], s["layanan"])
        responden_sel[nama] = responden_sel.get(nama, 0) + 1
        sel_per_sesi[s["id"]] = nama

    bobot_sel = bobot_pasca_stratifikasi(
        responden_sel, {k: v[2] for k, v in populasi_sel.items()}
    )
    for nama in sorted(set(populasi_sel) | set(responden_sel)):
        cab, lay, pop = populasi_sel.get(nama, ("", "", 0))
        if not cab:
            cab, _, lay = nama.partition("/")
        hasil.sel.append(
            Sel(
                nama=nama,
                cabang_kode=cab,
                layanan=lay,
                populasi=pop,
                responden=responden_sel.get(nama, 0),
                bobot=bobot_sel.get(nama, 0.0),
            )
        )

    tanpa_responden = [s for s in hasil.sel if s.populasi and not s.responden]
    if tanpa_responden:
        hilang = sum(s.populasi for s in tanpa_responden)
        hasil.peringatan.append(
            f"{len(tanpa_responden)} sel tanpa satu pun responden "
            f"({hilang} pasien). Bagian populasi itu tidak terwakili sama "
            f"sekali, dan pembobotan tidak bisa menambalnya."
        )

    bobot_per_sesi = {
        sid: bobot_sel.get(nama, 1.0) for sid, nama in sel_per_sesi.items()
    }
    hasil.n_efektif = ukuran_efektif(list(bobot_per_sesi.values()))

    if not sesi:
        hasil.peringatan.append("Belum ada jawaban pada periode ini.")
        return hasil

    if len(sesi) < MINIMAL_UNTUK_DISIMPULKAN:
        hasil.peringatan.append(
            f"Baru {len(sesi)} jawaban terkumpul. Selang kepercayaannya "
            f"terlalu lebar untuk menyimpulkan apa pun; angka di periode ini "
            f"sebaiknya hanya dipakai memeriksa bahwa alurnya berjalan."
        )

    # ---- jawaban per pertanyaan ------------------------------------------
    id_sesi = list(sel_per_sesi)
    tanda = ",".join("?" * len(id_sesi))
    jawaban = conn.execute(
        "SELECT j.sesi_id, p.kode, p.teks, p.revisi, p.jenis, p.mengubah_makna,"
        " p.urutan, j.nilai_angka, j.nilai_teks"
        f" FROM jawaban j JOIN pertanyaan p ON p.id = j.pertanyaan_id"
        f" WHERE j.sesi_id IN ({tanda})",
        id_sesi,
    ).fetchall()

    semua_pertanyaan = conn.execute(
        "SELECT kode, teks, jenis, urutan, tampil_bila, peran FROM pertanyaan"
        " WHERE set_pertanyaan = ? AND aktif = 1 ORDER BY urutan",
        (set_pertanyaan,),
    ).fetchall()

    per_kode: dict[str, list[sqlite3.Row]] = {}
    for j in jawaban:
        per_kode.setdefault(j["kode"], []).append(j)

    nama_pasien = [
        b["nama_terakhir"] for b in conn.execute("SELECT nama_terakhir FROM pasien")
    ]

    for p in semua_pertanyaan:
        isi = per_kode.get(p["kode"], [])
        revisi = tuple(sorted({j["revisi"] for j in isi}))
        makna = any(j["mengubah_makna"] for j in isi)
        # Pertanyaan bersyarat hanya ditawarkan ke sebagian responden, jadi
        # "dikosongkan" tidak bermakna untuknya.
        bisa_dijawab = len(sesi) if p["tampil_bila"] is None else len(isi)

        if p["jenis"] == "skala_1_5":
            nilai = [j["nilai_angka"] for j in isi if j["nilai_angka"] is not None]
            bobot = [bobot_per_sesi.get(j["sesi_id"], 1.0) for j in isi
                     if j["nilai_angka"] is not None]
            populasi = sum(s.populasi for s in hasil.sel) or None
            ringkas = ringkas_nilai(nilai, populasi, bobot)
        elif p["jenis"] == "ya_tidak":
            nilai = [j["nilai_angka"] for j in isi if j["nilai_angka"] is not None]
            ringkas = Ringkasan(
                n=len(nilai),
                rata_rata=None,
                top2=proporsi(sum(nilai), len(nilai)) if nilai else None,
                sebaran={0: nilai.count(0), 1: nilai.count(1)},
            )
            if p["peran"] == "izin_kontak":
                hasil.izin_kontak = sum(nilai)
        else:
            ringkas = None
            for j in isi:
                if not j["nilai_teks"]:
                    continue
                bersih, disensor = saring_teks(j["nilai_teks"], nama_pasien)
                if not bersih:
                    continue
                s_row = next(x for x in sesi if x["id"] == j["sesi_id"])
                hasil.teks_bebas.append(
                    {
                        "kode": p["kode"],
                        "cabang": s_row["cabang_kode"],
                        "layanan": s_row["layanan"],
                        "teks": bersih,
                        "disensor": list(disensor),
                    }
                )

        hasil.pertanyaan.append(
            RingkasanPertanyaan(
                kode=p["kode"],
                teks=p["teks"],
                revisi_terpakai=revisi,
                mengubah_makna=makna,
                jenis=p["jenis"],
                ringkasan=ringkas,
                dijawab=len(isi),
                dikosongkan=max(0, bisa_dijawab - len(isi)),
            )
        )

    berubah = [p.kode for p in hasil.pertanyaan if p.mengubah_makna]
    if berubah:
        hasil.peringatan.append(
            f"Pertanyaan berikut pernah diubah maknanya: {', '.join(berubah)}. "
            f"Jangan bandingkan langsung dengan periode sebelum perubahan."
        )
    banyak_revisi = [
        p.kode for p in hasil.pertanyaan if len(p.revisi_terpakai) > 1
    ]
    if banyak_revisi:
        hasil.peringatan.append(
            f"Jawaban pada periode ini mencakup lebih dari satu revisi "
            f"pertanyaan: {', '.join(banyak_revisi)}."
        )
    disensor = sum(1 for t in hasil.teks_bebas if t["disensor"])
    if disensor:
        hasil.peringatan.append(
            f"{disensor} jawaban teks disensor sebagian karena memuat nomor "
            f"telepon, nomor RM, surel, atau nama lengkap pasien."
        )
    return hasil


# --------------------------------------------------------------------------
# Perbandingan antar periode
#
# Inilah bagian yang bermakna. Tingkat skornya sendiri tidak banyak berguna
# karena tertekan courtesy bias dan jangkar bintang (metodologi bagian D dan
# bagian Skala); yang bisa ditindaklanjuti adalah arah dan besar
# perubahannya.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Perbandingan:
    kode: str
    teks: str
    sekarang: Selang | None
    sebelum: Selang | None

    @property
    def selisih(self) -> float | None:
        if self.sekarang is None or self.sebelum is None:
            return None
        return self.sekarang.nilai - self.sebelum.nilai

    @property
    def nyata(self) -> bool:
        """Apakah perubahannya lebih besar daripada derau.

        Memakai aturan tumpang tindih selang: kalau kedua selang bersinggungan,
        perubahannya belum tentu nyata. Ini uji yang berhati-hati -- selang
        yang tidak bersinggungan adalah bukti lebih kuat daripada sekadar
        berbeda nyata secara uji baku.
        """
        if self.sekarang is None or self.sebelum is None:
            return False
        return not self.sekarang.tumpang_tindih(self.sebelum)

    @property
    def arah(self) -> str:
        """``naik``, ``turun``, atau ``derau``."""
        selisih = self.selisih
        if selisih is None:
            return "baru"
        if not self.nyata:
            return "derau"
        return "naik" if selisih > 0 else "turun"


def periode_sebelumnya(p: Periode) -> Periode:
    """Periode sepanjang itu juga, tepat sebelum ``p``.

    >>> periode_sebelumnya(Periode(_dt.date(2026, 10, 1), _dt.date(2026, 10, 31)))
    Periode(awal=datetime.date(2026, 8, 31), akhir=datetime.date(2026, 9, 30))
    """
    panjang = (p.akhir - p.awal).days
    akhir = p.awal - _dt.timedelta(days=1)
    return Periode(akhir - _dt.timedelta(days=panjang), akhir)


def banding(
    sekarang: RingkasanPeriode, sebelum: RingkasanPeriode | None
) -> list[Perbandingan]:
    """Bandingkan skor tiap pertanyaan dengan periode sebelumnya."""
    lama: dict[str, Selang | None] = {}
    if sebelum is not None:
        lama = {
            p.kode: (p.ringkasan.rata_rata if p.ringkasan else None)
            for p in sebelum.pertanyaan
        }
    hasil: list[Perbandingan] = []
    for p in sekarang.pertanyaan:
        if p.jenis != "skala_1_5":
            continue
        hasil.append(
            Perbandingan(
                kode=p.kode,
                teks=p.teks,
                sekarang=p.ringkasan.rata_rata if p.ringkasan else None,
                sebelum=lama.get(p.kode),
            )
        )
    return hasil
