# Metodologi dan Kerangka Survei

Disepakati 11 Oktober 2026. Acuan untuk tahap 1-6.

---

## 1. Sifat survei ini

**Ini sensus dengan respons sukarela, bukan survei sampel.** Link dikirim ke
semua pasien yang memenuhi syarat; tidak ada pemilihan sampel.

Akibatnya kesalahan utama bukan *sampling error* melainkan **nonresponse
bias** — siapa yang memilih mengisi. Bias ini **tidak mengecil kalau n
bertambah**, jadi usaha terbesar diarahkan ke menaikkan tingkat pengisian dan
mengukur siapa yang tidak mengisi, bukan ke memperbanyak pertanyaan.

Keunggulan yang dimiliki desain ini: **kerangka populasi lengkap** dari
Omnicare. Kita tahu persis siapa seluruh populasinya beserta cabang, layanan,
dokter, dan nilai transaksinya — sehingga keterwakilan bisa diukur dan
dikoreksi. Kebanyakan survei tidak bisa melakukan ini.

## 2. Populasi

Setelah keputusan "RJ saja" (lihat 4.3), populasi = pasien dengan minimal satu
transaksi RJ dalam periode.

| | Semua pasien | Punya RJ | OTC-saja (diparkir) |
|---|---|---|---|
| Jemur | 497 | **380** | 117 |
| Citraland | 244 | **210** | 34 |
| Gabungan (RM unik) | 736 | **586** | 150 |

Acuan September 2026. 20% pasien diparkir sampai set pertanyaan OTC dibuat.

## 3. Presisi yang realistis

Laporan bulanan, skor rata-rata skala 1-5, asumsi simpangan baku 0,9, 95%,
dengan koreksi populasi terbatas:

| Populasi | N | 15% resp | 20% resp | 30% resp |
|---|---|---|---|---|
| Jemur | 380 | n=57 ±0,22 | n=76 **±0,18** | n=114 ±0,14 |
| Citraland | 210 | n=32 ±0,29 | n=42 **±0,24** | n=63 ±0,19 |
| Gabungan | 586 | n=88 ±0,17 | n=117 **±0,15** | n=176 ±0,11 |

**Aturan baca:** jangan bereaksi pada pergerakan yang lebih kecil dari MoE.
Jemur ~0,18 poin, Citraland ~0,24 poin. Ini wajib tercetak di laporan PDF.

Perbandingan untuk Citraland dengan jendela bergulir 3 bulan (N=630):
n=126 @20% -> ±0,14 poin. Dipakai sebagai garis tren pendamping.

### Skor per dokter

Tidak layak bulanan maupun kuartalan. Contoh pada tingkat pengisian 20%:

| Dokter (Jemur) | Pasien/bulan | n | MoE |
|---|---|---|---|
| Dokter A | ~190 | ≈39 | ±0,25 |
| Dokter B | ~135 | ≈27 | ±0,30 |
| Dokter C | ~40 | ≈8 | ±0,56 |
| Dokter D | ~13 | ≈3 | ±0,93 |

(Nama dokter sengaja tidak ditulis: berkas ini ikut ke repo publik, dan
volume pasien per dokter adalah data bisnis per individu. Pemetaan kode ke
nama ada di ekspor analisis, yang tidak dipublikasikan.)

Aturan (keputusan 4.7): skor per dokter **hanya tahunan**, hanya untuk dokter
dengan **minimal 100 jawaban** terkumpul, dan **selalu** dengan rentang
keyakinan. Tidak pernah sebagai angka tunggal, tidak pernah untuk
perbandingan antar dokter di bawah ambang itu.

### Jumlah pertanyaan vs presisi

Margin of error ditentukan oleh **n**, bukan oleh jumlah pertanyaan.
Hubungannya berlawanan arah: menambah pertanyaan menurunkan tingkat
pengisian, mengecilkan n, dan **melebarkan** MoE.

| Panjang | Perkiraan resp | n (gabungan) | MoE proporsi |
|---|---|---|---|
| 6 pertanyaan ~90 detik | ~25% | 147 | ±6,9% |
| 12 pertanyaan ~3 menit | ~15% | 88 | ±9,5% |
| 20+ pertanyaan ~6 menit | ~10% | 59 | ±11,9% |

Konsekuensi desain: satu pertanyaan untuk satu keputusan. Pertanyaan yang
tidak akan mengubah tindakan dibuang — ia membayar ongkos berupa n yang lebih
kecil untuk semua pertanyaan lain.

## 4. Keputusan kerangka survei (11 Okt 2026)

