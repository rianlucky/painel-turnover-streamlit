"""Cálculo dos indicadores do painel Turnover — sem Streamlit, para poder testar e validar.

Entrada: core.v_turnover_base (Neon), uma linha por atribuição. Regras de negócio da
especificação do dashboard do Databricks (ZZ - Prompts Migração.../Dashboard_Turnover_Streamlit_Spec.md):
  1. Voluntário: motivo contém "Pedido"/"pedido"/"Voluntári"; o resto é Involuntário
  2. Taxa de turnover = (desligamentos + admissões) / 2 / headcount do fim do mês anterior
  3. Headcount em uma data: admitido até a data e sem desligamento (ou desligado depois dela);
     pessoas distintas
  4. Admissão "real": não conta recontratação no dia seguinte a um desligamento
  5. Desligamento incorreto (flag da silver 00004) nunca conta
  6. Recontratação em até 10 dias (30/09/2026): desligamento seguido de nova admissão da mesma pessoa
     em até 10 dias não é desligamento, e essa readmissão não é admissão (view: desligamento_readmitido,
     admissao_real; migração 021)
Diferenças deliberadas em relação ao Databricks (ver README.md):
  - data de referência = foto mais recente da base (não CURRENT_DATE)
  - diretoria/área = mapeamento oficial (core.mapeamento_diretoria), não a dim desatualizada
  - família de cargo = a da própria atribuição (sem o cruzamento com dim_cargo que duplicava pessoas)
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

VOLUNTARIO_REGEX = r"Pedido|pedido|Voluntári"
FAIXAS_TEMPO_CASA = [
    (91, "0 a 3 meses"), (183, "3 a 6 meses"), (365, "6 meses a 1 ano"), (730, "1 ano a 2 anos"),
    (1095, "2 anos a 3 anos"), (1826, "3 anos a 5 anos"), (3652, "5 anos a 10 anos"),
]
ORDEM_TEMPO_CASA = ["+ 10 anos", "5 anos a 10 anos", "3 anos a 5 anos", "2 anos a 3 anos",
                    "1 ano a 2 anos", "6 meses a 1 ano", "3 a 6 meses", "0 a 3 meses"]
ORDEM_FAIXA_ETARIA = ["60+", "55 a 59", "50 a 54", "45 a 49", "40 a 44", "35 a 39", "30 a 34",
                      "25 a 29", "18 a 24", "Menor de 18"]
NAO_INFORMADO = "Não informado"
DIAS_EXPERIENCIA = 90  # período de experiência (CLT: até 90 dias)
ESTAGIARIO = "Estagiário"
# nível de gerenciamento com as variações juntas (mesmo agrupamento do Headcount, Aderência e Demográficos)
NIVEL_GERENCIAMENTO = {"Gerente de Vendas": "Gerente", "Gerente Executivo de Obras": "Gerente Executivo",
                       "Gerente Executivo Estadual de Obras": "Gerente Executivo", "Coordenador de Obras": "Coordenador/Especialista",
                       "Diretor de Obras": "Diretor"}
ORDEM_NIVEL = ["Operacional", "Pilotos", "Staff", "Supervisor/Advogado/Engenheiro", "Coordenador/Especialista",
               "Gerente", "Gerente Executivo", "Diretor", "Conselheiro"]
ORDEM_FRENTE = ["Obras", "Corporativo", "Comercial"]
ORDEM_RACA = ["Branca", "Parda", "Preta", "Amarela", "Não Informada"]
ORDEM_ESCOLARIDADE = ["Até o fundamental", "Ensino médio", "Superior incompleto", "Superior completo", "Pós-graduação"]


def escolaridade_grupo(e) -> str:
    """Os 14 valores do cadastro em 5 níveis (técnico conta como ensino médio)."""
    e = "" if e is None or pd.isna(e) else str(e)
    if any(x in e for x in ("Pós", "Mestrado", "Doutorado")):
        return "Pós-graduação"
    if "Superior Completo" in e:
        return "Superior completo"
    if "Superior Incompleto" in e:
        return "Superior incompleto"
    if "Médio" in e:
        return "Ensino médio"
    if any(x in e for x in ("Fundamental", "Alfabet", "Analfab")):
        return "Até o fundamental"
    return NAO_INFORMADO


# ----------------------------------------------------------------------------- preparação

def faixa_tempo_casa(dias) -> str | None:
    if dias is None or pd.isna(dias):
        return None
    for limite, nome in FAIXAS_TEMPO_CASA:
        if dias < limite:
            return nome
    return "+ 10 anos"


def faixa_etaria(idade) -> str | None:
    if idade is None or pd.isna(idade):
        return None
    if idade < 18:
        return "Menor de 18"
    for teto, nome in ((24, "18 a 24"), (29, "25 a 29"), (34, "30 a 34"), (39, "35 a 39"),
                       (44, "40 a 44"), (49, "45 a 49"), (54, "50 a 54"), (59, "55 a 59")):
        if idade <= teto:
            return nome
    return "60+"


def grupo(diretoria: str | None) -> str:
    d = diretoria or ""
    if "Obras" in d:
        return "Obras"
    if "Comercial" in d:
        return "Comercial"
    return "Corporativo"


def preparar(base: pd.DataFrame) -> pd.DataFrame:
    """Tipos e colunas derivadas usadas pelos filtros e gráficos."""
    df = base.copy()
    for c in ("data_referencia", "data_admissao", "data_desligamento"):
        df[c] = pd.to_datetime(df[c]).dt.date
    df["idade_desligamento"] = pd.to_numeric(df["idade_desligamento"], errors="coerce")
    df["tempo_empresa_dias_desligamento"] = pd.to_numeric(df["tempo_empresa_dias_desligamento"], errors="coerce")
    df["grupo"] = df["diretoria"].map(grupo)
    df["voluntario"] = df["motivo"].fillna("").str.contains(VOLUNTARIO_REGEX, regex=True)
    df["tipo_desligamento"] = df["voluntario"].map({True: "Voluntário", False: "Involuntário"}).where(df["data_desligamento"].notna())
    df["faixa_tempo_casa"] = df["tempo_empresa_dias_desligamento"].map(faixa_tempo_casa)
    df["faixa_etaria"] = df["idade_desligamento"].map(faixa_etaria)
    for c in ("diretoria", "area", "nome_centro_custo", "familia_cargo", "sexo", "motivo"):
        df[c] = df[c].fillna("Não informado")
    if "nivel_gerenciamento" in df:  # colunas da migração 022
        df["nivel"] = df["nivel_gerenciamento"].replace(NIVEL_GERENCIAMENTO).fillna(NAO_INFORMADO)
        df["escolaridade_grupo"] = df["escolaridade"].map(escolaridade_grupo)
        df["raca_cor"] = df["raca_cor"].fillna("Não Informada")
        for c in ("frente", "vinculo", "cargo"):
            df[c] = df[c].fillna(NAO_INFORMADO)
        df["estagiario"] = df["vinculo"] == ESTAGIARIO
    # quais desligamentos entram nas contagens: nunca os incorretos; os filtros de motivo e
    # tempo de casa (que só existem no desligamento) desligam os que não batem — ver filtrar_desligamentos
    df["desligamento_readmitido"] = df["desligamento_readmitido"].fillna(False).astype(bool) if "desligamento_readmitido" in df else False
    df["conta_desligamento"] = ~df["desligamento_incorreto"].astype(bool) & ~df["desligamento_readmitido"]
    return df


def filtrar_desligamentos(df: pd.DataFrame, motivos: list[str] | None = None,
                          faixas_tempo_casa: list[str] | None = None) -> pd.DataFrame:
    """Filtros que só fazem sentido no desligamento (motivo, tempo de casa): o desligamento que
    não bate deixa de ser contado, mas a linha fica — o headcount e as admissões não mudam."""
    df = df.copy()
    ok = df["conta_desligamento"]
    if motivos:
        ok &= df["motivo"].isin(motivos)
    if faixas_tempo_casa:
        ok &= df["faixa_tempo_casa"].isin(faixas_tempo_casa)
    df["conta_desligamento"] = ok
    return df


def data_referencia(df: pd.DataFrame) -> date:
    return max(df["data_referencia"].dropna())


# ----------------------------------------------------------------------------- blocos básicos

def _fim_mes(d: date) -> date:
    return (d.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)


def meses(ref: date, n_atras: int = 12) -> list[date]:
    """Inícios de mês desde o mesmo mês do ano anterior até o mês da referência (13 meses,
    como o `data_inicio_tempo >= trunc(ref - 12 meses)` do Databricks)."""
    ini = ref.replace(day=1)
    lista = []
    for i in range(n_atras, -1, -1):
        y, m = ini.year, ini.month - i
        while m <= 0:
            y, m = y - 1, m + 12
        lista.append(date(y, m, 1))
    return lista


def meses_entre(ini: date, fim: date) -> list[date]:
    """Inícios de mês de `ini` até `fim` (inclusive); `ini` pode ser qualquer dia do mês."""
    lista, d = [], ini.replace(day=1)
    while d <= fim:
        lista.append(d)
        d = (d + timedelta(days=32)).replace(day=1)
    return lista


def inicio_padrao(ref: date) -> date:
    """Início do período padrão: mesmo mês do ano anterior (13 meses até a referência)."""
    return meses(ref)[0]


def headcount_em(df: pd.DataFrame, d: date) -> int:
    ativo = (df["data_admissao"] <= d) & (df["data_desligamento"].isna() | (df["data_desligamento"] > d))
    return int(df.loc[ativo, "id_funcionario"].nunique())


def desligamentos(df: pd.DataFrame, ini: date, fim: date) -> pd.DataFrame:
    d = df["data_desligamento"]
    conta = df["conta_desligamento"] if "conta_desligamento" in df else (
        ~df["desligamento_incorreto"].astype(bool) & ~df.get("desligamento_readmitido", False))
    return df[d.notna() & (d >= ini) & (d <= fim) & conta]


def admissoes(df: pd.DataFrame, ini: date, fim: date) -> pd.DataFrame:
    a = df["data_admissao"]
    return df[(a >= ini) & (a <= fim) & df["admissao_real"]]


def _taxa(desl: int, adm: int, hc: int) -> float | None:
    return (desl + adm) / 2 / hc if hc else None


# ----------------------------------------------------------------------------- indicadores

def evolucao_mensal(df: pd.DataFrame, ref: date, inicio: date | None = None) -> pd.DataFrame:
    """Uma linha por mês de `inicio` (padrão: 13 meses) até `ref`: admitidos, desligamentos
    (vol./invol.), headcount do fim do mês anterior e as taxas. O último mês vai até `ref`."""
    linhas = []
    inicio = inicio or inicio_padrao(ref)
    for mes in meses_entre(inicio, ref):
        # primeiro e último mês contam só os dias dentro do período; o headcount de
        # referência continua sendo o do fim do mês anterior
        ini, fim = max(mes, inicio), min(_fim_mes(mes), ref)
        hc_ant = headcount_em(df, mes - timedelta(days=1))
        des = desligamentos(df, ini, fim)
        adm = len(admissoes(df, ini, fim))
        vol = int(des["voluntario"].sum())
        linhas.append({
            "periodo": mes, "admitidos": adm, "desligamentos": len(des),
            "desligamentos_voluntario": vol, "desligamentos_involuntario": len(des) - vol,
            "headcount_anterior": hc_ant, "taxa_turnover": _taxa(len(des), adm, hc_ant),
            "taxa_turnover_voluntario": vol / hc_ant if hc_ant else None,
            "taxa_turnover_involuntario": (len(des) - vol) / hc_ant if hc_ant else None,
        })
    return pd.DataFrame(linhas)


def kpis(df: pd.DataFrame, ref: date) -> dict:
    """Cards do topo: headcount, desligamentos e taxa do mês corrente vs mês anterior."""
    ini_atual = ref.replace(day=1)
    ini_ant = (ini_atual - timedelta(days=1)).replace(day=1)
    res = {"headcount": headcount_em(df, ref)}
    for nome, ini, fim in (("atual", ini_atual, ref), ("anterior", ini_ant, _fim_mes(ini_ant))):
        des = len(desligamentos(df, ini, fim))
        adm = len(admissoes(df, ini, fim))
        hc = headcount_em(df, ini - timedelta(days=1))
        res |= {f"desligamentos_{nome}": des, f"admitidos_{nome}": adm, f"headcount_den_{nome}": hc,
                f"taxa_turnover_{nome}": _taxa(des, adm, hc)}
    return res


def desligados_12m(df: pd.DataFrame, ref: date) -> pd.DataFrame:
    """Desligamentos dos últimos 12 meses até a referência, sem os incorretos (padrão do Databricks)."""
    ini = date(ref.year - 1, ref.month, min(ref.day, 28))
    return desligamentos(df, ini, ref)


def desligados_periodo(df: pd.DataFrame, ini: date, fim: date) -> pd.DataFrame:
    """Base dos gráficos de perfil (sexo, tempo de casa, faixa etária, motivo, diretoria) num
    período escolhido: desligamentos de `ini` a `fim`, sem os incorretos."""
    return desligamentos(df, ini, fim)


def tempo_medio_casa(des: pd.DataFrame) -> str:
    dias = des["tempo_empresa_dias_desligamento"].dropna()
    if dias.empty:
        return "—"
    media = float(dias.mean())
    anos, meses_ = int(media // 365), int((media % 365) // 30)
    partes = ([f"{anos} {'Ano' if anos == 1 else 'Anos'}"] if anos else []) + \
             ([f"{meses_} {'Mês' if meses_ == 1 else 'Meses'}"] if meses_ else [])
    return " e ".join(partes) or "0 Meses"


def contagem(des: pd.DataFrame, coluna: str) -> pd.DataFrame:
    """Desligamentos (pessoas distintas) por uma dimensão."""
    return (des.groupby(coluna)["id_funcionario"].nunique().rename("desligamentos")
            .reset_index().sort_values("desligamentos", ascending=False))


HEADCOUNT_MINIMO_AREA = 10  # áreas menores que isso distorcem a taxa (1 saída em 2 pessoas = 50%)


def turnover_por(df: pd.DataFrame, coluna: str, ref: date, inicio: date, somente_voluntario: bool = False,
                 minimo: int = HEADCOUNT_MINIMO_AREA, ordem: list[str] | None = None) -> pd.DataFrame:
    """Taxa de turnover por uma dimensão (nível, frente, raça/cor, escolaridade…) no período, mesma conta
    de turnover_por_area: desligamentos (+ admissões) do grupo ÷ headcount médio mensal do grupo.
    Grupos com headcount médio abaixo de `minimo` ficam de fora; `ordem` fixa a ordem das linhas."""
    t = turnover_por_area(df.assign(area=df[coluna]), ref, somente_voluntario, top=10_000, inicio=inicio, minimo=minimo)
    t = t.rename(columns={"area": coluna})
    if ordem:
        t = t.set_index(coluna).reindex([o for o in ordem if o in set(t[coluna])] +
                                        sorted(set(t[coluna]) - set(ordem))).reset_index()
    return t


def turnover_por_area(df: pd.DataFrame, ref: date, somente_voluntario: bool = False, top: int = 10,
                      inicio: date | None = None, minimo: int = HEADCOUNT_MINIMO_AREA) -> pd.DataFrame:
    """Taxa de turnover de cada área no período (padrão: últimos 12 meses): soma dos desligamentos (e admissões,
    se não for só voluntário) da área dividida pelo headcount médio mensal da própria área.
    Só entram áreas com headcount médio >= `minimo`."""
    linhas = []
    for area, dfa in df.groupby("area"):
        tot_des = tot_adm = 0
        hcs = []
        for mes in (meses_entre(inicio, ref) if inicio else meses(ref)[1:]):
            ini, fim = max(mes, inicio or mes), min(_fim_mes(mes), ref)
            des = desligamentos(dfa, ini, fim)
            tot_des += int(des["voluntario"].sum()) if somente_voluntario else len(des)
            tot_adm += 0 if somente_voluntario else len(admissoes(dfa, ini, fim))
            hcs.append(headcount_em(dfa, mes - timedelta(days=1)))
        hc_medio = sum(hcs) / len(hcs) if hcs else 0
        if hc_medio >= minimo and area != "Não informado":
            taxa = (tot_des / hc_medio) if somente_voluntario else (tot_des + tot_adm) / 2 / hc_medio
            linhas.append({"area": area, "desligamentos": tot_des, "admitidos": tot_adm,
                           "headcount_medio": round(hc_medio, 1), "taxa_turnover": taxa})
    out = pd.DataFrame(linhas, columns=["area", "desligamentos", "admitidos", "headcount_medio", "taxa_turnover"])
    return out.sort_values("taxa_turnover", ascending=False).head(top)


def resumo_diretoria_area(des: pd.DataFrame) -> pd.DataFrame:
    """Pivot: diretoria × área × tipo de desligamento, com tempo médio de casa."""
    colunas = ["diretoria", "area", "Voluntário", "Involuntário", "Total", "Tempo médio de casa"]
    if des.empty:
        return pd.DataFrame(columns=colunas)
    g = des.groupby(["diretoria", "area", "tipo_desligamento"])
    tab = g["id_funcionario"].nunique().unstack("tipo_desligamento", fill_value=0)
    for c in ("Voluntário", "Involuntário"):
        if c not in tab:
            tab[c] = 0
    tab["Total"] = tab["Voluntário"] + tab["Involuntário"]
    # agg numa coluna só (o apply por grupo devolvia DataFrame em alguns filtros e quebrava)
    tab["Tempo médio de casa"] = des.groupby(["diretoria", "area"])["tempo_empresa_dias_desligamento"].agg(
        lambda s: tempo_medio_casa(s.to_frame()))
    return tab[["Voluntário", "Involuntário", "Total", "Tempo médio de casa"]].reset_index()


# ----------------------------------------------------------------------------- período de experiência

def saidas_experiencia(des: pd.DataFrame) -> pd.DataFrame:
    """Desligamentos (já filtrados e contados) com até DIAS_EXPERIENCIA dias de casa."""
    return des[des["tempo_empresa_dias_desligamento"] <= DIAS_EXPERIENCIA]


def coorte_experiencia(df: pd.DataFrame, ini: date, ref: date) -> dict:
    """De quem foi admitido no período e já completou 90 dias até a referência: quantos saíram
    antes de completar o período de experiência."""
    limite = ref - timedelta(days=DIAS_EXPERIENCIA)
    adm = admissoes(df, ini, limite)
    if adm.empty:
        return {"admitidos": 0, "sairam": 0, "taxa": None, "ate": limite}
    dias = (pd.to_datetime(adm["data_desligamento"]) - pd.to_datetime(adm["data_admissao"])).dt.days
    saiu = adm["data_desligamento"].notna() & adm["conta_desligamento"] & (dias <= DIAS_EXPERIENCIA)
    return {"admitidos": len(adm), "sairam": int(saiu.sum()), "taxa": float(saiu.mean()), "ate": limite}


def evolucao_experiencia(df: pd.DataFrame, ini: date, ref: date) -> pd.DataFrame:
    """Por mês de desligamento: saídas em experiência e o % delas sobre todos os desligamentos."""
    linhas = []
    for mes in meses_entre(ini, ref):
        des = desligamentos(df, max(mes, ini), min(_fim_mes(mes), ref))
        exp = saidas_experiencia(des)
        linhas.append({"periodo": mes, "desligamentos": len(des), "experiencia": len(exp),
                       "experiencia_voluntario": int(exp["voluntario"].sum()),
                       "pct": len(exp) / len(des) if len(des) else None})
    return pd.DataFrame(linhas)


# ----------------------------------------------------------------------------- retenção por turma

HORIZONTES_RETENCAO = (3, 6, 12)


def _mais_meses(d: date, n: int) -> date:
    y, m = d.year, d.month + n
    while m > 12:
        y, m = y + 1, m - 12
    while m < 1:
        y, m = y - 1, m + 12
    return date(y, m, min(d.day, 28))


def retencao_coortes(df: pd.DataFrame, ref: date, n_turmas: int = 18) -> pd.DataFrame:
    """Turmas de contratação (mês de admissão) dos últimos `n_turmas` meses: admitidos e o % que continua
    na empresa 3, 6 e 12 meses depois (só quando a turma inteira já tem essa idade). Recontratação em até
    10 dias não conta como saída (regra da migração 021)."""
    linhas = []
    for mes in meses_entre(_mais_meses(ref.replace(day=1), -n_turmas), ref):
        adm = admissoes(df, mes, min(_fim_mes(mes), ref))
        if adm.empty:
            continue
        linha = {"turma": mes, "admitidos": len(adm)}
        saida = pd.to_datetime(adm["data_desligamento"].where(adm["conta_desligamento"]))
        dias_ate_saida = (saida - pd.to_datetime(adm["data_admissao"])).dt.days
        for h in HORIZONTES_RETENCAO:
            if _mais_meses(_fim_mes(mes), h) > ref:
                linha[f"ret_{h}"] = None
            else:
                ficou = dias_ate_saida.isna() | (dias_ate_saida > h * 30.4)
                linha[f"ret_{h}"] = float(ficou.mean())
        linhas.append(linha)
    return pd.DataFrame(linhas, columns=["turma", "admitidos"] + [f"ret_{h}" for h in HORIZONTES_RETENCAO])


# ----------------------------------------------------------------------------- cargos com mais saídas voluntárias

def cargos_voluntarios(des: pd.DataFrame, top: int = 15, minimo: int = 3) -> pd.DataFrame:
    """Cargos com mais pedidos de demissão no período (pelo menos `minimo`), com o total de saídas,
    o % voluntário e o tempo médio de casa de quem pediu para sair."""
    colunas = ["cargo", "voluntarios", "desligamentos", "pct_voluntario", "tempo_medio"]
    if des.empty:
        return pd.DataFrame(columns=colunas)
    g = des.groupby("cargo")
    t = pd.DataFrame({"voluntarios": g["voluntario"].sum().astype(int), "desligamentos": g.size()})
    t["pct_voluntario"] = t["voluntarios"] / t["desligamentos"]
    vol = des[des["voluntario"]]
    t["tempo_medio"] = vol.groupby("cargo")["tempo_empresa_dias_desligamento"].agg(lambda x: tempo_medio_casa(x.to_frame()))
    t = t[t["voluntarios"] >= minimo].sort_values(["voluntarios", "pct_voluntario"], ascending=False).head(top)
    return t.reset_index()[colunas]
