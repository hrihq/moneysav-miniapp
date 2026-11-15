# MoneySav Telegram Mini App

Mini App Telegram untuk MoneySav: catat pemasukan/pengeluaran dari Telegram,
lihat saldo & grafik 6 bulan, semua tampilan mengikuti bahasa desain aplikasi
Android-nya (palet lavender `#7050D5` / `#FFC928`, kartu kaca, nav 5 tab).

## Arsitektur

```
moneysav.html        Mini App statis (GitHub Pages)
  └─ Telegram.WebApp.sendData(payload base64)  ← tutup Mini App, kirim ke bot
       └─ bot.py     getUpdates → validasi initData (HMAC) → store.json
            └─ sendMessage(ringkasan bulan ini) ke chat
```

Kenapa `sendData`, bukan server HTTP: Mini App butuh jalur dua arah yang
bergantung hanya pada bot Telegram. `sendData` tersedia kalau Mini App dibuka
lewat tombol keyboard (`web_app`) — itulah cara yang dipakai di sini. Server
HTTP opsional (`/submit` + `/health`) ikut disertakan untuk mode self-host.

## Verifikasi identitas

`telegram_auth.py` mengimplementasikan validasi initData Telegram:
HMAC-SHA256 dengan kunci `WebAppData` + bot token, `auth_date` dibatasi 1 jam,
dan dicek terhadap vektor resmi Telegram (`python telegram_auth.py`).

Data `initDataUnsafe` hanya dipakai untuk tampilan (nama/avatar); pencatatan
transaksi selalu dari `initData` yang sudah diverifikasi bot.

## Menjalankan

Token bot diambil dari Hermes `.env` (bot `hermes_…_bot`) lewat secret Actions
`TELEGRAM_BOT_TOKEN`; jangan hardcode.

```bash
MONEYSAV_BOT_TOKEN=... python miniapp/bot.py        # polling + server opsional
```

## Deploy

- **Mini App**: GitHub Pages otomatis dari branch `main` (halaman di root).
- **Bot**: workflow `bot.yml` memulai `bot.py` sebagai job `bot` (polling
  getUpdates). Token masuk lewat `secrets.TELEGRAM_BOT_TOKEN`.
