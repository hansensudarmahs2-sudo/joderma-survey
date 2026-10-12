# Temuan Laporan Omnicare "Transaksi Penjualan"

Diverifikasi langsung dari dua laporan contoh periode **September 2026**
(Jemur kode 30376, Citraland kode 31281) pada 11 Oktober 2026.

Berkas ini **tidak memuat data pasien** — hanya jumlah, bentuk, dan nama
kolom. Ini acuan untuk menulis tes di tahap 1.

---

## Bentuk berkas

| Hal | Nilai |
|---|---|
| Format | BIFF `.xls` (OLE2), satu lembar bernama `Data Export` |
| Jumlah kolom | 17 |
| Baris 0 | Judul + periode, memakai **nama bulan Indonesia** |
| Baris 1 | Baris filter (`STATUS: SEMUA`, `PENGGUNA: SEMUA`, dst) |
| Baris 2 | Kosong |
| Baris 3 | **Header kolom** |
| Baris 4 ke bawah | Data |
| 2 baris terakhir | Catatan kaki: baris `TOTAL` + baris legenda layanan |

Jumlah baris data: **827** (Jemur), **351** (Citraland).

## Nama kolom (persis seperti di berkas)

```
TANGGAL | NO. FAKTUR | LAYANAN | NO. ID | PASIEN | TENAGA MEDIS | ASURANSI
HARGA (Rp) | LAIN-LAIN | TUSLAH (Rp) | PAJAK (Rp) | TANGGUNGAN (Rp)
KURANG BAYAR (Rp) | CATATAN | STATUS | PENGGUNA | WAKTU TRANSAKSI
```

Kolom nomor RM bernama **`NO. ID`**, bukan "NO. RM". Validasi header harus
memakai nama ini.

## Hal yang harus dijaga di parser

### T1. Struktur OLE2 cacat
Pembacaan biasa gagal: `CompDocError: Workbook corruption: seen[2] == 4`.
Harus `ignore_workbook_corruption=True`. Konsekuensi: **`pandas.read_excel()`
tidak bisa dipakai** untuk berkas Omnicare asli.

### T2. Baris TOTAL bergeser satu kolom
Label `TOTAL` berada di kolom `HARGA (Rp)`, angkanya mulai dari `LAIN-LAIN`.
Jumlah kolom `HARGA` tidak muncul sama sekali di baris itu.

**Jangan deteksi catatan kaki lewat posisi kolom.** Cara yang sudah terbukti:
baris dianggap data hanya bila kolom `TANGGAL` cocok `dd/mm/yyyy`. Di kedua
berkas itu menyisakan tepat 2 baris catatan kaki.

### T3. Kolom TANGGAL selalu teks `dd/mm/yyyy`
1.178 dari 1.178 baris bertipe teks dengan pola `dd/mm/yyyy`. **Tidak ada satu
pun tanggal serial Excel.** Dibaca dengan format tetap, disimpan `YYYY-MM-DD`.

### T4. Nama bulan hanya muncul di baris 0
Periode laporan hanya tersedia sebagai nama bulan Indonesia, contoh pola:
`TRANSAKSI PENJUALAN PER 01 <BULAN> 2026 S/D 30 <BULAN> 2026`.

Di sinilah tabel pemetaan bulan wajib dipakai — bukan di kolom tanggal.
Tanggal di nama berkas (`sales_transactions_DD_MM_YYYY_<kode>.xls`) adalah
**tanggal ekspor**, bukan periode laporan.

### T5. NO. FAKTUR bertipe angka, dan tidak unik global
Tersimpan sebagai float (contoh `26090001.0`) — harus dijadikan integer, bukan
`str(float)`.

Nomor **bentrok antar cabang**: 341 nomor yang sama dipakai di kedua cabang
pada periode yang sama. Nomor memuat tahun+bulan (`2609` = 2026-09), jadi
kunci `UNIQUE(cabang, no_faktur)` sudah cukup dan sekaligus menolak unggahan
ganda.

### T6. Nomor RM kotor
| Macam | Jemur | Citraland | Penanganan |
|---|---|---|---|
| Spasi di ujung | 8 baris | 3 baris | `strip()` — aman |
| Huruf kecil | 0 | 2 baris | `upper()` — aman |
| RM `-` (anonim, nama juga kosong) | 9 baris | 0 | dibuang |
| Jumlah angka menyimpang dari pola baku | 9 baris | 2 baris | dinormalisasi berdasarkan nilai angka, lihat keputusan 2.9 |

Pola baku: Jemur `J` + 5 angka (806 dari 815 baris), Citraland `JC` + 4 angka
(321 dari 321 baris).

Uji tabrakan pada contoh September: **0 kasus** — tidak ada RM menyimpang yang
kembarannya hadir di data, dan tidak ada nomor RM yang memuat lebih dari satu
nama setelah normalisasi.

Bukti bahwa lebar angka memang tetap: nilai kecil pun ditulis penuh
(`J00001` untuk nilai 1, `JC0027` untuk 27). Jadi **angkanya adalah identitas
pasien dan nol di depan hanya kosmetik.** Nilai tertinggi yang ditemukan,
**J08146** dan **JC1099**, cocok dengan jumlah pasien yang dilaporkan klinik
per Oktober 2026 (Jemur ~8200, Citraland ~2000).