| # | Keputusan | Catatan |
|---|---|---|
| 4.1 | **Jawaban anonim dengan izin.** Jawaban disimpan tanpa tautan identitas. Ada satu pertanyaan izin di akhir; hanya yang menjawab ya yang jawabannya ditautkan ke nomor RM | Menurunkan *courtesy bias* tanpa kehilangan ketertelusuran keluhan. **Menentukan skema tabel jawaban — tidak bisa diubah belakangan** |
| 4.2 | **Unggah laporan mingguan**, bukan bulanan | Jeda kunjungan->survei turun dari median 25 hari (maks 40) menjadi 1-8 hari. Aturan 30 hari tetap mencegah kiriman ganda |
| 4.3 | **Mulai dengan set pertanyaan RJ saja.** Set OTC ditunda | Pasien OTC-saja tidak dibuatkan link sampai Set B ada |
| 4.4 | **Metrik utama: rata-rata skala 1-5 + persentase menjawab 4 atau 5** (*top-2-box*). **NPS tidak dipakai** | NPS membuang informasi dan butuh n jauh lebih besar; pada n≈76 rentangnya ±14 poin |
| 4.5 | **Kerangka 6 pertanyaan + 1 terbuka** disetujui tanpa pengurangan | |
| 4.6 | **Irama laporan bulanan untuk kedua cabang** | Citraland ±0,24 poin. Dikelola dengan menampilkan rentang keyakinan + tren bergulir 3 bulan |
| 4.7 | **Skor per dokter tahunan**, ambang minimal 100 jawaban | Perlu disampaikan ke owner lebih awal |
| 4.8 | **Survei satu halaman**, label skala selalu tampil | Lihat keputusan 2.26 dan 2.27 |

## 5. Prinsip desain pertanyaan

| Prinsip | Alasan |
|---|---|
| Satu gagasan per pertanyaan | Pertanyaan ganda tidak bisa dijawab bila kedua sisinya berbeda |
| Skala khusus per pertanyaan, **bukan** setuju/tidak setuju | Format setuju/tidak setuju memicu *acquiescence bias* |
| Jangkar seimbang | Jumlah pilihan positif dan negatif harus sama |
| Hindari kata "kami" | Mengundang kesopanan, bukan penilaian |
| Tanpa kata mutlak ("selalu", "sangat") | Memaksa jawaban hitam-putih |
| Tanpa premis tersembunyi | "Seberapa membantu penjelasan dokter" mengandaikan ada penjelasan |
| Pertanyaan kunci di awal | Tidak terbentuk oleh pertanyaan sebelumnya, dan terisi walau pasien berhenti |
| Teks terbuka di akhir, opsional | Penyebab berhenti mengisi paling besar |

### Skala

5 titik, ditampilkan sebagai **bintang** (keputusan 2.27), dengan makna:

```
1 Sangat buruk   2 Buruk   3 Cukup   4 Baik   5 Sangat baik
```

Dipilih 5 dan bukan 7 atau 10: muat di satu layar ponsel, beban berpikir
rendah, dan labelnya bisa dibuat jelas dalam bahasa Indonesia.

**Catatan yang perlu diingat saat membaca hasilnya.** Tampilan bintang punya
jangkar budaya yang kuat - lima bintang dibaca sebagai "sempurna" - sehingga
sebarannya cenderung menumpuk di ujung atas lebih kuat daripada skala
berlabel biasa. Digabung dengan courtesy bias di bagian D, artinya **level
skor makin tidak bermakna dan yang berguna hanya perubahannya**. Dua
penangkal yang dipasang: jangkar kata "1 Sangat buruk" dan "5 Sangat baik"
selalu terlihat, dan kata untuk nilai yang dipilih ditampilkan setelah
dipilih.

Konsekuensi praktis: jangan membandingkan skor JoDerma dengan tolok ukur
bintang dari industri lain, dan tetapkan garis dasar sendiri dari dua sampai
tiga bulan pertama seperti rencana semula.

## 6. Set A — pasien RJ (satu-satunya set di versi pertama)

