"""Uji bot.py tanpa Telegram nyata: API dipalsukan, initData ditandatangani sendiri."""
import base64
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BOT_TOKEN = "999:TESTTOKEN"
HOME_CHAT = "1"
APP_URL = "https://example.com/moneysav.html"

calls: list[tuple[str, dict]] = []
updates: list[dict] = []


def fake_api(method: str, payload: dict | None = None) -> dict:
    """Ganti api() bawaan: catat panggilan, balas seperti Telegram."""
    calls.append((method, payload or {}))
    if method == "getUpdates":
        batch, updates[:] = list(updates), []
        return {"ok": True, "result": batch}
    if method == "sendMessage":
        return {"ok": True, "result": {"message_id": 1}}
    if method == "answerCallbackQuery":
        return {"ok": True, "result": True}
    raise AssertionError(f"metode tak terduga: {method}")


def sign_init_data(user: dict, auth_date: int | None = None) -> str:
    """Buat initData sah dengan token uji."""
    auth_date = auth_date or int(time.time())
    fields = {
        "query_id": "Q1",
        "user": json.dumps(user, separators=(",", ":")),
        "auth_date": str(auth_date),
    }
    pairs = sorted(f"{k}={v}" for k, v in fields.items())
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, "\n".join(pairs).encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(fields)


def run() -> None:
    import bot

    bot.api = fake_api
    bot.BOT_TOKEN = BOT_TOKEN
    bot.HOME_CHAT = HOME_CHAT
    bot.APP_URL = APP_URL
    bot.ALLOWED_USERS = {1, 2}
    bot.STORE = "store.test.json"
    if os.path.exists(bot.STORE):
        os.remove(bot.STORE)

    user = {"id": 1, "first_name": "Tester", "username": "tester"}
    raw = sign_init_data(user)

    # 1. /start mengirim tombol web_app
    updates.append({"message": {"chat": {"id": 1}, "from": {"id": 1}, "text": "/start"}})
    for upd in bot.poll_updates():
        bot.handle_update(upd)
    assert calls[-1][0] == "sendMessage", calls
    markup = calls[-1][1]["reply_markup"]["inline_keyboard"][0][0]
    assert markup["web_app"]["url"] == APP_URL, markup

    # 2. data Mini App (base64) + initData sah -> tercatat
    payload = {"action": "add", "type": "EXPENSE", "amount": 25000,
               "category": "Makanan & Minuman", "note": "Kopi", "method": "Tunai",
               "date": int(time.time() * 1000)}
    encoded = base64.b64encode(json.dumps(payload).encode()).decode()
    updates.append({"message": {"chat": {"id": 1}, "from": {"id": 1},
                                "web_app_data": {"data": encoded},
                                "web_app_data_init": raw}})
    for upd in bot.poll_updates():
        bot.handle_update(upd)
    store = bot.load_store()
    assert len(store["transactions"]) == 1, store
    assert store["transactions"][0]["amount"] == 25000
    assert store["users"]["1"]["first_name"] == "Tester"

    # 3. initData kedaluwarsa -> ditolak, tidak tercatat
    stale = sign_init_data(user, auth_date=int(time.time()) - 7200)
    updates.append({"message": {"chat": {"id": 1}, "from": {"id": 1},
                                "web_app_data": {"data": encoded},
                                "web_app_data_init": stale}})
    for upd in bot.poll_updates():
        bot.handle_update(upd)
    assert len(bot.load_store()["transactions"]) == 1, "initData basi tercatat"

    # 4. user di luar daftar -> ditolak
    bot.ALLOWED_USERS = {1}
    other = sign_init_data({"id": 2, "first_name": "Lain"})
    updates.append({"message": {"chat": {"id": 1}, "from": {"id": 1},
                                "web_app_data": {"data": encoded},
                                "web_app_data_init": other}})
    for upd in bot.poll_updates():
        bot.handle_update(upd)
    assert len(bot.load_store()["transactions"]) == 1, "user asing tercatat"

    # 5. /summary memakai data tersimpan
    updates.append({"message": {"chat": {"id": 1}, "from": {"id": 1}, "text": "/summary"}})
    for upd in bot.poll_updates():
        bot.handle_update(upd)
    text = calls[-1][1]["text"]
    assert "Rp 25.000" in text, text
    assert "Keluar" in text, text

    os.remove(bot.STORE)
    print("test_bot OK")


if __name__ == "__main__":
    run()
