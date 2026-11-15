"""Validasi initData Telegram Mini App (HMAC-SHA256, spesifikasi Telegram).

Dipakai server-side sebelum data Mini App dipercaya. Diuji dengan vektor
resmi Telegram (core.telegram.org/bots/webapps).
"""
import hashlib
import hmac
import json
import time
import urllib.parse


def _secret(bot_token: str) -> bytes:
    return hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()


def parse_init_data(raw: str, bot_token: str, expires_in: int = 3600) -> dict:
    """Verifikasi tanda tangan initData; raise ValueError bila tidak valid."""
    params = urllib.parse.parse_qs(raw, keep_blank_values=True)
    if "hash" not in params:
        raise ValueError("hash hilang")
    given_hash = params["hash"][0]
    if "auth_date" not in params:
        raise ValueError("auth_date hilang")
    auth_date = int(params["auth_date"][0])
    if expires_in and time.time() - auth_date > expires_in:
        raise ValueError("initData kedaluwarsa")
    pairs = sorted(
        f"{k}={v}" for k, vals in params.items() if k != "hash" for v in vals
    )
    expected = hmac.new(
        _secret(bot_token), "\n".join(pairs).encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, given_hash):
        raise ValueError("tanda tangan tidak cocok")
    out: dict[str, str] = {k: vals[0] for k, vals in params.items() if vals}
    out.pop("hash", None)
    if "user" in out:
        out["user"] = json.loads(out["user"])
    return out


def verify_vectors() -> None:
    """Vektor resmi Telegram: harus lolos."""
    bot_token = "5768337691:AAH5YkoiEuPk8-FZa32hStHTqXiLPtAEhx8"
    raw = (
        "query_id=AAHdF6IQAAAAAN0XohDhrOrc"
        "&user=%7B%22id%22%3A279058397%2C%22first_name%22%3A%22Vladislav%22%2C"
        "%22last_name%22%3A%22Kibenko%22%2C%22username%22%3A%22vdkfrost%22%2C"
        "%22language_code%22%3A%22ru%22%2C%22is_premium%22%3Atrue%7D"
        "&auth_date=1662771648"
        "&hash=c501b71e775f74ce10e377dea85a7ea24ecd640b223ea86dfe453e0eaed2e2b2"
    )
    data = parse_init_data(raw, bot_token, expires_in=0)
    assert data["user"]["id"] == 279058397, data
    assert data["auth_date"] == "1662771648"
    # auth_date basi harus ditolak
    try:
        parse_init_data(raw, bot_token, expires_in=1)
        raise AssertionError("initData basi lolos")
    except ValueError as e:
        assert "kedaluwarsa" in str(e)
    # token salah harus ditolak
    try:
        parse_init_data(raw, bot_token + "x", expires_in=0)
        raise AssertionError("token salah lolos")
    except ValueError as e:
        assert "tanda tangan" in str(e)
    print("vector OK")


if __name__ == "__main__":
    verify_vectors()
