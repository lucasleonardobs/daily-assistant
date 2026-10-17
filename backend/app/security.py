"""Senhas e tokens. Tudo que é sensível para autenticação mora aqui."""
import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# argon2id com os parâmetros mínimos recomendados pela OWASP (19 MiB, 2 passes): cabe no plano pequeno do Railway.
_hasher = PasswordHasher(time_cost=2, memory_cost=19_456, parallelism=1)
_DUMMY_HASH = _hasher.hash("senha-falsa-para-igualar-o-tempo")

MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 128


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    """Compara em tempo parecido mesmo quando o usuário não existe (evita revelar quais e-mails são válidos)."""
    try:
        _hasher.verify(password_hash or _DUMMY_HASH, password)
        return password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def password_problem(password: str, email: str) -> str | None:
    """Devolve a mensagem do que está errado, ou None se a senha é aceitável."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"A senha precisa ter pelo menos {MIN_PASSWORD_LENGTH} caracteres."
    if len(password) > MAX_PASSWORD_LENGTH:
        return f"A senha pode ter no máximo {MAX_PASSWORD_LENGTH} caracteres."
    lowered = password.lower()
    if email.lower() in lowered or email.split("@")[0].lower() in lowered:
        return "A senha não pode conter o seu e-mail."
    if len(set(password)) < 5:
        return "Escolha uma senha menos repetitiva."
    return None


def new_token() -> str:
    """Token aleatório de 256 bits para links de convite."""
    return secrets.token_urlsafe(32)


def token_digest(token: str) -> str:
    """O banco guarda só o hash: quem lê o banco não consegue usar um convite."""
    return hashlib.sha256(token.encode()).hexdigest()


def same_origin(origin: str | None, host: str | None) -> bool:
    """Defesa contra CSRF: o Origin de uma requisição que altera dados deve ser o próprio site."""
    if not origin:
        return True  # navegadores sempre enviam em POST cross-site; clientes sem Origin não carregam o cookie de outro site
    return hmac.compare_digest(origin.split("://", 1)[-1].lower(), (host or "").lower())
