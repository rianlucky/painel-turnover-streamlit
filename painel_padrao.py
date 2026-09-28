"""Padrão visual dos painéis Streamlit da Central de Gente & Dados (Pacaembu Construtora).

Modelo mantido na skill `padrao-painel-streamlit` (People Analytics/.claude/skills). Cada
painel tem a sua cópia deste arquivo (o deploy no Streamlit Cloud é por repositório).

Barra lateral, sempre nesta ordem:
    1. Logo: ícone do painel + nome (st.logo, fixo no topo)
    2. "Olá, {nome}" + botão Sair   (quando há login; em desenvolvimento, aviso discreto)
    3. Abas / páginas, se houver   (st.navigation ou st.radio, feito pelo painel)
    4. Filtros                      (feitos pelo painel dentro do `with barra_lateral(...)`)
    5. Fonte e Atualizado em        (mesmo visual do card do Hub de Indicadores)

Uso:
    import painel_padrao as pp
    pp.logo("assets/icone.png", "Turnover")
    with pp.barra_lateral(fonte="Neon + Databricks", atualizado_em=datetime(...)):
        st.multiselect(...)
"""
from __future__ import annotations

import contextlib
from datetime import date, datetime
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st

AZUL = "#064D66"
AZUL_ESCURO = "#003244"
AMARELO = "#FAB900"
FUSO = ZoneInfo("America/Sao_Paulo")

_CSS = f"""<style>
[data-testid="stSidebar"] .pp-ola {{ color:{AZUL_ESCURO}; font-size:.95rem; margin:.1rem 0 .35rem; }}
[data-testid="stSidebar"] .pp-dev {{ color:#7A8C96; font-size:.78rem; margin:.1rem 0 .35rem; }}
[data-testid="stSidebar"] .pp-meta {{ background:#F3F6F8; border-radius:10px; padding:.55rem .75rem;
    font-size:.8rem; border-left:4px solid {AMARELO}; margin-top:.4rem; }}
[data-testid="stSidebar"] .pp-meta div {{ display:flex; gap:.5rem; padding:.12rem 0; color:{AZUL_ESCURO}; }}
[data-testid="stSidebar"] .pp-meta span {{ flex:0 0 5.9rem; color:#7A8C96; font-weight:600; font-size:.74rem; white-space:nowrap; }}
</style>"""


@st.cache_resource
def _wordmark(icone: str, titulo: str):
    """Ícone + nome do painel numa imagem só (st.logo aceita só imagem). Mesmo padrão do
    Headcount Total e da Aderência Salarial."""
    try:
        from PIL import Image, ImageDraw, ImageFont
        img = Image.open(icone).convert("RGBA")
        alt = 64
        img = img.resize((int(img.width * alt / img.height), alt))
        fonte = None
        for f in (r"C:\Windows\Fonts\segoeuib.ttf", r"C:\Windows\Fonts\arialbd.ttf",
                  "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
            if Path(f).exists():
                fonte = ImageFont.truetype(f, 34)
                break
        fonte = fonte or ImageFont.load_default(size=34)  # Pillow >= 10.1: fonte escalável, não a de 11px
        caixa = ImageDraw.Draw(Image.new("RGBA", (1, 1))).textbbox((0, 0), titulo, font=fonte)
        larg, alt_txt = caixa[2] - caixa[0], caixa[3] - caixa[1]
        tela = Image.new("RGBA", (img.width + 14 + larg + 4, alt), (0, 0, 0, 0))
        tela.paste(img, (0, 0), img)
        ImageDraw.Draw(tela).text((img.width + 14, (alt - alt_txt) // 2 - caixa[1]), titulo, font=fonte, fill=AZUL)
        return tela
    except Exception:  # noqa: BLE001 — sem PIL/fonte, cai só no ícone
        return None


def logo(icone: str | Path, titulo: str) -> None:
    """Usa assets/logo-wordmark.png (ícone + nome já desenhados) quando existe. Gerar a imagem na
    hora depende das fontes do Windows, que o Streamlit Cloud (Linux) não tem: lá o nome saía
    minúsculo (fonte de emergência de ~11px). Ver a skill padrao-painel-streamlit."""
    icone = Path(icone)
    pronto = icone.parent / "logo-wordmark.png"
    marca = str(pronto) if pronto.exists() else _wordmark(str(icone), titulo)
    st.logo(marca if marca is not None else str(icone), icon_image=str(icone), size="large")


def _conta() -> None:
    usuario = st.session_state.get("auth_user")
    if usuario:
        st.html(f'<div class="pp-ola">Olá, <b>{escape(usuario.get("name") or usuario.get("email", ""))}</b></div>')
        if st.button("Sair", key="pp_sair", width="stretch", icon=":material/logout:"):
            st.session_state["auth_user"] = None
            st.session_state["auth_email"] = None
            st.rerun()
    else:
        st.html('<div class="pp-dev">Modo desenvolvimento · sem login</div>')
    st.divider()


def _formatar(valor) -> str:
    if isinstance(valor, datetime):
        if valor.tzinfo is not None:
            valor = valor.astimezone(FUSO)
        return f"{valor:%d/%m/%Y %H:%M}"
    if isinstance(valor, date):
        return f"{valor:%d/%m/%Y}"
    return str(valor)


def rodape(fonte: str, atualizado_em=None, extra: dict[str, str] | None = None) -> None:
    linhas = {"Fonte": fonte}
    if atualizado_em is not None:
        linhas["Atualizado em"] = _formatar(atualizado_em)
    linhas |= extra or {}
    corpo = "".join(f"<div><span>{escape(k)}</span>{escape(str(v))}</div>" for k, v in linhas.items())
    st.html(f'<div class="pp-meta">{corpo}</div>')


@contextlib.contextmanager
def barra_lateral(fonte: str, atualizado_em=None, extra: dict[str, str] | None = None):
    """Monta a barra lateral no padrão: conta no topo, o conteúdo do `with` (abas e filtros)
    no meio, Fonte/Atualizado em no fim."""
    with st.sidebar:
        st.html(_CSS)
        _conta()
        yield
        st.divider()
        rodape(fonte, atualizado_em, extra)
