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
from joderma_survey.pengguna import IZIN, KEMAMPUAN
from joderma_survey.sesi_ops import BELUM_MASUK, BERHAK, TANPA_HAK, HasilSesi
from joderma_survey.web_admin import buat_app

HARI_H = dt.date(2026, 10, 11)
HOST_OPS = "ops.contoh.id"
LOGIN_OPS = f"https://{HOST_OPS}/akun/login/?next="


class PemeriksaPalsu:
    """Pengganti tanya-ke-ops: nilai kuki ``sessionid`` -> jawaban ops.

    Tanpa jaringan sama sekali. Setiap panggilan dicatat, supaya tes bisa
    memastikan ops ditanya pada setiap permintaan.
    """

    def __init__(self) -> None:
        self.jawab: dict[str, HasilSesi] = {
            "kuki-owner1": HasilSesi(BERHAK, "owner1", "Owner Satu", "owner"),
            "kuki-dirops": HasilSesi(BERHAK, "dirops", "Direktur Ops", "direktur"),
            "kuki-cs1": HasilSesi(BERHAK, "cs1", "CS Satu", "cs"),
            "kuki-gudang": HasilSesi(TANPA_HAK, "gudang", "Staf Gudang", None),
        }
        self.panggilan: list[str | None] = []

    def __call__(self, kuki: str | None) -> HasilSesi:
        self.panggilan.append(kuki)
        if kuki is None:
            return HasilSesi(BELUM_MASUK)
        return self.jawab.get(kuki, HasilSesi(BELUM_MASUK))


