"""MoneySav Telegram Mini App — bot.

Mini App (moneysav.html) dipasang di GitHub Pages dan dibuka lewat deep link.
Data dikirim balik lewat Telegram.WebApp.sendData (maks 4096 byte) lalu Mini App
ditutup; bot mencatatnya ke store lokal dan mengirim ringkasan ke chat.
"""
import base64
import json
import logging
import os
import re
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from telegram_auth import parse_init_data

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO
)
log = logging.getLogger("moneysav")

BOT_TOKEN = os.environ.get("MONEYSAV_BOT_TOKEN", "CHANGEME")
HOME_CHAT = os.environ.get("MONEYSAV_HOME_CHAT", "7238979587")
APP_URL = os.environ.get(
    "MONEYSAV_APP_URL", "https://hrihq.github.io/moneysav-miniapp/moneysav.html"
)
STORE = os.environ.get("MONEYSAV_STORE", "store.json")
ALLOWED_USERS = {
    int(u) for u in os.environ.get("MONEYSAV_ALLOWED_USERS", HOME_CHAT).split(",") if u
}

_lock = threading.Lock()
_stop = threading.Event()


def api(method: str, payload: dict | None = None) -> dict:
    data = urllib.parse.urlencode(payload or {}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{BOT_TOKEN}/{method}",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        body = json.loads(r.read())
    if not body.get("ok"):
        log.warning("api %s gagal: %s", method, body)
    return body


def load_store() -> dict:
    if os.path.exists(STORE):
        with open(STORE, encoding="utf-8") as f:
            return json.load(f)
    return {"transactions": [], "users": {}, "seq": 0}


def save_store(store: dict) -> None:
    tmp = STORE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STORE)


def add_transaction(store: dict, user_id: int, payload: dict) -> dict:
    with _lock:
        store["seq"] = store.get("seq", 0) + 1
        t = {
            "id": store["seq"],
            "user_id": user_id,
            "type": payload["type"],
            "amount": int(payload["amount"]),
            "category": payload["category"],
            "note": payload.get("note", ""),
            "method": payload.get("method", "Tunai"),
            "date": payload.get("date") or int(time.time() * 1000),
            "created": int(time.time() * 1000),
        }
        store.setdefault("transactions", []).append(t)
        save_store(store)
        return t


def fmt_rp(n: int) -> str:
    return "Rp " + f"{abs(n):,}".replace(",", ".")


def month_stats(store: dict, user_id: int, month_key: str) -> dict:
    from datetime import datetime

    tx = [t for t in store["transactions"] if t["user_id"] == user_id]
    inc = exp = 0
    for t in tx:
        key = datetime.fromtimestamp(t["date"] / 1000).strftime("%Y-%m")
        if key != month_key:
            continue
        if t["type"] == "INCOME":
            inc += t["amount"]
        else:
            exp += t["amount"]
    return {"income": inc, "expense": exp, "balance": inc - exp}


