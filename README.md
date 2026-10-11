# Sistem Survei Pelanggan JoDerma

Membuat link survei unik per pasien dari laporan transaksi klinik, dikirim
manual oleh CS lewat WhatsApp Web, hasilnya dirapikan dan dianalisis berkala.

JoDerma adalah klinik kulit dengan dua cabang.

## Status

**Tahap 4 selesai.** Alur lengkap sudah jalan: unggah laporan, buat link, daftar kirim CS, sampai pasien mengisi survei (681 tes).

| Tahap | Isi | Status |
|---|---|---|
| 0 | Kerangka proyek, modul tanggal + tes | **selesai** |
| 1 | Parser laporan + pembersihan data + tes | **selesai** |
| 2 | Basis data + aturan jeda kirim + tes | **selesai** |
| 3 | Pembuatan link + daftar kirim CS | **selesai** |
| 4 | Halaman survei publik | **selesai** |
| 5 | Perapian data + ekspor anonim | belum |
| 6 | Laporan PDF | belum |

## Menjalankan

```
uv run python -m joderma_survey --basis joderma.db siapkan
uv run python -m joderma_survey --basis joderma.db pengguna --nama <nama> --peran direktur
uv run python -m joderma_survey --basis joderma.db jalankan --porta 8000
uv run python -m joderma_survey --basis joderma.db jalankan-survei --porta 8001
```

Dua aplikasi terpisah: `jalankan` untuk admin (porta 8000) dan
`jalankan-survei` untuk halaman pasien (porta 8001). Di mini PC keduanya
dipetakan ke subdomain berbeda lewat Cloudflare Tunnel, dan hanya porta
survei yang berada di luar kebijakan Cloudflare Access.

Mengubah isi survei: sunting `config/pertanyaan.toml`, lalu

```
uv run python -m joderma_survey --basis joderma.db pertanyaan            # uji kering
uv run python -m joderma_survey --basis joderma.db pertanyaan --terapkan
```

Peubah lingkungan: `JODERMA_URL_SURVEI` (alamat halaman survei publik) dan
`JODERMA_KUNCI_RAHASIA` (kunci sesi; harus tetap, kalau tidak semua pengguna
keluar setiap aplikasi dijalankan ulang).

## Menjalankan tes

```
uv run pytest
```

## Aturan kelayakan kirim

```
Pasien boleh dibuatkan link baru bila:   hari_ini >= terblokir_sampai

terblokir_sampai = yang paling akhir dari:
    diisi_pada_terakhir  + 365 hari     (bila pernah mengisi)
    dibuat_pada_terakhir +  30 hari     (bila pernah dibuatkan link)
```

Kuncinya **nomor rekam medis pasien**, bukan nomor faktur dan bukan nomor
telepon. Satu pasien satu link per unggahan laporan. Jeda berlaku gabungan
lintas cabang, karena satu pasien punya satu nomor rekam medis.

`terblokir_sampai` dihitung saat ditanya, tidak disimpan sebagai penanda —
jadi tidak perlu penjadwal yang bisa mati tanpa ketahuan.

## Hak akses

| Peran | Daftar kirim | Unggah laporan | Hasil survei | Kelola pengguna |
|---|---|---|---|---|
| Owner | ya | ya | ya | tidak |
| Direktur operasional | ya | ya | ya | ya |
| CS | ya | **tidak** | **tidak** | tidak |

Aplikasi admin dan halaman survei publik adalah **dua aplikasi terpisah**,
bukan satu aplikasi dengan aturan rute, sehingga subdomain survei secara
fisik tidak punya kode admin untuk dijangkau.

## Pemisahan identitas dan jawaban

Jawaban survei disimpan **tanpa kaitan ke pasien**. Tidak ada kolom yang
menghubungkan tabel jawaban ke tabel pasien maupun ke tabel undangan.
Satu-satunya jembatan adalah tabel izin, yang barisnya hanya dibuat bila
pasien menjawab bahwa ia boleh dihubungi untuk tindak lanjut.

Aturan jeda tetap bisa berjalan karena yang dicatat di sisi identitas hanya
*bahwa* seseorang sudah mengisi dan *tanggalnya*, bukan apa jawabannya.

## Privasi

- Nomor telepon pasien **tidak pernah masuk aplikasi.** CS mencari kontak di
  WhatsApp klinik secara manual.
- NIK dan diagnosa **tidak pernah dibaca maupun disimpan**, walau tersedia di
  salah satu laporan sumber.
- Laporan sumber dan basis data **tidak pernah masuk git.** Lihat
  `.gitignore`.
- Berkas untuk analisis memakai ID anonim, bukan nama atau nomor rekam medis.
- Link survei memakai token acak sekali pakai, tanpa nama atau nomor apa pun
  di URL.
- Untuk pengujian dipakai contoh yang sudah disamarkan, bukan data asli.

Dokumen perencanaan (PRD, catatan keputusan, temuan data, daftar gap) ditahan
lokal dan tidak ikut di repo ini.

## Teknologi

Python + SQLite. Tanpa kerangka kerja JavaScript.

Pembacaan `.xls` memakai `xlrd` langsung dengan
`ignore_workbook_corruption=True` — laporan sumber punya struktur OLE2 cacat
sehingga `pandas.read_excel()` gagal membacanya dengan
`CompDocError: Workbook corruption`.
