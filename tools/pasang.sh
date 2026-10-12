#!/usr/bin/env bash
#
# Pemasangan JoDerma Survei di mini PC.
#
# Menjalankan langkah 1 sampai 5 di docs/operasional.md yang bisa diotomatiskan:
# kunci rahasia, dua unit systemd, dan cron cadangan. Yang tidak bisa
# diotomatiskan -- Cloudflare Tunnel dan pemasangan Syncthing -- dicetak
# sebagai langkah lanjutan di akhir.
#
# AMAN DIJALANKAN ULANG. Berkas yang sudah ada tidak pernah ditimpa diam-diam:
#   * kunci rahasia dibuat sekali, tidak pernah dibuat ulang (menggantinya
#     akan mengeluarkan semua pengguna yang sedang bekerja)
#   * unit systemd yang sudah ada hanya ditimpa setelah Anda mengiyakan
#   * baris cron yang sudah ada tidak digandakan
#
# Pemakaian:
#   ./tools/pasang.sh --kering          lihat yang akan dikerjakan, tanpa mengubah
#   ./tools/pasang.sh                   kerjakan
#   ./tools/pasang.sh --tanpa-systemd   lewati layanan systemd (untuk menguji,
#                                       atau bila memakai penyelia lain)
#
set -euo pipefail

# ---------------------------------------------------------------- pengaturan
PROYEK="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASIS="${JODERMA_BASIS:-$PROYEK/joderma.db}"
ENV_BERKAS="${JODERMA_ENV:-$HOME/.config/joderma/env}"
CADANGAN="${JODERMA_CADANGAN:-$HOME/cadangan-joderma}"
PORTA_ADMIN="${JODERMA_PORTA_ADMIN:-8000}"
PORTA_SURVEI="${JODERMA_PORTA_SURVEI:-8001}"
URL_SURVEI="${JODERMA_URL_SURVEI:-https://survey.joderma.id}"
SIMPAN_CADANGAN="${JODERMA_SIMPAN:-30}"

KERING=0
TANPA_SYSTEMD=0
for arg in "$@"; do
  case "$arg" in
    --kering)        KERING=1 ;;
    --tanpa-systemd) TANPA_SYSTEMD=1 ;;
    -h|--help)       sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \?//'; exit 0 ;;
    *) echo "Pilihan tidak dikenal: $arg" >&2; exit 2 ;;
  esac
done

# ------------------------------------------------------------------- tampilan
merah()  { printf '\033[31m%s\033[0m\n' "$*"; }
hijau()  { printf '\033[32m%s\033[0m\n' "$*"; }
kuning() { printf '\033[33m%s\033[0m\n' "$*"; }
judul()  { printf '\n\033[1m%s\033[0m\n' "$*"; }
langkah() { printf '  %s\n' "$*"; }
akan()   { printf '  \033[33m[kering]\033[0m %s\n' "$*"; }

jalan() {
  if (( KERING )); then akan "$*"; else eval "$@"; fi
}

gagal() { merah "GAGAL: $*"; exit 1; }

# Pertanyaan ya/tidak. Di konteks non-interaktif (pipa, cron, CI) tidak ada
# yang bisa menjawab, jadi dijawab TIDAK alih-alih menggantung selamanya.
# JODERMA_IYAKAN=1 menjawab ya untuk semuanya, dipakai pemasangan tanpa awak.
tanya() {
  local pesan="$1"
  if [[ "${JODERMA_IYAKAN:-0}" == "1" ]]; then
    langkah "$pesan -> ya (JODERMA_IYAKAN=1)"
    return 0
  fi
  if [[ ! -t 0 ]]; then
    kuning "  $pesan -> tidak (tidak ada terminal untuk menjawab)"
    kuning "  Jalankan dari terminal, atau setel JODERMA_IYAKAN=1."
    return 1
  fi
  local jwb
  read -rp "  $pesan [y/N] " jwb
  [[ "$jwb" == [yY] ]]
}

