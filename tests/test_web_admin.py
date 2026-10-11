"""Uji aplikasi web admin, terutama penegakan hak akses (F14)."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Iterator

import pytest
from bantu import laporan, transaksi
from flask import Flask
from flask.testing import FlaskClient

from joderma_survey import db
from joderma_survey.daftar_kirim import buat_undangan
from joderma_survey.pengguna import buat_pengguna
from joderma_survey.web_admin import buat_app

SANDI = "sandi-uji-yang-panjang"
HARI_H = dt.date(2026, 10, 11)


@pytest.fixture
def path_basis(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("JODERMA_URL_SURVEI", "https://survey.contoh.id")
    monkeypatch.setenv("JODERMA_KUKI_AMAN", "0")
    path = tmp_path / "uji.db"
    conn = db.buka(path)
    db.migrasi(conn)
    for nama, peran in (("owner1", "owner"), ("dirops", "direktur"), ("cs1", "cs")):
        buat_pengguna(conn, nama, peran, SANDI)
    conn.close()
    return path


@pytest.fixture
def app(path_basis: Path) -> Flask:
    aplikasi = buat_app(path_basis, kunci_rahasia="kunci-uji")
    aplikasi.config["TESTING"] = True
    return aplikasi


@pytest.fixture
def klien(app: Flask) -> Iterator[FlaskClient]:
    with app.test_client() as c:
        yield c


def masuk_sebagai(klien: FlaskClient, nama: str) -> None:
    jawab = klien.post("/masuk", data={"nama": nama, "sandi": SANDI})
    assert jawab.status_code == 302, "login seharusnya berhasil"


def csrf(klien: FlaskClient) -> str:
    with klien.session_transaction() as sesi:
        return sesi["csrf"]


def isi_undangan(path_basis: Path, nama: str = "Tatik Mindari") -> str:
    conn = db.buka(path_basis)
    lap = laporan(transaksi(no_id="J00143", pasien=nama))
    uid = db.simpan_laporan(conn, lap, diunggah_pada=HARI_H).unggahan_id
    buat_undangan(conn, lap, uid, hari_ini=dt.date.today())
    token = conn.execute("SELECT token FROM undangan").fetchone()["token"]
    conn.close()
    return token


# --------------------------------------------------------------------------
# Masuk dan keluar
# --------------------------------------------------------------------------


def test_tanpa_masuk_dialihkan_ke_halaman_masuk(klien: FlaskClient) -> None:
    for jalur in ("/", "/kirim", "/unggah", "/hasil"):
        jawab = klien.get(jalur)
        assert jawab.status_code == 302
        assert "/masuk" in jawab.headers["Location"]


def test_masuk_berhasil(klien: FlaskClient) -> None:
    masuk_sebagai(klien, "dirops")
    assert klien.get("/kirim").status_code == 200


def test_masuk_sandi_salah(klien: FlaskClient) -> None:
    jawab = klien.post("/masuk", data={"nama": "dirops", "sandi": "salah-sekali-ini"})
    assert jawab.status_code == 401
    assert "salah" in jawab.get_data(as_text=True).lower()


def test_pesan_gagal_tidak_membocorkan_nama_terdaftar(klien: FlaskClient) -> None:
    ada = klien.post("/masuk", data={"nama": "dirops", "sandi": "salah-sekali-ini"})
    tiada = klien.post("/masuk", data={"nama": "hantu", "sandi": "salah-sekali-ini"})
    assert ada.get_data(as_text=True) == tiada.get_data(as_text=True)


def test_keluar_menghapus_sesi(klien: FlaskClient) -> None:
    masuk_sebagai(klien, "cs1")
    klien.post("/keluar", data={"csrf": csrf(klien)})
    assert klien.get("/kirim").status_code == 302


def test_pengalihan_setelah_masuk_hanya_jalur_internal(klien: FlaskClient) -> None:
    jawab = klien.post(
        "/masuk?lanjut=https://jahat.example/ambil",
        data={"nama": "cs1", "sandi": SANDI},
    )
    assert jawab.status_code == 302
    assert "jahat.example" not in jawab.headers["Location"]


def test_pengalihan_lanjut_internal_dihormati(klien: FlaskClient) -> None:
    jawab = klien.post("/masuk?lanjut=/kirim", data={"nama": "cs1", "sandi": SANDI})
    assert jawab.headers["Location"].endswith("/kirim")


# --------------------------------------------------------------------------
# Hak akses (F14) -- bagian terpenting
# --------------------------------------------------------------------------


def test_cs_tidak_bisa_membuka_hasil_survei(klien: FlaskClient) -> None:
    """Syarat inti F14: CS tidak dapat melihat hasil survei."""
    masuk_sebagai(klien, "cs1")
    assert klien.get("/hasil").status_code == 403


def test_cs_tidak_bisa_mengunggah_laporan(klien: FlaskClient) -> None:
    masuk_sebagai(klien, "cs1")
    assert klien.get("/unggah").status_code == 403
    assert klien.post("/unggah", data={"csrf": csrf(klien)}).status_code == 403


def test_cs_bisa_membuka_daftar_kirim(klien: FlaskClient) -> None:
    masuk_sebagai(klien, "cs1")
    assert klien.get("/kirim").status_code == 200


@pytest.mark.parametrize("nama", ["owner1", "dirops"])
def test_owner_dan_direktur_bisa_semua_halaman(klien: FlaskClient, nama: str) -> None:
    masuk_sebagai(klien, nama)
    for jalur in ("/kirim", "/unggah", "/hasil"):
        assert klien.get(jalur).status_code == 200, jalur


def test_beranda_mengarah_sesuai_peran(klien: FlaskClient) -> None:
    masuk_sebagai(klien, "cs1")
    assert klien.get("/").headers["Location"].endswith("/kirim")


def test_beranda_direktur_ke_unggah(klien: FlaskClient) -> None:
    masuk_sebagai(klien, "dirops")
    assert klien.get("/").headers["Location"].endswith("/unggah")


def test_menu_cs_tidak_memuat_tautan_hasil(klien: FlaskClient) -> None:
    masuk_sebagai(klien, "cs1")
    isi = klien.get("/kirim").get_data(as_text=True)
    assert "/hasil" not in isi
    assert "/unggah" not in isi


def test_menu_direktur_memuat_semua_tautan(klien: FlaskClient) -> None:
    masuk_sebagai(klien, "dirops")
    isi = klien.get("/kirim").get_data(as_text=True)
    assert "/hasil" in isi and "/unggah" in isi


# --------------------------------------------------------------------------
# CSRF
# --------------------------------------------------------------------------


def test_post_tanpa_token_csrf_ditolak(klien: FlaskClient, path_basis: Path) -> None:
    token = isi_undangan(path_basis)
    masuk_sebagai(klien, "cs1")
    jawab = klien.post(f"/kirim/{token}/batal", data={})
    assert jawab.status_code == 400


def test_post_token_csrf_salah_ditolak(klien: FlaskClient, path_basis: Path) -> None:
    token = isi_undangan(path_basis)
    masuk_sebagai(klien, "cs1")
    jawab = klien.post(f"/kirim/{token}/batal", data={"csrf": "palsu"})
    assert jawab.status_code == 400


def test_token_csrf_berbeda_antar_sesi(app: Flask) -> None:
    with app.test_client() as a, app.test_client() as b:
        masuk_sebagai(a, "cs1")
        masuk_sebagai(b, "dirops")
        assert csrf(a) != csrf(b)


# --------------------------------------------------------------------------
# Daftar kirim
# --------------------------------------------------------------------------


def test_daftar_kirim_menampilkan_teks_siap_salin(
    klien: FlaskClient, path_basis: Path
) -> None:
    isi_undangan(path_basis, nama="Ade Wijaya")
    masuk_sebagai(klien, "cs1")
    isi = klien.get("/kirim").get_data(as_text=True)
    assert "Ade Wijaya - J00143" in isi, "teks pencarian WhatsApp"
    assert "https://survey.contoh.id/s/" in isi
    assert "Teks pencarian" in isi and "Isi pesan" in isi


def test_daftar_kirim_kosong_memberi_keterangan(klien: FlaskClient) -> None:
    masuk_sebagai(klien, "cs1")
    isi = klien.get("/kirim").get_data(as_text=True)
    assert "Tidak ada yang perlu dikirim" in isi


def test_daftar_kirim_menandai_keraguan(klien: FlaskClient, path_basis: Path) -> None:
    conn = db.buka(path_basis)
    lap = laporan(transaksi(no_id="JC1093", pasien="Dr. Muhlis Yusuf"),
                  kode_cabang="31281")
    uid = db.simpan_laporan(conn, lap, diunggah_pada=HARI_H).unggahan_id
    buat_undangan(conn, lap, uid, hari_ini=dt.date.today())
    conn.close()
    masuk_sebagai(klien, "cs1")
    isi = klien.get("/kirim").get_data(as_text=True)
    assert "Periksa dulu" in isi


def test_saring_cabang(klien: FlaskClient, path_basis: Path) -> None:
    isi_undangan(path_basis)
    masuk_sebagai(klien, "cs1")
    assert "J00143" in klien.get("/kirim?cabang=30376").get_data(as_text=True)
    assert "J00143" not in klien.get("/kirim?cabang=31281").get_data(as_text=True)


def test_cabang_tak_dikenal_diabaikan(klien: FlaskClient, path_basis: Path) -> None:
    isi_undangan(path_basis)
    masuk_sebagai(klien, "cs1")
    jawab = klien.get("/kirim?cabang=99999")
    assert jawab.status_code == 200
    assert "J00143" in jawab.get_data(as_text=True)


# --------------------------------------------------------------------------
# Pembatalan undangan
# --------------------------------------------------------------------------


def test_cs_bisa_membatalkan_undangan(
    klien: FlaskClient, path_basis: Path
) -> None:
    token = isi_undangan(path_basis)
    masuk_sebagai(klien, "cs1")
    jawab = klien.post(f"/kirim/{token}/batal", data={"csrf": csrf(klien)},
                       follow_redirects=True)
    assert jawab.status_code == 200
    assert "dibatalkan" in jawab.get_data(as_text=True).lower()
    conn = db.buka(path_basis)
    baris = conn.execute("SELECT dibatalkan_pada FROM undangan").fetchone()
    conn.close()
    assert baris["dibatalkan_pada"] is not None


def test_undangan_dibatalkan_hilang_dari_daftar(
    klien: FlaskClient, path_basis: Path
) -> None:
    token = isi_undangan(path_basis)
    masuk_sebagai(klien, "cs1")
    klien.post(f"/kirim/{token}/batal", data={"csrf": csrf(klien)})
    assert "J00143" not in klien.get("/kirim").get_data(as_text=True)


def test_membatalkan_dua_kali_memberi_pesan_galat(
    klien: FlaskClient, path_basis: Path
) -> None:
    token = isi_undangan(path_basis)
    masuk_sebagai(klien, "cs1")
    klien.post(f"/kirim/{token}/batal", data={"csrf": csrf(klien)})
    jawab = klien.post(f"/kirim/{token}/batal", data={"csrf": csrf(klien)},
                       follow_redirects=True)
    assert "tidak ditemukan" in jawab.get_data(as_text=True).lower()


def test_token_asing_tidak_membocorkan_apa_pun(
    klien: FlaskClient, path_basis: Path
) -> None:
    masuk_sebagai(klien, "cs1")
    jawab = klien.post("/kirim/token-palsu/batal", data={"csrf": csrf(klien)},
                       follow_redirects=True)
    assert jawab.status_code == 200


# --------------------------------------------------------------------------
# Unggah laporan
# --------------------------------------------------------------------------


def test_unggah_tanpa_berkas(klien: FlaskClient) -> None:
    masuk_sebagai(klien, "dirops")
    jawab = klien.post("/unggah", data={"csrf": csrf(klien)}, follow_redirects=True)
    assert "Pilih berkas" in jawab.get_data(as_text=True)


def test_unggah_berkas_bukan_laporan(klien: FlaskClient) -> None:
    import io

    masuk_sebagai(klien, "dirops")
    jawab = klien.post(
        "/unggah",
        data={
            "csrf": csrf(klien),
            "laporan": (io.BytesIO(b"bukan xls sama sekali"),
                        "sales_transactions_11_10_2026_30376.xls"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert jawab.status_code == 200
    assert "tidak bisa dibuka" in jawab.get_data(as_text=True).lower()


def test_unggah_nama_berkas_tanpa_kode_cabang(klien: FlaskClient) -> None:
    import io

    masuk_sebagai(klien, "dirops")
    jawab = klien.post(
        "/unggah",
        data={"csrf": csrf(klien),
              "laporan": (io.BytesIO(b"apa saja"), "laporan.xls")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert "kode cabang tidak ditemukan" in jawab.get_data(as_text=True).lower()


BERKAS_ASLI = (
    Path(__file__).resolve().parent.parent
    / "contoh-xls-omnicare"
    / "sales_transactions_11_10_2026_30376.xls"
)


def test_unggah_berkas_asli_sampai_daftar_kirim(
    klien: FlaskClient, path_basis: Path
) -> None:
    """Alur lengkap dengan berkas asli; dilewati bila berkasnya tidak ada."""
    if not BERKAS_ASLI.exists():
        pytest.skip("berkas contoh tidak ada")
    masuk_sebagai(klien, "dirops")
    with BERKAS_ASLI.open("rb") as f:
        jawab = klien.post(
            "/unggah",
            data={"csrf": csrf(klien), "laporan": (f, BERKAS_ASLI.name)},
            content_type="multipart/form-data",
        )
    isi = jawab.get_data(as_text=True)
    assert jawab.status_code == 200
    assert "Jemur Andayani" in isi
    assert "380" in isi, "380 link dibuat"
    assert "117" in isi, "117 pasien OTC diparkir"
    assert "J0635" in isi, "normalisasi RM dilaporkan"

    conn = db.buka(path_basis)
    jumlah = conn.execute("SELECT COUNT(*) AS n FROM undangan").fetchone()["n"]
    conn.close()
    assert jumlah == 380

    daftar = klien.get("/kirim").get_data(as_text=True)
    assert "https://survey.contoh.id/s/" in daftar


def test_berkas_laporan_tidak_disimpan(klien: FlaskClient, tmp_path: Path) -> None:
    """PRD bagian Privasi: berkas laporan tidak disimpan permanen."""
    if not BERKAS_ASLI.exists():
        pytest.skip("berkas contoh tidak ada")
    masuk_sebagai(klien, "dirops")
    with BERKAS_ASLI.open("rb") as f:
        klien.post("/unggah",
                   data={"csrf": csrf(klien), "laporan": (f, BERKAS_ASLI.name)},
                   content_type="multipart/form-data")
    sisa = list(Path(tempfile_gettempdir()).glob("omnicare-*"))
    assert sisa == [], f"berkas sementara tertinggal: {sisa}"


def tempfile_gettempdir() -> str:
    import tempfile

    return tempfile.gettempdir()


# --------------------------------------------------------------------------
# Halaman laporan (F13) -- dicetak ke PDF dari peramban
# --------------------------------------------------------------------------


def siapkan_jawaban(
    path_basis: Path, jumlah: int = 12, diisi_pada: str = "2026-10-15",
    nilai: str = "5",
) -> None:
    """Isi beberapa survei agar laporan punya data."""
    from joderma_survey.survei import StatusLink, periksa_token, simpan_jawaban

    conn = db.buka(path_basis)
    baris = [
        transaksi(no_id=f"J0{i:04d}", faktur=26100000.0 + i, pasien=f"Pasien {i}",
                  tanggal="05/10/2026", waktu="05/10/2026 10:00:00")
        for i in range(1, jumlah + 1)
    ]
    lap = laporan(*baris,
                  judul="TRANSAKSI PENJUALAN PER 01 OKTOBER 2026 S/D 31 OKTOBER 2026")
    uid = db.simpan_laporan(conn, lap, diunggah_pada=dt.date(2026, 10, 11)).unggahan_id
    buat_undangan(conn, lap, uid, hari_ini=dt.date(2026, 10, 11))
    token = [b["token"] for b in conn.execute(
        "SELECT token FROM undangan WHERE diisi_pada IS NULL")]
    for t in token:
        status, undangan = periksa_token(conn, t, dt.date(2026, 10, 11))
        if status is not StatusLink.SIAP or undangan is None:
            continue
        simpan_jawaban(conn, undangan, {
            "keseluruhan": nilai, "penjelasan_dokter": nilai,
            "waktu_tunggu": nilai, "sikap_staf": nilai, "kenyamanan": nilai,
            "kejelasan_biaya": nilai, "perbaikan": "Parkir sempit.",
            "izin_kontak": "tidak",
        }, hari_ini=dt.date.fromisoformat(diisi_pada))
    conn.close()


def test_laporan_butuh_hak_lihat_hasil(klien: FlaskClient) -> None:
    masuk_sebagai(klien, "cs1")
    assert klien.get("/hasil").status_code == 403


def test_laporan_menampilkan_semua_bagian(
    klien: FlaskClient, path_basis: Path
) -> None:
    siapkan_jawaban(path_basis)
    masuk_sebagai(klien, "dirops")
    isi = klien.get("/hasil?awal=2026-10-01&akhir=2026-10-31").get_data(as_text=True)
    for bagian in ["Jangkauan pengiriman", "Skor per pertanyaan",
                   "Perubahan dari periode sebelumnya", "Keterwakilan",
                   "Cara membaca laporan ini"]:
        assert bagian in isi, bagian


def test_laporan_memuat_skor_dan_selang(
    klien: FlaskClient, path_basis: Path
) -> None:
    siapkan_jawaban(path_basis, jumlah=12, nilai="4")
    masuk_sebagai(klien, "dirops")
    isi = klien.get("/hasil?awal=2026-10-01&akhir=2026-10-31").get_data(as_text=True)
    assert "4.00" in isi
    assert "&plusmn;" in isi or "±" in isi


def test_laporan_memuat_aturan_baca(klien: FlaskClient, path_basis: Path) -> None:
    """Tanpa ini, orang akan bereaksi pada pergerakan yang sebenarnya derau."""
    siapkan_jawaban(path_basis)
    masuk_sebagai(klien, "dirops")
    isi = klien.get("/hasil?awal=2026-10-01&akhir=2026-10-31").get_data(as_text=True)
    assert "Bacalah perubahannya, bukan tingkat skornya" in isi
    assert "derau" in isi
    assert "skor per dokter" in isi.lower()


def test_laporan_punya_css_cetak(klien: FlaskClient, path_basis: Path) -> None:
    siapkan_jawaban(path_basis)
    masuk_sebagai(klien, "dirops")
    isi = klien.get("/hasil?awal=2026-10-01&akhir=2026-10-31").get_data(as_text=True)
    assert "@media print" in isi
    assert "@page" in isi and "A4" in isi
    assert "break-inside: avoid" in isi
    assert "window.print()" in isi


def test_laporan_tanpa_pembanding_memberi_keterangan(
    klien: FlaskClient, path_basis: Path
) -> None:
    siapkan_jawaban(path_basis)
    masuk_sebagai(klien, "dirops")
    isi = klien.get("/hasil?awal=2026-10-01&akhir=2026-10-31").get_data(as_text=True)
    assert "Belum ada data periode sebelumnya" in isi


def test_laporan_periode_kosong(klien: FlaskClient) -> None:
    masuk_sebagai(klien, "dirops")
    jawab = klien.get("/hasil?awal=2026-01-01&akhir=2026-01-31")
    assert jawab.status_code == 200
    assert "Belum ada jawaban" in jawab.get_data(as_text=True)


def test_laporan_tanggal_salah_memakai_bulan_berjalan(klien: FlaskClient) -> None:
    masuk_sebagai(klien, "dirops")
    jawab = klien.get("/hasil?awal=bukan-tanggal&akhir=2026-10-31",
                      follow_redirects=True)
    assert jawab.status_code == 200
    assert "Tanggal tidak dikenali" in jawab.get_data(as_text=True)


def test_laporan_disaring_per_cabang(klien: FlaskClient, path_basis: Path) -> None:
    siapkan_jawaban(path_basis)
    masuk_sebagai(klien, "dirops")
    isi = klien.get(
        "/hasil?awal=2026-10-01&akhir=2026-10-31&cabang=31281"
    ).get_data(as_text=True)
    assert "Citraland" in isi
    assert "Belum ada jawaban" in isi, "tidak ada jawaban Citraland pada data uji"


def test_laporan_menampilkan_teks_tersaring(
    klien: FlaskClient, path_basis: Path
) -> None:
    siapkan_jawaban(path_basis, jumlah=3)
    conn = db.buka(path_basis)
    pid = conn.execute(
        "SELECT id FROM pertanyaan WHERE kode='perbaikan' AND aktif=1"
    ).fetchone()["id"]
    sesi = conn.execute("SELECT id FROM sesi_jawaban LIMIT 1").fetchone()["id"]
    conn.execute(
        "UPDATE jawaban SET nilai_teks='Hubungi 081234567890' "
        "WHERE sesi_id=? AND pertanyaan_id=?", (sesi, pid)
    )
    conn.close()
    masuk_sebagai(klien, "dirops")
    isi = klien.get("/hasil?awal=2026-10-01&akhir=2026-10-31").get_data(as_text=True)
    assert "081234567890" not in isi
    assert "[TELEPON]" in isi


def test_laporan_hanya_untuk_owner_dan_direktur(
    klien: FlaskClient, path_basis: Path
) -> None:
    siapkan_jawaban(path_basis, jumlah=3)
    for nama in ("owner1", "dirops"):
        masuk_sebagai(klien, nama)
        assert klien.get("/hasil?awal=2026-10-01&akhir=2026-10-31").status_code == 200
        klien.post("/keluar", data={"csrf": csrf(klien)})
