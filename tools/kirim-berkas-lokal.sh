#!/usr/bin/env bash
#
# Mengirim berkas yang sengaja TIDAK masuk repo publik ke mini PC.
#
# Tiga berkas ini ditahan dari GitHub (lihat .gitignore):
#   docs/gaps.md         daftar kelemahan yang masih terbuka
#   docs/operasional.md  runbook: pemetaan hostname Cloudflare Tunnel
#   PRD ...              topologi infrastruktur
#
# Karena tidak ikut `git clone`, berkas-berkas ini harus dikirim terpisah.
# Yang paling dibutuhkan saat pemasangan adalah operasional.md.
#
# Pemakaian:
#   ./tools/kirim-berkas-lokal.sh                       ke bawaan
#   ./tools/kirim-berkas-lokal.sh pengguna@host         ke mesin lain
#   ./tools/kirim-berkas-lokal.sh --kering              lihat saja
#   ./tools/kirim-berkas-lokal.sh --bundel              buat berkas tempel,
#                                                       tanpa jaringan sama sekali
#
set -euo pipefail

TUJUAN_BAWAAN="${JODERMA_MINIPC:-joderma-jemur@joderma-jemur}"
FOLDER_BAWAAN="${JODERMA_FOLDER:-joderma-survey}"

PROYEK="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROYEK"

BERKAS=(
  "docs/gaps.md"
  "docs/operasional.md"
  "PRD Survei Pelanggan JoDerma.md"
)

KERING=0
BUNDEL=0
TUJUAN=""
for arg in "$@"; do
  case "$arg" in
    --kering) KERING=1 ;;
    --bundel) BUNDEL=1 ;;
    -h|--help) sed -n '2,22p' "${BASH_SOURCE[0]}" | sed 's/^# \?//'; exit 0 ;;
    -*) echo "Pilihan tidak dikenal: $arg" >&2; exit 2 ;;
    *) TUJUAN="$arg" ;;
  esac
done
TUJUAN="${TUJUAN:-$TUJUAN_BAWAAN}"

merah()  { printf '\033[31m%s\033[0m\n' "$*"; }
hijau()  { printf '\033[32m%s\033[0m\n' "$*"; }
kuning() { printf '\033[33m%s\033[0m\n' "$*"; }
judul()  { printf '\n\033[1m%s\033[0m\n' "$*"; }

# ------------------------------------------------------- periksa berkasnya
judul "Berkas yang akan dikirim"
ADA=()
for b in "${BERKAS[@]}"; do
  if [[ -f "$b" ]]; then
    printf '  %-36s %6s bita\n' "$b" "$(stat -c%s "$b")"
    ADA+=("$b")
  else
    kuning "  $b -- tidak ada di sini, dilewati"
  fi
