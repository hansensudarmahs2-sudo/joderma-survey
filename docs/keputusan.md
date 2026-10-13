# Catatan Keputusan — Sistem Survei Pelanggan JoDerma

Tanggal mulai: 11 Oktober 2026
Pemilik keputusan: Hansen Sudarma (Direktur Operasional)

Berkas ini mencatat keputusan yang sudah final beserta alasannya, supaya
tidak dibahas ulang. Tidak memuat data pasien.

---

## 1. Keputusan dari PRD (sudah final sejak awal)

| # | Keputusan |
|---|---|
| 1.1 | Aplikasi berdiri sendiri, terpisah dari sistem operasional klinik yang sudah ada |
| 1.2 | Python + SQLite, jalan di mini PC lewat Cloudflare Tunnel |
| 1.3 | Sumber data tunggal: laporan Omnicare "Transaksi Penjualan" (17 kolom) |
| 1.4 | Nomor HP tidak pernah masuk aplikasi; CS cari kontak di WhatsApp |
| 1.5 | Tidak ada pengiriman WhatsApp otomatis |
| 1.6 | NIK dan diagnosa tidak pernah dibaca maupun disimpan |
| 1.7 | Cabang dipilih saat unggah (kode di nama file: 30376=Jemur, 31281=Citraland) |
| 1.8 | Berkas analisis untuk Claude agent memakai ID anonim |
| 1.9 | Analisis dan laporan PDF dijalankan manual, tidak terjadwal |
| 1.10 | Data dan laporan dipisah per cabang |

## 2. Keputusan hasil pembahasan (11 Okt 2026)