# ------------------------------------------------------------- pemeriksaan
judul "1. Memeriksa prasyarat"

[[ $EUID -ne 0 ]] || gagal "jangan jalankan sebagai root. Layanan berjalan sebagai pengguna biasa, dan skrip ini memakai sudo hanya saat diperlukan."

if (( TANPA_SYSTEMD )); then
  langkah "systemd            dilewati (--tanpa-systemd)"
else
  command -v systemctl >/dev/null || gagal "systemd tidak ada di mesin ini. Pakai --tanpa-systemd bila memang memakai penyelia lain."
  langkah "systemd            ada"
fi

UV="$(command -v uv || true)"
[[ -n "$UV" ]] || gagal "uv tidak ditemukan. Pasang dulu: curl -LsSf https://astral.sh/uv/install.sh | sh"
langkah "uv                 $UV"

PYVER="$(cd "$PROYEK" && "$UV" run python -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || true)"
[[ -n "$PYVER" ]] || gagal "tidak bisa menjalankan python lewat uv di $PROYEK"
langkah "python             $PYVER"

[[ -f "$PROYEK/pyproject.toml" ]] || gagal "$PROYEK bukan folder proyek joderma-survey"
langkah "proyek             $PROYEK"

# Deteksi laptop lewat keberadaan baterai. Cara sebelumnya -- membandingkan
# hostname dengan nama pengguna -- selalu kena di mini PC juga, karena
# keduanya bernama sama. Peringatan yang selalu muncul akan diabaikan orang.
if compgen -G "/sys/class/power_supply/BAT*" >/dev/null; then
  kuning "  PERHATIAN: mesin ini punya baterai, jadi tampaknya laptop."
  kuning "  Layanan systemd akan ikut mati setiap mesin ditutup atau dimatikan."
  if (( ! KERING )); then
    tanya "Tetap lanjutkan?" || { echo "  Dibatalkan."; exit 0; }
  fi
fi

# ------------------------------------------------------- basis data & skema
judul "2. Basis data"

if [[ -f "$BASIS" ]]; then
  langkah "basis data sudah ada: $BASIS"
else
  langkah "basis data akan dibuat: $BASIS"
fi
jalan "(cd '$PROYEK' && '$UV' run python -m joderma_survey --basis '$BASIS' siapkan)"

# ------------------------------------------------------------ kunci rahasia
judul "3. Kunci rahasia dan peubah lingkungan"

if [[ -f "$ENV_BERKAS" ]]; then
  hijau "  $ENV_BERKAS sudah ada -- TIDAK disentuh."
  langkah "Mengganti kuncinya akan mengeluarkan semua pengguna yang sedang bekerja."
  HAK="$(stat -c '%a' "$ENV_BERKAS")"
  if [[ "$HAK" != "600" ]]; then
    kuning "  Hak aksesnya $HAK, seharusnya 600. Memperbaiki."
    jalan "chmod 600 '$ENV_BERKAS'"
  else
    langkah "hak akses          600"
  fi
else
  langkah "membuat $ENV_BERKAS dengan kunci acak baru"
  if (( KERING )); then
    akan "mkdir -p $(dirname "$ENV_BERKAS") && tulis kunci acak 64 karakter"
  else
    mkdir -p "$(dirname "$ENV_BERKAS")"
    KUNCI="$("$UV" run --directory "$PROYEK" python -c 'import secrets; print(secrets.token_hex(32))')"
    ( umask 077; cat > "$ENV_BERKAS" <<ENVEOF
# Dibuat oleh tools/pasang.sh. Jangan masukkan ke git.
# Mengganti JODERMA_KUNCI_RAHASIA akan mengeluarkan semua pengguna.
JODERMA_KUNCI_RAHASIA=$KUNCI
JODERMA_URL_SURVEI=$URL_SURVEI
ENVEOF
    )
    chmod 600 "$ENV_BERKAS"
    hijau "  kunci dibuat, hak akses 600"
  fi
