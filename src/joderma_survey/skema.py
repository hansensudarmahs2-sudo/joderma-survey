"""Skema basis data SQLite, sebagai daftar migrasi bernomor.

Gagasan inti rancangan: **identitas pasien dan jawaban survei dipisah secara
struktural** (keputusan 4.1). Tidak ada kolom yang menghubungkan
``sesi_jawaban`` ke ``pasien`` atau ke ``undangan``. Satu-satunya jembatan
adalah tabel ``izin_kontak``, dan barisnya hanya dibuat bila pasien menjawab
bahwa ia boleh dihubungi.

Dengan begitu janji di halaman survei bisa jujur: jawaban memang tidak
tersimpan bersama nama pasien. Batas yang tidak dijamin rancangan ini dicatat
di docs/gaps.md butir G11.
"""

from __future__ import annotations

from typing import Final

__all__ = ["MIGRASI", "VERSI_TERBARU"]


_V1_TABEL: Final[str] = """
-- ---------------------------------------------------------------- sisi identitas
CREATE TABLE pasien (
    rm                TEXT PRIMARY KEY,
    nama_terakhir     TEXT NOT NULL,
    awalan            TEXT NOT NULL,
    pertama_terlihat  TEXT NOT NULL,
    terakhir_terlihat TEXT NOT NULL
) STRICT;

CREATE TABLE unggahan (
    id            INTEGER PRIMARY KEY,
    nama_berkas   TEXT NOT NULL,
    cabang_kode   TEXT NOT NULL,
    periode_awal  TEXT NOT NULL,
    periode_akhir TEXT NOT NULL,
    diunggah_pada TEXT NOT NULL,
    baris_data    INTEGER NOT NULL,
    baris_dipakai INTEGER NOT NULL,
    pasien_unik   INTEGER NOT NULL,
    ringkasan     TEXT NOT NULL
) STRICT;

CREATE TABLE transaksi (
    id          INTEGER PRIMARY KEY,
    unggahan_id INTEGER NOT NULL REFERENCES unggahan(id),
    cabang_kode TEXT NOT NULL,
    no_faktur   INTEGER NOT NULL,
    rm          TEXT NOT NULL REFERENCES pasien(rm),
    tanggal     TEXT NOT NULL,
    waktu       TEXT,
    layanan     TEXT NOT NULL,
    dokter      TEXT NOT NULL,
    harga       REAL NOT NULL,
    -- Penangkal unggahan ganda. Sah karena nomor faktur memuat tahun-bulan
    -- (2609 = September 2026), jadi unik per cabang sepanjang waktu.
    UNIQUE(cabang_kode, no_faktur)
) STRICT;

CREATE INDEX idx_transaksi_rm ON transaksi(rm);
CREATE INDEX idx_transaksi_tanggal ON transaksi(tanggal);

CREATE TABLE undangan (
    id               INTEGER PRIMARY KEY,
    token            TEXT NOT NULL UNIQUE,
    rm               TEXT NOT NULL REFERENCES pasien(rm),
    cabang_kode      TEXT NOT NULL,
    no_faktur        INTEGER NOT NULL,
    unggahan_id      INTEGER NOT NULL REFERENCES unggahan(id),
    set_pertanyaan   TEXT NOT NULL,
    dibuat_pada      TEXT NOT NULL,
    kedaluwarsa_pada TEXT NOT NULL,
    -- Tanggal saja, tanpa jam: aturan 365 hari tidak butuh jam, dan menyimpan
    -- jam mempermudah menebak jawaban siapa lewat kecocokan waktu.
    diisi_pada       TEXT,
    dibatalkan_pada  TEXT
) STRICT;

CREATE INDEX idx_undangan_rm ON undangan(rm);
CREATE INDEX idx_undangan_dibuat ON undangan(dibuat_pada);

-- ------------------------------------------------------------------ pertanyaan
CREATE TABLE pertanyaan (
    id             INTEGER PRIMARY KEY,
    kode           TEXT NOT NULL,
    revisi         INTEGER NOT NULL,
    set_pertanyaan TEXT NOT NULL,
    teks           TEXT NOT NULL,
    jenis          TEXT NOT NULL,
    urutan         INTEGER NOT NULL,
    wajib          INTEGER NOT NULL DEFAULT 0,
    peran          TEXT NOT NULL DEFAULT 'biasa',
    tampil_bila    TEXT,
    mengubah_makna INTEGER NOT NULL DEFAULT 0,
    aktif          INTEGER NOT NULL DEFAULT 1,
    dibuat_pada    TEXT NOT NULL,
    UNIQUE(kode, revisi),
    CHECK (jenis IN ('skala_1_5', 'teks', 'ya_tidak')),
    CHECK (peran IN ('biasa', 'izin_kontak')),
    CHECK (tampil_bila IS NULL OR tampil_bila IN ('ada_nilai_rendah')),
    CHECK (revisi >= 1)
) STRICT;

CREATE INDEX idx_pertanyaan_set ON pertanyaan(set_pertanyaan, aktif, urutan);

-- -------------------------------------------------------------- sisi analisis
-- Sengaja TIDAK punya kolom rm maupun undangan_id.
CREATE TABLE sesi_jawaban (
    id               TEXT PRIMARY KEY,
    diisi_pada       TEXT NOT NULL,
    set_pertanyaan   TEXT NOT NULL,
    cabang_kode      TEXT NOT NULL,
    layanan          TEXT NOT NULL,
    dokter           TEXT NOT NULL,
    unggahan_id      INTEGER NOT NULL REFERENCES unggahan(id),
    selesai          INTEGER NOT NULL DEFAULT 0,
    berhenti_di_kode TEXT,
    durasi_detik     INTEGER
) STRICT;

CREATE INDEX idx_sesi_diisi ON sesi_jawaban(diisi_pada);

CREATE TABLE jawaban (
    id            INTEGER PRIMARY KEY,
    sesi_id       TEXT NOT NULL REFERENCES sesi_jawaban(id) ON DELETE CASCADE,
    pertanyaan_id INTEGER NOT NULL REFERENCES pertanyaan(id),
    nilai_angka   INTEGER,
    nilai_teks    TEXT,
    UNIQUE(sesi_id, pertanyaan_id),
    CHECK (nilai_angka IS NOT NULL OR nilai_teks IS NOT NULL)
) STRICT;

CREATE INDEX idx_jawaban_pertanyaan ON jawaban(pertanyaan_id);

-- Satu-satunya jembatan antara jawaban dan identitas pasien.
CREATE TABLE izin_kontak (
    sesi_id     TEXT PRIMARY KEY REFERENCES sesi_jawaban(id) ON DELETE CASCADE,
    rm          TEXT NOT NULL REFERENCES pasien(rm),
    dibuat_pada TEXT NOT NULL
) STRICT;

CREATE INDEX idx_izin_rm ON izin_kontak(rm);

-- ---------------------------------------------------------------- hak akses
CREATE TABLE pengguna (
    id          INTEGER PRIMARY KEY,
    nama        TEXT NOT NULL UNIQUE,
    peran       TEXT NOT NULL,
    hash_sandi  TEXT NOT NULL,
    aktif       INTEGER NOT NULL DEFAULT 1,
    dibuat_pada TEXT NOT NULL,
    CHECK (peran IN ('owner', 'direktur', 'cs'))
) STRICT;
"""


