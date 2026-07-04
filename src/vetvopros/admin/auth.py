"""Проверка логина/пароля админки из настроек (.env)."""


def verify_admin_credentials(username: str, password: str, expected_username: str, expected_password: str) -> bool:
    u = (username or "").strip()
    p = password or ""
    return u == (expected_username or "").strip() and p == (expected_password or "")