done
[[ ${#ADA[@]} -gt 0 ]] || { merah "Tidak ada satu pun berkas untuk dikirim."; exit 1; }

# --------------------------------------------- jalur tanpa jaringan: bundel
buat_bundel() {
  local keluar="${TMPDIR:-/tmp}/joderma-berkas-lokal.sh"
  {
    echo '#!/usr/bin/env bash'
    echo '# Berkas lokal JoDerma. Jalankan di dalam folder joderma-survey:'
    echo '#   bash joderma-berkas-lokal.sh'
    echo 'set -euo pipefail'
    echo '[[ -f pyproject.toml ]] || { echo "Jalankan dari dalam folder joderma-survey." >&2; exit 1; }'
    echo 'mkdir -p docs'
    echo "base64 -d <<'B64' | tar xzf -"
    tar czf - "${ADA[@]}" | base64 -w76
    echo 'B64'
    echo 'echo "Berkas lokal dipulihkan:"; ls -la docs/gaps.md docs/operasional.md 2>/dev/null || true'
  } > "$keluar"
  echo "$keluar"
}

if (( BUNDEL )); then
  judul "Membuat bundel untuk disalin tanpa jaringan"
  if (( KERING )); then
    kuning "  [kering] akan menulis skrip bundel ke \${TMPDIR:-/tmp}"
    exit 0
  fi
  LOKASI="$(buat_bundel)"
  hijau "  $LOKASI  ($(stat -c%s "$LOKASI") bita)"
  cat <<SELESAI

  Pindahkan berkas itu ke mini PC dengan cara apa pun -- USB, atau tempel
  isinya lewat terminal yang sudah terbuka di sana:

      cat > joderma-berkas-lokal.sh    # tempel isinya, lalu Ctrl+D
      cd ~/$FOLDER_BAWAAN
      bash ~/joderma-berkas-lokal.sh
SELESAI
  exit 0
fi

# -------------------------------------------------------------- lewat SSH
judul "Memeriksa sambungan ke $TUJUAN"
if ! timeout 10 ssh -o BatchMode=yes -o ConnectTimeout=5 "$TUJUAN" 'true' 2>/dev/null; then
  merah "  Tidak bisa masuk tanpa sandi ke $TUJUAN."
  cat <<BANTUAN

  Tiga kemungkinan, berurutan dari yang paling sering:

  1. Nama penggunanya berbeda. Prompt di mini PC menunjukkan nama yang
     benar, misalnya "joderma-jemur@joderma-jemur:~$" berarti:
         ./tools/kirim-berkas-lokal.sh joderma-jemur@joderma-jemur

  2. Kunci SSH belum terpasang. Sekali saja, lalu seterusnya tanpa sandi:
         ssh-copy-id $TUJUAN

  3. Tidak bisa SSH sama sekali. Buat bundel yang bisa disalin lewat USB
     atau ditempel di terminal mini PC:
         ./tools/kirim-berkas-lokal.sh --bundel
BANTUAN
  exit 1
fi
hijau "  tersambung tanpa sandi"

JAUH="$(ssh "$TUJUAN" "cd '$FOLDER_BAWAAN' 2>/dev/null && pwd" || true)"
if [[ -z "$JAUH" ]]; then
  merah "  Folder ~/$FOLDER_BAWAAN tidak ada di $TUJUAN."
  echo "  Jalankan dulu di sana: git clone <repo> $FOLDER_BAWAAN"
  exit 1
fi
hijau "  folder tujuan: $JAUH"

judul "Berkas yang sudah ada di sana"
SUDAH_ADA=0
for b in "${ADA[@]}"; do
  if ssh "$TUJUAN" "test -f '$JAUH/$b'"; then
    kuning "  $b -- SUDAH ADA, akan ditimpa"
    SUDAH_ADA=1
  fi
done
(( SUDAH_ADA )) || echo "  (belum ada satu pun -- aman)"

if (( KERING )); then
  judul "Uji kering -- tidak ada yang dikirim."
  for b in "${ADA[@]}"; do echo "  akan dikirim: $b -> $JAUH/$b"; done
  exit 0
fi

judul "Mengirim"
ssh "$TUJUAN" "mkdir -p '$JAUH/docs'"
for b in "${ADA[@]}"; do
  scp -q "$b" "$TUJUAN:$JAUH/$b"
  echo "  $b"
done

judul "Memeriksa hasil"
for b in "${ADA[@]}"; do
  LOKAL="$(sha256sum "$b" | cut -c1-16)"
  JAUHSUM="$(ssh "$TUJUAN" "sha256sum '$JAUH/$b'" | cut -c1-16)"
  if [[ "$LOKAL" == "$JAUHSUM" ]]; then
    hijau "  $b  sama persis ($LOKAL)"
  else
    merah "  $b  BERBEDA ($LOKAL vs $JAUHSUM)"
  fi
done

judul "Selesai. Langkah berikutnya di mini PC:"
cat <<LANJUT
    cd ~/$FOLDER_BAWAAN
    less docs/operasional.md       # runbook pemasangan
    ./tools/pasang.sh --kering
LANJUT