| # | Keputusan | Alasan |
|---|---|---|
| 2.1 | **Masa berlaku link 30 hari**, bukan 7 hari | Pengiriman semi-manual: link bisa baru dikirim CS lebih dari 7 hari setelah dibuat. Efek sampingnya bagus: masa berlaku link dan jeda 30 hari jadi satu jam yang sama, sehingga "link kedaluwarsa" dan "jeda habis" adalah peristiwa identik — satu kolom, tanpa penjadwal |
| 2.2 | **Status "terkirim" dihapus.** Aplikasi hanya mencatat link tergenerate | Tidak ada cara memastikan pengiriman manual. F6 dicabut; F5 jadi daftar baca-saja untuk CS |
| 2.3 | **Pasien OTC ikut disurvei** | Prioritas bukan jenis transaksi, tapi nomor RM dan statusnya |
| 2.4 | **Baris Rp0 ikut disurvei** | Alasan sama dengan 2.3 |
| 2.5 | **Jeda 30/365 hari berlaku gabungan lintas cabang**, bukan per cabang | Satu pasien punya satu nomor RM; RM unik per orang. Jeda adalah soal tidak mengganggu orang, bukan cabang |
| 2.6 | **Baris tanpa RM (`-`) dibuang** | Tidak ada identitas untuk dihubungi. Di contoh September: 9 baris, semuanya OTC dengan nama kosong |
| 2.7 | **Akun bukan pasien tidak diblokir otomatis, tapi diberi warning keraguan** di daftar kirim | Penyaringan akhir ada di tangan CS. Aplikasi hanya menandai yang patut diragukan |
| 2.8 | **Normalisasi RM: hanya `strip()` + `upper()`** | Lihat 2.9 untuk sisanya |
| 2.9 | **Lebar angka RM dinormalisasi otomatis berdasarkan nilai angkanya** (`J` + 5 angka, `JC` + 4 angka). Baris yang terkena tetap dilaporkan di ringkasan unggahan | **Diperbarui 11 Okt 2026** setelah diketahui jumlah pasien: Jemur ~8200 (berdiri 3 tahun), Citraland ~2000 (10 bulan). Omnicare memakai lebar tetap, dibuktikan oleh nilai kecil yang ditulis penuh (`J00001`, `JC0027`) — jadi **angkanya identitas, nol di depan hanya kosmetik**. Nilai tertinggi di laporan September (J08146, JC1099) cocok dengan jumlah pasien itu. Kelima RM menyimpang jatuh di dalam jangkauan dan tidak satu pun bertabrakan. Keputusan sebelumnya (tidak dinormalisasi, diputuskan manual) dibatalkan |
| 2.10 | **Awalan RM TIDAK dipakai untuk menentukan cabang kunjungan** | Awalan menandakan cabang *pendaftaran*. Di contoh September ada 33 baris pasien yang berobat di cabang lain dari tempat ia mendaftar. Cabang diambil dari kode di nama file |
| 2.11 | **Format kontak WhatsApp: `Nama Pasien - Jxxxxx`** | CS mencari kontak lewat nama atau RM; satu format melayani keduanya |
| 2.12 | **Kerangka survei dibahas lebih dulu sebelum koding** | Menentukan bentuk tabel jawaban |
| 2.13 | ~~Ada survey editor~~ **DIBATALKAN 11 Okt 2026.** Pertanyaan diatur lewat berkas `config/pertanyaan.toml` dan perintah `pertanyaan --terapkan` | Pertanyaan yang bisa diubah satu klik mengundang perubahan tak sengaja di tengah periode, dan itu merusak perbandingan antar periode. Berkas konfigurasi tetap memenuhi F10 ("diganti tanpa mengubah kode") tapi menuntut tindakan yang disadari penuh: sunting berkas, jalankan uji kering, baru terapkan |
| 2.14 | **Pertanyaan tidak pernah diubah di tempat.** Menyunting berarti menambah **revisi baru dengan kode yang tetap**, dan menonaktifkan revisi lama. Jawaban menunjuk revisi yang persis dijawab. Suntingan yang mengubah makna ditandai `mengubah_makna` | **Diperbarui 11 Okt 2026:** versi per pertanyaan, bukan versi survei menyeluruh. Dengan versi menyeluruh, memperbaiki satu salah ketik membuat seluruh survei naik versi dan laporan menganggap semua pertanyaan berubah - data terpotong tanpa perlu. Dengan versi per pertanyaan, perbaikan ejaan menjaga rangkaian data tetap tersambung, sementara perubahan makna memotongnya di titik yang benar |
| 2.15 | **Data contoh asli tidak masuk git** | `contoh-xls-omnicare/` dan semua `*.xls` masuk `.gitignore` |
| 2.16 | **Cabang diambil otomatis dari kode di nama berkas**, tidak dipilih manual. Bila cabang tetap dipilih, kode harus cocok atau berkas ditolak | Kode di nama berkas (30376/31281) tidak ambigu, jadi pemilihan manual hanya menambah sumber kesalahan manusia. Menyederhanakan alur PRD butir 1 |
| 2.17 | **Filter `STATUS = LUNAS` dibuat tersurat** | Di laporan contoh semua baris LUNAS, tapi baris filter berbunyi `STATUS: SEMUA`, jadi ekspor lain bisa memuat baris belum lunas |
| 2.18 | **Kolom CATATAN tidak dibaca** | Teks bebas yang bisa memuat keterangan pribadi, dan tidak diperlukan sistem ini. Hanya 9 dari 17 kolom dibaca |
| 2.19 | **Pengurutan kunjungan terakhir: TANGGAL utama, WAKTU TRANSAKSI pemutus** | TANGGAL adalah tanggal kunjungan, WAKTU TRANSAKSI adalah saat pelunasan dicatat dan bisa jatuh di hari berikutnya (29 baris di laporan contoh). Lihat docs/temuan-data.md butir T13 |
| 2.20 | **Tombol "kontak tidak ditemukan" dipakai.** CS bisa membatalkan undangan yang belum diisi; pasien kembali memenuhi syarat di unggahan berikutnya | Tanpa ini, pasien yang linknya gagal dikirim terblokir 30 hari tanpa pernah menerima apa pun. Pengisian tidak bisa ditarik kembali, jadi undangan yang sudah diisi tetap terkena jeda 365 hari walau dibatalkan |
| 2.21 | **Owner punya login sendiri**, tidak hanya menerima PDF | Tiga peran di tabel `pengguna`: owner, direktur, cs |
| 2.22 | **Anonimitas tidak sempurna, dan risikonya diterima** | Tidak ada kolom yang menghubungkan jawaban ke pasien kecuali bila pasien mengizinkan. Yang tidak dijamin: urutan baris di basis data, kombinasi cabang + dokter + periode yang menyempitkan, dan teks bebas yang bisa membongkar sendiri. Dicatat di docs/gaps.md butir G11 |
| 2.23 | **Link ditempel ke kunjungan RJ terakhir**, bukan transaksi terakhir | Set A menanyakan "kunjungan Anda" dan "penjelasan dokter". Di laporan contoh ada 59 pasien (41 Jemur, 18 Citraland) yang transaksi terakhirnya OTC padahal punya kunjungan RJ; memakai faktur OTC akan membuat kolom dokter berisi "-" dan merusak skor per dokter |
| 2.24 | **Teks pesan WhatsApp ada di satu templat** di `daftar_kirim.py` | Mengikuti metodologi bagian 8: menyebut lamanya pengisian dan tujuannya, tanpa imbalan apa pun. Janji anonimitas ditulis persis sesuai kenyataan rancangan basis data |
| 2.25 | **Tidak ada tombol "terkirim"** di daftar kirim, hanya "tidak ditemukan" | Menegaskan keputusan 2.2. Satu-satunya tindakan CS adalah menyalin, atau membatalkan bila kontak tidak ketemu |
| 2.26 | **Survei satu halaman**, bukan satu pertanyaan per layar | Tanpa keadaan antar langkah di server, tidak ada jawaban yang hilang di tengah, dan pasien bisa melihat panjang survei sebelum mulai. Ongkosnya ada di 5.x: titik berhenti per pertanyaan jadi tidak terukur |
| 2.27 | **Skala memakai bintang 1-5**, dengan jangkar kata "1 Sangat buruk" dan "5 Sangat baik" selalu tampil, plus kata untuk nilai yang dipilih | **Diperbarui 11 Okt 2026** atas permintaan direktur. Catatan metodologis: bintang punya jangkar budaya kuat (5 bintang = sempurna) dan cenderung menghasilkan sebaran yang menumpuk di ujung atas; digabung dengan courtesy bias yang sudah ada, ragam jawaban jadi lebih kecil. Jangkar kata dipertahankan justru untuk menahan efek itu - bintang hanya mengganti tampilan angkanya, bukan maknanya |
| 2.28 | **`undangan.dibuka_pada` dicatat** (tanggal saja) | Memisahkan "link tidak pernah sampai" dari "sampai tapi tidak diisi". Yang pertama masalah pengiriman CS, yang kedua masalah surveinya |
| 2.29 | **Tidak ada token CSRF di halaman survei publik** | Token di alamat adalah satu-satunya kredensial; penyerang yang sudah memilikinya bisa mengisi survei secara langsung, jadi CSRF tidak menambah perlindungan apa pun |
| 2.30 | **`Referrer-Policy: no-referrer` dan tanpa tautan keluar** di halaman survei | Alamat halaman memuat token. Satu tautan keluar saja sudah cukup membocorkannya lewat kepala Referer |
| 2.31 | **Tata letak dua kolom** (pertanyaan kiri, bintang kanan) hanya mulai lebar 600px; di ponsel menumpuk | Di lebar 375px kolom kanan hanya kebagian ~150px untuk lima bintang, di bawah ukuran sasaran sentuh yang nyaman. Pasien membuka dari WhatsApp, jadi tampilan ponsel yang menentukan |
| 2.32 | **Bintang diwarnai dengan CSS saja**, tanpa JavaScript | Urutan DOM dibalik (5..1) dengan `row-reverse`, sehingga `input:checked ~ label` mewarnai bintang terpilih beserta yang di kirinya. Survei tetap berfungsi penuh bila JavaScript tidak jalan |
| 2.33 | **Perubahan teks pertanyaan dianggap mengubah makna secara bawaan** | Arah yang aman: laporan memotong rangkaian datanya, sehingga dua pertanyaan berbeda tidak pernah diam-diam dibandingkan. Perbaikan ejaan ditandai tersurat lewat `--ejaan <kode>` |
| 2.34 | **Berkas pertanyaan memakai TOML**, bukan YAML | `tomllib` ada di pustaka standar Python 3.11+, jadi tidak perlu dependensi baru |
| 2.35 | **Nama dokter diganti kode D1, D2, ...** di berkas ekspor; pemetaannya hanya ikut bila `--sertakan-dokter` dinyalakan | Analisis per dokter tetap bisa dilakukan, tapi nama staf tidak ikut keluar dari klinik secara bawaan |
| 2.36 | **Selang kepercayaan rata-rata dipotong ke jangkauan skala 1-5** | Rata-rata nilai 1-5 mustahil di luar 1-5. Pada n sangat kecil selangnya bisa keluar jangkauan, dan menyajikannya begitu menyesatkan. Yang dipotong hanya ujung selang, bukan nilai titiknya |
| 2.37 | **Proporsi memakai selang Wilson**, bukan hampiran normal | Top-2-box biasanya di 0,85-0,95; di dekat ujung itu hampiran normal menghasilkan selang terlalu sempit dan bisa melewati 100% |
| 2.38 | **Rata-rata memakai sebaran t**, bukan z | Pada n=30 bedanya 2,042 vs 1,960. Mengabaikannya membuat perbedaan tampak nyata padahal belum tentu |
| 2.39 | **Berkas ekspor selalu disertai `konteks.md`** yang memuat lima hal yang tidak boleh dilakukan | Tanpa itu Claude agent akan menyimpulkan berlebihan dari angka yang sebenarnya penuh keterbatasan. Ada tes yang memastikan isinya menyebut nonresponse bias, courtesy bias, tolok ukur industri, tumpang tindih selang, skor per dokter, dan batas pembobotan |
| 2.40 | **Laporan PDF dibuat dengan mencetak halaman HTML dari peramban**, bukan pustaka PDF | Nol dependensi baru di mini PC yang sudah menjalankan 10 container. ReportLab menuntut tata letak diprogram manual; WeasyPrint menuntut pustaka sistem (pango, cairo). Halaman laporan punya CSS `@media print` dengan ukuran A4 dan pengaturan pemenggalan halaman |
| 2.41 | **Perubahan antar periode hanya disebut nyata bila selang kedua periode tidak bertumpang tindih** | Uji yang berhati-hati: tidak bertumpang tindih adalah bukti lebih kuat daripada uji beda baku. Arah ini dipilih supaya laporan tidak pernah menyebut perbaikan atau penurunan yang sebenarnya derau |
| 2.42 | **Periode pembanding dihitung otomatis**: sepanjang periode berjalan, tepat sebelumnya | Laporan bulanan dibandingkan dengan bulan sebelumnya, laporan mingguan dengan pekan sebelumnya, tanpa perlu dipilih manual |
| 2.43 | **Pembatasan laju Cloudflare untuk subdomain survei dihilangkan sama sekali** (F15 dicabut) | Token 96 bit acak, sekali pakai, berlaku 30 hari — menebaknya praktis mustahil, jadi pembatasan laju hanya menambah sedikit sekali perlindungan. Perlindungan DDoS bawaan Cloudflare tetap berlaku tanpa aturan tambahan. Risiko sisa dicatat di gap G15 |
| 2.44 | **Cadangan memakai `VACUUM INTO`, bukan menyalin berkas** | Aplikasi berjalan dalam mode WAL, jadi sebagian transaksi masih di `.db-wal`. Menyalin dengan `cp` pada basis data aktif bisa menghasilkan salinan robek yang baru ketahuan saat dibutuhkan. Hasil salinan langsung diperiksa `integrity_check` |
| 2.45 | **Cadangan menyertakan `docs/`, `config/`, dan PRD**, bukan hanya basis data | `docs/gaps.md` dan PRD tidak masuk repo publik, jadi cadangan inilah satu-satunya salinannya di luar mini PC |
| 2.46 | **Pemindahan cadangan ke desktop rumah memakai Syncthing**, di luar kode sistem ini | Kedua mesin di belakang NAT. Syncthing menghubungkan langsung tanpa membuka porta dan tanpa kredensial apa pun yang perlu disimpan di dalam kode |
| 2.47 | **`docs/` masuk repo publik kecuali `gaps.md`; nama dokter diganti kode** | `gaps.md` adalah daftar kelemahan yang masih terbuka dan mutakhir. Volume pasien per dokter adalah data bisnis per individu yang tidak pernah disetujui para dokter untuk dipublikasikan |
| 2.48 | **Set pertanyaan OTC (Set B) ditunda; pasien OTC sementara tidak disurvei** | 150 pasien per bulan diparkir. Angkanya tetap dilaporkan di ringkasan tiap unggahan supaya tidak terlupa |
| 2.49 | **Kedua aplikasi memakai waitress secara bawaan**; server Flask hanya dengan `--debug` | Murni Python, tanpa pustaka sistem di mini PC, berbeda dengan gunicorn atau uWSGI. Aman secara bawaan: unit systemd tidak perlu menyalakan apa pun, dan justru harus sengaja salah untuk mendapat server pengembangan. `channel_timeout` 60 detik dan `connection_limit` 100 lebih ketat dari bawaan, karena pembatasan laju sudah dicabut |
| 2.50 | **Skrip pemasangan `tools/pasang.sh`**, aman dijalankan ulang, dengan `--kering` | Menyalin-tempel dari runbook rawan terlewat satu langkah, dan yang paling berbahaya terlewat adalah kunci rahasia tetap. Skripnya tidak pernah mengganti kunci yang sudah ada, tidak menggandakan cron, dan menanyakan sebelum menimpa unit systemd |
| 2.51 | **Pertanyaan interaktif dijawab TIDAK bila tidak ada terminal** | Skrip pemasangan yang menggantung menunggu jawaban di cron atau pipa lebih buruk daripada yang berhenti. `JODERMA_IYAKAN=1` untuk pemasangan tanpa awak |
| 2.52 | **Aplikasi admin dipasang di bawah `ops.joderma.id/survei`**, bukan subdomain sendiri | Cloudflare Access mendefinisikan aplikasi per hostname, jadi staf yang sudah masuk ke `ops.joderma.id` tidak diminta login lagi. Itu menjawab keluhan OTP yang disebut PRD, tanpa mengurangi perlindungan: admin survei justru ikut terlindungi Access, yang lebih kuat daripada login aplikasi sendiri |
| 2.53 | **Awalan jalur lewat `SCRIPT_NAME`**, bukan `APPLICATION_ROOT` | Mengisi keduanya membuat awalan terpasang dua kali (`/survei/survei/kirim`): halaman tetap terbuka, tapi semua tautannya rusak. Ada tes anti-regresinya |
| 2.54 | **Nama kuki sesi dibuat khas dan dibatasi ke awalan** | Aplikasi berbagi hostname dengan joderma-ops; kuki bernama `session` bawaan Flask berisiko saling menimpa, dan kuki tanpa batas jalur ikut terkirim ke aplikasi tetangga |
| 2.55 | **Login survei sendiri dihapus; aplikasi admin memakai sesi ops** (13 Okt 2026, disetujui PO). Halaman `/masuk`, tombol "Keluar", dan alur sandi di web dihapus | Staf sebelumnya login dua kali (ops, lalu survei). Pada setiap permintaan ke rute yang dilindungi, aplikasi menanyakan `GET /akun/sesi-survei/` ke ops di `JODERMA_OPS_INTERNAL` (bawaan `http://127.0.0.1:8731`) dengan meneruskan **hanya** kuki `sessionid`, header `Host: JODERMA_OPS_HOST` dan `X-Forwarded-Proto: https`, tenggat 3 detik, tanpa mengikuti pengalihan. 200 = peran dari ops langsung dipakai dengan `IZIN` yang sama; 403 = halaman tanpa hak dengan tautan ke ops; 401 atau apa pun selain itu (302, 5xx, timeout, ops mati, isi tidak sah) = dialihkan ke login ops, **tidak pernah** dianggap berhak. Status login tidak disimpan di sesi survei, supaya logout ops dan peran yang dicabut langsung berlaku. Lihat 2.56 dan 2.57 |
| 2.56 | **Tabel `pengguna` tidak dipakai login web; tidak ada provisioning** | Tidak ada tabel lain yang mencatat pelaku (unggahan tidak menyimpan pengunggah), jadi membuat baris pengguna otomatis hanya menambah data dan sandi acak yang harus dijaga tanpa manfaat. Pengguna web dibentuk di memori dari jawaban ops (nama = username ops). Tabel dan perintah CLI `pengguna` dibiarkan, dengan catatan bahwa login web kini lewat ops |
| 2.57 | **Tombol "Keluar" diganti tautan "Kembali ke ops"**, bukan `POST /keluar` yang menghapus sesi survei | Sesi survei hanya menyimpan token CSRF; menghapusnya tidak mengeluarkan siapa pun dari ops, sehingga tombol "Keluar" justru menyesatkan. Logout dilakukan di ops. Token CSRF dibuat pada GET pertama dan tetap wajib untuk setiap POST |
| 2.58 | **`next` ke login ops selalu jalur internal berawalan `JODERMA_AWALAN_ADMIN`** | Tujuan pengalihan selalu `https://<JODERMA_OPS_HOST>/akun/login/`, dan `next` dibangun dari jalur permintaan (bukan dari parameter apa pun), garis miring di depan dirapikan, lalu dikodekan utuh. Permintaan langsung ke 127.0.0.1 tanpa `/survei` tetap kembali lewat `ops.joderma.id/survei` |

