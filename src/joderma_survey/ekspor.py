"""Ekspor data rapi untuk dianalisis Claude agent (F12).

Menulis beberapa berkas ke satu folder:

======================  ====================================================
``konteks.md``          Penjelasan cara membaca datanya, termasuk batas yang
                        tidak boleh dilanggar. **Dibaca lebih dulu.**
``ringkasan.json``      Angka ringkasan per pertanyaan beserta selangnya
``jawaban.csv``         Satu baris per jawaban skala, sudah berbobot
``teks.csv``            Jawaban teks bebas yang sudah disaring
``dokter.csv``          Pemetaan kode dokter, hanya bila diminta
======================  ====================================================

**Tidak ada nama pasien, nomor RM, maupun nomor telepon di berkas mana pun.**
Itu bukan karena disensor saat ekspor, melainkan karena tabel jawaban memang
tidak pernah menyimpannya (keputusan 4.1).

Nama dokter diganti kode ``D1``, ``D2``, ... secara bawaan. Analisis per
dokter tetap bisa dilakukan, tapi nama stafnya tidak ikut keluar dari klinik.
Pemetaannya ditulis ke ``dokter.csv`` hanya bila ``sertakan_dokter`` dinyalakan.
"""

from __future__ import annotations

import csv
import datetime as _dt
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .cabang import CABANG
from .perapian import Periode, RingkasanPeriode, rapikan
from .statistik import Selang
from .tanggal import format_periode_id, ke_iso

__all__ = ["HasilEkspor", "ekspor", "kode_dokter"]


@dataclass(frozen=True)
class HasilEkspor:
    folder: Path
    berkas: tuple[Path, ...]
    jumlah_jawaban: int
    jumlah_teks: int

    def ringkas(self) -> str:
        baris = [f"Ekspor ke {self.folder}"]
        for b in self.berkas:
            baris.append(f"  {b.name}")
        baris.append(
            f"{self.jumlah_jawaban} jawaban skala, {self.jumlah_teks} jawaban teks"
        )
        return "\n".join(baris)


def kode_dokter(nama: list[str]) -> dict[str, str]:
    """Petakan nama dokter ke kode D1, D2, ... secara tetap.

    Diurutkan menurut nama supaya kode yang sama muncul lagi di ekspor
    berikutnya selama daftar dokternya tidak berubah.
    """
    unik = sorted({n.strip() for n in nama if n and n.strip() and n.strip() != "-"})
    return {n: f"D{i}" for i, n in enumerate(unik, start=1)}


def _selang(s: Selang | None) -> dict[str, Any] | None:
    if s is None:
        return None
    return {
        "nilai": round(s.nilai, 4),
        "bawah": round(s.bawah, 4),
        "atas": round(s.atas, 4),
        "lebar_setengah": round(s.lebar_setengah, 4),
        "n": s.n,
    }


