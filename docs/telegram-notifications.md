# Notifikasi Telegram Helpdesk IT

Implementasi menggantikan rencana notifikasi email untuk tiket baru. Pada checkout ini tidak ditemukan trigger SMTP/email, outbox, atau worker lama; tidak ada data email yang dihapus. Balasan, penugasan, klaim, prioritas dan status tidak membuat notifikasi baru.

## Konfigurasi bot khusus (jangan gunakan bot Hermes)

1. Buka akun resmi `@BotFather` di Telegram. Jalankan `/newbot`, pilih nama dan username bot Helpdesk khusus. Simpan token hanya di `.env` server yang diabaikan Git, dengan izin `chmod 600 .env`. Jangan tempel token di UI, URL browser, screenshot, perintah shell, atau laporan.
2. Isi dua environment berikut di `.env` checkout ini:

       TELEGRAM_BOT_TOKEN=<token dari BotFather>
       APP_BASE_URL=https://alamat-helpdesk-yang-dapat-dibuka-tim-IT

   `.env.example` berisi contoh, bukan credential. Compose meneruskan variabel ke web dan telegram-worker. Aplikasi Flask yang dijalankan di luar Compose memerlukan environment diekspor sendiri.
3. Untuk tujuan pribadi, buka bot dan kirim `/start`. Bot tidak dapat memulai percakapan dengan pengguna yang belum memulainya. Untuk grup tim IT, tambahkan bot, izinkan mengirim pesan, lalu kirim `/start@UsernameBot` di grup agar update diterima walaupun privacy mode aktif. Batasi anggota grup karena judul tiket dapat memuat informasi internal.
4. Ambil Chat ID melalui `getUpdates` dari server, tanpa mencetak token:

       docker compose exec -T web python scripts/telegram_chat_ids.py

   Script membaca token dari environment container, menampilkan hanya ID dan nama chat. ID grup umumnya negatif (misalnya `-1001234567890`); jangan hilangkan tanda minus. Jika belum ada hasil, kirim pesan baru ke bot lalu ulangi. Bot khusus ini tidak membutuhkan webhook atau poller lain; jika getUpdates konflik, periksa penggunaan webhook/poller sebelum mengubahnya. Jangan memakai bot yang sudah digunakan integrasi lain.
5. Login administrator → **Notifikasi Telegram**. Isi **Chat ID Tujuan**, simpan, lalu klik **Kirim Pesan Tes**. Tombol tes selalu memakai tujuan tersimpan, bukan nilai formulir yang belum disimpan; tetap dapat dipakai saat notifikasi otomatis nonaktif. Pesan berhasil berarti API Telegram menerima pesan, bukan tanda bahwa manusia sudah membacanya.
6. Aktifkan toggle **Aktifkan notifikasi tiket baru**, simpan. Antrean dan kegagalan terbaru terlihat pada halaman admin yang sama. Karyawan/agen IT tidak boleh membaca atau mengubah pengaturan ini. Semua POST dilindungi CSRF.

## Tautan tiket dan VPN/Tailscale

APP_BASE_URL harus HTTP/HTTPS tanpa user/password, query, atau fragment, dan bukan localhost/loopback. Gunakan URL yang benar-benar tersedia pada perangkat penerima; alamat atau path-prefix harus cocok dengan reverse proxy yang ada. Tidak ada perubahan binding publik otomatis.

Deployment saat ini tetap terikat ke `127.0.0.1:5017`. Alamat Tailscale saja tidak membuat port loopback dapat diakses. Gunakan reverse proxy/Tailscale Serve yang dikelola operator, atau SSH tunnel dan URL yang sesuai. Jangan mengubah binding ke 0.0.0.0 tanpa keputusan keamanan terpisah.

Setelah konfigurasi, dari perangkat penerima yang benar-benar terhubung VPN/Tailscale: buka pesan Telegram, tekan **Buka Tiket**, pastikan halaman login tampil jika belum login, lalu login sebagai agen/admin yang berhak dan buka tiketnya. Uji karyawan lain tetap menerima 403. Tes server/hostname lokal bukan pengganti tes perangkat tersebut.

Pesan berisi nomor, judul, kategori, prioritas dan waktu pembuatan WIB, tanpa deskripsi/balasan. Tombol inline **Buka Tiket** berada di bawah ringkasan. URL teks selalu disertakan; jika Telegram menolak URL tombol, pengiriman dicoba sekali tanpa keyboard. Rute detail, autentikasi dan izin tiket tidak diubah.

## Transaksi dan worker

