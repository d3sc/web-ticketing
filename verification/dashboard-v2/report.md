# Hasil perbaikan dashboard, akses peran, dan prioritas

## Akar masalah yang direproduksi sebelum perubahan
- Login karyawan diarahkan ke `/`, dengan judul `Tiket Saya`.
- `/tickets` juga dapat dibuka oleh karyawan, menampilkan template antrean bersama dan filter agen. Route ini tidak memiliki pembatas peran.
- `visible()` sudah menerapkan `creator_id == current_user.id` untuk karyawan. Kebocoran data lintas karyawan tidak berhasil direproduksi; masalah yang terbukti adalah pemisahan route, navigasi dan UX yang tidak tegas.
- Semua peran sebelumnya diarahkan ke root; admin/IT tidak langsung menuju antrean.
- Form tidak memiliki field prioritas dan backend memaksa `normal`.

## Perbaikan
- Karyawan login/root -> `/`, daftar terpaginasikan berjudul Tiket Saya.
- IT/admin login -> `/tickets`, kunjungan root dialihkan ke antrean.
- Karyawan mengakses `/tickets` -> 403. Izin admin/detail/reply dan action lain tetap diperiksa server-side.
- Base query ownership dipakai sebelum pencarian, filter, hitungan status dan pagination. Hitungan atas seluruh scope pemilik, bukan scope filter saat ini.
- Renderer daftar bersama: kartu status, filter terpadu, nomor/judul, kategori, prioritas/status berwarna, pembaruan terakhir, kolom agen hanya untuk IT/admin, empty state dan pagination yang mempertahankan filter.
- Prioritas awal low/normal/high, label Indonesia, default Normal jika field tidak dikirim. Blank/nilai tidak dikenal ditolak dengan Prioritas tidak valid. Nilai pilihan dipertahankan ketika field lain gagal.
- Tidak ada perubahan skema; migrasi tetap 0001_initial.

## Berkas berubah (relatif terhadap direktori proyek)
- helpdesk/auth.py, helpdesk/tickets.py, helpdesk/forms.py
- helpdesk/static/app.css
- helpdesk/templates/base.html, queue.html, dashboard.html, detail.html, macros.html, new_ticket.html, login.html, users.html, categories.html, error.html
- tests/test_helpdesk.py, tests/test_additional.py, tests/test_role_listing_priority.py
- scripts/browser_acceptance.py, scripts/browser_dashboard_regression.py
- README.md
- verification/dashboard-v2/results.json dan screenshot bukti

## Bukti pengujian
- Test-first backend: 11 gagal, 3 lulus sebelum implementasi perbaikan baru.
- Suite lokal SQLite: 31 passed, 35 peringatan, 81.25 detik.
- Profil MySQL terisolasi: database tmpfs baru + migrasi + 31 passed, 36 peringatan, 63.31 detik.
- Suite MySQL diulang dengan tambahan assertion label prioritas pada daftar ketiga peran: 31 passed, 36 peringatan, 72.77 detik.
- Peringatan: deprecation tuple choices WTForms dan cache pytest yang tidak dapat ditulis; bukan kegagalan tes.
- Regresi meliputi dua pemilik/50 tiket, hitungan status, pencarian nomor/judul, pagination, larangan direct URL/action, semua prioritas, default/invalid/preservation, dan klaim bersamaan tepat satu pemenang.
- Playwright Chromium: login/root tiga peran, jumlah/daftar milik karyawan, pencarian lintas pemilik kosong, GET antrean/admin/tiket orang lain dan POST reply -> 403, validasi prioritas, claim/reply/close lulus.
- Browser workflow lengkap lama dijalankan ulang: karyawan melihat balasan, reopen/resolve/close, agen tak ditugaskan -> 403, balasan tiket tertutup -> 409.
- Desktop 1440px dan mobile 390px: dashboard karyawan, antrean IT/admin, form tiket; tidak ada overflow dokumen. Tabel bergulir lokal untuk kolom tambahan. Tidak ada JavaScript page errors.
- Penyimpanan MySQL dikonfirmasi: tiket regresi 4=low, 5=normal, 6=high.

## Deployment dan data
- Build image web-ticketing:local (juga diberi tag dashboard-v2), hanya service web direcreate dengan --no-deps.
- MySQL aplikasi tidak direstart/direcreate; data tiket lama 1/2 diperiksa dan dipertahankan. Database/volume tidak direset.
- Web/MySQL healthy, restart 0, OOM false. /login -> HTTP 200; /health -> status ok.
- Proyek Docker lain tetap berjalan. Service database tes dihentikan.
- Akun dan tiket QA baru sengaja dipertahankan sebagai bukti pengujian; tidak mengubah atau menghapus data pengguna sebelumnya.

## Akses privat laptop
Jalankan pada laptop:

    ssh -N -o ExitOnForwardFailure=yes -L 127.0.0.1:5017:127.0.0.1:5017 tpang@192.168.0.121

Buka http://127.0.0.1:5017/login. Binding tetap 127.0.0.1:5017, bukan publik.

## Batas verifikasi
Koneksi SSH/browser dari laptop pengguna sendiri, audit aksesibilitas menyeluruh, load test dan pemulihan backup tidak diuji. Bukti browser berasal dari Chromium nyata di server. Kredensial tidak dimasukkan ke laporan.