fi

# ------------------------------------------------------------ unit systemd
judul "4. Layanan systemd"

if (( TANPA_SYSTEMD )); then
  kuning "  Dilewati (--tanpa-systemd). Jalankan kedua aplikasi dengan penyelia pilihan Anda:"
  langkah "$UV run python -m joderma_survey --basis $BASIS jalankan --alamat 127.0.0.1 --porta $PORTA_ADMIN"
  langkah "$UV run python -m joderma_survey --basis $BASIS jalankan-survei --alamat 127.0.0.1 --porta $PORTA_SURVEI"
fi

buat_unit() {
  (( TANPA_SYSTEMD )) && return 0
  local nama="$1" keterangan="$2" perintah="$3"
  local tujuan="/etc/systemd/system/$nama.service"
  local isi
  isi="$(cat <<UNITEOF
[Unit]
Description=$keterangan
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$PROYEK
EnvironmentFile=$ENV_BERKAS
ExecStart=$perintah
Restart=always
RestartSec=5
# Pengetatan ringan; aplikasi hanya perlu menulis ke folder proyek.
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
UNITEOF
)"

  if [[ -f "$tujuan" ]]; then
    if diff -q <(echo "$isi") "$tujuan" >/dev/null 2>&1; then
      langkah "$nama sudah ada dan isinya sama -- dilewati"
      return
    fi
    kuning "  $tujuan sudah ada dengan isi berbeda."
    if (( KERING )); then akan "akan menanyakan apakah boleh ditimpa"; return; fi
    tanya "Timpa $tujuan?" || { langkah "$nama dilewati"; return; }
  fi

  if (( KERING )); then
    akan "tulis $tujuan (lewat sudo)"
  else
    echo "$isi" | sudo tee "$tujuan" >/dev/null
    hijau "  $tujuan ditulis"
  fi
}

buat_unit "joderma-admin" "JoDerma Survei - aplikasi admin" \
  "$UV run python -m joderma_survey --basis $BASIS jalankan --alamat 127.0.0.1 --porta $PORTA_ADMIN"
buat_unit "joderma-survei" "JoDerma Survei - halaman pasien" \
  "$UV run python -m joderma_survey --basis $BASIS jalankan-survei --alamat 127.0.0.1 --porta $PORTA_SURVEI"

if (( ! TANPA_SYSTEMD )); then
  jalan "sudo systemctl daemon-reload"
  jalan "sudo systemctl enable --now joderma-admin joderma-survei"
fi

# ------------------------------------------------------------------ cadangan
judul "5. Cadangan berkala"

jalan "mkdir -p '$CADANGAN'"
BARIS_CRON="15 2 * * * cd $PROYEK && $UV run python -m joderma_survey --basis $BASIS cadangan --tujuan $CADANGAN --simpan $SIMPAN_CADANGAN >> $CADANGAN/cadangan.log 2>&1"

if crontab -l 2>/dev/null | grep -qF "joderma_survey --basis $BASIS cadangan"; then
  langkah "baris cron sudah ada -- tidak digandakan"
else
  langkah "menambah cron harian pukul 02:15"
  if (( KERING )); then
    akan "$BARIS_CRON"
  else
    ( crontab -l 2>/dev/null || true; echo "$BARIS_CRON" ) | crontab -
    hijau "  cron dipasang"
  fi
fi

langkah "menjalankan satu cadangan sekarang sebagai uji"
jalan "(cd '$PROYEK' && '$UV' run python -m joderma_survey --basis '$BASIS' cadangan --tujuan '$CADANGAN' --simpan $SIMPAN_CADANGAN)"

# ---------------------------------------------------------------- pemeriksaan
judul "6. Memeriksa hasil"

if (( KERING )); then
  akan "periksa systemctl is-active dan tanggapan HTTP kedua porta"
