# Sistem Survei Pelanggan JoDerma

Membuat link survei unik per pasien dari laporan transaksi klinik, dikirim
manual oleh CS lewat WhatsApp Web, hasilnya dirapikan dan dianalisis berkala.

JoDerma adalah klinik kulit dengan dua cabang.

## Status

**Seluruh tahap selesai.** Alur penuh berjalan dari unggah laporan Omnicare
sampai laporan siap cetak (812 tes). Kebutuhan wajib PRD terpenuhi kecuali
F6, yang sengaja dicabut: karena pengiriman WhatsApp dilakukan manual dan
tidak bisa dipastikan sistem, aplikasi hanya mencatat link yang dibuat,
bukan yang terkirim.

| Tahap | Isi | Status |
|---|---|---|
| 0 | Kerangka proyek, modul tanggal + tes | **selesai** |
| 1 | Parser laporan + pembersihan data + tes | **selesai** |
| 2 | Basis data + aturan jeda kirim + tes | **selesai** |
| 3 | Pembuatan link + daftar kirim CS | **selesai** |
| 4 | Halaman survei publik | **selesai** |
| 5 | Perapian data + ekspor anonim | **selesai** |
| 6 | Laporan PDF | **selesai** |

## Pemasangan di mini PC

```
git clone <repo> && cd joderma-survey
curl -LsSf https://astral.sh/uv/install.sh | sh   # bila uv belum ada
./tools/pasang.sh --kering     # lihat yang akan dikerjakan
./tools/pasang.sh              # kerjakan
```

Beberapa dokumen sengaja tidak masuk repo ini (runbook pemasangan, daftar
gap, PRD). Kirim dari mesin pengembangan dengan
`./tools/kirim-berkas-lokal.sh`.

Aman dijalankan ulang. Langkah yang tidak bisa diotomatiskan (Cloudflare
Tunnel, Syncthing, hak akses di ops, uji pemulihan cadangan) dicetak di
akhir.

## Menjalankan

```
uv run python -m joderma_survey --basis joderma.db siapkan
uv run python -m joderma_survey --basis joderma.db jalankan --porta 8000
uv run python -m joderma_survey --basis joderma.db jalankan-survei --porta 8001
```

Dua aplikasi terpisah: `jalankan` untuk admin (porta 8000) dan
`jalankan-survei` untuk halaman pasien (porta 8001). Di mini PC keduanya
dipetakan ke subdomain berbeda lewat Cloudflare Tunnel, dan hanya porta
survei yang berada di luar kebijakan Cloudflare Access.

**Login admin memakai sesi aplikasi ops** (keputusan 2.55). Aplikasi admin
tidak punya halaman masuk sendiri: setiap permintaan menanyakan ke ops
(`GET /akun/sesi-survei/`) siapa pemilik kuki `sessionid` yang dibawa
peramban. Belum login ops → dialihkan ke halaman login ops. Karena itu admin
hanya bisa dipakai lewat `ops.joderma.id/survei` dengan ops yang hidup;
dibuka langsung tanpa sesi ops, semua halaman mengalihkan ke login ops.
Perintah `pengguna` masih ada untuk tabel lama, tetapi akunnya tidak dipakai
untuk login web.

Mengubah isi survei: sunting `config/pertanyaan.toml`, lalu

```
uv run python -m joderma_survey --basis joderma.db pertanyaan            # uji kering
uv run python -m joderma_survey --basis joderma.db pertanyaan --terapkan
```

Laporan periode ada di halaman **Hasil survei** pada aplikasi admin, dan
dicetak ke PDF langsung dari peramban (Ctrl+P). Halamannya memakai CSS cetak
A4, jadi tidak ada pustaka PDF yang perlu dipasang di mini PC.

Menyiapkan data untuk dianalisis Claude agent:

```
uv run python -m joderma_survey --basis joderma.db ekspor \
    --folder ekspor --awal 2026-10-01 --akhir 2026-10-31
```

Menghasilkan `konteks.md`, `ringkasan.json`, `jawaban.csv`, dan `teks.csv`.
Berkas `konteks.md` memuat batas penafsiran dan harus dibaca lebih dulu oleh
siapa pun yang menganalisis.

Peubah lingkungan:

| Peubah | Isi | Bawaan |
|---|---|---|
| `JODERMA_URL_SURVEI` | alamat halaman survei publik | — |
| `JODERMA_KUNCI_RAHASIA` | kunci sesi; harus tetap, kalau tidak token formulir (CSRF) yang sedang terbuka jadi tidak sah setiap aplikasi dijalankan ulang | acak |
| `JODERMA_AWALAN_ADMIN` | awalan jalur admin, mis. `/survei` | kosong |
| `JODERMA_OPS_INTERNAL` | alamat internal aplikasi ops untuk menanyakan sesi | `http://127.0.0.1:8731` |
| `JODERMA_OPS_HOST` | hostname publik ops: header `Host` ke ops, tujuan login dan tautan "Kembali ke ops" | `ops.joderma.id` |

## Pemasangan di mini PC

```
git clone <repo> && cd joderma-survey
curl -LsSf https://astral.sh/uv/install.sh | sh   # bila uv belum ada
./tools/pasang.sh --kering     # lihat yang akan dikerjakan
./tools/pasang.sh              # kerjakan
```

Beberapa dokumen sengaja tidak masuk repo ini (runbook pemasangan, daftar
gap, PRD). Kirim dari mesin pengembangan dengan
`./tools/kirim-berkas-lokal.sh`.

Aman dijalankan ulang. Langkah yang tidak bisa diotomatiskan (Cloudflare
Tunnel, Syncthing, hak akses di ops, uji pemulihan cadangan) dicetak di
akhir.

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

| Peran | Daftar kirim | Unggah laporan | Hasil survei |
|---|---|---|---|
| Owner | ya | ya | ya |
| Direktur operasional | ya | ya | ya |
| CS | ya | **tidak** | **tidak** |

Peran **ditentukan di aplikasi ops**, bukan di sini: ops menjawab
`direktur`, `owner`, atau `cs`, dan aplikasi admin menerapkan tabel di atas
(`IZIN` di `pengguna.py`) di sisi server. Staf yang sudah login ops tetapi
tidak berhak Survei mendapat halaman 403 dengan tautan kembali ke ops. Ops
ditanya pada setiap permintaan, jadi logout ops atau peran yang dicabut
langsung berlaku. Jawaban ops yang tidak sah, timeout, atau ops mati selalu
dianggap belum login, tidak pernah berhak. Pengelolaan pengguna dan sandi
tidak lagi ada di aplikasi ini.

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

Python + SQLite + Flask, disajikan waitress. Tanpa kerangka kerja JavaScript
dan tanpa pustaka sistem yang perlu dipasang.

Pembacaan `.xls` memakai `xlrd` langsung dengan
`ignore_workbook_corruption=True` — laporan sumber punya struktur OLE2 cacat
sehingga `pandas.read_excel()` gagal membacanya dengan
`CompDocError: Workbook corruption`.
