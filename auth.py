"""Login por e-mail — o mesmo dos outros painéis da Central (tabela acesso.app_users no Neon).

Mesmo fluxo e mesmo visual da Aderência Salarial / Headcount Total: o acesso é liberado
cadastrando o e-mail em acesso.app_users (grant_access.py dos outros painéis); no primeiro
login a pessoa cria a senha; depois de MAX_TENTATIVAS senhas erradas seguidas a conta fica
bloqueada por BLOQUEIO_MINUTOS. Quem já tem login em outro painel entra com a mesma senha.

O usuário de banco do painel lê e atualiza acesso.app_users pelo grupo grp_auth (migração 012).
E-mail de suporte: [app] email_suporte nos Secrets (fora do código, que é público).
"""
from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path
from typing import Callable

import bcrypt
import pandas as pd
import psycopg2
import psycopg2.extras
import streamlit as st

TABELA = "acesso.app_users"  # nome completo: o search_path do usuário do painel é só `core`
MAX_TENTATIVAS = 5
BLOQUEIO_MINUTOS = 15
ICONE = Path(__file__).parent / "assets" / "icone-turnover.png"
TITULO = "Turnover"
SUBTITULO = "Admissões, desligamentos e taxa de turnover da Pacaembu Construtora"

_CSS = """<style>
.st-key-login_page { margin-top: 10vh; }
[data-testid="stVerticalBlockBorderWrapper"].st-key-login_card {
    border: none !important; border-radius: 16px; overflow: hidden; padding: 0 !important;
    box-shadow: 0 14px 40px rgba(6, 77, 102, .18);
}
.st-key-login_card [data-testid="stHorizontalBlock"] { gap: 0 !important; }
.st-key-login_left {
    background: linear-gradient(160deg, #064D66 0%, #2a78d6 100%);
    min-height: 460px; height: 100%; padding: 48px 30px;
    display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center;
}
.login-logo-pill {
    background: #FFFFFF; color: #064D66; border-radius: 12px; padding: 14px 18px;
    display: inline-flex; align-items: center; justify-content: center; gap: 10px; margin-bottom: 22px;
    box-shadow: 0 6px 18px rgba(0, 0, 0, .18); max-width: 100%; box-sizing: border-box;
    font-weight: 700; font-size: 15px;
}
.login-logo-pill img { height: 26px; width: auto; display: block; }
.login-brand-sub { color: rgba(255, 255, 255, .88); font-size: 12px; line-height: 1.65; max-width: 220px; margin: 0 auto; text-align: center; }
.st-key-login_right { padding: 48px 44px; min-height: 460px; height: 100%; display: flex; flex-direction: column; justify-content: center; }
.login-form-title { font-size: 18px; font-weight: 600; color: #111110; margin: 0 0 4px; line-height: 1.4; }
.login-form-sub { font-size: 12.5px; color: #6b6b68; margin: 0 0 22px; line-height: 1.5; }
.st-key-login_right div[data-testid="stButton"] button {
    background: linear-gradient(160deg, #064D66 0%, #2a78d6 100%) !important; border: none !important;
    font-weight: 600 !important; border-radius: 8px !important; padding: 10px 0 !important;
}
.st-key-login_right div[data-testid="stButton"] button p { color: #FFFFFF !important; }
.st-key-login_right div[data-testid="stButton"] button:hover { filter: brightness(1.08); }
</style>"""


# ----------------------------------------------------------------------------- banco

def _conectar():
    return psycopg2.connect(st.secrets["neon"]["database_url"], connect_timeout=10)


def _email_suporte() -> str:
    try:
        return st.secrets["app"]["email_suporte"]
    except Exception:  # noqa: BLE001
        return "o time de People Analytics"


def normalizar(email: str) -> str:
    return email.strip().lower()


def buscar_usuario(email: str) -> dict | None:
    with _conectar() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f"SELECT email, name, password_hash, failed_attempts, locked_until FROM {TABELA} WHERE email = %s",
                    (normalizar(email),))
        linha = cur.fetchone()
    return dict(linha) if linha else None


def bloqueado(usuario: dict) -> bool:
    ate = usuario.get("locked_until")
    return ate is not None and ate > pd.Timestamp.now(tz="UTC")