Migrasi `telegram_notifications` menambahkan `telegram_settings` (satu baris, default nonaktif) dan `telegram_outbox`, tanpa mengubah tabel inti. Saat toggle aktif, pembuatan tiket memasukkan satu snapshot outbox dalam transaksi tiket yang sama. Unique constraint ticket_id mencegah dua entry untuk tiket yang sama. Tidak ada panggilan jaringan di request pembuatan tiket. Rollback tiket juga membatalkan outbox. Worker memakai sesi MySQL terpisah dan hanya melihat baris yang sudah commit.

Worker mengunci satu baris InnoDB dengan `FOR UPDATE SKIP LOCKED` selama permintaan HTTP yang dibatasi timeout. Dua worker tidak mengirim baris yang sama bersamaan. Pengiriman bersifat **at least once**: crash setelah Telegram menerima pesan tetapi sebelum commit dapat menghasilkan duplikat, karena Telegram tidak menyediakan idempotency key untuk sendMessage.

Gangguan jaringan, respons rusak, 5xx, dan 429 dicoba ulang memakai backoff (5 detik, 10 detik, dst.) dan tidak lebih awal dari retry_after Telegram. Maksimal delapan percobaan. Error token/izin/chat dan konfigurasi permanen dicatat gagal. Token dan respons/error mentah tidak ditulis ke log atau UI. Worker mencatat jumlah pemrosesan dan menyimpan waktu, status, jumlah percobaan dan pesan error aman berbahasa Indonesia di MySQL. Riwayat outbox ditampilkan untuk 20 pengiriman terbaru. UI belum menyediakan resend manual; perbaiki konfigurasi sebelum mengaktifkan notifikasi.

Tujuan dan isi pesan merupakan snapshot saat tiket dibuat. Mengganti tujuan tidak mengalihkan entry lama. Mematikan toggle menjeda pending rows; menyalakannya kembali melanjutkan antrean lama. Pengiriman yang sudah berlangsung saat toggle dimatikan dapat selesai. Tidak ada backfill untuk tiket yang dibuat saat nonaktif. Baris terkirim tidak dikirim ulang otomatis.

       docker compose build web
       docker compose up -d db
       docker compose run --rm --no-deps web flask --app helpdesk db upgrade
       docker compose up -d --no-deps --wait web
       docker compose up -d --no-deps --wait telegram-worker

Setelah mengganti token atau APP_BASE_URL, buat ulang kedua service agar environment terbaru dipakai:

       docker compose up -d --no-deps --force-recreate --wait web
       docker compose up -d --no-deps --force-recreate --wait telegram-worker

Jangan membuat ulang database atau menghapus volumenya untuk mengubah token. Worker `restart: unless-stopped` memiliki healthcheck heartbeat dan polling lima detik. Untuk inspeksi/operator:

       docker compose ps
       docker compose logs --tail=50 telegram-worker
       docker compose exec -T web flask --app helpdesk telegram-worker --once

Jangan menjalankan worker sekali untuk replay gagal tanpa memahami statusnya; hanya pending yang jatuh tempo akan diproses. Kegagalan Telegram tidak menghalangi tiket tersimpan. Bila bot/token atau URL belum tersedia, biarkan toggle nonaktif dan gunakan informasi konfigurasi pada UI.

## Pengujian

       docker compose --profile test build tests
       docker compose --profile test run --rm tests

Semua fixture dibatasi ke database `helpdesk_test`. Suite meliputi pengaturan/otorisasi/CSRF, validasi group ID, payload/WIB/link, rollback outbox, visibilitas commit, fallback tombol, sanitasi error, retry_after/backoff, batas percobaan, serta dua worker MySQL. Telegram selalu ditiru di tes; tes tidak menghubungi bot nyata.

Untuk browser acceptance setelah suite lulus, jalankan service sementara dengan image yang baru diuji. Pastikan port 5018 kosong:

       docker compose --profile test run --rm --no-deps -d --name web-ticketing-telegram-browser -p 127.0.0.1:5018:8000 tests python -m scripts.telegram_browser_server
       .venv/bin/python scripts/browser_telegram_acceptance.py
       docker stop web-ticketing-telegram-browser
       docker compose --profile test stop test-db

Diperlukan Playwright Chromium lokal. Server fixture menolak database selain helpdesk_test pada host test-db. Ia mengganti transport Telegram dalam proses khusus tes, bukan menyediakan mode mock pada aplikasi produksi. Browser memakai mapping hostname helpdesk.test lokal. Bukti disimpan di `verification/telegram/`. Pengiriman nyata dan tautan perangkat VPN tetap harus diuji terpisah setelah token, tujuan, dan URL yang benar tersedia.
