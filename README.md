# Turnover — admissões, desligamentos e taxa de turnover

Painel Streamlit migrado do dashboard AI/BI "Dashboard Turnover" do Databricks
(especificação em `00 - Central de Gente & Dados/ZZ - Prompts Migração Databricks - Streamlit+Neon/Dashboard_Turnover_Streamlit_Spec.md`).
Lê **só do Neon**, por uma view própria no Neon, com um usuário de banco só de leitura.
Com login: o mesmo dos outros painéis da Central (`acesso.app_users`, `auth.py`); quem já tem
acesso em outro painel entra com a mesma senha. O e-mail de suporte vem dos Secrets (`[app] email_suporte`).

## Rodar

```powershell
streamlit run app.py
```

`.streamlit/secrets.toml` (fora do Git) tem o bloco `[neon]` com a conexão — ver `.streamlit/secrets.toml.example`.

## Arquivos

| Arquivo | Para quê |
|---|---|
| `app.py` | Tela: cards, filtros, gráficos (Vega-Lite) e resumo por diretoria/área |
| `auth.py` | Login por e-mail (mesmo fluxo e visual da Aderência Salarial) |
| `metricas.py` | Todos os cálculos, sem Streamlit. O relatório de validação (`_neon/validacao`) usa o mesmo módulo |
| `painel_padrao.py` | Barra lateral no padrão da Central (logo, conta, filtros, Fonte/Atualizado em) — skill `padrao-painel-streamlit` |
| `assets/icone-turnover.png` | Ícone do painel |
| `.streamlit/config.toml` | Tema (paleta da especificação, fonte Inter) |

## Regras de negócio (as mesmas do Databricks)

1. **Voluntário**: motivo contém "Pedido"/"pedido"/"Voluntári"; o resto é Involuntário.
2. **Taxa de turnover** = (desligamentos + admissões) / 2 / headcount do fim do mês anterior.
3. **Headcount numa data**: admitido até a data e sem desligamento (ou desligado depois); pessoas distintas.
4. **Admissão real**: recontratação no dia seguinte a um desligamento não conta.
5. **Desligamento incorreto** (flag da silver 00004, em `core.desligamento_incorreto`) nunca conta.

## O que mudou em relação ao Databricks (de propósito)

| Ponto | Databricks | Aqui | Por quê |
|---|---|---|---|
| Diretoria / área | `rh.gold.dim_departamento_areas_diretorias` + 527 CCs à mão no SQL | `core.v_funcionario_diretoria` (planilha oficial `_neon/mapeamento`) | a dim está desatualizada desde jun/2026 |
| Família de cargo | join com `rh.silver.dim_cargo` | a da própria atribuição | o join duplicava pessoas (várias versões por cargo) |
| Data de referência | `CURRENT_DATE()` | foto mais recente da base | evita misturar a data da carga com a de hoje |
| Top 10 turnover por área | desligamentos da área ÷ headcount e admissões **da empresa toda** | desligamentos + admissões da área ÷ headcount médio **da área**, 12 meses, só áreas com ≥ 10 pessoas | a fórmula original misturava área com empresa |
| Turnover voluntário (card) | fórmula sobre todos os meses juntos | média mensal dos últimos 12 meses | mais fácil de ler e comparar |
| Filtros | numa linha acima dos gráficos; vários não chegavam a todos os widgets | barra lateral (padrão da Central); todos valem para todos os widgets em que fazem sentido | pedido de 28/09 |
| Filtro Tempo de casa | aplicado a tudo (zerava o headcount) | vale para todas as contagens de desligamento; headcount e admissões não mudam | tempo de casa só existe no desligamento |
| Filtro Motivo | só nos gráficos de desligados | ao lado de "Turnover Voluntário", vale para a seção inteira (inclusive evolução e Top 10) | |
| Período | fixo: últimos 12/13 meses | filtro de datas "DD/MM/AAAA até DD/MM/AAAA" na barra lateral (padrão: 01 do mesmo mês do ano anterior até a data da base); cards = mês da data final | |

Conferência (28/09/2026, referência 27/09): admissões, desligamentos e taxa de agosto, headcount
total e da Diretoria Comercial e headcount por diretoria batem com a régua do relatório de
validação. Os desligamentos de agosto batem pessoa a pessoa com o dashboard do Databricks (53).

## Padrão visual atualizado (30/09/2026)

Login padrão da Central (card único, adaptável a celular), título em Nunito com selos de "Atualizado em" e dos filtros aplicados (vão junto num print/PDF), cards com o recorte em seta da marca e "i" explicando a taxa de turnover, seções numeradas por título e impressão em A4 deitada (cada seção numa folha). Cálculos e regras sem mudança.

## Regra de negócio: recontratação em até 10 dias (30/09/2026)

Quando o mesmo colaborador é readmitido em até 10 dias depois de um desligamento (transferência para
outra empresa do grupo, troca de obra, correção de cadastro), **não é desligamento nem admissão**: é a
mesma pessoa continuando. Regra em `core.v_turnover_base` (migração `021_recontratacao_10_dias.sql`):
`desligamento_readmitido` tira o desligamento das contagens e `admissao_real` passa a exigir mais de
10 dias depois do desligamento anterior (antes: mais de 1 dia, e só do lado da admissão). Vale também
para o Headcount Total e para a régua da validação (31/31 ✅ depois da mudança). Efeito: 32
desligamentos a menos nos 12 meses até 29/09/2026.

## Páginas e análises novas (30/09/2026)

Cinco páginas na barra lateral (st.navigation):
- **Visão geral** — cards, evolução, taxa por área, sexo, tempo de casa, faixa etária e resumo por
  diretoria e área; nota com a taxa do mês sem estagiários.
- **Turnover voluntário** — a seção de antes (filtro de motivo) + **cargos com mais pedidos de demissão**
  (pelo menos 3 no período, % voluntário e tempo de casa de quem pediu).
- **Período de experiência** — saídas com até 90 dias de casa (prazo da CLT): total e % das saídas,
  "de cada 100 admitidos, quantos saem antes dos 90 dias" (turma que já completaria 90 dias), quem
  pediu x quem foi desligado, evolução mensal e áreas/cargos com mais casos.
- **Retenção por turma** — de quem foi admitido em cada mês (últimos 18), o % que continua 3, 6 e 12
  meses depois; média ponderada nos cards, curva e tabela colorida.
- **Perfil das saídas** — taxa de turnover (total ou só voluntário) por nível de gerenciamento, frente,
  raça/cor, escolaridade (5 níveis) e vínculo; grupos com menos de 10 pessoas em média ficam de fora.

Barra lateral: **Estagiários: Incluir / Tirar** (tira estagiários de todas as contagens — o fim do
estágio é saída prevista) e filtros novos **Frente** e **Nível**. Colunas novas na view pela migração
`022_turnover_perfil.sql` (nível, frente, raça/cor, escolaridade, vínculo, cargo).
