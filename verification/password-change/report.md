# Verifikasi fitur Ganti Password

- Pengujian awal (RED): 13 tes gagal karena route dan tombol belum ada.
- Seluruh suite pada MySQL 8, database terpisah `helpdesk_test`: 44 passed, 40 warnings, 84.38 detik.
- Warnings: 39 deprecation WTForms dari pilihan SelectField lama dan satu izin cache pytest dalam image, bukan kegagalan tes.
- Uji Chromium/Playwright melalui localhost:5018 menggunakan MySQL test terpisah: semua pemeriksaan berhasil, 0 JavaScript page errors.
- Admin mengganti password karyawan, agen IT dan akun admin sendiri melalui UI; login password lama ditolak dan password baru diterima untuk ketiganya.
- Password admin saat ini yang salah, konfirmasi tidak sama, password terlalu pendek dan POST tanpa CSRF ditolak.
- Karyawan/agen tidak dapat mengakses atau POST langsung ke route ganti password (403).
- Tampilan desktop 1440px dan mobile 390px diperiksa; tidak ada overflow horizontal.
- Screenshot: desktop.png dan mobile.png. Hasil browser terstruktur: results.json.
- Akun dan password yang diubah dalam uji browser hanya berada pada database test, bukan aplikasi aktif.

Batasan yang didokumentasikan: perubahan password tidak mencabut sesi login yang sudah aktif. `.local-credentials` hanya catatan bootstrap dan tidak diperbarui otomatis oleh UI.