@pytest.fixture
def path_basis(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("JODERMA_URL_SURVEI", "https://survey.contoh.id")
    monkeypatch.setenv("JODERMA_KUKI_AMAN", "0")
    monkeypatch.setenv("JODERMA_OPS_HOST", HOST_OPS)
    monkeypatch.delenv("JODERMA_AWALAN_ADMIN", raising=False)
    path = tmp_path / "uji.db"
    conn = db.buka(path)
    db.migrasi(conn)
    conn.close()
    return path


@pytest.fixture
def pemeriksa() -> PemeriksaPalsu:
    return PemeriksaPalsu()


@pytest.fixture
def app(path_basis: Path, pemeriksa: PemeriksaPalsu) -> Flask:
    aplikasi = buat_app(path_basis, kunci_rahasia="kunci-uji", pemeriksa_sesi=pemeriksa)
    aplikasi.config["TESTING"] = True
    return aplikasi


@pytest.fixture
def klien(app: Flask) -> Iterator[FlaskClient]:
    with app.test_client() as c:
        yield c


def masuk_sebagai(klien: FlaskClient, nama: str) -> None:
    """Tiru peramban yang sudah login ops: ia membawa kuki ``sessionid``."""
    klien.set_cookie("sessionid", f"kuki-{nama}")
    # GET pertama membuat token CSRF di sesi survei.
    assert klien.get("/").status_code in (302, 403)


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
# Login lewat sesi ops (keputusan 13 Okt 2026)
# --------------------------------------------------------------------------


def test_tanpa_sesi_ops_dialihkan_ke_login_ops(klien: FlaskClient) -> None:
    for jalur in ("/", "/kirim", "/unggah", "/hasil"):
        jawab = klien.get(jalur)
        assert jawab.status_code == 302, jalur
        assert jawab.headers["Location"].startswith(LOGIN_OPS), jawab.headers["Location"]


def test_halaman_admin_tidak_disimpan_di_cache_peramban(klien: FlaskClient) -> None:
    """Daftar kirim memuat data pasien: sesudah logout ops, tombol kembali tidak boleh menampilkannya."""
    assert "no-store" in klien.get("/kirim").headers["Cache-Control"]  # dialihkan ke login
    masuk_sebagai(klien, "dirops")
    jawab = klien.get("/kirim")
    assert jawab.status_code == 200 and "no-store" in jawab.headers["Cache-Control"]


def test_next_memuat_jalur_yang_diminta(klien: FlaskClient) -> None:
    jawab = klien.get("/kirim?cabang=30376")
    assert jawab.headers["Location"] == LOGIN_OPS + "/kirim%3Fcabang%3D30376"


def test_jawaban_tak_sah_dialihkan_tidak_pernah_lolos(
    klien: FlaskClient, pemeriksa: PemeriksaPalsu
) -> None:
    """Kuki yang tidak dikenali ops (atau ops mati/timeout) = belum login."""
    klien.set_cookie("sessionid", "kuki-asing")
    for jalur in ("/", "/kirim", "/unggah", "/hasil"):
        jawab = klien.get(jalur)
        assert jawab.status_code == 302
        assert jawab.headers["Location"].startswith(LOGIN_OPS)


def test_hanya_kuki_sessionid_diteruskan(
    klien: FlaskClient, pemeriksa: PemeriksaPalsu
) -> None:
    klien.set_cookie("csrftoken", "lain")
    masuk_sebagai(klien, "cs1")
    klien.get("/kirim")
    assert pemeriksa.panggilan[-1] == "kuki-cs1"


@pytest.mark.parametrize(
    ("nama", "peran"), [("owner1", "owner"), ("dirops", "direktur"), ("cs1", "cs")]
)
def test_tiap_peran_mendapat_hak_sesuai_izin(
    klien: FlaskClient, nama: str, peran: str
) -> None:
    masuk_sebagai(klien, nama)
    rute = {"unggah_laporan": "/unggah", "lihat_daftar_kirim": "/kirim",
            "lihat_hasil": "/hasil"}
    for kemampuan, jalur in rute.items():
        assert kemampuan in KEMAMPUAN
        harap = 200 if kemampuan in IZIN[peran] else 403
        assert klien.get(jalur).status_code == harap, (peran, jalur)


def test_403_dari_ops_halaman_tanpa_hak(klien: FlaskClient) -> None:
    masuk_sebagai(klien, "gudang")
    for jalur in ("/", "/kirim", "/unggah", "/hasil"):
        jawab = klien.get(jalur)
        assert jawab.status_code == 403, jalur
        isi = jawab.get_data(as_text=True)
        assert "Halaman ini tidak terbuka untuk peran Anda." in isi
        assert f'href="https://{HOST_OPS}/"' in isi, "tautan kembali ke ops"


def test_ops_ditanya_setiap_permintaan(
    klien: FlaskClient, pemeriksa: PemeriksaPalsu
) -> None:
    masuk_sebagai(klien, "dirops")
    sebelum = len(pemeriksa.panggilan)
    klien.get("/kirim")
    klien.get("/kirim")
    assert len(pemeriksa.panggilan) == sebelum + 2


def test_peran_berubah_di_ops_langsung_berlaku(
    klien: FlaskClient, pemeriksa: PemeriksaPalsu
) -> None:
    masuk_sebagai(klien, "dirops")
    assert klien.get("/hasil").status_code == 200
    pemeriksa.jawab["kuki-dirops"] = HasilSesi(BERHAK, "dirops", "Direktur Ops", "cs")
    assert klien.get("/hasil").status_code == 403
    pemeriksa.jawab["kuki-dirops"] = HasilSesi(TANPA_HAK, "dirops", "Direktur Ops", None)
    assert klien.get("/kirim").status_code == 403


def test_logout_ops_langsung_berlaku(
    klien: FlaskClient, pemeriksa: PemeriksaPalsu
) -> None:
    masuk_sebagai(klien, "dirops")
    assert klien.get("/kirim").status_code == 200
    del pemeriksa.jawab["kuki-dirops"]
    jawab = klien.get("/kirim")
    assert jawab.status_code == 302
    assert jawab.headers["Location"].startswith(LOGIN_OPS)


def test_sesi_survei_saja_tidak_cukup(app: Flask, pemeriksa: PemeriksaPalsu) -> None:
    """Status login tidak disimpan di sesi survei; tanpa kuki ops = ditolak."""
    with app.test_client() as c:
        masuk_sebagai(c, "dirops")
        c.delete_cookie("sessionid")
        assert c.get("/kirim").status_code == 302


def test_halaman_masuk_tidak_ada_lagi(klien: FlaskClient) -> None:
    assert klien.get("/masuk").status_code == 404
    assert klien.post("/masuk", data={"nama": "x", "sandi": "y"}).status_code in (400, 404)


def test_tidak_ada_tombol_keluar_hanya_kembali_ke_ops(klien: FlaskClient) -> None:
    masuk_sebagai(klien, "dirops")
    isi = klien.get("/kirim").get_data(as_text=True)
    assert "/masuk" not in isi
    assert "/keluar" not in isi
    assert f'href="https://{HOST_OPS}/"' in isi
    assert "Kembali ke ops" in isi


def test_tombol_kembali_ke_ops_mencolok_di_awal_kepala(klien: FlaskClient) -> None:
    """13 Okt 2026: tombol, bukan tautan teks kecil di ujung kanan."""
    masuk_sebagai(klien, "cs1")
    isi = klien.get("/kirim").get_data(as_text=True)
    kepala = isi.split("<header>", 1)[1].split("</header>", 1)[0]
    tombol = f'<a class="tombol-ops" href="https://{HOST_OPS}/">'
    assert tombol in kepala and kepala.index(tombol) < kepala.index("JoDerma Survei")
    assert kepala.count(f'href="https://{HOST_OPS}/"') == 1


def test_kepala_halaman_menampilkan_nama_dari_ops(klien: FlaskClient) -> None:
    masuk_sebagai(klien, "dirops")
    isi = klien.get("/kirim").get_data(as_text=True)
    assert "Direktur Ops" in isi and "direktur" in isi


def test_tidak_ada_open_redirect(klien: FlaskClient) -> None:
    """Tujuan pengalihan selalu host ops yang dikonfigurasi, dan ``next``
    selalu jalur internal, apa pun yang ada di URL permintaan."""
    for jalur in ("/kirim?next=https://jahat.example", "/kirim?lanjut=//jahat.example",
                  "/hasil?awal=https://jahat.example/"):
        lokasi = klien.get(jalur).headers.get("Location", "")
        assert lokasi.startswith(LOGIN_OPS), (jalur, lokasi)
        nxt = lokasi[len(LOGIN_OPS):]
        assert nxt.startswith("/") and "://" not in nxt and "?" not in nxt, nxt
    # PATH_INFO janggal langsung dari server WSGI pun tidak lolos.
    for info in ("//jahat.example/kirim", "/\\jahat.example"):
        lokasi = klien.get("/", environ_overrides={"PATH_INFO": info}).headers.get(
            "Location", "")
        assert "jahat.example" not in lokasi.split("?")[0], lokasi


@pytest.mark.parametrize(
    ("awalan", "jalur", "kueri", "harap"),
    [
        ("", "/kirim", "", "/kirim"),
        ("/survei", "/kirim", "", "/survei/kirim"),
        ("/survei", "/", "", "/survei/"),
        ("/survei", "/kirim", "cabang=1", "/survei/kirim?cabang=1"),
        ("", "//jahat.example/x", "", "/jahat.example/x"),
        ("", "/\\jahat.example", "", "/jahat.example"),
        ("", "", "", "/"),
    ],
)
def test_jalur_lanjut(awalan: str, jalur: str, kueri: str, harap: str) -> None:
    from joderma_survey.sesi_ops import jalur_lanjut

    assert jalur_lanjut(awalan, jalur, kueri) == harap


def test_url_login_ops_mengode_next() -> None:
    from joderma_survey.sesi_ops import url_login_ops

    assert url_login_ops("ops.contoh.id", "/survei/kirim?cabang=1&x=2") == (
        "https://ops.contoh.id/akun/login/?next=/survei/kirim%3Fcabang%3D1%26x%3D2"
    )


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


def test_token_csrf_dibuat_pada_get_pertama(klien: FlaskClient) -> None:
    masuk_sebagai(klien, "cs1")
    token = csrf(klien)
    assert token
    klien.get("/kirim")
    assert csrf(klien) == token, "token tidak berganti tiap permintaan"


def test_post_tanpa_csrf_ditolak_walau_berhak(
    klien: FlaskClient, path_basis: Path
) -> None:
    """Sesi ops yang sah tidak menggantikan CSRF survei."""
    token = isi_undangan(path_basis)
    klien.set_cookie("sessionid", "kuki-cs1")
    assert klien.post(f"/kirim/{token}/batal", data={}).status_code == 400


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
    masuk_sebagai(klien, "cs1")
    assert klien.get("/hasil?awal=2026-10-01&akhir=2026-10-31").status_code == 403