### T7. Awalan RM = cabang pendaftaran, bukan cabang kunjungan
| Berkas | Awalan `J` | Awalan `JC` |
|---|---|---|
| Jemur (30376) | 815 baris | 3 baris |
| Citraland (31281) | 30 baris | 321 baris |

33 baris pasien berobat di cabang lain dari tempat ia mendaftar. Memakai
awalan RM sebagai pemeriksaan silang cabang akan memunculkan peringatan palsu
sebanyak itu setiap bulan. Tidak ada awalan `JJ` di data.

### T8. LAYANAN dan TENAGA MEDIS
`OTC` selalu berpasangan dengan `TENAGA MEDIS = "-"`; `RJ` selalu punya nama
dokter. Berlaku 1.178 dari 1.178 baris.

| Berkas | OTC | RJ |
|---|---|---|
| Jemur | 320 | 507 |
| Citraland | 83 | 268 |

### T9. STATUS seluruhnya LUNAS di contoh — tapi jangan diandalkan
Baris filter berbunyi `STATUS: SEMUA`, jadi ekspor lain bisa memuat baris
belum lunas. Filter `STATUS = LUNAS` harus eksplisit.

### T10. Kolom TENAGA MEDIS kotor
Penulisan gelar tidak seragam (`Sp.DVE` vs `Sp.dve` vs `Spdve.`), ada suffix
ganda, ada satu sel memuat **dua nama dokter**, dan ada yang tampak terpotong.
Hanya dipakai untuk analisis, bukan untuk aturan — perlu tabel pemetaan di
tahap 5, bukan tahap 1.

### T11. WAKTU TRANSAKSI memuat jam penuh
Pola `dd/mm/yyyy HH:MM:SS`. Dipakai sebagai pemutus saat satu pasien punya
lebih dari satu transaksi di hari yang sama.

### T12. Baris dengan HARGA = 0
29 baris Jemur, 9 Citraland (total 38). Dari 29 baris Jemur, 26 bernilai nol
di **semua** kolom uang; 3 sisanya hanya berisi ongkos kirim.

Keputusan 2.4: tetap disurvei.

## Jumlah pasien hasil penyaringan

| Berkas | Baris | Baris ber-RM | Pasien unik |
|---|---|---|---|
| Jemur | 827 | 818 | 497 |
| Citraland | 351 | 351 | 244 |
| **Gabungan lintas cabang** | 1.178 | 1.169 | **736** |

Selisih 741 - 736 = **5 pasien** yang bertransaksi di kedua cabang pada
periode yang sama. Inilah pasien yang akan menerima survei ganda bila jeda
diterapkan per cabang.

## Catatan selisih dengan PRD

PRD menyebut 118 pasien OTC-saja di Jemur dan 498 nomor RM; hitungan di sini
117 dan 497. Selisihnya karena RM `-` ikut terhitung sebagai satu "pasien".

### T13. TANGGAL dan WAKTU TRANSAKSI bisa beda hari

**TANGGAL = tanggal kunjungan. WAKTU TRANSAKSI = saat kasir mencatat
pelunasan.** Keduanya tidak selalu sehari.

| Berkas | Baris dengan selisih | Sebaran |
|---|---|---|
| Jemur | 21 dari 827 | +1 hari: 19 baris, +3 hari: 2 baris |
| Citraland | 8 dari 351 | +1 hari: 8 baris |

Contoh nyata: baris 116 Jemur, TANGGAL `05/09/2026`, WAKTU TRANSAKSI
`06/09/2026 14:08:58`. Pola khasnya kunjungan sore atau malam yang baru
dilunasi besoknya.

**Laporan disaring berdasarkan TANGGAL, bukan WAKTU TRANSAKSI.** Buktinya:
seluruh 1.178 TANGGAL berada di dalam periode laporan, sementara satu WAKTU
TRANSAKSI jatuh di luar periode. Ini kabar baik untuk unggah mingguan
(keputusan 4.2) — tidak ada kunjungan yang hilang atau terhitung dua kali
saat berpindah pekan.

**Akibatnya untuk memilih kunjungan terakhir:** urutkan dengan TANGGAL sebagai
kunci utama dan WAKTU TRANSAKSI hanya sebagai pemutus di dalam hari yang sama
(`tanggal.kunci_urut`). Mengurutkan dengan WAKTU TRANSAKSI saja memberi
jawaban salah: kunjungan 20/09 yang dilunasi 21/09 akan terlihat lebih baru
daripada kunjungan 21/09 yang dilunasi 21/09 pagi.

Pada laporan September, kedua cara kebetulan memberi hasil sama untuk semua
pasien (0 selisih) — jadi kesalahan ini tidak akan terlihat kalau hanya diuji
dengan data bulan ini. Itu sebabnya aturannya dipaku di `kunci_urut` beserta
tesnya, bukan diserahkan ke kebetulan.