def ekspor(
    conn: sqlite3.Connection,
    folder: str | Path,
    *,
    periode: Periode | None = None,
    cabang_kode: str | None = None,
    set_pertanyaan: str = "RJ",
    sertakan_dokter: bool = False,
) -> HasilEkspor:
    """Tulis berkas analisis ke ``folder``."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    ringkas = rapikan(
        conn, periode=periode, cabang_kode=cabang_kode, set_pertanyaan=set_pertanyaan
    )

    sesi = conn.execute(
        "SELECT id, diisi_pada, cabang_kode, layanan, dokter, durasi_detik"
        " FROM sesi_jawaban WHERE diisi_pada BETWEEN ? AND ? AND set_pertanyaan = ?"
        + (" AND cabang_kode = ?" if cabang_kode else ""),
        [
            ke_iso(ringkas.periode.awal),
            ke_iso(ringkas.periode.akhir),
            set_pertanyaan,
            *([cabang_kode] if cabang_kode else []),
        ],
    ).fetchall()
    peta_dokter = kode_dokter([s["dokter"] for s in sesi])
    bobot_sel = {s.nama: s.bobot for s in ringkas.sel}

    berkas: list[Path] = []
    jumlah_jawaban = 0

    # ---------------------------------------------------------- jawaban.csv
    jalur = folder / "jawaban.csv"
    with jalur.open("w", newline="", encoding="utf-8") as f:
        tulis = csv.writer(f)
        tulis.writerow(
            ["sesi", "tanggal", "cabang", "layanan", "dokter", "pertanyaan",
             "revisi", "nilai", "bobot", "durasi_detik"]
        )
        for s in sesi:
            sel = f"{s['cabang_kode']}/{s['layanan'] or '-'}"
            bobot = round(bobot_sel.get(sel, 1.0), 4)
            for j in conn.execute(
                "SELECT p.kode, p.revisi, j.nilai_angka FROM jawaban j"
                " JOIN pertanyaan p ON p.id = j.pertanyaan_id"
                " WHERE j.sesi_id = ? AND p.jenis = 'skala_1_5'"
                " ORDER BY p.urutan",
                (s["id"],),
            ):
                tulis.writerow([
                    s["id"], s["diisi_pada"],
                    CABANG[s["cabang_kode"]].nama if s["cabang_kode"] in CABANG
                    else s["cabang_kode"],
                    s["layanan"], peta_dokter.get(s["dokter"] or "", "-"),
                    j["kode"], j["revisi"], j["nilai_angka"], bobot,
                    s["durasi_detik"] if s["durasi_detik"] is not None else "",
                ])
                jumlah_jawaban += 1
    berkas.append(jalur)

    # ------------------------------------------------------------- teks.csv
    jalur = folder / "teks.csv"
    with jalur.open("w", newline="", encoding="utf-8") as f:
        tulis = csv.writer(f)
        tulis.writerow(["pertanyaan", "cabang", "layanan", "teks", "disensor"])
        for t in ringkas.teks_bebas:
            kode = str(t["cabang"])
            tulis.writerow([
                t["kode"],
                CABANG[kode].nama if kode in CABANG else kode,
                t["layanan"], t["teks"], ";".join(t["disensor"]),  # type: ignore[arg-type]
            ])
    berkas.append(jalur)

    # -------------------------------------------------------- ringkasan.json
    isi: dict[str, Any] = {
        "periode": {
            "awal": ke_iso(ringkas.periode.awal),
            "akhir": ke_iso(ringkas.periode.akhir),
            "sebutan": format_periode_id(ringkas.periode.awal, ringkas.periode.akhir),
        },
        "cabang": (
            CABANG[cabang_kode].nama
            if cabang_kode and cabang_kode in CABANG
            else "semua cabang"
        ),
        "set_pertanyaan": set_pertanyaan,
        "pengiriman": {
            "undangan": ringkas.undangan,
            "dibuka": ringkas.dibuka,
            "terisi": ringkas.terisi,
            "dibatalkan": ringkas.dibatalkan,
            "kedaluwarsa_belum_diisi": ringkas.kedaluwarsa_belum_diisi,
            "tingkat_pembukaan": _selang(ringkas.tingkat_pembukaan),
            "tingkat_pengisian": _selang(ringkas.tingkat_pengisian),
            "terisi_dari_yang_dibuka": _selang(ringkas.terisi_dari_yang_dibuka),
        },
        "ukuran_efektif_sampel": round(ringkas.n_efektif, 2),
        "izin_dihubungi": ringkas.izin_kontak,
        "sel": [
            {
                "sel": s.nama,
                "cabang": CABANG[s.cabang_kode].nama
                if s.cabang_kode in CABANG else s.cabang_kode,
                "layanan": s.layanan,
                "populasi": s.populasi,
                "responden": s.responden,
                "tingkat_pengisian": round(s.tingkat_pengisian, 4),
                "bobot": round(s.bobot, 4),
            }
            for s in ringkas.sel
        ],
        "pertanyaan": [
            {
                "kode": p.kode,
                "teks": p.teks,
                "jenis": p.jenis,
                "revisi_terpakai": list(p.revisi_terpakai),
                "pernah_mengubah_makna": p.mengubah_makna,
                "dijawab": p.dijawab,
                "dikosongkan": p.dikosongkan,
                "tingkat_pengisian_butir": round(p.tingkat_pengisian_butir, 4),
                "rata_rata": _selang(p.ringkasan.rata_rata) if p.ringkasan else None,
                "top_2_box": _selang(p.ringkasan.top2) if p.ringkasan else None,
                "sebaran": p.ringkasan.sebaran if p.ringkasan else None,
            }
            for p in ringkas.pertanyaan
        ],
        "peringatan": ringkas.peringatan,
    }
    jalur = folder / "ringkasan.json"
    jalur.write_text(
        json.dumps(isi, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    berkas.append(jalur)

    # ----------------------------------------------------------- dokter.csv
    if sertakan_dokter and peta_dokter:
        jalur = folder / "dokter.csv"
        with jalur.open("w", newline="", encoding="utf-8") as f:
            tulis = csv.writer(f)
            tulis.writerow(["kode", "nama"])
            for nama, kode in sorted(peta_dokter.items(), key=lambda kv: kv[1]):
                tulis.writerow([kode, nama])
        berkas.append(jalur)

    # ----------------------------------------------------------- konteks.md
    jalur = folder / "konteks.md"
    jalur.write_text(_konteks(ringkas, cabang_kode, sertakan_dokter), encoding="utf-8")
    berkas.insert(0, jalur)

    return HasilEkspor(
        folder=folder,
        berkas=tuple(berkas),
        jumlah_jawaban=jumlah_jawaban,
        jumlah_teks=len(ringkas.teks_bebas),
    )


def _konteks(
    r: RingkasanPeriode, cabang_kode: str | None, sertakan_dokter: bool
) -> str:
    cabang = (
        CABANG[cabang_kode].nama if cabang_kode and cabang_kode in CABANG
        else "semua cabang"
    )
    pengisian = r.tingkat_pengisian
    angka_pengisian = (
        f"{pengisian.nilai:.1%} ({pengisian.bawah:.1%}-{pengisian.atas:.1%})"
        if pengisian else "belum bisa dihitung"
    )
    return f"""# Konteks data survei JoDerma