def minutos_restantes(usuario: dict) -> int:
    seg = (usuario["locked_until"] - pd.Timestamp.now(tz="UTC")).total_seconds()
    return max(1, int(-(-seg // 60)))


def _falhou(email: str) -> None:
    with _conectar() as conn, conn.cursor() as cur:
        cur.execute(f"""
            UPDATE {TABELA}
            SET failed_attempts = failed_attempts + 1,
                locked_until = CASE WHEN failed_attempts + 1 >= %(max)s
                                    THEN now() + (%(min)s * interval '1 minute') ELSE locked_until END,
                updated_at = now()
            WHERE email = %(email)s""", {"email": normalizar(email), "max": MAX_TENTATIVAS, "min": BLOQUEIO_MINUTOS})


def _zerar_tentativas(email: str) -> None:
    with _conectar() as conn, conn.cursor() as cur:
        cur.execute(f"UPDATE {TABELA} SET failed_attempts = 0, locked_until = NULL, updated_at = now() WHERE email = %s",
                    (normalizar(email),))


def verificar(email: str, senha: str) -> dict | None:
    usuario = buscar_usuario(email)
    if not usuario or not usuario.get("password_hash") or bloqueado(usuario):
        return None
    if bcrypt.checkpw(senha.encode(), usuario["password_hash"].encode()):
        _zerar_tentativas(email)
        return usuario
    _falhou(email)
    return None


def criar_senha(email: str, senha: str) -> dict | None:
    with _conectar() as conn, conn.cursor() as cur:
        cur.execute(f"UPDATE {TABELA} SET password_hash = %s, updated_at = now() WHERE email = %s",
                    (bcrypt.hashpw(senha.encode(), bcrypt.gensalt()).decode(), normalizar(email)))
    return buscar_usuario(email)


# ----------------------------------------------------------------------------- telas

@lru_cache(maxsize=1)
def _icone_b64() -> str:
    return "data:image/png;base64," + base64.b64encode(ICONE.read_bytes()).decode()


def _cartao(titulo: str, subtitulo: str, formulario: Callable[[], None]) -> None:
    st.html(_CSS)
    with st.container(key="login_page"):
        _, meio, _ = st.columns([1, 2.3, 1])
        with meio, st.container(border=True, key="login_card"):
            esq, dir_ = st.columns([1, 1.25])
            with esq, st.container(key="login_left"):
                st.html(f'<div class="login-logo-pill"><img src="{_icone_b64()}" alt="" />{TITULO}</div>'
                        f'<p class="login-brand-sub">{SUBTITULO}</p>')
            with dir_, st.container(key="login_right"):
                st.html(f'<div class="login-form-title">{titulo}</div><p class="login-form-sub">{subtitulo}</p>')
                formulario()


def _tela_email() -> None:
    def form() -> None:
        email = st.text_input("E-mail", label_visibility="collapsed", placeholder="seu.email@pacaembu.com")
        if st.button("Continuar", width="stretch"):
            if "@" not in normalizar(email):
                st.error("Informe um e-mail válido.")
            else:
                st.session_state["auth_email"] = normalizar(email)
                st.rerun()
    _cartao("Entrar", "Digite seu e-mail corporativo para acessar o painel.", form)


def _tela_erro_conexao() -> None:
    def form() -> None:
        st.error("Não foi possível conectar ao banco de dados agora. Isso costuma ser passageiro — tente de novo em alguns segundos.")
        if st.button("Tentar novamente", width="stretch"):
            st.rerun()
    _cartao("Erro temporário de conexão", "Não conseguimos falar com o banco de dados agora.", form)


def _tela_sem_acesso(email: str) -> None:
    def form() -> None:
        st.warning(f"O e-mail **{email}** ainda não tem acesso a este painel. Solicite a inclusão para **{_email_suporte()}**.")
        if st.button("Tentar outro e-mail", width="stretch"):
            st.session_state["auth_email"] = None
            st.rerun()
    _cartao("Acesso não encontrado", "Esse e-mail ainda não está liberado.", form)


def _tela_criar_senha(usuario: dict) -> None:
    def form() -> None:
        senha = st.text_input("Senha", type="password", placeholder="Crie uma senha (mín. 8 caracteres)")
        conf = st.text_input("Confirmar senha", type="password", placeholder="Digite a senha de novo")
        if st.button("Criar senha e entrar", width="stretch"):
            if len(senha) < 8:
                st.error("A senha precisa ter pelo menos 8 caracteres.")
            elif senha != conf:
                st.error("As senhas não coincidem.")
            else:
                st.session_state["auth_user"] = criar_senha(usuario["email"], senha)
                st.rerun()
    _cartao(f"Olá, {usuario.get('name') or usuario['email']}", "Este é seu primeiro acesso — crie uma senha.", form)


def _tela_senha(usuario: dict) -> None:
    def form() -> None:
        if bloqueado(usuario):
            st.warning(f"Conta temporariamente bloqueada por tentativas de senha incorreta. Tente de novo em ~{minutos_restantes(usuario)} minuto(s).")
        else:
            senha = st.text_input("Senha", type="password", label_visibility="collapsed", placeholder="Digite sua senha")
            if st.button("Entrar", width="stretch"):
                ok = verificar(usuario["email"], senha)
                if ok:
                    st.session_state["auth_user"] = ok
                    st.rerun()
                novo = buscar_usuario(usuario["email"])
                st.error(f"Muitas tentativas erradas — conta bloqueada por ~{minutos_restantes(novo)} minuto(s)."
                         if novo and bloqueado(novo) else "Senha incorreta.")
        if st.button("Usar outro e-mail", key="trocar_email"):
            st.session_state["auth_email"] = None
            st.rerun()
    _cartao(f"Olá, {usuario.get('name') or usuario['email']}", "Digite sua senha para entrar.", form)


def exigir_login() -> None:
    """Para o script até a pessoa estar autenticada. Depois disso, a barra lateral do
    painel_padrao mostra "Olá, {nome}" e o botão Sair (lendo st.session_state["auth_user"])."""
    if st.session_state.get("auth_user") is not None:
        return
    email = st.session_state.get("auth_email")
    if not email:
        _tela_email()
        st.stop()
    try:
        usuario = buscar_usuario(email)
    except Exception:  # noqa: BLE001
        _tela_erro_conexao()
        st.stop()
    if usuario is None:
        _tela_sem_acesso(email)
    elif not usuario.get("password_hash"):
        _tela_criar_senha(usuario)
    else:
        _tela_senha(usuario)
    st.stop()