# Set A (pasien RJ) sesuai docs/metodologi-survei.md bagian 6.
# Pertanyaan tidak pernah diubah di tempat: menyunting berarti menambah revisi
# baru dengan kode yang sama (keputusan 2.14 sebagaimana diperbarui).
_V2_PERTANYAAN_RJ: Final[str] = """
INSERT INTO pertanyaan
    (kode, revisi, set_pertanyaan, teks, jenis, urutan, wajib, peran,
     tampil_bila, mengubah_makna, aktif, dibuat_pada)
VALUES
    ('keseluruhan', 1, 'RJ',
     'Secara keseluruhan, bagaimana penilaian Anda terhadap kunjungan Anda di JoDerma?',
     'skala_1_5', 1, 1, 'biasa', NULL, 0, 1, '2026-10-11'),

    ('penjelasan_dokter', 1, 'RJ',
     'Bagaimana penilaian Anda terhadap kejelasan penjelasan dokter mengenai kondisi dan perawatan Anda?',
     'skala_1_5', 2, 0, 'biasa', NULL, 0, 1, '2026-10-11'),

    ('waktu_tunggu', 1, 'RJ',
     'Bagaimana penilaian Anda terhadap waktu tunggu sebelum dilayani?',
     'skala_1_5', 3, 0, 'biasa', NULL, 0, 1, '2026-10-11'),

    ('sikap_staf', 1, 'RJ',
     'Bagaimana penilaian Anda terhadap sikap staf non-medis dalam melayani Anda?',
     'skala_1_5', 4, 0, 'biasa', NULL, 0, 1, '2026-10-11'),

    ('kenyamanan', 1, 'RJ',
     'Bagaimana penilaian Anda terhadap kenyamanan dan kebersihan ruang klinik?',
     'skala_1_5', 5, 0, 'biasa', NULL, 0, 1, '2026-10-11'),

    ('kejelasan_biaya', 1, 'RJ',
     'Bagaimana penilaian Anda terhadap kejelasan informasi biaya sebelum tindakan?',
     'skala_1_5', 6, 0, 'biasa', NULL, 0, 1, '2026-10-11'),

    ('keluhan_lanjutan', 1, 'RJ',
     'Boleh ceritakan apa yang kurang pada bagian itu?',
     'teks', 7, 0, 'biasa', 'ada_nilai_rendah', 0, 1, '2026-10-11'),

    ('perbaikan', 1, 'RJ',
     'Apa satu hal yang paling perlu kami perbaiki?',
     'teks', 8, 0, 'biasa', NULL, 0, 1, '2026-10-11'),

    ('izin_kontak', 1, 'RJ',
     'Boleh kami hubungi untuk menindaklanjuti masukan Anda?',
     'ya_tidak', 9, 0, 'izin_kontak', NULL, 0, 1, '2026-10-11');
"""


# Mencatat kapan link pertama kali dibuka pasien. Memisahkan "link tidak
# pernah sampai" dari "sampai tapi tidak diisi" -- yang pertama masalah
# pengiriman, yang kedua masalah surveinya. Tanggal saja, tanpa jam, sama
# alasannya dengan diisi_pada.
_V3_DIBUKA: Final[str] = """
ALTER TABLE undangan ADD COLUMN dibuka_pada TEXT;
"""


#: Daftar migrasi: (versi, SQL). Dijalankan berurutan, sekali saja.
MIGRASI: Final[tuple[tuple[int, str], ...]] = (
    (1, _V1_TABEL),
    (2, _V2_PERTANYAAN_RJ),
    (3, _V3_DIBUKA),
)

VERSI_TERBARU: Final[int] = max(versi for versi, _ in MIGRASI)
