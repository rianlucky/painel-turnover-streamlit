"""Painel Turnover — admissões, desligamentos e taxa de turnover (Pacaembu Construtora).

Migrado do dashboard AI/BI do Databricks (especificação em
"ZZ - Prompts Migração Databricks - Streamlit+Neon/Dashboard_Turnover_Streamlit_Spec.md").
Fonte: core.v_turnover_base no Neon (usuário de banco só de leitura). Cálculos em metricas.py.

    streamlit run app.py
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import psycopg2
import streamlit as st

import auth
import metricas as m
import painel_padrao as pp

ASSETS = Path(__file__).resolve().parent / "assets"

AZUL, AMARELO, VERMELHO, VERDE = "#064D66", "#FAB900", "#F02727", "#22C55E"
CINZA, CINZA_ESCURO, BORDA, GRID = "#6B7280", "#1F2937", "#CBD8DE", "#E5EDF1"
AZUL_CLARO = "#8FB8C8"
FONTE = "Nunito"

st.set_page_config(page_title="Turnover · Pacaembu Construtora", page_icon=str(ASSETS / "icone-turnover.png"), layout="wide")

st.html(f"""<style>
.mini {{ background:#fff; border:1px solid {BORDA}; border-radius:10px; overflow:hidden; text-align:center; }}
.mini-rotulo {{ color:{CINZA}; font-size:.72rem; font-weight:600; padding-top:.5rem; text-transform:uppercase; }}
.mini-valor {{ color:{AZUL}; font-size:1.6rem; font-weight:700; padding:.15rem 0 .4rem; }}
.mini-base {{ height:5px; background:{AMARELO}; }}
</style>""")
AJUDA_TAXA = ("Taxa de turnover = (admissões + desligamentos do mês) ÷ 2 ÷ headcount do fim do mês anterior. "
              "O card mostra o mês da data final do período, comparado com o mês anterior.")


# login antes de qualquer dado (mesma tabela acesso.app_users dos outros painéis)
auth.exigir_login()
auth.exigir_acesso_ao_painel("turnover")  # matriz de acessos (acesso.v_permissoes)


# ----------------------------------------------------------------------------- dados

@st.cache_data(ttl=600, show_spinner="Carregando dados…")
def carregar() -> tuple[pd.DataFrame, datetime | None]:
    with psycopg2.connect(st.secrets["neon"]["database_url"], connect_timeout=10) as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM core.v_turnover_base")
        base = pd.DataFrame(cur.fetchall(), columns=[d[0] for d in cur.description])
        cur.execute("SELECT max(concluido_em) FROM ops.v_ultima_carga WHERE schema_nome = 'core' AND tabela = 'fato_funcionario'")
        carga = cur.fetchone()[0]
    return m.preparar(base), carga


def _pct(v, casas=1) -> str:
    return "—" if v is None or pd.isna(v) else f"{v * 100:.{casas}f}%".replace(".", ",")


MESES_PT = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def _mes(s: pd.Series) -> pd.Series:
    d = pd.to_datetime(s)
    return [f"{MESES_PT[x.month - 1]}/{x:%y}" for x in d]


def _registros(df: pd.DataFrame) -> list[dict]:
    """Linhas prontas para o Vega-Lite: datas em texto e NaN como null (dados dentro das camadas
    vão direto para JSON, sem a conversão que o Streamlit faz nos dados do topo)."""
    return json.loads(df.to_json(orient="records", date_format="iso"))


def _mes_txt(d: date) -> str:
    return f"{MESES_PT[d.month - 1]}/{d:%y}"


def _int(v) -> str:
    return "—" if v is None or pd.isna(v) else f"{int(v):,}".replace(",", ".")


# ----------------------------------------------------------------------------- componentes

def mini(rotulo: str, valor: str) -> None:
    st.html(f"""<div class="mini"><div class="mini-rotulo">{rotulo}</div><div class="mini-valor">{valor}</div>
    <div class="mini-base"></div></div>""")


def _config() -> dict:
    return {"view": {"stroke": None}, "font": FONTE,
            "axis": {"labelFont": FONTE, "labelFontSize": 11, "labelColor": CINZA, "domainColor": BORDA,
                     "gridColor": GRID, "tickColor": BORDA, "title": None},
            "legend": {"labelFont": FONTE, "labelFontSize": 11, "labelColor": CINZA_ESCURO, "title": None, "orient": "top"}}


SEM_DADOS = "Sem desligamentos no filtro selecionado."


def _linhas(spec) -> list[dict]:
    """Todas as linhas de dados do spec (no topo e dentro das camadas)."""
    out = []
    if isinstance(spec, dict):
        out += (spec.get("data") or {}).get("values") or []
        for camada in spec.get("layer", []):
            out += _linhas(camada)
    return out


def _sem_dados(spec: dict) -> bool:
    """Nada para desenhar: sem linhas, ou todas as contagens zeradas (donut/funil de uma área sem
    desligados quebraria o gráfico)."""
    linhas = _linhas(spec)
    if not linhas:
        return True
    campos = [c for c in ("desligamentos", "admitidos", "desligamentos_voluntario", "desligamentos_involuntario")
              if c in linhas[0]]
    return bool(campos) and all(not (r.get(c) or 0) for r in linhas for c in campos)


def _json_seguro(linhas: list[dict]) -> list[dict]:
    return json.loads(pd.DataFrame(linhas).to_json(orient="records", date_format="iso")) if linhas else []


def _dados_nas_camadas(spec: dict) -> dict:
    """Leva os dados do topo para cada camada do primeiro nível (em JSON seguro). Com os dados no
    topo e várias camadas, o Streamlit separa os dados do desenho e o navegador às vezes não
    redesenha quando o filtro muda (evolução e donut de motivos, 28/09).
    Um grupo de camadas recebe os dados no próprio nível do grupo — junto com o transform dele
    (ex.: fold das séries); dar dados às camadas internas faria elas ignorarem esse transform."""
    spec = dict(spec)
    topo = spec.pop("data", None)
    if "layer" not in spec:
        if topo is not None:
            spec["data"] = {"values": _json_seguro(topo.get("values", []))}
        return spec
    camadas = []
    for camada in spec["layer"]:
        camada = dict(camada)
        dados = camada.get("data") or topo
        if dados is not None:
            camada["data"] = {"values": _json_seguro(dados.get("values", []))}
        camadas.append(camada)
    spec["layer"] = camadas
    return spec


def grafico(titulo: str, spec: dict, altura: int = 300, aviso: str = SEM_DADOS) -> None:
    st.html(f'<div class="titulo-graf">{titulo}</div>')
    if _sem_dados(spec):
        st.info(aviso, icon=":material/info:")
        return
    spec = _dados_nas_camadas(spec)
    spec = {"$schema": "https://vega.github.io/schema/vega-lite/v5.json", "height": altura, "config": _config(), **spec}
    # key muda junto com os dados: o Streamlit manda os dados separados do desenho e, em gráficos
    # com várias camadas, só trocar os dados às vezes não redesenha — com a key nova, redesenha sempre
    chave = hashlib.md5(json.dumps(spec, sort_keys=True, default=str).encode()).hexdigest()
    st.vega_lite_chart(spec, width="stretch", key=f"graf-{chave}")


def combo_admissoes(ev: pd.DataFrame) -> dict:
    d = _registros(ev.assign(mes=_mes(ev["periodo"]), taxa=ev["taxa_turnover"]))
    x = {"field": "mes", "type": "ordinal", "sort": None, "axis": {"labelAngle": 0}}
    fold = [{"fold": ["admitidos", "desligamentos"], "as": ["serie", "valor"]},
            {"calculate": "datum.serie === 'admitidos' ? 'Admissões' : 'Desligamentos'", "as": "serie_label"}]
    y_barra = {"field": "valor", "type": "quantitative", "axis": {"grid": True, "tickCount": 6}}
    y_taxa = {"field": "taxa", "type": "quantitative", "axis": {"orient": "right", "format": ".1%", "grid": False}}
    # dados dentro de cada grupo de camadas (com dados no topo + camadas aninhadas, o navegador
    # não redesenhava quando o filtro mudava)
    return {"resolve": {"scale": {"y": "independent", "color": "independent"}},
            "layer": [
                {"data": {"values": d}, "transform": fold, "encoding": {"x": x, "xOffset": {"field": "serie_label"}, "y": y_barra}, "layer": [
                    {"mark": {"type": "bar", "cornerRadiusTopLeft": 5, "cornerRadiusTopRight": 5},
                     "encoding": {"color": {"field": "serie_label", "scale": {"domain": ["Admissões", "Desligamentos"], "range": [AZUL, VERMELHO]}}}},
                    {"mark": {"type": "text", "dy": -6, "fontSize": 10, "fontWeight": 600, "baseline": "bottom", "color": CINZA_ESCURO},
                     "encoding": {"text": {"field": "valor"}}},
                ]},
                {"data": {"values": d}, "encoding": {"x": x, "y": y_taxa}, "layer": [
                    {"mark": {"type": "line", "strokeWidth": 2.5, "interpolate": "monotone", "color": AMARELO, "point": {"filled": True, "size": 40}},
                     "encoding": {"color": {"datum": "Taxa de Turnover", "scale": {"range": [AMARELO]}}}},
                    {"mark": {"type": "text", "dy": -12, "fontSize": 10, "fontWeight": 700, "color": "#9A7400"},
                     "encoding": {"text": {"field": "taxa", "format": ".1%"}}},
                ]},
            ]}


def combo_voluntario(ev: pd.DataFrame) -> dict:
    d = _registros(ev.assign(mes=_mes(ev["periodo"]), taxa=ev["taxa_turnover_voluntario"]))
    x = {"field": "mes", "type": "ordinal", "sort": None, "axis": {"labelAngle": 0}}
    return {"resolve": {"scale": {"y": "independent", "color": "independent"}},
            "layer": [
                {"data": {"values": d}, "layer": [
                    {"transform": [{"fold": ["desligamentos_involuntario", "desligamentos_voluntario"], "as": ["serie", "valor"]},
                                   {"calculate": "datum.serie === 'desligamentos_voluntario' ? 'Voluntário' : 'Involuntário'", "as": "tipo"}],
                     "mark": {"type": "bar", "cornerRadiusTopLeft": 5, "cornerRadiusTopRight": 5},
                     "encoding": {"x": x, "y": {"field": "valor", "type": "quantitative", "stack": "zero", "axis": {"grid": True}, "title": None},
                                  "color": {"field": "tipo", "scale": {"domain": ["Voluntário", "Involuntário"], "range": [AMARELO, AZUL]}},
                                  "order": {"field": "serie", "sort": "ascending"}}},
                    {"mark": {"type": "text", "dy": -6, "fontSize": 10, "fontWeight": 700, "baseline": "bottom", "color": CINZA_ESCURO},
                     "encoding": {"x": x, "y": {"field": "desligamentos", "type": "quantitative"}, "text": {"field": "desligamentos"}}},
                ]},
                {"data": {"values": d},
                 "encoding": {"x": x, "y": {"field": "taxa", "type": "quantitative", "axis": {"orient": "right", "format": ".1%", "grid": False}}},
                 "layer": [
                    {"mark": {"type": "line", "strokeWidth": 2.5, "interpolate": "monotone", "color": VERMELHO, "point": {"filled": True, "size": 40}},
                     "encoding": {"color": {"datum": "Taxa Turnover Voluntário", "scale": {"range": [VERMELHO]}}}},
                    {"mark": {"type": "text", "dy": 14, "fontSize": 10, "fontWeight": 700, "color": VERMELHO},
                     "encoding": {"text": {"field": "taxa", "format": ".1%"}}},
                ]},
            ]}


def barras_area(tab: pd.DataFrame, cor: str, cor_texto_dentro: str) -> dict:
    y = {"field": "area", "type": "nominal", "sort": "-x", "axis": {"labelLimit": 220}}
    xq = {"field": "taxa_turnover", "type": "quantitative", "axis": {"format": ".0%"}}
    return {"data": {"values": tab.to_dict("records")}, "layer": [
        {"mark": {"type": "bar", "cornerRadiusEnd": 6, "color": cor}, "encoding": {"y": y, "x": xq}},
        {"mark": {"type": "text", "align": "left", "dx": 4, "fontSize": 11, "fontWeight": 600, "color": CINZA_ESCURO},
         "encoding": {"y": y, "x": xq, "text": {"field": "taxa_turnover", "format": ".1%"}}},
    ], "padding": {"right": 40}}


def donut(tab: pd.DataFrame, campo: str, dominio: list[str], cores: list[str]) -> dict:
    total = tab["desligamentos"].sum()
    # a mesma ordem explícita nas duas camadas: sem isso as fatias seguem a ordem das cores e o
    # texto a ordem dos dados, e o percentual cai na fatia errada
    ordem = {v: i for i, v in enumerate(dominio)}
    d = tab.assign(pct=tab["desligamentos"] / total if total else 0,
                   ordem=tab[campo].map(ordem).fillna(len(dominio))).to_dict("records")
    return {"data": {"values": d}, "layer": [
        {"mark": {"type": "arc", "innerRadius": 48, "outerRadius": 82, "padAngle": 0.025, "cornerRadius": 4},
         "encoding": {"theta": {"field": "desligamentos", "type": "quantitative", "stack": True},
                      "order": {"field": "ordem", "type": "quantitative"},
                      "color": {"field": campo, "scale": {"domain": dominio, "range": cores}, "legend": {"orient": "bottom", "columns": 1}}}},
        {"mark": {"type": "text", "radius": 65, "fontSize": 12, "fontWeight": 700, "color": "#FFFFFF"},
         "encoding": {"theta": {"field": "desligamentos", "type": "quantitative", "stack": True},
                      "order": {"field": "ordem", "type": "quantitative"},
                      "text": {"field": "pct", "format": ".0%"}}},
    ], "view": {"stroke": None}}


def funil(tab: pd.DataFrame, campo: str, ordem: list[str], cor: str, cor_texto: str) -> dict:
    total = tab["desligamentos"].sum()
    d = tab.assign(lo=-tab["desligamentos"] / 2, hi=tab["desligamentos"] / 2,
                   rotulo=[f"{int(v)} ({v / total:.0%})" if total else "" for v in tab["desligamentos"]]).to_dict("records")
    y = {"field": campo, "type": "nominal", "sort": ordem, "axis": {"labelLimit": 160, "ticks": False, "domain": False}}
    return {"data": {"values": d}, "layer": [
        {"mark": {"type": "bar", "cornerRadius": 4, "color": cor},
         "encoding": {"y": y, "x": {"field": "lo", "type": "quantitative", "axis": None}, "x2": {"field": "hi"}}},
        {"mark": {"type": "text", "align": "left", "dx": 5, "fontSize": 10, "fontWeight": 600, "color": CINZA_ESCURO},
         "encoding": {"y": y, "x": {"field": "hi", "type": "quantitative"}, "text": {"field": "rotulo"}}},
    ], "padding": {"right": 55}}


def top_diretorias(des: pd.DataFrame) -> dict:
    tab = des.groupby(["diretoria", "tipo_desligamento"])["id_funcionario"].nunique().rename("desligamentos").reset_index()
    top5 = tab.groupby("diretoria")["desligamentos"].sum().nlargest(5).index
    tab = tab[tab["diretoria"].isin(top5)]
    tot = tab.groupby("diretoria")["desligamentos"].sum().rename("total").reset_index()
    y = {"field": "diretoria", "type": "nominal", "sort": list(tot.sort_values("total", ascending=False)["diretoria"]), "axis": {"labelLimit": 220}}
    return {"layer": [
        {"data": {"values": tab.to_dict("records")}, "mark": {"type": "bar", "cornerRadiusEnd": 4},
         "encoding": {"y": y, "x": {"field": "desligamentos", "type": "quantitative", "stack": "zero"},
                      "color": {"field": "tipo_desligamento", "scale": {"domain": ["Voluntário", "Involuntário"], "range": [AMARELO, AZUL]}}}},
        {"data": {"values": tot.to_dict("records")}, "mark": {"type": "text", "align": "left", "dx": 6, "fontWeight": 700, "color": CINZA_ESCURO},
         "encoding": {"y": y, "x": {"field": "total", "type": "quantitative"}, "text": {"field": "total"}}},
    ]}


def barras_taxa(tab: pd.DataFrame, campo: str, cor: str, ordem: list[str] | None = None, taxa: str = "taxa_turnover") -> dict:
    """Taxa de turnover por grupo (nível, frente, raça/cor, escolaridade…), na ordem dada, com o
    headcount médio do grupo no rótulo do eixo."""
    d = tab.assign(rotulo=[f"{g} ({_int(round(h))})" for g, h in zip(tab[campo], tab["headcount_medio"])],
                   txt=[_pct(t, 1) for t in tab[taxa]])
    ordem_y = [f"{g} ({_int(round(h))})" for g, h in zip(tab[campo], tab["headcount_medio"])]
    y = {"field": "rotulo", "type": "nominal", "sort": ordem_y if ordem else "-x", "axis": {"labelLimit": 260, "title": None}}
    xq = {"field": taxa, "type": "quantitative", "axis": {"format": ".0%", "grid": True, "title": None}}
    return {"data": {"values": _registros(d)}, "layer": [
        {"mark": {"type": "bar", "cornerRadiusEnd": 5, "color": cor},
         "encoding": {"y": y, "x": xq, "tooltip": [{"field": campo, "title": " "}, {"field": "txt", "title": "Taxa"},
                                                   {"field": "desligamentos", "title": "Desligamentos"},
                                                   {"field": "headcount_medio", "title": "Headcount médio"}]}},
        {"mark": {"type": "text", "align": "left", "dx": 4, "fontSize": 11, "fontWeight": 700, "color": CINZA_ESCURO},
         "encoding": {"y": y, "x": xq, "text": {"field": "txt"}}},
    ], "padding": {"right": 46}}


def combo_experiencia(ev: pd.DataFrame) -> dict:
    """Saídas em experiência por mês (barras: voluntárias e involuntárias) e o % delas sobre todas as saídas."""
    d = _registros(ev.assign(mes=_mes(ev["periodo"]), involuntario=ev["experiencia"] - ev["experiencia_voluntario"]))
    x = {"field": "mes", "type": "ordinal", "sort": None, "axis": {"labelAngle": 0}}
    return {"resolve": {"scale": {"y": "independent", "color": "independent"}},
            "layer": [
                {"data": {"values": d}, "layer": [
                    {"transform": [{"fold": ["involuntario", "experiencia_voluntario"], "as": ["serie", "valor"]},
                                   {"calculate": "datum.serie === 'experiencia_voluntario' ? 'Pediu para sair' : 'Desligado pela empresa'", "as": "tipo"}],
                     "mark": {"type": "bar", "cornerRadiusTopLeft": 5, "cornerRadiusTopRight": 5},
                     "encoding": {"x": x, "y": {"field": "valor", "type": "quantitative", "stack": "zero", "axis": {"grid": True}, "title": None},
                                  "color": {"field": "tipo", "scale": {"domain": ["Pediu para sair", "Desligado pela empresa"], "range": [AMARELO, AZUL]}},
                                  "order": {"field": "serie", "sort": "ascending"}}},
                    {"mark": {"type": "text", "dy": -6, "fontSize": 10, "fontWeight": 700, "baseline": "bottom", "color": CINZA_ESCURO},
                     "encoding": {"x": x, "y": {"field": "experiencia", "type": "quantitative"}, "text": {"field": "experiencia"}}},
                ]},
                {"data": {"values": d},
                 "encoding": {"x": x, "y": {"field": "pct", "type": "quantitative", "axis": {"orient": "right", "format": ".0%", "grid": False}}},
                 "layer": [
                    {"mark": {"type": "line", "strokeWidth": 2.5, "interpolate": "monotone", "color": VERMELHO, "point": {"filled": True, "size": 40}},
                     "encoding": {"color": {"datum": "% das saídas do mês", "scale": {"range": [VERMELHO]}}}},
                    {"mark": {"type": "text", "dy": -12, "fontSize": 10, "fontWeight": 700, "color": VERMELHO},
                     "encoding": {"text": {"field": "pct", "format": ".0%"}}},
                ]},
            ]}


def curva_retencao(t: pd.DataFrame) -> dict:
    """% de cada turma que continua 3, 6 e 12 meses depois da admissão (uma linha por marco)."""
    linhas = []
    for _, r in t.iterrows():
        for h in m.HORIZONTES_RETENCAO:
            v = r[f"ret_{h}"]
            if pd.notna(v):
                linhas.append({"turma": _mes_txt(r["turma"]), "marco": f"Após {h} meses", "pct": float(v), "txt": _pct(v, 0),
                               "admitidos": int(r["admitidos"])})
    x = {"field": "turma", "type": "ordinal", "sort": [_mes_txt(p) for p in t["turma"]], "axis": {"labelAngle": 0, "title": "Mês de admissão"}}
    y = {"field": "pct", "type": "quantitative", "scale": {"domain": [0, 1]}, "axis": {"format": ".0%", "grid": True, "title": None}}
    cor = {"field": "marco", "scale": {"domain": [f"Após {h} meses" for h in m.HORIZONTES_RETENCAO], "range": [AZUL_CLARO, AZUL, AMARELO]},
           "legend": {"orient": "top", "title": None}}
    return {"layer": [
        {"data": {"values": linhas}, "mark": {"type": "line", "strokeWidth": 2.5, "point": {"size": 40, "filled": True}},
         "encoding": {"x": x, "y": y, "color": cor, "tooltip": [{"field": "turma", "title": "Turma"}, {"field": "marco", "title": " "},
                                                               {"field": "txt", "title": "Continuam"}, {"field": "admitidos", "title": "Admitidos"}]}},
        {"data": {"values": linhas}, "mark": {"type": "text", "dy": -10, "fontSize": 9, "fontWeight": 700},
         "encoding": {"x": x, "y": y, "text": {"field": "txt"}, "color": cor}},
    ]}


def tabela_retencao(t: pd.DataFrame):
    """Turmas x marcos, com cor do vermelho (retém pouco) ao verde (retém muito)."""
    tab = t.assign(Turma=[_mes_txt(p) for p in t["turma"]]).rename(columns={"admitidos": "Admitidos"})
    tab = tab[["Turma", "Admitidos"] + [f"ret_{h}" for h in m.HORIZONTES_RETENCAO]]
    tab.columns = ["Turma", "Admitidos"] + [f"Após {h} meses" for h in m.HORIZONTES_RETENCAO]

    def cor(v):
        if v is None or pd.isna(v):
            return "color:#9AA3AE"
        t_ = max(0.0, min(1.0, (v - .4) / .55))
        r, g, b = (int(0xF0 + (0xD8 - 0xF0) * t_), int(0xC6 + (0xF0 - 0xC6) * t_), int(0xC6 + (0xD8 - 0xC6) * t_))
        return f"background-color:#{r:02X}{g:02X}{b:02X}"

    return tab.style.format({c: (lambda v: "ainda sem idade" if v is None or pd.isna(v) else _pct(v, 0))
                             for c in tab.columns[2:]}).map(cor, subset=list(tab.columns[2:]))


# ----------------------------------------------------------------------------- página

try:
    df, carga = carregar()
except Exception as exc:  # noqa: BLE001
    st.error("Não consegui ler a base do Neon. Confira o bloco [neon] em .streamlit/secrets.toml.", icon=":material/error:")
    st.caption(f"{type(exc).__name__}")
    st.stop()

ref = m.data_referencia(df)
pp.logo(ASSETS / "icone-turnover.png", "Turnover")
navegacao = st.navigation([
    st.Page(lambda: pagina_geral(), title="Visão geral", icon=":material/dashboard:", url_path="visao-geral", default=True),
    st.Page(lambda: pagina_voluntario(), title="Turnover voluntário", icon=":material/logout:", url_path="voluntario"),
    st.Page(lambda: pagina_experiencia(), title="Período de experiência", icon=":material/hourglass_top:", url_path="experiencia"),
    st.Page(lambda: pagina_retencao(), title="Retenção por turma", icon=":material/groups:", url_path="retencao"),
    st.Page(lambda: pagina_perfil(), title="Perfil das saídas", icon=":material/query_stats:", url_path="perfil"),
])

# Barra lateral no padrão da Central (painel_padrao.py). Filtros de pessoa (frente, diretoria, área,
# centro de custo, família, nível, sexo, grupo) valem para tudo; tempo de casa só existe no desligamento
# e vale para todas as contagens de desligamento (headcount e admissões não mudam).
opcoes = lambda c: sorted(df[c].dropna().unique())  # noqa: E731
with pp.barra_lateral(fonte="Neon + Databricks", atualizado_em=carga):
    st.markdown("**Período**")
    _padrao = (m.inicio_padrao(ref), ref)
    _escolha = st.date_input("Período", value=_padrao, min_value=date(2020, 1, 1), max_value=ref,
                             format="DD/MM/YYYY", label_visibility="collapsed")
    # enquanto a pessoa escolhe só a primeira data, o widget devolve uma data só
    per_ini, per_fim = (_escolha if isinstance(_escolha, (tuple, list)) and len(_escolha) == 2 else _padrao)
    estagiarios = st.segmented_control("Estagiários", ["Incluir", "Tirar"], default="Incluir",
                                       help="O fim do estágio é uma saída prevista e costuma inflar a taxa. "
                                            "“Tirar” exclui estagiários de todas as contagens (headcount, admissões e desligamentos).") or "Incluir"
    st.markdown("**Filtros**")
    sel = {
        "frente": st.multiselect("Frente", [f for f in m.ORDEM_FRENTE if f in set(df["frente"])], placeholder="Todas"),
        "diretoria": st.multiselect("Diretoria", opcoes("diretoria"), placeholder="Todas"),
        "area": st.multiselect("Área", opcoes("area"), placeholder="Todas"),
        "nome_centro_custo": st.multiselect("Centro de custo", opcoes("nome_centro_custo"), placeholder="Todos"),
        "familia_cargo": st.multiselect("Família de cargo", opcoes("familia_cargo"), placeholder="Todas"),
        "nivel": st.multiselect("Nível", [n for n in m.ORDEM_NIVEL if n in set(df["nivel"])] +
                                sorted(set(df["nivel"]) - set(m.ORDEM_NIVEL)), placeholder="Todos"),
        "sexo": st.multiselect("Sexo", opcoes("sexo"), placeholder="Todos"),
    }
    st.markdown("**Desligamentos**")
    sel_tempo = st.multiselect("Tempo de casa", list(reversed(m.ORDEM_TEMPO_CASA)), placeholder="Todos",
                               help="Tempo de casa na data do desligamento.")
    st.caption("Tempo de casa filtra só os desligamentos; headcount e admissões seguem inteiros.")

# o período vai até a data final escolhida (nunca depois da data da base)
ref_p = min(per_fim, ref)
rotulos = {"frente": "Frente", "diretoria": "Diretoria", "area": "Área", "nome_centro_custo": "Centro de custo",
           "familia_cargo": "Família de cargo", "nivel": "Nível", "sexo": "Sexo"}
titulo = "Turnover" if navegacao.title == "Visão geral" else navegacao.title
pp.cabecalho(titulo, atualizado_em=carga,
             filtros={"Período": f"{per_ini:%d/%m/%Y} a {ref_p:%d/%m/%Y}", **{rotulos[c]: v for c, v in sel.items()},
                      "Estagiários": "fora" if estagiarios == "Tirar" else None,
                      "Tempo de casa (desligamentos)": sel_tempo},
             legenda=f"Cards do mês de {_mes_txt(ref_p)} (até {ref_p:%d/%m}) · dados de {ref:%d/%m/%Y} · "
                     "recontratação em até 10 dias não conta como desligamento nem admissão")

base = df if estagiarios == "Incluir" else df[~df["estagiario"]]
for col, vals in sel.items():
    if vals:
        base = base[base[col].isin(vals)]
base = m.filtrar_desligamentos(base, faixas_tempo_casa=sel_tempo)

k = m.kpis(base, ref_p)
des12 = m.desligados_periodo(base, per_ini, ref_p)
ev = m.evolucao_mensal(base, ref_p, inicio=per_ini)


# ================================================================ visão geral
def pagina_geral() -> None:
    pp.secao("Admissões, desligamentos e taxa de turnover")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        pp.kpi("Headcount ativo", _int(k["headcount"]), f"em {ref_p:%d/%m/%Y}")
    with c2:
        delta = k["desligamentos_atual"] - k["desligamentos_anterior"]
        pp.kpi("Desligamentos no mês", _int(k["desligamentos_atual"]),
               "Estável" if delta == 0 else f"{'+' if delta > 0 else '−'} {abs(delta)} vs mês ant.", VERMELHO if delta > 0 else VERDE if delta < 0 else CINZA)
    with c3:
        ta, tb = k["taxa_turnover_atual"], k["taxa_turnover_anterior"]
        dif = (ta - tb) * 100 if ta is not None and tb is not None else 0  # em pontos percentuais
        pp.kpi("Taxa de turnover", _pct(ta, 2), "Estável" if abs(dif) < 0.05 else f"{'+' if dif > 0 else '−'} {abs(dif):.1f}".replace(".", ",") + " pp vs mês ant.",
               VERMELHO if dif >= 0.05 else VERDE if dif <= -0.05 else CINZA, ajuda=AJUDA_TAXA)
    with c4:
        pp.kpi("Tempo médio de casa", m.tempo_medio_casa(des12), "desligados no período", CINZA)
    if estagiarios == "Incluir" and base["estagiario"].any():
        k_sem = m.kpis(base[~base["estagiario"]], ref_p)
        st.html(f'<div class="nota">Sem estagiários, a taxa do mês seria {_pct(k_sem["taxa_turnover_atual"], 2)} '
                f'({_int(k["desligamentos_atual"] - k_sem["desligamentos_atual"])} dos desligamentos do mês são de estagiários). '
                'Use “Estagiários: Tirar” na barra lateral para ver o painel inteiro sem eles.</div>')

    grafico("Evolução de admissões, desligamentos e taxa de turnover", combo_admissoes(ev), 320)

    g1, g2, g3, g4 = st.columns([4, 2, 3, 3])
    with g1:
        tab = m.turnover_por_area(base, ref_p, inicio=per_ini)
        if tab.empty:
            st.info("Sem áreas com headcount suficiente no filtro.", icon=":material/info:")
        else:
            grafico("Top 10 taxa de turnover por área (no período)", barras_area(tab, AZUL, "#FFFFFF"), 290)
    with g2:
        grafico("Desligamentos por sexo", donut(m.contagem(des12, "sexo"), "sexo", ["Masculino", "Feminino"], [AZUL, AMARELO]), 290)
    with g3:
        grafico("Desligamentos por tempo de casa", funil(m.contagem(des12, "faixa_tempo_casa"), "faixa_tempo_casa", m.ORDEM_TEMPO_CASA, AZUL, "#FFFFFF"), 290)
    with g4:
        grafico("Desligamentos por faixa etária", funil(m.contagem(des12, "faixa_etaria"), "faixa_etaria", m.ORDEM_FAIXA_ETARIA, AZUL, "#FFFFFF"), 290)

    pp.secao("Resumo por diretoria e área")
    resumo = m.resumo_diretoria_area(des12)
    if resumo.empty:
        st.info(SEM_DADOS, icon=":material/info:")
    else:
        st.dataframe(resumo, hide_index=True, width="stretch",
                     column_config={"diretoria": "Diretoria", "area": "Área",
                                    "Voluntário": st.column_config.NumberColumn(format="%d"),
                                    "Involuntário": st.column_config.NumberColumn(format="%d"),
                                    "Total": st.column_config.NumberColumn(format="%d")})
    st.caption(f"Desligamentos no período · {_int(des12['id_funcionario'].nunique())} pessoas "
               "(quem saiu de duas áreas no período aparece nas duas linhas)")


# ================================================================ voluntário
def pagina_voluntario() -> None:
    with st.container(horizontal=True, vertical_alignment="center"):
        pp.secao("Turnover voluntário")
        motivo = st.selectbox("Motivo", ["Todos"] + sorted(des12["motivo"].dropna().unique()), label_visibility="collapsed",
                              help="Filtra todos os indicadores desta página.", width=260)
    base_vol = base if motivo == "Todos" else m.filtrar_desligamentos(base, motivos=[motivo])
    ev_vol = ev if motivo == "Todos" else m.evolucao_mensal(base_vol, ref_p, inicio=per_ini)
    des_m = m.desligados_periodo(base_vol, per_ini, ref_p)

    hc_med = ev_vol["headcount_anterior"].mean()
    c = st.columns(3)
    with c[0]:
        pp.kpi("Turnover voluntário médio/mês", _pct(ev_vol["desligamentos_voluntario"].sum() / hc_med / len(ev_vol) if hc_med else None),
               "pedidos de demissão ÷ headcount", ajuda="Média mensal de (pedidos de demissão ÷ headcount do fim do mês anterior) no período.")
    with c[1]:
        pp.kpi("Desligados voluntários", _int(des_m.loc[des_m["voluntario"], "id_funcionario"].nunique()), "no período")
    with c[2]:
        pp.kpi("Total de desligados", _int(des_m["id_funcionario"].nunique()), "no período")
    grafico("Evolução dos desligamentos por tipo e taxa de turnover voluntário", combo_voluntario(ev_vol), 330)

    w1, w2, w3, w4 = st.columns([2, 4, 3, 3])
    with w1:
        grafico("Motivos de desligamento", donut(m.contagem(des_m, "tipo_desligamento"), "tipo_desligamento", ["Voluntário", "Involuntário"], [AMARELO, AZUL]), 290)
    with w2:
        grafico("Top 5 desligamentos por diretoria", top_diretorias(des_m), 290)
    with w3:
        tabv = m.turnover_por_area(base_vol, ref_p, somente_voluntario=True, inicio=per_ini)
        if tabv.empty:
            st.info("Sem áreas com headcount suficiente no filtro.", icon=":material/info:")
        else:
            grafico("Top 10 taxa de turnover voluntário por área", barras_area(tabv, AMARELO, AZUL), 290)
    with w4:
        vol = des_m[des_m["voluntario"]]
        grafico("Voluntários por tempo de casa", funil(m.contagem(vol, "faixa_tempo_casa"), "faixa_tempo_casa", m.ORDEM_TEMPO_CASA, AMARELO, AZUL), 290)

    pp.secao("Cargos com mais pedidos de demissão")
    cv = m.cargos_voluntarios(des_m)
    if cv.empty:
        st.info("Nenhum cargo com 3 ou mais pedidos de demissão no filtro.", icon=":material/info:")
    else:
        st.dataframe(cv, hide_index=True, width="stretch",
                     column_config={"cargo": st.column_config.TextColumn("Cargo", width="large"),
                                    "voluntarios": st.column_config.NumberColumn("Pedidos de demissão", format="%d"),
                                    "desligamentos": st.column_config.NumberColumn("Total de saídas", format="%d"),
                                    "pct_voluntario": st.column_config.ProgressColumn("% voluntário", format="percent", min_value=0, max_value=1),
                                    "tempo_medio": "Tempo médio de casa (de quem pediu)"})
        st.html('<div class="nota">Cargos com pelo menos 3 pedidos de demissão no período, do que mais perde gente por vontade própria '
                'para o que menos. Tempo de casa baixo = saída cedo, sinal de problema de atração ou integração.</div>')


# ================================================================ período de experiência
def pagina_experiencia() -> None:
    pp.secao("Saídas no período de experiência (até 90 dias de casa)")
    exp = m.saidas_experiencia(des12)
    co = m.coorte_experiencia(base, per_ini, ref_p)
    c = st.columns(4)
    with c[0]:
        pp.kpi("Saídas em experiência", _int(len(exp)), f"{_pct(len(exp) / len(des12) if len(des12) else None)} de todas as saídas")
    with c[1]:
        pp.kpi("De cada 100 admitidos", "—" if co["taxa"] is None else f"{co['taxa'] * 100:.0f}".replace(".", ","),
               f"saem antes dos 90 dias ({_int(co['sairam'])} de {_int(co['admitidos'])})",
               VERMELHO if (co["taxa"] or 0) >= .15 else CINZA,
               ajuda=f"Admitidos de {per_ini:%d/%m/%Y} até {co['ate']:%d/%m/%Y} (quem já completaria 90 dias de casa na data final) "
                     "e quantos saíram antes disso.")
    with c[2]:
        vol = int(exp["voluntario"].sum())
        pp.kpi("Pediram para sair", _pct(vol / len(exp) if len(exp) else None), f"{_int(vol)} das saídas em experiência")
    with c[3]:
        pp.kpi("Desligados pela empresa", _pct((len(exp) - vol) / len(exp) if len(exp) else None),
               f"{_int(len(exp) - vol)} das saídas em experiência")
    grafico("Saídas em experiência por mês e o % delas sobre todas as saídas", combo_experiencia(m.evolucao_experiencia(base, per_ini, ref_p)), 320)

    e1, e2 = st.columns(2)
    with e1:
        t = m.contagem(exp, "area").head(10).rename(columns={"desligamentos": "saidas"})
        if t.empty:
            st.info("Sem saídas em experiência no filtro.", icon=":material/info:")
        else:
            grafico("Áreas com mais saídas em experiência",
                    {"data": {"values": _registros(t)}, "layer": [
                        {"mark": {"type": "bar", "cornerRadiusEnd": 5, "color": AZUL},
                         "encoding": {"y": {"field": "area", "type": "nominal", "sort": "-x", "axis": {"labelLimit": 240, "title": None}},
                                      "x": {"field": "saidas", "type": "quantitative", "axis": None}}},
                        {"mark": {"type": "text", "align": "left", "dx": 4, "fontWeight": 700, "color": CINZA_ESCURO},
                         "encoding": {"y": {"field": "area", "type": "nominal", "sort": "-x"}, "x": {"field": "saidas", "type": "quantitative"},
                                      "text": {"field": "saidas"}}}], "padding": {"right": 30}}, 320)
    with e2:
        t = m.contagem(exp, "cargo").head(10).rename(columns={"desligamentos": "saidas"})
        if t.empty:
            st.info("Sem saídas em experiência no filtro.", icon=":material/info:")
        else:
            grafico("Cargos com mais saídas em experiência",
                    {"data": {"values": _registros(t)}, "layer": [
                        {"mark": {"type": "bar", "cornerRadiusEnd": 5, "color": AMARELO},
                         "encoding": {"y": {"field": "cargo", "type": "nominal", "sort": "-x", "axis": {"labelLimit": 240, "title": None}},
                                      "x": {"field": "saidas", "type": "quantitative", "axis": None}}},
                        {"mark": {"type": "text", "align": "left", "dx": 4, "fontWeight": 700, "color": CINZA_ESCURO},
                         "encoding": {"y": {"field": "cargo", "type": "nominal", "sort": "-x"}, "x": {"field": "saidas", "type": "quantitative"},
                                      "text": {"field": "saidas"}}}], "padding": {"right": 30}}, 320)
    st.html('<div class="nota">Período de experiência = até 90 dias de casa (prazo máximo do contrato de experiência na CLT). '
            'Saída cedo costuma apontar problema de recrutamento (perfil) ou de integração (primeiras semanas).</div>')


# ================================================================ retenção
def pagina_retencao() -> None:
    pp.secao("Quanto de cada turma de contratação continua na empresa")
    rc = m.retencao_coortes(base, ref_p)
    if rc.empty:
        st.info("Sem admissões nos últimos 18 meses no filtro.", icon=":material/info:")
        st.stop()
    c = st.columns(3)
    for col, h in zip(c, m.HORIZONTES_RETENCAO):
        validas = rc[rc[f"ret_{h}"].notna()]
        media = (validas[f"ret_{h}"] * validas["admitidos"]).sum() / validas["admitidos"].sum() if len(validas) else None
        with col:
            pp.kpi(f"Continuam após {h} meses", _pct(media, 0), f"média de {_int(len(validas))} turmas (ponderada)",
                   ajuda=f"De cada 100 admitidos, quantos continuam na empresa {h} meses depois da admissão. Média das turmas "
                         f"que já têm {h} meses, ponderada pelo número de admitidos.")
    grafico("Retenção por turma: % que continua 3, 6 e 12 meses depois", curva_retencao(rc), 330)
    st.dataframe(tabela_retencao(rc), hide_index=True, width="stretch", height=38 + 35 * len(rc))
    st.html('<div class="nota">Turma = mês de admissão (últimos 18 meses; admissões reais, sem recontratação em até 10 dias). '
            '“Ainda sem idade” = a turma ainda não completou aquele marco. Os filtros valem aqui; o período da barra lateral não '
            '(a retenção precisa do histórico).</div>')


# ================================================================ perfil das saídas
def pagina_perfil() -> None:
    with st.container(horizontal=True, vertical_alignment="center"):
        pp.secao("Onde o turnover se concentra")
        tipo = st.segmented_control("Taxa", ["Turnover total", "Só voluntário"], default="Turnover total",
                                    label_visibility="collapsed", key="tipo_perfil") or "Turnover total"
    so_vol = tipo == "Só voluntário"
    cor = AMARELO if so_vol else AZUL
    blocos = [("nivel", "Por nível de gerenciamento", m.ORDEM_NIVEL), ("frente", "Por frente", m.ORDEM_FRENTE),
              ("raca_cor", "Por raça/cor", m.ORDEM_RACA), ("escolaridade_grupo", "Por escolaridade", m.ORDEM_ESCOLARIDADE)]
    for par in (blocos[:2], blocos[2:]):
        cols = st.columns(2)
        for col, (campo, titulo_g, ordem) in zip(cols, par):
            with col:
                t = m.turnover_por(base, campo, ref_p, per_ini, somente_voluntario=so_vol, ordem=ordem)
                t = t[t[campo] != m.NAO_INFORMADO]
                if t.empty:
                    st.html(f'<div class="titulo-graf">{titulo_g}</div>')
                    st.info("Sem grupos com headcount suficiente no filtro.", icon=":material/info:")
                else:
                    grafico(titulo_g, barras_taxa(t, campo, cor, ordem), max(220, 46 * len(t)))
    pp.secao("Vínculo")
    t = m.turnover_por(base, "vinculo", ref_p, per_ini, somente_voluntario=so_vol)
    if not t.empty:
        grafico("Por vínculo (estagiários, experiência, prazo determinado…)", barras_taxa(t, "vinculo", cor), max(200, 46 * len(t)))
    st.html('<div class="nota">Taxa no período = (desligamentos + admissões) ÷ 2 ÷ headcount médio do grupo (“Só voluntário”: pedidos '
            'de demissão ÷ headcount médio). Entre parênteses, o headcount médio. Grupos com menos de 10 pessoas em média ficam de fora. '
            'Nível agrupa as variações (Gerente inclui Gerente de Vendas; Gerente Executivo, os de Obras). A taxa soma o período '
            'inteiro — com 12 meses, 80% quer dizer que o grupo trocou quase uma vez o próprio tamanho.</div>')


navegacao.run()