Dibuat {ke_iso(_dt.date.today())} ·
periode {format_periode_id(r.periode.awal, r.periode.akhir)} · {cabang}

**Baca berkas ini sebelum menganalisis apa pun.** Isinya bukan keterangan
tambahan, melainkan batas-batas yang menentukan kesimpulan mana yang boleh
ditarik dari angka-angka di sini.

## Sifat data

Ini **sensus dengan respons sukarela**, bukan survei sampel. Link dikirim ke
semua pasien yang memenuhi syarat; yang menentukan siapa terwakili adalah
pasien sendiri, bukan rancangan pengambilan sampel.

Akibatnya **kesalahan utamanya nonresponse bias, bukan kesalahan pengambilan
sampel.** Bias itu tidak mengecil kalau jumlah jawaban bertambah.

- Undangan dikirim: {r.undangan}
- Link dibuka: {r.dibuka}
- Survei terisi: {r.terisi}
- Tingkat pengisian: {angka_pengisian}
- Ukuran efektif sampel setelah pembobotan: {r.n_efektif:.1f}

## Lima hal yang tidak boleh dilakukan

1. **Jangan membandingkan skor dengan tolok ukur industri.** Skalanya
   ditampilkan sebagai bintang, yang punya jangkar budaya kuat (lima bintang
   = sempurna), sehingga sebarannya menumpuk di ujung atas lebih kuat
   daripada skala berlabel biasa.
2. **Jangan membaca tingkat skornya, bacalah perubahannya.** Jawaban
   dikumpulkan lewat link yang dikirim klinik sendiri, dan pasien tahu
   dirinya dikenali saat mengisi. Itu menekan kritik ke atas
   (courtesy bias). Yang bermakna adalah arah dan besar perubahannya
   antar periode, bukan ketinggian angkanya.
3. **Jangan menyatakan dua angka berbeda bila selangnya bertumpang tindih.**
   Setiap angka di `ringkasan.json` punya `bawah` dan `atas`. Perubahan yang
   lebih kecil daripada `lebar_setengah` adalah derau, bukan perbaikan atau
   penurunan.
4. **Jangan membuat skor per dokter dari data satu periode.** Satu dokter
   biasanya hanya punya belasan jawaban per bulan, dengan selang sekitar
   ±0,3 sampai ±0,9 poin. Skor per dokter hanya sah secara tahunan dengan
   minimal 100 jawaban terkumpul.
5. **Jangan menganggap pembobotan sudah menambal nonresponse bias.**
   Pembobotan hanya memperbaiki bias pada variabel yang dipakai membobot
   (cabang dan jenis layanan). Bila pasien yang tidak puas lebih enggan
   mengisi **di dalam tiap sel**, pembobotan tidak memperbaiki apa pun.

## Isi berkas

- `ringkasan.json` — angka per pertanyaan: rata-rata, top-2-box
  (persentase menjawab 4 atau 5), sebaran, dan selang kepercayaan 95%.
  Juga tingkat pengisian per sel.
- `jawaban.csv` — satu baris per jawaban skala, dengan `bobot` untuk
  pembobotan pasca-stratifikasi.
- `teks.csv` — jawaban teks bebas. Kolom `disensor` menyebut jenis
  keterangan yang sudah dibuang (nomor telepon, nomor RM, surel, nama).
{"- `dokter.csv` — pemetaan kode dokter ke nama." if sertakan_dokter else
 "- Nama dokter **tidak disertakan**; hanya kode D1, D2, dan seterusnya."}

## Privasi

Tidak ada nama pasien, nomor rekam medis, maupun nomor telepon di berkas mana
pun. Itu bukan hasil penyensoran saat ekspor, melainkan karena tabel jawaban
memang tidak pernah menyimpannya: jawaban survei disimpan terpisah dari
identitas, dan tautan ke pasien hanya dibuat bila pasien sendiri mengizinkan
untuk dihubungi.

Pada periode ini {r.izin_kontak} responden memberi izin dihubungi.

## Peringatan untuk periode ini

{chr(10).join("- " + p for p in r.peringatan) if r.peringatan
 else "- Tidak ada."}
"""