def esc(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def report(user_id: int) -> str:
    from datetime import datetime

    store = load_store()
    name = store.get("users", {}).get(str(user_id), {}).get("first_name", "Kamu")
    month = datetime.now().strftime("%Y-%m")
    st = month_stats(store, user_id, month)
    tx = [
        t
        for t in store["transactions"]
        if t["user_id"] == user_id
        and datetime.fromtimestamp(t["date"] / 1000).strftime("%Y-%m") == month
    ]
    lines = [
        f"<b>{esc(name)}</b> — {month}",
        f"Masuk: <b>{fmt_rp(st['income'])}</b>",
        f"Keluar: <b>{fmt_rp(st['expense'])}</b>",
        f"Saldo bulan ini: <b>{fmt_rp(st['balance'])}</b>",
        f"Transaksi: {len(tx)}",
    ]
    return "\n".join(lines)


class Handler(BaseHTTPRequestHandler):
    server_version = "MoneySav/1.0"

    def log_message(self, format, *args):  # noqa: A002 - nama sesuai base class
        log.info("%s", format % args)

    def _send(self, code: int, body: str, ctype: str = "application/json") -> None:
        raw = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/health":
            self._send(200, '{"ok":true}')
        elif self.path == "/pending":
            store = load_store()
            self._send(200, json.dumps({"pending": store.get("pending", 0)}))
        else:
            self._send(404, '{"error":"not found"}')

    def do_POST(self):
        if self.path != "/submit":
            return self._send(404, '{"error":"not found"}')
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode()
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            return self._send(400, '{"error":"json"}')
        try:
            user = parse_init_data(body["initData"], BOT_TOKEN, expires_in=3600)["user"]
        except (KeyError, ValueError, IndexError, json.JSONDecodeError) as e:
            log.warning("initData ditolak: %s", e)
            return self._send(403, '{"error":"initData"}')
        uid = int(user["id"])
        if uid not in ALLOWED_USERS:
            log.warning("user %s di luar daftar", uid)
            return self._send(403, '{"error":"user"}')
        store = load_store()
        store.setdefault("users", {})[str(uid)] = {
            "first_name": user.get("first_name", ""),
            "username": user.get("username", ""),
        }
        save_store(store)
        if body.get("action") == "add":
            t = add_transaction(store, uid, body)
            log.info("user %s menambah %s %s", uid, t["type"], t["amount"])
        with _lock:
            store["pending"] = store.get("pending", 0) + 1
            save_store(store)
        self._send(200, '{"ok":true}')


def main():
    if not BOT_TOKEN or BOT_TOKEN.endswith("CHANGEME"):
        raise SystemExit("MONEYSAV_BOT_TOKEN belum diisi")
    threading.Thread(target=serve, daemon=True).start()
    log.info("bot siap; home=%s app=%s", HOME_CHAT, APP_URL)
    while not _stop.is_set():
        try:
            for upd in poll_updates():
                handle_update(upd)
        except Exception as e:  # jangan mati karena satu error
            log.exception("loop: %s", e)
            time.sleep(5)


def serve():
    ThreadingHTTPServer(("127.0.0.1", int(os.environ.get("PORT", "8787"))), Handler).serve_forever()


def poll_updates() -> list[dict]:
    body = api("getUpdates", {"timeout": "25", "allowed_updates": '["message","callback_query"]'})
    return body.get("result", [])


def handle_update(upd: dict) -> None:
    if "callback_query" in upd:
        cq = upd["callback_query"]
        api("answerCallbackQuery", {"callback_query_id": cq["id"]})
        if cq.get("data") == "refresh":
            api(
                "sendMessage",
                {
                    "chat_id": cq["message"]["chat"]["id"],
                    "text": report(int(cq["from"]["id"])),
                    "parse_mode": "HTML",
                },
            )
        return
    msg = upd.get("message") or {}
    text = msg.get("text", "") or ""
    chat = msg["chat"]["id"]
    uid = msg["from"]["id"]
    web = msg.get("web_app_data")
    if web:
        handle_web_data(uid, chat, web.get("data", ""), msg.get("web_app_data_init", ""))
        return
    if text.startswith("/"):
        cmd = text.split()[0].split("@")[0]
        if cmd in ("/start", "/menu"):
            api(
                "sendMessage",
                {
                    "chat_id": chat,
                    "text": "MoneySav — catat keuangan dari Telegram.",
                    "reply_markup": {
                        "inline_keyboard": [
                            [
                                {
                                    "text": "💰 Buka MoneySav",
                                    "web_app": {"url": APP_URL},
                                }
                            ]
                        ]
                    },
                },
            )
        elif cmd == "/summary":
            api(
                "sendMessage",
                {
                    "chat_id": chat,
                    "text": report(uid),
                    "parse_mode": "HTML",
                    "reply_markup": {
                        "inline_keyboard": [
                            [{"text": "🔄 Muat ulang", "callback_data": "refresh"}]
                        ]
                    },
                },
            )
        else:
            api(
                "sendMessage",
                {
                    "chat_id": chat,
                    "text": "Perintah: /start — buka Mini App\n/summary — ringkasan bulan ini",
                },
            )


def handle_web_data(uid: int, chat: int, encoded: str, init_raw: str) -> None:
    """Catat transaksi yang dikirim Mini App via sendData."""
    try:
        payload = json.loads(base64.b64decode(encoded).decode())
    except (ValueError, UnicodeDecodeError) as e:
        log.warning("payload buruk dari %s: %s", uid, e)
        return reply(chat, "Data transaksi tidak bisa dibaca.")
    if not init_raw:
        # Mini App dibuka lewat tombol keyboard: initData kosong. Terima payload
        # hanya kalau user sudah dikenal dari sesi sebelumnya.
        store = load_store()
        if str(uid) not in store.get("users", {}):
            log.warning("user %s belum punya identitas tervalidasi", uid)
            return reply(chat, "Buka lagi lewat tombol MoneySav untuk verifikasi.")
    else:
        try:
            user = parse_init_data(init_raw, BOT_TOKEN, expires_in=3600)["user"]
        except (ValueError, KeyError, IndexError, json.JSONDecodeError) as e:
            log.warning("initData %s ditolak: %s", uid, e)
            return reply(chat, "Verifikasi gagal. Coba buka lagi dari tombol MoneySav.")
        if not user or int(user["id"]) != uid:
            return reply(chat, "Identitas tidak cocok.")
        if uid not in ALLOWED_USERS:
            log.warning("user %s di luar daftar", uid)
            return reply(chat, "Kamu tidak punya akses.")
        store = load_store()
        store.setdefault("users", {})[str(uid)] = {
            "first_name": user.get("first_name", ""),
            "username": user.get("username", ""),
        }
        save_store(store)
    if payload.get("action") == "add":
        t = add_transaction(load_store(), uid, payload)
        log.info("user %s menambah %s %s", uid, t["type"], t["amount"])
        reply(chat, f"Tersimpan: {t['type']} {fmt_rp(t['amount'])} — {t['category']}\n\n{report(uid)}")
    elif payload.get("action") == "sync":
        reply(chat, report(uid))
    else:
        reply(chat, "Aksi tidak dikenal.")


def reply(chat: int, text: str) -> None:
    api("sendMessage", {"chat_id": chat, "text": text, "parse_mode": "HTML"})


if __name__ == "__main__":
    main()