| # | Pertanyaan | Jenis | Wajib |
|---|---|---|---|
| 1 | Secara keseluruhan, bagaimana penilaian Anda terhadap kunjungan Anda di JoDerma? | skala 1-5 | ya |
| 2 | Bagaimana penilaian Anda terhadap kejelasan penjelasan dokter mengenai kondisi dan perawatan Anda? | skala 1-5 | tidak |
| 3 | Bagaimana penilaian Anda terhadap waktu tunggu sebelum dilayani? | skala 1-5 | tidak |
| 4 | Bagaimana penilaian Anda terhadap sikap staf non-medis dalam melayani Anda? | skala 1-5 | tidak |
| 5 | Bagaimana penilaian Anda terhadap kenyamanan dan kebersihan ruang klinik? | skala 1-5 | tidak |
| 6 | Bagaimana penilaian Anda terhadap kejelasan informasi biaya sebelum tindakan? | skala 1-5 | tidak |
| 7 | Apa satu hal yang paling perlu kami perbaiki? | teks | tidak |

**Pertanyaan bersyarat** — muncul bila ada jawaban <=2 pada nomor 1-6:
"Boleh ceritakan apa yang kurang pada bagian itu?" (teks, opsional)

**Pertanyaan izin** (dari keputusan 4.1), selalu terakhir:
"Boleh kami hubungi untuk menindaklanjuti masukan Anda?" (ya/tidak)

Perkiraan waktu pengisian 60-90 detik. Pertanyaan 2-6 adalah **pendorong**
yang dianalisis pengaruhnya terhadap pertanyaan 1, sehingga prioritas
perbaikan bisa ditentukan dari data, bukan dari dugaan.

## 7. Pembobotan pasca-stratifikasi

Sel yang dipakai (per pasien): **cabang x jenis layanan**. Komposisi populasi
September 2026:

| Sel | Jemur | Citraland |
|---|---|---|
| RJ saja | 257 (51,7%) | 178 (73,0%) |
| RJ + OTC | 123 (24,7%) | 32 (13,1%) |
| OTC saja | 117 (23,5%) | 34 (13,9%) |

Catatan: selama keputusan 4.3 berlaku, sel "OTC saja" tidak punya responden
dan pembobotan hanya memakai dua sel.

Batasan praktis:
- **Maksimal 3 sel per cabang** — dengan n~100 lebih banyak sel membuat tiap
  sel terlalu kecil
- **Batasi bobot maksimal 3x** — bobot ekstrem memperbesar ragam
- **Laporkan ukuran efektif sampel**, bukan hanya n mentah

**Batasan jujur:** pembobotan hanya memperbaiki bias pada variabel yang
dipakai membobot. Bila pasien tidak puas lebih enggan mengisi **di dalam
setiap sel**, pembobotan tidak memperbaiki apa pun. Pembobotan adalah tambalan
kedua, bukan solusi utama.

## 8. Menaikkan tingkat pengisian

Karena nonresponse bias adalah kesalahan dominan, ini prioritas tertinggi:

| Cara | Dampak |
|---|---|
| Survei 60-90 detik | terbesar |
| Jeda kunjungan->survei 1-8 hari (keputusan 4.2) | besar |
| Pengantar menyebut lama pengisian dan tujuannya | sedang |
| Pertanyaan pertama langsung muncul, tanpa halaman pembuka | sedang |
| Satu layar ponsel per pertanyaan, tombol besar | sedang |
| Hanya pertanyaan 1 yang wajib | sedang |

**Tidak dipakai: imbalan atau diskon.** Menaikkan pengisian tapi memasukkan
bias baru — responden merasa berutang dan skornya meninggi.

## 9. Yang wajib ada di laporan PDF

Bukan hanya skor:

1. **Tingkat pengisian per sel** (cabang x layanan) — alat deteksi nonresponse bias
2. **Perbandingan responden vs seluruh yang dikirimi** pada variabel Omnicare:
   komposisi layanan, dokter, nilai transaksi, jumlah kunjungan
3. **Tingkat penyelesaian dan pertanyaan tempat orang berhenti** — titik
   berhenti yang sering berarti pertanyaannya bermasalah
4. **Ukuran efektif sampel** setelah pembobotan
5. **Rentang keyakinan di setiap skor**, tidak pernah angka tunggal
6. **Aturan baca**: pergerakan di bawah MoE adalah derau

## 10. Catatan untuk tahap berikutnya

- Teks terbuka (pertanyaan 7 dan bersyarat) bisa memuat informasi yang
  mengidentifikasi pasien. Ekspor untuk Claude agent perlu langkah penyaringan
  atau penandaan supaya anonimitas tidak bocor lewat teks bebas.
- "Pasien baru vs lama" tidak ada di laporan penjualan. Bisa diturunkan
  sendiri seiring waktu dari kemunculan pertama di basis data kita.
- Set B (OTC) menyusul setelah versi pertama jalan. Rancangannya sudah ada di
  riwayat pembahasan dan bisa diangkat kembali.