## 3. Aturan kelayakan kirim (final)

```
Pasien boleh dibuatkan link baru bila:   hari_ini >= terblokir_sampai

terblokir_sampai = yang paling akhir dari:
    diisi_pada_terakhir  + 365 hari     (bila pernah mengisi)
    dibuat_pada_terakhir +  30 hari     (bila pernah dibuatkan link)

Tanpa riwayat sama sekali -> langsung boleh.
```

Catatan penting: `terblokir_sampai` **dihitung saat ditanya**, tidak disimpan
sebagai penanda. Jadi tidak ada yang perlu membalik nilai tiap hari dan tidak
perlu penjadwal yang bisa mati tanpa ketahuan.

Alur per unggahan:

```
unggah file
  -> validasi header (nama kolom asli Omnicare)
  -> validasi kode cabang dari nama file vs cabang yang dipilih
  -> buang 2 baris catatan kaki
  -> buang baris tanpa RM ("-")
  -> buang baris STATUS != LUNAS
  -> normalisasi RM (strip + upper saja)
  -> kelompokkan per RM, ambil transaksi terakhir (pemutus: WAKTU TRANSAKSI)
  -> untuk tiap pasien: hari_ini >= terblokir_sampai ?
       ya    -> buat token + link, catat dibuat_pada
       tidak -> lewati, catat alasannya
  -> ringkasan: dibuat N, dilewati M (per alasan), warning keraguan, RM low confidence
```