else
  if (( TANPA_SYSTEMD )); then
    langkah "pemeriksaan layanan dilewati (--tanpa-systemd)"
  else
  sleep 3
  for layanan in joderma-admin joderma-survei; do
    if systemctl is-active --quiet "$layanan"; then
      hijau "  $layanan aktif"
    else
      merah "  $layanan TIDAK aktif -- lihat: journalctl -u $layanan -n 30"
    fi
  done

  periksa_http() {
    local nama="$1" url="$2" harap="$3"
    local kode
    kode="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$url" || echo 000)"
    if [[ "$kode" == "$harap" ]]; then
      hijau "  $nama -> HTTP $kode (sesuai harapan)"
    else
      merah "  $nama -> HTTP $kode (diharapkan $harap)"
    fi
  }
  periksa_http "admin  /masuk" "http://127.0.0.1:$PORTA_ADMIN/masuk" 200
  # Halaman survei memang 404 di akar: tanpa token tidak ada yang ditampilkan.
  periksa_http "survei /" "http://127.0.0.1:$PORTA_SURVEI/" 404

  if journalctl -u joderma-survei -n 20 --no-pager 2>/dev/null | grep -q "waitress"; then
    hijau "  survei memakai waitress"
  else
    kuning "  tidak menemukan baris waitress di log; periksa journalctl -u joderma-survei"
  fi

  fi

  JML_PENGGUNA="$(cd "$PROYEK" && "$UV" run python -c "
from joderma_survey import db
c = db.buka('$BASIS')
print(c.execute('SELECT COUNT(*) n FROM pengguna').fetchone()['n'])
c.close()" 2>/dev/null || echo 0)"
  if [[ "$JML_PENGGUNA" == "0" ]]; then
    kuning "  belum ada pengguna"
  else
    hijau "  pengguna terdaftar: $JML_PENGGUNA"
  fi
fi

# ------------------------------------------------------------ langkah manual
judul "Langkah yang harus Anda kerjakan sendiri"

cat <<LANJUT
  1. Buat pengguna (sekali per orang):
       cd $PROYEK
       $UV run python -m joderma_survey --basis $BASIS pengguna --nama <nama> --peran direktur
       (peran: owner | direktur | cs)

  2. Cloudflare Tunnel -- tambahkan dua hostname di ~/.cloudflared/config.yml:
       ingress:
         - hostname: <subdomain admin>
           service: http://127.0.0.1:$PORTA_ADMIN
         - hostname: <subdomain survei>
           service: http://127.0.0.1:$PORTA_SURVEI
         - service: http_status:404

     Subdomain survei HARUS di luar kebijakan Cloudflare Access. Kalau tidak,
     pasien akan diminta kode OTP dan tidak akan pernah mengisi survei.
     Uji dari ponsel di jaringan seluler, bukan wifi klinik.

  3. Syncthing untuk menyalin cadangan ke desktop rumah:
       sudo apt install syncthing && systemctl --user enable --now syncthing
     Lalu di http://127.0.0.1:8384 tambahkan folder $CADANGAN,
     hubungkan dengan desktop rumah, dan setel di rumah sebagai Receive Only.

  4. Uji pemulihan cadangan SEKALI sebelum dianggap selesai:
       cd /tmp && mkdir -p uji-pulih && cd uji-pulih
       tar xzf $CADANGAN/joderma-*.tar.gz
       sqlite3 joderma.db "PRAGMA integrity_check; SELECT COUNT(*) FROM undangan;"

     Yang dipastikan bukan jawabannya, melainkan tabel undangan: di situlah
     status jeda 30/365 hari tersimpan.
LANJUT

if (( KERING )); then
  judul "Ini uji kering -- tidak ada yang diubah."
  echo "  Jalankan tanpa --kering untuk mengerjakannya."
else
  judul "Pemasangan selesai."
fi
