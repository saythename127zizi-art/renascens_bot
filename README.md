# DuitKu Bot — Telegram Personal Finance Tracker

Bot Telegram untuk mencatat pemasukan, pengeluaran, budget, utang/piutang, tabungan, reminder harian, laporan, statistik, dan export CSV.

## Fitur

- `/start` dengan tombol menu
- `/keluar nominal kategori catatan`
- `/masuk nominal kategori catatan`
- kategori default + custom
- laporan `/hariini`, `/mingguini`, `/bulanini`, `/tahunini`, `/range`
- budget bulanan per kategori
- reminder harian
- hapus transaksi terakhir dengan konfirmasi
- edit transaksi terakhir
- riwayat transaksi
- export CSV
- statistik sederhana
- multi-user berdasarkan Telegram `user_id`
- utang/piutang
- target tabungan

## Struktur folder

```text
duitku_bot/
├── main.py
├── database.py
├── models.py
├── handlers.py
├── utils.py
├── requirements.txt
├── .env.example
├── Procfile
├── runtime.txt
└── README.md
```

## 1. Cara mendapatkan BOT_TOKEN dari BotFather

1. Buka Telegram.
2. Cari akun resmi `@BotFather`.
3. Kirim `/newbot`.
4. Ikuti instruksi: isi nama bot dan username bot.
5. BotFather akan memberi token seperti `123456:ABC-DEF...`.
6. Copy token itu.

## 2. Cara install di laptop

Pastikan Python 3.11+ sudah terinstall.

```bash
cd duitku_bot
python -m venv .venv
```

Aktifkan virtual environment:

Windows:

```bash
.venv\Scripts\activate
```

macOS/Linux:

```bash
source .venv/bin/activate
```

Install dependency:

```bash
pip install -r requirements.txt
```

Buat file `.env`:

```bash
cp .env.example .env
```

Isi `.env`:

```env
BOT_TOKEN=token_dari_botfather
```

Jalankan bot:

```bash
python main.py
```

Buka Telegram, cari bot kamu, lalu kirim `/start`.

## 3. Cara deploy ke Railway

1. Upload project ini ke GitHub.
2. Buka Railway.
3. Pilih **New Project** → **Deploy from GitHub Repo**.
4. Pilih repo bot ini.
5. Tambahkan environment variable:
   - `BOT_TOKEN` = token dari BotFather
6. Railway akan membaca `requirements.txt` dan menjalankan `Procfile`:

```text
worker: python main.py
```

7. Deploy.
8. Buka Telegram dan coba `/start`.

Catatan: file SQLite `finance.db` tersimpan di storage app. Untuk production serius, lebih aman pakai volume/persistent storage atau pindah ke PostgreSQL.

## 4. Command testing

```text
/start
/keluar 12000 makan seblak
/keluar 8000 transport ojek
/masuk 45000 jualan mie
/kategori
/kategori_tambah keluar skincare
/budget makan 500000
/hariini
/mingguini
/bulanini
/tahunini
/range 2026-05-01 2026-05-26
/riwayat
/riwayat 20
/stat
/export_csv
/reminder 21:00
/reminder_off
/hapus_terakhir
/edit_terakhir 15000 makan bakso
/utang Rani 50000 pinjam makan
/piutang Dini 30000 titip beli
/daftar_utang
/lunas 1
/tabungan HP 3000000
/nabung 1 50000
```

## 5. Cara backup database SQLite

Database ada di file:

```text
finance.db
```

Backup manual:

```bash
cp finance.db backup_finance_$(date +%Y%m%d).db
```

Atau export transaksi dari Telegram:

```text
/export_csv
```

Untuk Railway, download/copy file database dari persistent storage bila tersedia. Kalau belum pakai persistent storage, data bisa hilang saat redeploy tertentu. Untuk pemakaian jangka panjang, pertimbangkan PostgreSQL.

## 6. Catatan teknis

- Library utama: `python-telegram-bot[job-queue]==22.7`
- Reminder memakai JobQueue.
- Data dipisah berdasarkan Telegram `user_id`.
- Bot memakai polling, jadi tidak butuh webhook.
- Jangan share token bot ke siapa pun.

## Update: Mode input interaktif

Bot ini sudah punya tombol menu utama. Untuk catat transaksi tanpa hafal command:

1. Klik **➖ Catat Pengeluaran** atau **➕ Catat Pemasukan**.
2. Pilih kategori dari tombol.
3. Ketik nominal, misalnya `12000` atau `12k`.
4. Ketik catatan, atau ketik `-` kalau tidak ada catatan.

## Update: Mode jualan

Mode jualan bisa dipakai lewat tombol **🛒 Mode Jualan** atau command manual.

### Tambah produk jualan

Format:

```bash
/produk nama barang | modal | harga jual | stok
```

Contoh:

```bash
/produk indomie soto | 2200 | 4000 | 10
```

Artinya:

- modal per pcs: Rp2.200
- harga jual per pcs: Rp4.000
- stok awal: 10 pcs
- laba per pcs otomatis dihitung Rp1.800

### Catat penjualan

Format:

```bash
/jual id_produk qty catatan
```

Contoh:

```bash
/jual 1 2 pembeli tetangga
```

Bot akan otomatis:

- mengurangi stok produk
- menghitung omzet
- menghitung modal total
- menghitung laba
- mencatat omzet sebagai pemasukan kategori `jualan`

### Lihat stok

```bash
/stok
```

### Tambah stok

```bash
/tambah_stok 1 5
```

### Laporan laba

```bash
/laba_hariini
/laba_bulanini
```

Laporan laba menampilkan:

- barang terjual
- omzet
- modal
- laba bersih
- breakdown per barang
- transaksi jualan terakhir