## 4. Masih terbuka

| # | Pertanyaan | Menghambat |
|---|---|---|
| 4.1 | Pemasangan di mini PC mengikuti docs/operasional.md | Sebelum peluncuran |
| 4.2 | Set pertanyaan OTC (Set B) | Ditunda (keputusan 2.48) |

Yang sudah diputuskan dan tinggal dikerjakan saat pemasangan: kunci rahasia
tetap (2.x, gap G13), cadangan berkala (2.44-2.46), unggah mingguan (4.2),
pembatasan laju dicabut (2.43), dan Set B ditunda (2.48).

### Status kebutuhan PRD

| Kebutuhan | Status |
|---|---|
| F1-F5, F7-F14 | terpenuhi |
| **F6** (CS menandai "terkirim") | **dicabut** oleh keputusan 2.2 — tidak ada cara memastikan pengiriman manual, jadi aplikasi hanya mencatat link tergenerate. Akibatnya penyebut "tingkat pengisian" berubah; lihat bagian 5 |
| F15 (pembatasan laju) | **dicabut** oleh keputusan 2.43 |
| F16 (cadangan berkala) | terpenuhi — perintah `cadangan`, lihat docs/operasional.md |

## 5. Konsekuensi yang perlu diingat

- **F14 dan tabel peran di PRD tidak sepenuhnya sejalan soal owner.** F14
  berbunyi "unggah laporan dan hasil survei hanya untuk owner dan direktur",
  sementara tabel peran menggambarkan owner hanya membaca laporan. Yang
  diterapkan F14, karena itu kebutuhan fungsional yang mengikat: owner bisa
  mengunggah laporan. Pengelolaan pengguna tetap hanya di direktur, mengikuti
  "mengelola sistem" di tabel peran.

- **Ukuran "tingkat pengisian" berubah penyebutnya.** PRD memakai "link yang
  ditandai terkirim". Karena status terkirim dihapus (2.2), penyebutnya jadi
  "link tergenerate" — termasuk link yang CS tidak pernah kirim karena kontak
  tidak ditemukan. Angkanya akan terlihat lebih rendah dari kenyataan.
- **Pasien yang linknya gagal dikirim terblokir 30 hari tanpa menerima apa
  pun.** Ditangani oleh tombol pembatalan (keputusan 2.20).
- **Titik berhenti per pertanyaan tidak terukur.** Metodologi bagian 9.3
  meminta "pertanyaan tempat orang berhenti". Dengan survei satu halaman
  (keputusan 2.26), yang bisa diukur adalah **pertanyaan yang dikosongkan**
  dan **tingkat pembukaan link** (keputusan 2.28) - keduanya tersedia dan
  menurut saya lebih berguna, tapi bukan hal yang sama persis. Kalau titik
  berhenti benar-benar diperlukan, surveinya harus dipecah per layar.
