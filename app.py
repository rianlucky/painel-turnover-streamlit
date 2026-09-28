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

import metricas as m
import painel_padrao as pp

ASSETS = Path(__file__).resolve().parent / "assets"

AZUL, AMARELO, VERMELHO, VERDE = "#064D66", "#FAB900", "#F02727", "#22C55E"
CINZA, CINZA_ESCURO, BORDA, GRID = "#6B7280", "#1F2937", "#CBD8DE", "#E5EDF1"
FONTE = "Inter"

st.set_page_config(page_title="Turnover · Pacaembu Construtora", page_icon=str(ASSETS / "icone-turnover.png"), layout="wide")

st.html(f"""<style>
.kpi {{ background:#fff; border:1px solid {BORDA}; border-radius:10px; overflow:hidden; height:100%; }}
.kpi-topo {{ background:{AZUL}; color:#fff; font-weight:700; font-size:.78rem; letter-spacing:.04em; padding:.45rem .85rem; }}
.kpi-valor {{ color:{CINZA_ESCURO}; font-size:1.9rem; font-weight:700; text-align:center; padding:.7rem 0 .1rem; }}
.kpi-delta {{ text-align:center; font-size:.8rem; font-weight:600; min-height:1.2rem; padding-bottom:.55rem; }}
.kpi-base {{ height:7px; background:{AMARELO}; }}
.mini {{ background:#fff; border:1px solid {BORDA}; border-radius:10px; overflow:hidden; text-align:center; }}
.mini-rotulo {{ color:{CINZA}; font-size:.72rem; font-weight:600; padding-top:.5rem; text-transform:uppercase; }}
.mini-valor {{ color:{AZUL}; font-size:1.6rem; font-weight:700; padding:.15rem 0 .4rem; }}
.mini-base {{ height:5px; background:{AMARELO}; }}
.secao {{ color:{AZUL}; font-weight:700; font-size:1.05rem; border-bottom:3px solid {AMARELO};
          display:inline-block; padding-bottom:.15rem; margin:.4rem 0 .2rem; }}
.titulo-graf {{ color:{CINZA_ESCURO}; font-weight:600; font-size:.92rem; margin-bottom:-.4rem; }}
</style>""")


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
    return f"{int(v):,}".replace(",", ".")


# ----------------------------------------------------------------------------- componentes

def kpi(rotulo: str, valor: str, delta: str = "", cor_delta: str = CINZA) -> None:
    st.html(f"""<div class="kpi"><div class="kpi-topo">{rotulo}</div><div class="kpi-valor">{valor}</div>
    <div class="kpi-delta" style="color:{cor_delta}">{delta}</div><div class="kpi-base"></div></div>""")


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


# ----------------------------------------------------------------------------- página

try:
    df, carga = carregar()
except Exception as exc:  # noqa: BLE001
    st.error("Não consegui ler a base do Neon. Confira o bloco [neon] em .streamlit/secrets.toml.", icon=":material/error:")
    st.caption(f"{type(exc).__name__}")
    st.stop()

ref = m.data_referencia(df)
pp.logo(ASSETS / "icone-turnover.png", "Turnover")
with st.container(horizontal=True, vertical_alignment="bottom"):
    st.title("Turnover", anchor=False)
    cabecalho = st.empty()  # preenchido depois que o período é lido na barra lateral

# Barra lateral no padrão da Central (painel_padrao.py). Filtros de pessoa (diretoria, área,
# centro de custo, família, sexo, grupo) valem para tudo; tempo de casa só existe no desligamento e
# vale para todas as contagens de desligamento (headcount e admissões não mudam). O filtro de
# Motivo fica ao lado do título "Turnover Voluntário" e vale para toda aquela seção.
opcoes = lambda c: sorted(df[c].dropna().unique())  # noqa: E731
with pp.barra_lateral(fonte="Neon + Databricks", atualizado_em=carga):
    st.markdown("**Período**")
    _padrao = (m.inicio_padrao(ref), ref)
    _escolha = st.date_input("Período", value=_padrao, min_value=date(2020, 1, 1), max_value=ref,
                             format="DD/MM/YYYY", label_visibility="collapsed")
    # enquanto a pessoa escolhe só a primeira data, o widget devolve uma data só
    per_ini, per_fim = (_escolha if isinstance(_escolha, (tuple, list)) and len(_escolha) == 2 else _padrao)
    st.markdown("**Filtros**")
    sel = {
        "diretoria": st.multiselect("Diretoria", opcoes("diretoria"), placeholder="Todas"),
        "area": st.multiselect("Área", opcoes("area"), placeholder="Todas"),
        "nome_centro_custo": st.multiselect("Centro de custo", opcoes("nome_centro_custo"), placeholder="Todos"),
        "familia_cargo": st.multiselect("Família de cargo", opcoes("familia_cargo"), placeholder="Todas"),
        "sexo": st.multiselect("Sexo", opcoes("sexo"), placeholder="Todos"),
        "grupo": st.multiselect("Grupo", ["Obras", "Comercial", "Corporativo"], placeholder="Todos"),
    }
    st.markdown("**Desligamentos**")
    sel_tempo = st.multiselect("Tempo de casa", list(reversed(m.ORDEM_TEMPO_CASA)), placeholder="Todos",
                               help="Tempo de casa na data do desligamento.")
    st.caption("Tempo de casa filtra só os desligamentos; headcount e admissões seguem inteiros.")

