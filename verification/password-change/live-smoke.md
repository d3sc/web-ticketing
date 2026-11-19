# Verifikasi aplikasi aktif setelah deploy

- Docker web dibuat ulang dari image fitur baru, database aktif tidak dibuat ulang.
- Snapshot sebelum/sesudah deploy: ID, email, role, aktivasi, hash password seluruh pengguna dan jumlah tiket identik.
- Login administrator melalui Chromium menggunakan credential yang sudah ada berhasil.
- Seluruh 3 akun yang sudah ada (administrator, karyawan, agen IT) memiliki tautan Ganti Password dan form dapat dibuka (HTTP 200).
- Pemeriksaan awal mengasumsikan hanya 2 akun sesuai konteks lama sehingga assertion jumlah tautan gagal. Pemeriksaan database menemukan akun agen IT yang sudah ada; tidak ada akun yang dihapus/diubah. Pemeriksaan ulang dengan keadaan aktual berhasil.
- `/health` mengembalikan status ok.
- Container web: running, healthy, restart count 0, OOMKilled false.
- Tidak ada password akun aktif yang diubah untuk pengujian; reset password browser memakai MySQL terpisah pada port 5018.
- Container browser pengujian dan test-db sudah dihentikan setelah verifikasi.