# o período vai até a data final escolhida (nunca depois da data da base)
ref_p = min(per_fim, ref)
cabecalho.caption(f"Período: {per_ini:%d/%m/%Y} até {ref_p:%d/%m/%Y} · cards do mês de {_mes_txt(ref_p)} "
                  f"(até {ref_p:%d/%m}) · dados de {ref:%d/%m/%Y}")

base = df
for col, vals in sel.items():
    if vals:
        base = base[base[col].isin(vals)]
base = m.filtrar_desligamentos(base, faixas_tempo_casa=sel_tempo)

k = m.kpis(base, ref_p)
des12 = m.desligados_periodo(base, per_ini, ref_p)
ev = m.evolucao_mensal(base, ref_p, inicio=per_ini)

c1, c2, c3, c4 = st.columns(4)
with c1:
    kpi("HEADCOUNT ATIVO", _int(k["headcount"]))
with c2:
    delta = k["desligamentos_atual"] - k["desligamentos_anterior"]
    kpi("DESLIGAMENTOS MÊS", _int(k["desligamentos_atual"]),
        "Estável" if delta == 0 else f"{'+' if delta > 0 else '−'} {abs(delta)} vs mês ant.", VERMELHO if delta > 0 else VERDE if delta < 0 else CINZA)
with c3:
    ta, tb = k["taxa_turnover_atual"], k["taxa_turnover_anterior"]
    pp = (ta - tb) * 100 if ta is not None and tb is not None else 0
    kpi("TAXA DE TURNOVER", _pct(ta, 2), "Estável" if abs(pp) < 0.05 else f"{'+' if pp > 0 else '−'} {abs(pp):.1f} pp".replace(".", ","),
        VERMELHO if pp >= 0.05 else VERDE if pp <= -0.05 else CINZA)
with c4:
    kpi("TEMPO MÉDIO CASA", m.tempo_medio_casa(des12), "desligados no período", CINZA)
st.caption("Taxa = (admissões + desligamentos) / 2 / headcount do fim do mês anterior")

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

# ------------------------------------------------------------------ turnover voluntário
h1, h2 = st.columns([9, 3], vertical_alignment="bottom")
h1.html('<div class="secao">Turnover Voluntário</div>')
motivo = h2.selectbox("Motivo", ["Todos"] + sorted(des12["motivo"].dropna().unique()), label_visibility="collapsed",
                      help="Filtra todos os indicadores desta seção.")
# a seção inteira (evolução, cards, gráficos e resumo) usa a base filtrada pelo motivo
base_vol = base if motivo == "Todos" else m.filtrar_desligamentos(base, motivos=[motivo])
ev_vol = ev if motivo == "Todos" else m.evolucao_mensal(base_vol, ref_p, inicio=per_ini)
des_m = m.desligados_periodo(base_vol, per_ini, ref_p)

v1, v2 = st.columns([10, 2])
with v1:
    grafico("Evolução dos desligamentos por tipo e taxa de turnover voluntário", combo_voluntario(ev_vol), 330)
with v2:
    ult12 = ev_vol
    hc_med = ult12["headcount_anterior"].mean()
    mini("Turnover vol. médio/mês", _pct(ult12["desligamentos_voluntario"].sum() / hc_med / len(ult12) if hc_med else None))
    mini("Desligados voluntários", _int(des_m.loc[des_m["voluntario"], "id_funcionario"].nunique()))
    mini("Total desligados", _int(des_m["id_funcionario"].nunique()))
    st.caption("No período")

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

st.html('<div class="secao">Resumo por diretoria e área</div>')
resumo = m.resumo_diretoria_area(des_m)
if resumo.empty:
    st.info(SEM_DADOS, icon=":material/info:")
else:
    st.dataframe(
        resumo, hide_index=True, width="stretch",
        column_config={"diretoria": "Diretoria", "area": "Área",
                       "Voluntário": st.column_config.NumberColumn(format="%d"),
                       "Involuntário": st.column_config.NumberColumn(format="%d"),
                       "Total": st.column_config.NumberColumn(format="%d")},
    )
st.caption(f"Desligamentos no período · {_int(des_m['id_funcionario'].nunique())} pessoas "
           "(quem saiu de duas áreas no período aparece nas duas linhas)")
