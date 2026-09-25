"""
html_render.py — converte os dados de uma AF em uma página HTML limpa, com a
identidade Eletronet (prévia bonita + galeria). Reaproveitado/calibrado a partir
das 46 AFs reais: total autoritativo = U19; itens lidos por conteúdo (28-44);
extenso regenerado quando a planilha vem com erro.
"""

from __future__ import annotations

import base64
import html
import os
import re
import unicodedata
from datetime import datetime

from openpyxl import load_workbook

from .modelos import valor_por_extenso, moeda_info, ELETRONET
from .dados_eletronet import LOGO

# Azul EXATO da marca, lido do site (eletronet.com usa #1100FF como cor de
# campo). O #1320e0 anterior era uma aproximação de memória.
AZUL = "#1100ff"
# Explicação de cada imposto — a mesma do formulário (web/app.js). Vale como
# tooltip na prévia; no PDF impresso não aparece, mas não atrapalha.
IMPOSTOS_INFO = {
    "IPI": "federal, sobre o produto industrializado",
    "ICMS": "estadual, sobre a venda de mercadoria",
    "ISS": "municipal, sobre prestação de serviço",
    "PIS": "contribuição federal sobre a receita",
    "COFINS": "contribuição federal sobre a receita",
    "ST": "substituição tributária — ICMS recolhido de uma vez pela cadeia",
    "FRETE": "não é imposto: valor do transporte somado ao produto",
}
# Logo em base64 cacheado — a prévia é refeita a cada tecla; reler+codificar o
# arquivo toda vez era desperdício. Calcula uma vez só.
_LOGO_B64 = None


def _logo_html() -> str:
    global _LOGO_B64
    if _LOGO_B64 is None:
        _LOGO_B64 = (base64.b64encode(open(LOGO, "rb").read()).decode()
                     if os.path.exists(LOGO) else "")
    return (f'<img class="logo" src="data:image/jpeg;base64,{_LOGO_B64}" alt="Eletronet">'
            if _LOGO_B64 else "")


# ---------------------------------------------------------------- leitura --
def _t(v) -> str:
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.strftime("%d/%m/%Y")
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() else str(v)
    return str(v).strip()


def _achar(ws, label):
    # a folha INTEIRA: com notas longas, "LOCAIS DE ENTREGA" desce para além
    # da linha 56 (AF-E-084: linha 60) e o teto antigo não o achava
    for row in ws.iter_rows(min_row=1, max_row=min(ws.max_row or 56, 400), max_col=3):
        for c in row:
            if c.value and label.lower() in str(c.value).lower():
                return c.row, c.column
    return None, None


def _txt_linha(ws, r, c0=1, c1=22) -> str:
    return " ".join(v for v in (_t(ws.cell(r, c).value) for c in range(c0, c1 + 1)) if v)


_FECHO_TABELA = re.compile(r"\b(TOTAL FORNECIMENTO|VALOR TOTAL|TOTAL SERVICOS?|TOTAL GERAL)\b")
_SO_NUMERACAO = re.compile(r"\d+(?:[.,]\d+)*[.:)]?")


def _tabela_itens(pg1) -> tuple[int, int]:
    """Da 1ª linha de item até a linha do total, achadas pelos RÓTULOS.

    Célula fixa não serve: quem faz a AF à mão INSERE linhas para caber mais
    itens, e tudo o que vem abaixo desce. Com 28-44 fixos, a AF-E-118 (28
    itens) voltava com 16, e a B51 — onde deveria estar o pagamento — caía em
    cima do código de um produto ("PRE-SFP-20")."""
    cab = None
    for r in range(15, 80):
        if _t(pg1.cell(r, 1).value).lower().startswith("item") and \
                "descri" in _txt_linha(pg1, r, 2, 12).lower():
            cab = r
            break
    if cab is None:
        return 28, 45
    for r in range(cab + 1, cab + 400):
        lin = _semac(_txt_linha(pg1, r)).upper()
        if _FECHO_TABELA.search(lin) or lin.startswith("NOTAS"):
            return cab + 1, r
    return cab + 1, cab + 60


def _bloco(ws, r0: int, ate: int = 25, vao: bool = False) -> str:
    """As linhas de texto logo abaixo de `r0`, até a próxima nota numerada
    ("4" na coluna A) — ou até o primeiro vão, a não ser que `vao` diga que
    a nota continua depois dele (a condição de pagamento da CIENA tem as
    subnotas 3.1, 3.2... separadas por linha em branco)."""
    partes = []
    for r in range(r0 + 1, r0 + 1 + ate):
        a, b = _t(ws.cell(r, 1).value), _txt_linha(ws, r, 2)
        if re.fullmatch(r"\d{1,2}", a) and b:
            break
        if re.fullmatch(r"#[A-Z/0!]+[?!]?", b.strip()):     # #VALUE!, #REF!: erro de fórmula
            continue
        if a and b and re.fullmatch(r"\d{1,2}[.,]\d{1,2}[.:)]?", a):
            b = f"{a} {b}"               # a subnota "3.1" mora na coluna A
        # o TÍTULO da próxima nota, sozinho na linha — não a palavra no meio
        # do texto ("A garantia para o objeto...")
        if re.fullmatch(r"(\d{1,2}\s+)?(GARANTIA|PRAZO DE ENTREGA)|NOTAS \(CONTINUA\w*\)?",
                        _semac(b).upper().strip()):
            break
        if not b:
            if partes and not vao:
                break
            continue
        if not _SO_NUMERACAO.fullmatch(b):       # "0"/"3.1" de fórmula vazia
            partes.append(b)
    return "\n".join(partes)


def ler_af(caminho: str) -> dict:
    wb = load_workbook(caminho, data_only=True)
    pg1, pg2 = wb["AF-pg1"], wb["AF-pg2"]
    ini, fim = _tabela_itens(pg1)
    d = {
        "arquivo": os.path.basename(caminho),
        "titulo": _t(pg1["A1"].value) or "AUTORIZAÇÃO DE FORNECIMENTO - AF",
        "af_id": _t(pg1["O10"].value), "cpm": _t(pg1["L11"].value),
        "data": _t(pg1["O13"].value), "proposta": _t(pg1["L17"].value),
        "fornecedor": _t(pg1["B10"].value), "endereco": _t(pg1["B12"].value),
        "cep": _t(pg1["B13"].value), "cnpj": _t(pg1["B14"].value), "ie": _t(pg1["B15"].value),
        "moeda": _t(pg1["A19"].value) or "Real", "extenso": _t(pg1["A22"].value),
        "objeto": _t(pg1["A25"].value), "total": _t(pg1[f"R{fim}"].value),
        "total_topo": _t(pg1["U19"].value), "pagamento": "", "itens": [],
    }
    # O bloco do fornecedor pelo RÓTULO da coluna A. Na AF feita à mão ele
    # está uma linha abaixo do modelo do app (CNPJ na 15, IE na 16), e com as
    # células fixas a inscrição estadual sumia em 27 de 100 planilhas.
    for r in range(8, 22):
        rot = _semac(_t(pg1.cell(r, 1).value)).lower().replace(" ", "")
        val = _t(pg1.cell(r, 2).value)
        for chave, pref in (("fornecedor", "fornecedor"), ("endereco", "endereco"),
                            ("cep", "cep"), ("cnpj", "cnpj"), ("ie", "insc")):
            if rot.startswith(pref) and val:
                d[chave] = val
    if not d["cnpj"] and re.match(r"\d{2}\.\d{3}\.\d{3}/", d["ie"]):
        d["cnpj"], d["ie"] = d["ie"], ""

    # A condição de pagamento vem logo depois de "... conforme segue:" — na
    # folha 1 ou, quando a tabela de itens cresceu muito, na folha 2. Só se o
    # rótulo não existir é que vale a B51 de antes, e NUNCA se a B51 caiu
    # dentro da tabela (seria o código de um produto).
    for ws, de in ((pg1, fim), (pg2, 1)):
        r0 = next((r for r in range(de, de + 60) if "conforme segue" in _txt_linha(ws, r).lower()), None)
        if r0:
            d["pagamento"] = _bloco(ws, r0, vao=True)
            if ws is pg1:
                # a nota 3 continua na folha 2, depois de "NOTAS (Continuação)"
                # — é lá que a CIENA tem as subnotas "3.1 Preços: USD DDP..."
                rc = next((r for r in range(1, 40)
                           if "continua" in _txt_linha(pg2, r).lower()
                           and "notas" in _txt_linha(pg2, r).lower()), None)
                resto = _bloco(pg2, rc, vao=True) if rc else ""
                if resto:
                    d["pagamento"] = (d["pagamento"] + "\n" + resto).strip()
            break
    else:
        d["pagamento"] = _t(pg1["B51"].value) if not (ini <= 51 < fim) else ""

    nao_item = ("TOTAL FORNECIMENTO", "VALOR TOTAL", "TOTAL GERAL", "SUBTOTAL",
                "TOTAL DA PROPOSTA", "NOTAS", "A PROPOSTA DA", "OS PREÇOS")
    d["total_forn"] = d["total"]
    for r in range(ini, fim):
        cod, desc = _t(pg1[f"B{r}"].value), _t(pg1[f"C{r}"].value)
        rr = _t(pg1[f"R{r}"].value)
        linha = (cod + desc).upper()
        if not (cod or desc):
            continue
        if any(m in linha for m in nao_item):
            continue
        if "descri" in desc.lower() and "item" in desc.lower():
            continue
        d["itens"].append(dict(
            cod=cod, desc=desc, qtd=_t(pg1[f"L{r}"].value), un=_t(pg1[f"M{r}"].value),
            us=_t(pg1[f"N{r}"].value), uc=_t(pg1[f"P{r}"].value), tot=rr))

    gr, _ = _achar(pg2, "GARANTIA")
    d["garantia"] = _bloco(pg2, gr, 8) if gr else ""
    pr, _ = _achar(pg2, "PRAZO DE ENTREGA")
    d["prazo"] = _bloco(pg2, pr, 8) if pr else ""
    # Faturamento/entrega podem ter VÁRIAS linhas (a AF aceita múltiplos locais):
    # lê em coluna fixa B (onde o gerador escreve) até a primeira linha vazia —
    # ou até a nota seguinte, que em AF feita à mão vem colada, sem linha vazia
    # ("Enviar NF para ..." virava um local de entrega). O teto de 15 que havia
    # aqui cortava as AFs da CIENA e da Precision, com 16 a 20 locais.
    def _secao_multi(row0, chaves, max_linhas=300):
        out = []
        for r in range(row0, row0 + max_linhas):
            vals = {k: _t(pg2.cell(r, 2 + i).value) for i, k in enumerate(chaves)}
            if not any(vals.values()):
                break
            linha = " ".join(vals.values())
            if re.fullmatch(r"\d{1,2}", _t(pg2.cell(r, 1).value)) or re.search(r"Enviar\s+NF|@", linha):
                break
            out.append(vals)
        return out

    fr, _ = _achar(pg2, "DADOS PARA FATURAMENTO")
    d["faturamentos"] = _secao_multi(fr + 2, ["uf", "razao", "cnpj", "endereco", "cep"]) if fr else []
    d["faturamento"] = d["faturamentos"][0] if d["faturamentos"] else {}
    er, _ = _achar(pg2, "LOCAIS DE ENTREGA")
    d["entregas"] = _secao_multi(er + 2, ["nome", "sigla", "endereco", "municipio", "uf"]) if er else []
    d["entrega"] = d["entregas"][0] if d["entregas"] else {}

    d["avisos"] = []
    if "dolar" in _semac(d["extenso"]) and "real" in _semac(d["moeda"]):
        d["avisos"].append("Moeda divergente: o valor por extenso está em dólar, mas a célula diz Real.")
    if "#" in d["extenso"]:
        d["avisos"].append("Valor por extenso veio com erro de fórmula na planilha (#NAME?) — foi regenerado.")
    return d


# -------------------------------------------------------------- formatação --
def _f(v, simb):
    try:
        x = float(str(v).replace(".", "").replace(",", ".")) if ("," in str(v)) else float(v)
    except (ValueError, TypeError):
        return html.escape(str(v or ""))
    s = f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{simb} {s}"


def _simbolo(moeda: str) -> str:
    """UMA regra só, a mesma do motor. Este arquivo tinha a sua própria tabela e
    reconhecia "Dólar" por pedaço do nome; o motor exigia a chave exata do
    catálogo e não reconhecia. O documento saía com US$ e a conta em R$."""
    return moeda_info(moeda)["simb"]


def _data_br(s: str) -> str:
    s = str(s or "")                      # campo ausente não pode derrubar a prévia
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    return f"{m.group(3)}/{m.group(2)}/{m.group(1)}" if m else s


def _e(s):
    return html.escape(str(s or ""))


def _semac(s):
    return unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()


def _end_curto(endereco, empresa=""):
    """Enxuga o endereço para gastar menos linhas no documento.

    O extrator costuma trazer o nome da empresa colado no começo ("Padtec S/A
    Rua das Castanheiras 200 …") — repetir a razão social logo abaixo do campo
    "Razão social" só consome espaço. Também colapsa espaços duplicados."""
    end = re.sub(r"\s+", " ", str(endereco or "")).strip(" ,;-")
    nome = re.sub(r"\s+", " ", str(empresa or "")).strip()
    if nome:
        # tira a razão social (e variações sem LTDA / S.A.) do início do endereço
        base = re.sub(r"\b(s\.?/?a\.?|ltda\.?|me|epp|eireli|do brasil|comercio|com\.?)\b", " ", _semac(nome))
        palavras = [p for p in base.split() if len(p) > 2]
        while palavras:
            alvo = r"\s+".join(re.escape(p) for p in palavras)
            m = re.match(r"^\W*" + alvo + r"[\s,\-–/]*(s\.?/?a\.?|ltda\.?)?[\s,\-–]*", _semac(end))
            if m and m.end() < len(end):
                end = end[m.end():].strip(" ,;-")
                break
            palavras.pop()          # tenta com menos palavras (nome abreviado)
    return end


def _n(v):
    try:
        return round(float(v), 2)
    except (ValueError, TypeError):
        return None


def total_af(d: dict) -> float:
    total = _n(d.get("total_topo")) or _n(d.get("total")) or _n(d.get("total_forn"))
    if total is None:
        total = round(sum((_n(it["tot"]) or 0) for it in d.get("itens", [])), 2)
    return total or 0.0


# ------------------------------------------ prévia do CPM/CPS ----------------
# REGRAS DE IMPRESSÃO COMUNS AOS DOIS DOCUMENTOS (AF/AS e CPM/CPS).
#
# Estavam escritas duas vezes, uma em cada renderizador, e a cópia já cobrou:
# o encolhimento da assinatura existia só no lado da AF, e a assinatura do CPM
# saiu sozinha numa folha (85% em branco). Aqui elas ficam num lugar só, para
# que consertar valha para os dois.
#
# Só entra o que é igual nos dois E deve continuar igual. O que é próprio de
# cada documento (a tabela de itens da AF que precisa fluir, o `.orc` do CPM)
# continua no bloco de cada um: dois documentos diferentes têm de poder
# divergir onde faz sentido.
_PRINT_COMUM = """
  body{background:#fff}
  .folha{border:none;margin:0;max-width:none;box-shadow:none;border-radius:0}
  .rod{display:none}                          /* o "Pré-visualização" não vai ao PDF */
  tr{break-inside:avoid}                      /* uma linha de item não parte ao meio */
  thead{display:table-header-group}           /* cabeçalho repete em tabela longa */
  /* TÍTULO não fica órfão no pé. `break-after:avoid` sozinho não bastou: com
     24 itens o cartão "Locais de entrega" saía com o título numa folha e o
     conteúdo na outra. O par completo — o título recusa quebra DEPOIS e o
     primeiro conteúdo recusa quebra ANTES — segura os dois juntos. */
  .sec{break-after:avoid}
  .bloco>.sec+*,.foot>div>.sec+*,.locais>.sec+*{break-before:avoid}
  /* Cada CARTÃO inteiro numa folha. O par break-after/break-before não
     resolve: dentro de célula de tabela o Chromium ignora os dois;
     `break-inside` ele respeita. */
  .bloco:not(.tabela){break-inside:avoid}
  /* ASSINATURA NUNCA SOZINHA. Medido: a folha 3 da AF-E-362 tinha só os dois
     nomes e 93% de papel branco; no CPM, 85%. E ela ENCOLHE no papel: na tela
     os 62px de respiro acima da linha ficam bem, no PDF engordam o bloco o
     bastante para não caber — no RTC-CPM-E-362 sobravam 122pt e o bloco pedia
     ~110pt, pulou por 12pt. Com 34px (~9mm, espaço de assinatura normal) cabe. */
  .assin{break-before:avoid;padding:8px 14px 2px;margin-top:0}
  .assin div{break-inside:avoid;margin-top:34px}
"""


def montar_cpm_html(c: dict) -> str:
    """Prévia visual do CPM/CPS (mostra como o documento está ficando)."""
    from .modelos import brl_para_float
    el = ELETRONET
    simb = _simbolo(c.get("moeda", "Real"))   # moeda LINKADA da AF (R$, US$, €, CN¥…)
    eh_real = (simb == "R$")
    vstr = _f(c.get("valor", ""), simb)

    def _num(v):
        if isinstance(v, (int, float)):
            return float(v)
        return brl_para_float(v) or 0.0
    valor_n = _num(c.get("valor"))
    valor_reais_n = _num(c.get("valor_reais")) or (valor_n if eh_real else 0.0)
    capex_n = _num(c.get("capex"))
    # O SALDO APARECE SEMPRE — decisão do usuário, e ela vale mais do que a minha
    # ressalva anterior (que sem verba informada o vermelho parecia acusar um
    # rombo que ninguém tinha declarado). Quem lê o documento vê "CAPEX: não
    # informado" logo ao lado e sabe de onde veio o número. Só o documento AINDA
    # VAZIO — sem verba E sem valor — mantém o travessão: ali não há conta a
    # fazer, e "R$ 0,00" seria ruído num formulário em branco.
    tem_capex = capex_n > 0                  # vale só para o rótulo da verba
    ha_conta = tem_capex or valor_reais_n > 0
    saldo_n = capex_n - valor_reais_n   # saldo em R$ = CAPEX − valor convertido
    # O cartão "Soma da compra" saiu do Orçamento: em REAL ele repetia o "Valor" e
    # ainda empurrava o "Saldo" p/ fora da folha. Em moeda ESTRANGEIRA ele continua,
    # como "Valor em R$", porque aí é a conversão — e é ela que define a alçada.

    def linha(rot, val):
        # Valor CURTO ("45 dias") fica na mesma linha, alinhado à direita. Valor
        # LONGO (prazo escrito como texto corrido) vira bloco: rótulo em cima e o
        # texto embaixo à esquerda — espremido à direita ficava ilegível.
        txt = str(val or "")
        cls = " longa" if len(txt) > 34 else ""
        # valor de UMA palavra (AF-E-256/2026-TR, CNPJ, CEP, data) não pode ser
        # partido no meio; frase com espaços quebra normalmente entre palavras.
        cls += " nq" if txt and " " not in txt.strip() else ""
        # Campo SEM valor mostrava o rótulo e um vazio do lado, e o bloco ficava
        # com cara de documento pela metade. Um travessão discreto diz "esta
        # informação não veio" — que é diferente de "faltou imprimir".
        if not txt:
            return f'<div class="f{cls}"><span class="fk">{rot}</span><span class="fv vazio">—</span></div>'
        return f'<div class="f{cls}"><span class="fk">{rot}</span><span class="fv">{_e(val)}</span></div>'

    # Fornecedores consultados: Fornecedor → Prazo → Valor (mais motivo p/ a escolha).
    def _cons(x):
        row = (list(x) + ["", "", ""])[:3] if isinstance(x, list) else [x, "", ""]
        return (f'<tr><td class="cons-f">{_e(row[0])}</td>'
                f'<td class="cons-p">{_e(row[1])}</td>'
                f'<td class="cons-v">{_f(row[2], simb) if str(row[2]).strip() else ""}</td></tr>')
    cons = [x for x in (c.get("consultados") or []) if (x[0] if isinstance(x, list) else x)]
    # ORÇAMENTO em grade de 3 colunas. As células são montadas aqui, em lista,
    # porque a ÚLTIMA LINHA quase nunca vem cheia: com 5 células (moeda Real)
    # sobra o terço final. Preencher com uma célula vazia fechava o retângulo,
    # mas deixava um quadrado em branco no meio do documento. Agora a sobra é
    # DIVIDIDA entre as células que existem: a última se estica pelo que resta.
    def _cel(rot, val, cls=""):
        return [rot, val, cls]          # vira HTML no fim: a última muda de classe

    _rs = chr(82) + chr(36)
    celulas = [_cel("Identificação", _e(c.get("af_id"))),
               _cel("Fornecedor", _e(c.get("fornecedor_fantasia"))),
               _cel("Valor" if eh_real else f"Valor ({simb})", vstr)]
    if not eh_real:
        celulas.append(_cel("Valor em R$", _f(valor_reais_n, _rs)))
    # CAPEX ou OPEX: quem decide e o formulario. Vale so para o rotulo — a
    # conta do saldo (verba - valor) nao muda com o tipo da verba.
    verba = "OPEX" if str(c.get("tipo_verba", "")).strip().upper() == "OPEX" else "CAPEX"
    celulas.append(_cel(verba, _f(capex_n, "R$") if tem_capex
                        else '<span class="vazio">não informado</span>'))
    celulas.append(_cel("Saldo", _f(saldo_n, "R$") if ha_conta else '<span class="vazio">—</span>',
                        "neg" if (ha_conta and saldo_n < 0) else ""))
    sobra = (-len(celulas)) % 3          # 0, 1 ou 2 colunas livres na última linha
    if sobra:
        celulas[-1][2] = (celulas[-1][2] + " sp%d" % (sobra + 1)).strip()
    orc_html = "".join(
        '<div class="%s"><div class="cl">%s</div><div class="cv">%s</div></div>'
        % (" ".join(["cel"] + (cls.split() if cls else [])), rot, val)
        for rot, val, cls in celulas)

    # TABELA de verdade (não grade de proporção fixa): o navegador reparte a
    # largura pelo CONTEÚDO de todas as linhas juntas, então um prazo curto
    # ("Pronta-entrega") devolve o espaço para o nome do fornecedor.
    cons_html = ('<div class="cons-tab"><table class="cons"><thead><tr><th>Fornecedor</th>'
                 '<th>Prazo</th><th class="cons-v">Valor</th></tr></thead><tbody>'
                 + "".join(_cons(x) for x in cons) + "</tbody></table></div>") if cons else '<div class="muted">—</div>'

    # Locais de entrega: vêm numa string única ("A (X) — end, Mun/UF; B (Y) — …").
    # Com muitos POPs isso virava um parágrafo justificado gigante — quebramos em
    # cards numa grade de largura total (mesmo tratamento da AF).
    locais = [p.strip() for p in re.split(r"\s*;\s*", str(c.get("local_entrega") or "")) if p.strip()]

    def _loc_card(p):
        m = re.match(r"^(.*?)\s+—\s+(.+)$", p)          # "Nome (SIGLA) — endereço"
        cab, end = (m.group(1), m.group(2)) if m else (p, "")
        mu = re.search(r",\s*([^,]+/[A-Z]{2})\s*$", end)  # tira "Município/UF" do fim → pill
        tag = ""
        if mu:
            tag = f'<span class="uf">{_e(mu.group(1))}</span>'
            end = end[:mu.start()].strip(" ,")
        return (f'<div class="loc2"><div class="loc2-t">{_e(cab)}{tag}</div>'
                f'<div class="loc2-s">{_e(end)}</div></div>')

    # Os locais ficam DENTRO de Condições comerciais. Antes viravam uma seção lá
    # embaixo e a condição só dizia "12 locais (ver abaixo)" — informação da mesma
    # condição comercial partida em dois pontos do documento.
    locais_html = ""          # não há mais seção separada
    if len(locais) > 1:
        local_linha = (f'<div class="f longa locais-campo"><span class="fk">Locais de entrega '
                       f'<b class="cont">({len(locais)})</b></span>'
                       f'<div class="loc-grid">{"".join(_loc_card(p) for p in locais)}</div></div>')
    else:
        local_linha = linha("Local de entrega", c.get("local_entrega"))

    aprov = [("gerente", "Gerente", c.get("gerente")),
             ("gerente_geral", "Gerente Geral", c.get("gerente_geral")),
             ("diretor", "Diretor", c.get("diretor")),
             ("cfo", "CFO", c.get("cfo")),
             ("presidencia", "Presidência", c.get("presidencia")),
             ("conselho", "Conselho de Administração", c.get("conselho"))]
    # Assinantes EXTRAS cadastrados pelo usuário (papel livre + nome). Entram
    # depois dos cargos fixos, com chave própria p/ o "assina" funcionar igual.
    for n, x in enumerate(c.get("extras") or []):
        nome = str((x or {}).get("nome", "")).strip()
        if nome:
            aprov.append((f"extra{n}", str(x.get("papel", "")).strip() or "Responsável", nome))
    aprov_html = "".join(linha(r, v) for _, r, v in aprov if v)

    # Assinaturas: solicitante + os responsáveis da alçada preenchidos. Espaço
    # amplo acima das linhas p/ caber a assinatura de várias pessoas.
    # Quem ASSINA: por padrão todos os responsáveis preenchidos (comportamento
    # antigo). Se vier a lista "assinam", só esses ganham linha de assinatura —
    # os demais seguem registrados na alçada, mas sem assinar.
    escolhidos = c.get("assinam")
    assinantes = [(r, v) for k, r, v in aprov
                  if v and (escolhidos is None or k in escolhidos)]
    assin_html = "".join(
        f'<div><b>{_e(rot)}</b><br>{_e((nm or "").split(",")[0].strip())}</div>'
        for rot, nm in assinantes)

    # DENTRO do documento os rotulos acompanham o tipo: num CPS o que existe e
    # uma AS associada e a data da CPS, nao "AF associada"/"Data da CPM". Fora do
    # documento (abas, botoes) "AF/AS" e "CPM/CPS" seguem valendo — la o par
    # cobre os dois casos e nao ha o que decidir.
    _eh_servico = c.get("tipo") == "CPS"
    _doc = "AS" if _eh_servico else "AF"
    _coleta = "CPS" if _eh_servico else "CPM"
    titulo = ("COLETA DE PREÇOS DE SERVIÇO - CPS" if c.get("tipo") == "CPS"
              else "COLETA DE PREÇOS DE MATERIAL - CPM")
    return f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<!-- sem esta linha o navegador finge uma janela de 980px e ENCOLHE a
     pagina: as @media de 760/430px nunca disparam e a previa fica presa
     no desenho de tela larga, ilegivel no celular. -->
<title>{_e(c.get('cpm_id'))}</title><style>
*{{box-sizing:border-box}} body{{margin:0;background:#eef1f6;color:#1c2433;font:12.5px/1.5 'Segoe UI',Arial,sans-serif}}
.folha{{max-width:1040px;margin:16px auto;background:#fbfcfe;border:1px solid #dbe2ee;border-radius:16px;overflow:hidden;box-shadow:0 1px 2px rgba(20,45,130,.10),0 10px 34px -12px rgba(20,45,130,.26)}}
.top{{background:#fff}}
.top{{display:flex;align-items:center;gap:18px;padding:14px 18px;border-bottom:3px solid {AZUL}}}
.logo{{height:40px}} .ti{{flex:1}} .tit{{font-size:16px;font-weight:700}}
.tisub{{font-size:10px;letter-spacing:1.5px;text-transform:uppercase;color:#8a94a6;margin-top:4px}}
.idbox{{text-align:right;border:1px solid #dbe2ee;border-radius:12px;padding:6px 14px;background:#f7f9ff}}
.idbox .lbl{{font-size:9px;color:#6b7686;text-transform:uppercase;letter-spacing:1px}}
.idbox .num{{font:700 15px/1.2 Consolas,monospace;color:{AZUL};margin-top:2px}}
/* Título da seção como FAIXA no topo do bloco: o começo fica tão marcado
   quanto o fim, que a borda do bloco já delimitava. */
.sec{{font-size:10.5px;font-weight:700;color:{AZUL};text-transform:uppercase;letter-spacing:.9px;
  margin:0 -14px 10px;padding:9px 14px 8px;background:#eef2fb;
  border-bottom:1px solid #dbe3f3;border-radius:11px 11px 0 0}}
/* DIVISÃO ENTRE SEÇÕES: as faixas cinza foram removidas (não conversavam com o
   layout) e o respiro sozinho era pouco — quem não conhece o documento não sabia
   onde uma seção acaba. Agora cada seção é um bloco DELIMITADO: fundo branco,
   borda fina e cantos arredondados, no mesmo desenho da tabela de itens. */
/* margem lateral mínima: a folha é estreita (A4) e o que importa é caber
   informação — o bloco continua delimitado, só que quase de ponta a ponta */
.grid2,.bloco{{margin:0 10px 10px;padding:0 14px 11px;background:#fff;
  border:1px solid #e0e7f3;border-radius:12px;box-shadow:0 1px 2px rgba(20,45,130,.05)}}
.grid2{{display:grid;grid-template-columns:1.4fr 1fr;gap:10px;
  background:none;border:0;border-radius:0;padding:0 10px}}
.grid2>div{{background:#fff;border:1px solid #e0e7f3;border-radius:12px;padding:0 14px 11px;
  box-shadow:0 1px 2px rgba(20,45,130,.05)}}
.obj{{font-size:13px;color:#3a4456;margin:0}}
/* o título já não precisa do fio: a borda do bloco faz a separação */
/* a faixa já traz o próprio fio — a regra antiga só o repetia */
/* Fio do campo na MESMA cor das bordas dos cards: o #f0f2f7 de antes sumia no
   fundo branco e os campos pareciam colados uns nos outros. O último não leva
   fio — a borda do bloco já fecha. */
/* COLUNA FIXA DE RÓTULO: todo rótulo ocupa a mesma fatia da largura, em
   qualquer linha de qualquer bloco. Assim os valores alinham na vertical e os
   fios divisórios ficam na mesma altura. Antes cada linha decidia sozinha se
   empilhava (regra do rótulo > 15 caracteres) e o bloco saía irregular. */
.f{{display:flex;align-items:baseline;gap:10px;padding:6px 0;border-bottom:1px solid #e6ecf6}}
.fk{{flex:0 0 44%;min-width:0;overflow-wrap:break-word;color:#6b7686}}
.fv{{flex:1;min-width:0;overflow-wrap:break-word;font-weight:600;text-align:right}}
/* só o último campo SOLTO no bloco perde o fio; dentro das grades de 2 colunas
   isso deixaria um lado com fio e o outro sem */
.bloco>.f:last-child{{border-bottom:0;padding-bottom:2px}}
.fv.vazio{{color:#b6bece;font-weight:400}}      /* "—": não veio, e não foi esquecido */
.f.nq .fv{{white-space:nowrap}}
/* campo com texto CORRIDO: empilha e alinha à esquerda (ver linha() no Python) */
.f.longa{{display:block}}
.f.longa .fv{{display:block;text-align:left;margin-top:3px;font-weight:500;line-height:1.45}}
/* O cabeçalho "Orçamento" ficava sozinho numa faixa vazia e os cartões vinham
   numa faixa separada — parecia seção quebrada. Agora é um bloco só. */
/* O ORÇAMENTO usa a folha inteira, de lateral a lateral: com 6 cartões de valor
   e nada podendo quebrar, dentro das margens do bloco o último era CORTADO.
   Full-bleed + auto-fit maior faz a fila quebrar em vez de estourar. */
.orc-bloco{{padding:0 14px 14px}}
/* campo do orçamento sem dado: dito com todas as letras, em cinza — melhor que
   um zero que parece informação */
.orc .vazio{{color:#8a94a6;font-weight:500;font-size:12px}}
/* ORÇAMENTO — faixa contínua, não seis caixinhas de largura fixa.
   O problema anterior era estrutural: colunas rígidas (repeat(N,1fr)) com o
   valor em `nowrap`. Um número longo — "R$ -1.217.012,16" — não cabia na fatia
   e vazava para FORA da folha. Aqui cada célula toma a largura do próprio
   conteúdo (`max-content`), divide a sobra com as demais e, se ainda assim não
   couber, QUEBRA para uma segunda linha em vez de transbordar. */
/* O vão de 1px + fundo do container = divisórias perfeitas, na horizontal E na
   vertical, inclusive entre linhas quebradas — o que `border-left` sozinho não
   dava (a 2ª linha ficava sem fio em cima). */
/* GRADE de 3 colunas, não flex. Com base flex de 30%, as 5 células viravam
   3 + 2, e as duas de baixo esticavam para metade da largura cada — o "Saldo"
   começava no meio do nada e nada alinhava na vertical. Em grade, a coluna 1 é
   a coluna 1 em toda linha. O fio de 1px entre as células é o `gap` deixando
   passar o fundo. */
/* DIVISÓRIA É BORDA, NÃO VÃO PINTADO. Antes o fio era o fundo do container
   aparecendo por um `gap` de 1px. Medido: as células caem em posição
   fracionária (a 1ª termina em 344,656 e a 2ª começa em 345,656), e um fio de
   1px aí não cobre um pixel inteiro do dispositivo — o navegador reparte a
   tinta entre dois pixels e, em tela com escala do Windows, ele some. Some em
   UMAS colunas e não em outras, porque cada uma cai numa fração diferente:
   era o padrão irregular que aparecia na tela.
   A prova estava na própria folha: o fio do saldo negativo é `inset 3px` e
   nunca sumiu. Borda entra no LAYOUT e o navegador garante um pixel para ela.
   A moldura vem de cima/esquerda aqui e de direita/baixo das células, para
   não dobrar o traço na borda externa. */
.orc{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:0;
  border-top:1px solid #c9d2e5;border-left:1px solid #c9d2e5;
  border-radius:12px;overflow:hidden;background:#fff}}
@media screen and (max-width:760px){{.orc{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}
@media screen and (max-width:430px){{.orc{{grid-template-columns:1fr}}}}
/* ULTIMA LINHA INCOMPLETA: a celula final ocupa as colunas que sobraram, em vez
   de dividir a fila com um retangulo em branco. `sp2` = ela mais uma coluna,
   `sp3` = ela mais duas. Como o numero de colunas muda com a largura da tela, o
   span tem de ser LIMITADO junto — um `span 3` numa grade de 2 colunas criaria
   uma terceira coluna e a moldura sairia torta. */
.orc .cel.sp2{{grid-column:span 2}}
.orc .cel.sp3{{grid-column:span 3}}
@media screen and (max-width:760px){{.orc .cel.sp3{{grid-column:span 2}}}}
@media screen and (max-width:430px){{.orc .cel.sp2,.orc .cel.sp3{{grid-column:span 1}}}}
/* as OUTRAS grades de 2 colunas do CPM: em tela estreita cada metade fica
   com ~150px e o rotulo (44%) espreme o valor em 3 linhas. Empilha. */
@media screen and (max-width:640px){{.grid2,.foot{{grid-template-columns:1fr}}}}
/* CABECALHO em tela estreita: logo, titulo e o numero do documento numa
   fila so espremiam o titulo em UMA PALAVRA POR LINHA. A fila quebra: logo
   e numero em cima, titulo com a largura toda embaixo. */
@media screen and (max-width:560px){{
  .top{{flex-wrap:wrap;gap:10px 12px}}
  .logo{{order:1}} .idbox{{order:2;margin-left:auto}} .ti{{order:3;flex:1 1 100%}}
}}
/* O FIO é pintado pela célula, não pelo vão. Um vão de 1px que cai em
   posição fracionária de pixel de tela some no arredondamento — e some de
   forma irregular, deixando o quadro com alguns fios e outros não. A sombra
   parte da borda já arredondada da célula e acompanha o arredondamento.
   O `overflow:hidden` do container apara as sombras da última coluna e da
   última linha. */
.orc .cel{{padding:9px 15px;background:#fff;display:flex;flex-direction:column;gap:2px;
  min-width:0;border-right:1px solid #c9d2e5;border-bottom:1px solid #c9d2e5}}
.orc .cl{{font-size:9px;color:#7b8798;text-transform:uppercase;letter-spacing:.7px;white-space:nowrap}}
.orc .cv{{font-weight:700;font-variant-numeric:tabular-nums;white-space:nowrap;
  font-size:14px;letter-spacing:-.3px;color:#1c2433}}
/* Saldo NEGATIVO é informação de decisão — precisa saltar aos olhos, mas sem
   virar caixa de alarme: um fio vertical e a cor no número bastam. */
/* o saldo negativo mantém os mesmos fios; o fio vermelho é o de dentro */
/* o saldo negativo mantém as mesmas bordas; o vermelho é um fio INTERNO */
.orc .cel.neg{{background:#fdf6f7;box-shadow:inset 3px 0 0 #d9534f}}
.orc .cel.neg .cl{{color:#a94442}}
.orc .cel.neg .cv{{color:#c0392b}}
.loc2{{padding:6px 0;border-bottom:1px dashed #e7ebf3;display:flex;justify-content:space-between;gap:10px}}
.loc2-t{{font-weight:600}} .loc2-s{{color:#6b7686}}
/* Locais de entrega em grade (evita o parágrafo justificado gigante) */
.loc-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(212px,1fr));
           gap:13px 26px;align-items:start}}
.loc-grid .loc2{{display:block;padding:0;border-bottom:0;break-inside:avoid;page-break-inside:avoid}}
.loc-grid .loc2-t{{display:block;line-height:1.35}}
.loc-grid .loc2-s{{font-size:11.5px;margin-top:2px;line-height:1.4}}
.loc-grid .uf{{display:inline-block;margin-left:5px;vertical-align:1px}}
.uf{{font-size:9.5px;font-weight:700;background:#eaf1ff;color:{AZUL};border:1px solid #d2e0fb;
     border-radius:20px;padding:1px 8px;letter-spacing:.3px;white-space:nowrap}}
/* Consultados = TABELA, não grade de proporção fixa. A proporção fixa (prazo
   com a maior fatia, p/ os casos de texto corrido) sobrava espaço quando o
   prazo era curto ("Pronta-entrega") e espremia o nome do fornecedor em 3
   linhas. Com `table-layout:auto` o navegador reparte pelo conteúdo REAL de
   todas as linhas, e a coluna que precisa é a que cresce.
   O VALOR fica com `width:1%`+nowrap: pega só o que o número ocupa. */
.cons-tab{{border:1px solid #dfe5f1;border-radius:10px;overflow:hidden}}
table.cons{{width:100%;border-collapse:collapse;table-layout:auto}}
/* padding NA CÉLULA + `vertical-align:top`: o fio lateral acompanha a altura
   inteira da linha, mesmo quando o nome do fornecedor quebra em 2-3 linhas. */
table.cons th,table.cons td{{padding:7px 12px;vertical-align:top;text-align:left}}
table.cons thead th{{font-size:9px;text-transform:uppercase;letter-spacing:.5px;color:#6b7686;
  font-weight:700;background:#f4f7fd;border-bottom:1px solid #cfd8e9}}
table.cons tbody td{{border-top:1px solid #dfe5f1}}
table.cons tbody tr:nth-child(even) td{{background:#fafbfe}}
table.cons th+th,table.cons td+td{{border-left:1px solid #dfe5f1}}
.cons-f{{font-weight:600}} .cons-p{{color:#3a4456}}
table.cons .cons-v{{text-align:right;font-weight:600;font-variant-numeric:tabular-nums;
  white-space:nowrap;width:1%}}
.muted{{color:#9aa3b2}}
.foot{{display:grid;grid-template-columns:1fr 1fr;gap:0 26px;margin:0 10px 8px;padding:11px 14px;
  background:#fff;border:1px solid #dfe5f1;border-radius:12px}}
/* Condições comerciais e Alçada agora ocupam a LARGURA TOTAL, empilhadas. Os
   campos ficam em 2 colunas: uma frase curta deixa de gastar 3 linhas por caber
   só metade da página. Campo com texto longo (.longa) atravessa as 2 colunas. */
.cond-bloco{{padding-bottom:6px}}
/* Locais dentro das Condições comerciais: ocupa as 2 colunas e a grade dos POPs
   entra logo abaixo do rótulo, sem mandar o leitor procurar noutra seção. */
.locais-campo{{grid-column:1/-1}}
.locais-campo .loc-grid{{margin-top:5px}}
.locais-campo .cont{{color:{AZUL};font-weight:700}}
/* mesma razao do .foot da AF: em duas colunas, um valor curto ("Anexo
   (proposta)") terminava no meio da folha ao lado de um vazio, e a linha
   parecia sem divisoria. */
.cond-grid{{display:block}}
.assin{{display:flex;flex-wrap:wrap;gap:26px 70px;justify-content:center;padding:24px 18px 30px;color:#6b7686}}
.assin div{{border-top:1px solid #98a2b3;margin-top:62px;padding-top:8px;min-width:230px;max-width:300px;text-align:center;font-size:11.5px;line-height:1.5}}
.assin b{{color:#1c2433}}
.rod{{text-align:center;color:#9aa3b2;font-size:11px;padding:0 0 14px}}
@page{{size:A4;margin:10mm 12mm}}
@media print{{{_PRINT_COMUM}
  /* PRÓPRIAS DO CPM. O `.foot>div` continua indivisível aqui de propósito:
     na AF ele foi retirado porque o rodapé de duas colunas saltava inteiro e
     deixava 273pt em branco, mas isso foi MEDIDO no layout da AF. Tirar do
     CPM sem medir seria mudar a paginação dele de carona. */
  .grid2>div,.foot>div,.orc .cel{{break-inside:avoid}}
  .bloco,.grid2,.foot,.orc{{break-inside:auto}}
}}
</style></head><body><div class="folha">
  <div class="top">{_logo_html()}
    <div class="ti"><div class="tit">{titulo}</div><div class="tisub">Relatório Técnico-Comercial · Eletronet S.A.</div></div>
    <div class="idbox"><div class="lbl">{'CPS nº' if c.get('tipo') == 'CPS' else 'CPM nº'}</div><div class="num">{_e(c.get('cpm_id'))}</div></div>
  </div>
  <div class="grid2">
    <div><div class="sec">Finalidade</div><div class="obj">{_e(c.get('finalidade'))}</div></div>
    <div><div class="sec">Identificação</div>
      {linha(_doc + ' associada', c.get('af_id'))}{linha('Data da ' + _coleta, _data_br(c.get('data_cpm')))}
      {linha('Data do relatório', _data_br(c.get('data_relatorio')))}{linha('Projeto', c.get('projeto') or c.get('proposta'))}</div>
  </div>
  <div class="bloco"><div class="sec">Justificativa da aquisição</div><div class="obj">{_e(c.get('justificativa'))}</div></div>
  <div class="bloco orc-bloco"><div class="sec">Orçamento</div>
    <div class="orc">{orc_html}</div>
  </div>
  {('<div class="bloco"><div class="sec">Câmbio</div>' + linha('Relação cambial', c.get('relacao_cambial')) + linha('Valor em Reais', _f(valor_reais_n, "R$")) + '</div>') if not eh_real else ''}
  <div class="bloco"><div class="sec">Consequências da não realização</div><div class="obj">{_e(c.get('consequencias'))}</div></div>
  <div class="bloco"><div class="sec">Fornecedores consultados</div>{cons_html}</div>
  <div class="bloco"><div class="sec">Atendimento &amp; recomendação</div>
    <div class="obj">{_e(c.get('atendimento'))}</div>
    {linha('Fornecedor recomendado', c.get('fornecedor_completo'))}{linha('Valor', vstr)}{(linha('Relação cambial', c.get('cotacao')) if c.get('cotacao') else '')}</div>
  <div class="bloco cond-bloco"><div class="sec">Condições comerciais</div>
    <div class="cond-grid">
      {linha('Prazo de entrega', c.get('prazo_entrega'))}{linha('Forma de pagamento', c.get('forma_pagamento'))}
      {linha('Anexo (proposta)', c.get('proposta'))}{local_linha}
    </div>
  </div>
  <div class="bloco"><div class="sec">Alçada &amp; aprovação</div>
    <div class="obj" style="font-size:11.5px;margin-bottom:6px">{_e(c.get('alcada'))}</div>
    <div class="cond-grid">{aprov_html or '<div class="muted">—</div>'}</div>
  </div>
  {locais_html}
  <div class="assin">{assin_html}</div>
  <div class="rod">Pré-visualização do CPM/CPS</div>
</div></body></html>"""


# --------------------------------------------------------------- render -----
def _norm_espacos_nome(s: str) -> str:
    """Nome do fornecedor enxuto para caber na faixa de rubrica."""
    n = re.sub(r"\s+", " ", str(s or "")).strip()
    return n if len(n) <= 34 else n[:33].rstrip(" ,.-") + "…"


# CSS da faixa de rubrica. Só entra no documento quando o campo está marcado:
# quem não pediu rubrica não paga nenhum preço de layout por ela.
#
# APARENCIA — vale nos dois modos (toda folha / so a ultima).
_CSS_RUBRICA_BASE = """
/* A ESQUERDA, do mesmo lado da Eletronet no documento. A Eletronet e a parte
   que confere e rubrica; alinhar a faixa com ela e o que o documento da casa
   faz. (Antes saia a direita, que e o lado do fornecedor.) */
.rubricas{display:flex !important;flex-direction:column;align-items:flex-start;gap:3px;
  padding:10px 26px 4px}
/* o recuo centra o rotulo sobre a linha de 165px — espelhado, porque o
   alinhamento virou para a esquerda */
.rubricas .rb-t{text-transform:uppercase;letter-spacing:.8px;font-size:8px;color:#98a2b3;
  padding-left:34px}
/* Tamanho calibrado pelo documento assinado que veio de exemplo: la cada caixa
   mede ~13x8mm. Aqui e uma caixa so (nao tres), e foi pedida MAIS ALTA — fica
   linha de ~44mm com ~13mm
   de espaco livre acima dela para escrever. */
.rubricas .rb-c{display:block;width:165px}
/* LINHA, nao caixa: so a borda de baixo. A altura e o espaco livre ACIMA
   da linha, para escrever a rubrica. */
.rubricas .rb-c i{display:block;height:58px;border-bottom:1px solid #c4ccda}
@media print{
  .rubricas{padding:14px 14px 2px;break-inside:avoid}
  .rubricas .rb-c i{height:52px}
}
"""

# SO NO MODO "TODAS AS FOLHAS": a maquina de rodape que se repete.
# O documento inteiro vira o <tbody> de uma tabela e a rubrica vira o <tfoot>.
# Isso custa uma tabela envolvendo o documento, e por isso so entra quando o
# modo pede — no modo "so a ultima" a faixa e um bloco comum no fim do fluxo,
# sem tabela nenhuma.
_CSS_RUBRICA_TODAS = """
/* A tabela-pagina nao pode ter aparencia nenhuma: ela existe so para dar ao
   documento um rodape que se repete e que RESERVA espaco no fluxo. */
table.pagina{width:100%;border-collapse:collapse}
table.pagina>tbody>tr>td,table.pagina>tfoot>tr>td{padding:0;border:0;background:none}
@media print{
  /* SO o rodape da tabela-pagina vira rodape de folha. O <tfoot> da tabela
     de ITENS ("Valor total") tem de continuar onde esta — repetido em toda
     folha ele viraria um total falso no pe de cada pagina. */
  table.pagina>tfoot{display:table-footer-group}
}
"""


def montar_html(d: dict) -> str:
    simb = _simbolo(d["moeda"])
    total = total_af(d)

    extenso = d.get("extenso", "")
    if (not extenso or "#" in extenso) and "lar" not in (d["moeda"] or "").lower():
        try:
            extenso = valor_por_extenso(float(total)) + "."
        except (ValueError, TypeError):
            pass

    logo = _logo_html()

    avisos_html = ""
    if d.get("avisos"):
        linhas = "".join(f"<div>{_e(a)}</div>" for a in d["avisos"])
        avisos_html = f'<div class="aviso"><strong>Atenção (dado da planilha de origem):</strong>{linhas}</div>'

    el = ELETRONET   # dados fixos da contratante (Eletronet)
    el_endereco = f'{el["endereco"]}, {el["bairro"]}'

    itens = ""
    # Célula vazia vira "—" discreto: em branco parecia dado faltando/erro.
    def _cel(v, classe="r"):
        return (f'<td class="{classe}">{v}</td>' if v
                else f'<td class="{classe} vazio">—</td>')

    def _imp(it):
        """Impostos do item como sub-linha da descrição.

        Coluna própria por imposto era o caminho óbvio e o errado: cada proposta
        usa um conjunto diferente (IPI aqui, ISS ali) e a tabela ficaria larga e
        cheia de vazio. Como sub-linha, cabe qualquer combinação e a Descrição
        continua com o espaço dela."""
        linhas = [x for x in (it.get("imp") or [])
                  if str((x or {}).get("nome", "")).strip()]
        if not linhas:
            return ""
        partes, dica = [], []
        for x in linhas:
            aliq = str(x.get("aliq", "")).strip().rstrip("%").strip()
            # zero à toa fora: "5,00" vira "5" — a mesma regra da etiqueta na
            # tela, senão o documento mostra uma grafia e o formulário outra
            aliq = re.sub(r"([.,])0+$", "", aliq)
            partes.append(f'{_e(x["nome"])} {_e(aliq)}%' if aliq else _e(x["nome"]))
            expl = IMPOSTOS_INFO.get(str(x["nome"]).strip().upper(), "")
            dica.append(f'{x["nome"]}: {expl}' if expl else str(x["nome"]))
        return f'<span class="it-imp" title="{_e(chr(10).join(dica))}">{" · ".join(partes)}</span>'

    for i, it in enumerate(d.get("itens", []), 1):
        itens += (
            f'<tr><td class="c ix">{i}</td><td class="cod">{_e(it["cod"])}</td>'
            f'<td class="desc">{_e(it["desc"])}{_imp(it)}</td>'
            f'{_cel(_e(it["qtd"]), "c qt")}'
            f'{_cel(_f(it["us"], simb) if it["us"] else "", "r pu")}'
            f'{_cel(_f(it["uc"], simb) if it["uc"] else "", "r pu")}'
            f'{_cel(_f(it["tot"], simb) if it["tot"] else "", "r tot")}</tr>')

    # Faturamento e entrega podem ter VÁRIOS locais por AF (lista). Mantém
    # compatibilidade com o dict único produzido por ler_af().
    faturamentos = d.get("faturamentos")
    if faturamentos is None:
        faturamentos = [d["faturamento"]] if d.get("faturamento") else []
    entregas = d.get("entregas")
    if entregas is None:
        entregas = [d["entrega"]] if d.get("entrega") else []

    def _fat_item(fat):
        sub = " · ".join(p for p in (
            _e(fat.get("endereco")),
            ("CEP " + _e(fat.get("cep"))) if fat.get("cep") else "",
            ("CNPJ " + _e(fat.get("cnpj"))) if fat.get("cnpj") else "") if p)
        tag = f'<span class="uf">{_e(fat.get("uf"))}</span>' if fat.get("uf") else ""
        return (f'<div class="loc2"><div class="loc2-t">{_e(fat.get("razao"))}{tag}</div>'
                f'<div class="loc2-s">{sub}</div></div>')

    def _ent_item(ent):
        cab = _e(ent.get("nome"))
        if ent.get("sigla"):
            cab += f' ({_e(ent.get("sigla"))})'
        local = "/".join(p for p in (_e(ent.get("municipio")), _e(ent.get("uf"))) if p)
        tag = f'<span class="uf">{local}</span>' if local else ""
        return (f'<div class="loc2"><div class="loc2-t">{cab}{tag}</div>'
                f'<div class="loc2-s">{_e(ent.get("endereco"))}</div></div>')

    fat_list = [f for f in faturamentos if f and (f.get("razao") or f.get("endereco") or f.get("uf"))]
    ent_list = [e for e in entregas if e and (e.get("nome") or e.get("municipio") or e.get("endereco"))]
    fat_html = ("".join(_fat_item(f) for f in fat_list) if fat_list
                else '<div class="muted">—</div>')
    ent_html = "".join(_ent_item(e) for e in ent_list)

    # FATURAMENTO ao lado da garantia só enquanto são POUCAS filiais. Com muitas,
    # a coluna da direita empilhava sete endereços enquanto a esquerda terminava
    # em três linhas — meia página em branco. A partir de 3, vira bloco de
    # largura total em grade, exatamente como os locais de entrega já fazem.
    fat_solto = len(fat_list) >= 3
    fat_bloco = (f'<div class="bloco locais fat"><div class="sec">Faturamento</div>'
                 f'<div class="loc-grid">{fat_html}</div></div>') if fat_solto else ""
    # Locais de entrega vira uma seção de LARGURA TOTAL em grade (várias colunas)
    # só quando há locais — evita a lista vertical gigante do lado do faturamento.
    locais_html = (f'<div class="bloco locais"><div class="sec">Locais de entrega</div>'
                   f'<div class="loc-grid">{ent_html}</div></div>') if ent_list else ""

    def campo(rot, val):
        # igual ao CPM: valor longo (ex.: cláusula de garantia) empilha e alinha
        # à esquerda em vez de ficar espremido à direita
        txt = str(val or "")
        cls = " longa" if len(txt) > 34 else ""
        # valor de UMA palavra (AF-E-256/2026-TR, CNPJ, CEP, data) não pode ser
        # partido no meio; frase com espaços quebra normalmente entre palavras.
        cls += " nq" if txt and " " not in txt.strip() else ""
        # mesma regra do CPM: rotulo com um branco do lado parece documento
        # impresso pela metade. "—" diz que a informacao nao veio.
        if not txt:
            return f'<div class="f{cls}"><span class="fk">{rot}</span><span class="fv vazio">—</span></div>'
        return f'<div class="f{cls}"><span class="fk">{rot}</span><span class="fv">{_e(val)}</span></div>'

    # RUBRICAS no pé (opcional). Duas linhas curtas — uma para cada parte —
    # e o nome miúdo embaixo, só para saber quem rubrica onde. Nada mais: quem
    # pediu foi claro que é "apenas as rubricas".
    _forn_curto = _norm_espacos_nome(d.get("fornecedor", "")) or "Fornecedor"
    # Os dois quadros vão num grupo e o espaço sai do `justify-content`.
    # UM retângulo só, da Eletronet. Quem rubrica a folha é quem confere o
    # documento aqui dentro; o fornecedor assina no fim e não rubrica folha a
    # folha. (Antes saíam três caixas — leitura errada minha do exemplo.)
    rubricas_html = ('<div class="rubricas"><span class="rb-t">Rubrica</span>'
                     '<span class="rb-c"><i></i></span></div>')
    # RODAPE DE PAGINA de verdade: o documento inteiro vira o <tbody> de uma
    # tabela e a rubrica vira o <tfoot>. `display:table-footer-group` repete o
    # rodape no pe de TODA folha e — o que importa — RESERVA o espaco dele no
    # fluxo. Medido com conteudo denso enchendo a folha: com `position:fixed`
    # sobravam 2pt entre o texto e a caixa (na pratica, por cima); com tfoot,
    # 21pt em todas as folhas. Foi isso que pos a caixa sobre o cartao de
    # locais de entrega.
    # Sem rubrica nao ha tabela nenhuma: quem nao pediu nao paga o preco.
    # O <tfoot> vem DEPOIS do <tbody> na marcacao. Antes dele, o navegador
    # desenha o rodape no TOPO da tela — na impressao daria certo, mas a previa
    # sairia com a rubrica antes do cabecalho do documento.
    #
    # DOIS MODOS. O padrão é rubricar SÓ A ÚLTIMA FOLHA; "todas as folhas" é
    # escolha explícita de quem gera. Cada modo usa um mecanismo diferente,
    # porque `table-footer-group` repete em toda folha POR DEFINIÇÃO — não há
    # como pedir a ele "só na última".
    #
    #   todas   -> tabela-pagina + <tfoot> (o mecanismo medido e descrito acima)
    #   ultima  -> bloco comum no fim do fluxo, DENTRO do grupo `.fim`
    #
    # No modo "ultima" a faixa entra junto com as notas fiscais e a assinatura,
    # que já viajam como peça única (`break-inside:avoid`). Assim ela não abre
    # folha sozinha — o mesmo problema que a assinatura teve e que custou uma
    # folha com 93% de papel branco.
    quer = bool(d.get("rubricas"))
    todas = quer and bool(d.get("rubricas_todas"))
    abre_pag = '<table class="pagina"><tbody><tr><td>' if todas else ""
    fecha_pag = ("</td></tr></tbody><tfoot><tr><td>" + rubricas_html
                 + "</td></tr></tfoot></table>") if todas else ""
    rubrica_ultima = rubricas_html if (quer and not todas) else ""
    # a faixa só existe se o campo estiver marcado; a máquina do rodapé que se
    # repete, só no modo que precisa dela
    css_rubricas = ((_CSS_RUBRICA_BASE + (_CSS_RUBRICA_TODAS if todas else ""))
                    if quer else "")

    # Assinaturas: Eletronet + fornecedor (as duas de sempre) e, depois, os
    # gestores que o usuário escolher para ESTA AF/AS — cada um com o cargo em
    # cima do nome, igual ao CPM/CPS.
    assin_af = '<div>Eletronet S.A</div><div>' + _e(d["fornecedor"]) + '</div>'
    for x in (d.get("assinantes") or []):
        nome = str((x or {}).get("nome", "")).strip()
        if nome:
            papel = str(x.get("papel", "")).strip() or "Responsável"
            assin_af += f'<div><b>{_e(papel)}</b><br>{_e(nome)}</div>'

    # Observações opcionais (fora do escopo padrão) — só aparece o bloco se houver.
    obs = [o for o in (d.get("observacoes") or []) if str(o).strip()]
    obs_html = ('<div class="bloco"><div class="sec">Observações</div><ul class="obs-list">'
                + "".join(f"<li>{_e(o)}</li>" for o in obs) + "</ul></div>") if obs else ""

    return f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<!-- sem esta linha o navegador finge uma janela de 980px e ENCOLHE a
     pagina: as @media de 760/430px nunca disparam e a previa fica presa
     no desenho de tela larga, ilegivel no celular. -->
<title>{_e(d["af_id"])} — {_e(d["fornecedor"])}</title>
<style>
*{{box-sizing:border-box}}
body{{margin:0;background:#eef1f6;color:#1c2433;font:13px/1.5 'Segoe UI',Arial,sans-serif}}
.folha{{max-width:1040px;margin:18px auto;background:#fff;border:1px solid #dbe2ee;border-radius:16px;overflow:hidden;box-shadow:0 1px 2px rgba(20,45,130,.10),0 10px 34px -12px rgba(20,45,130,.26)}}
.top{{display:flex;align-items:center;gap:16px;padding:16px 16px;border-bottom:3px solid {AZUL}}}
.logo{{height:44px}}
.ti{{flex:1}}
.tit{{font-size:18px;font-weight:700;color:#1c2433;letter-spacing:.3px}}
.tisub{{font-size:10px;letter-spacing:2px;text-transform:uppercase;color:#8a94a6;margin-top:5px}}
.idbox{{text-align:right;border:1px solid #dbe2ee;border-radius:12px;padding:7px 15px;background:#f7f9ff}}
.idbox .lbl{{font-size:9.5px;color:#6b7686;text-transform:uppercase;letter-spacing:1px}}
.idbox .num{{font:700 17px/1.2 Consolas,monospace;color:{AZUL};margin-top:2px}}
.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:0 26px;padding:14px 12px}}
/* Colunas proporcionais ao CONTEÚDO: Fornecedor e Contratante carregam endereço
   e razão social; Identificação só tem valores curtos (data, moeda, nº) e antes
   sobravam ~300px vagos nela enquanto o endereço quebrava em 4 linhas. */
.metagrid{{display:grid;grid-template-columns:1.15fr 1.15fr .9fr;gap:12px;padding:12px}}
/* NAS TRES CAIXAS DO TOPO o rotulo vai EM CIMA do valor, nao ao lado.
   Medido na largura real do papel (A4 util, 186mm): a caixa tem 201px; com o
   rotulo numa coluna fixa sobravam 87px para o valor — e o CNPJ precisa de 104
   e o "Originado da Licitacao" de 112. O valor era cortado na borda da caixa.
   O endereco, espremido em 87px, saia com duas palavras por linha e gastava
   cinco linhas.
   Empilhado, o valor usa os 190px inteiros: nada transborda, o endereco cai
   para duas linhas e a altura total fica parecida — o rotulo longo ja gastava
   duas linhas de qualquer jeito. Nos blocos LARGOS (garantia, condicoes) o
   lado a lado continua, que la sobra largura. */
.metagrid .f{{font-size:11.5px;display:block;padding:5px 0}}
.metagrid .fk{{display:block;font-size:10px;letter-spacing:.2px;line-height:1.35}}
.metagrid .fv{{display:block;text-align:left;margin-top:1px;line-height:1.4;
  overflow-wrap:break-word}}
.metagrid .f.nq .fv{{white-space:normal}}   /* na coluna larga ja nao precisa travar */
.metagrid .f.longa .fv{{margin-top:1px;font-weight:600}}
/* Só na TELA (prévia do app, que é estreita): 3 colunas espremidas picavam o
   endereço em 5 linhas. A folha impressa/PDF continua com as 3. */
@media screen and (max-width:700px){{.metagrid{{grid-template-columns:1fr 1fr}}}}
@media screen and (max-width:470px){{.metagrid{{grid-template-columns:1fr}}}}
/* mesma razao das faixas do topo: as grades de 2 colunas empilham antes de
   espremer rotulo e valor um contra o outro */
@media screen and (max-width:640px){{.grid2,.foot:not(.sozinho){{grid-template-columns:1fr}}}}
/* CABECALHO em tela estreita: logo, titulo e o numero do documento numa
   fila so espremiam o titulo em UMA PALAVRA POR LINHA. A fila quebra: logo
   e numero em cima, titulo com a largura toda embaixo. */
@media screen and (max-width:560px){{
  .top{{flex-wrap:wrap;gap:10px 12px}}
  .logo{{order:1}} .idbox{{order:2;margin-left:auto}} .ti{{order:3;flex:1 1 100%}}
}}
/* NÃO quebrar valor no meio: o `word-break:break-word` que havia aqui partia
   identificadores ("CPM-E-" / "BMW/2026-TR"). Só quebra em último caso. */
@media print{{.metagrid .fv{{word-break:normal;overflow-wrap:break-word}}}}
/* ONDE COMEÇA E ONDE TERMINA CADA SEÇÃO. Antes o título era só um texto azul
   com um fio embaixo e o conteúdo seguia solto: três seções em sequência viravam
   uma mancha só. Agora o título é uma FAIXA no topo de um bloco fechado — a
   faixa marca o começo, a borda do bloco marca o fim. */
.sec{{font-size:10.5px;font-weight:700;color:{AZUL};text-transform:uppercase;letter-spacing:.9px;
  margin:0 -13px 10px;padding:9px 13px 8px;background:#eef2fb;
  border-bottom:1px solid #dbe3f3;border-radius:11px 11px 0 0}}
/* cada seção é uma caixa: faixa de título no topo, fundo branco, borda fina e
   uma sombra de 1px que descola a caixa da folha sem pesar na impressão */
.metagrid>div,.foot>div{{background:#fff;border:1px solid #e0e7f3;border-radius:12px;
  padding:0 13px 11px;box-shadow:0 1px 2px rgba(20,45,130,.05)}}
/* mesmo fio do CPM: visível o bastante p/ marcar o limite de cada linha */
/* mesma régua do CPM: coluna fixa de rótulo, valores alinhados na vertical */
.f{{display:flex;align-items:baseline;gap:10px;padding:5px 0;border-bottom:1px solid #e6ecf6}}
.fk{{flex:0 0 44%;min-width:0;overflow-wrap:break-word;color:#6b7686}}
.fv{{flex:1;min-width:0;overflow-wrap:break-word;font-weight:600;text-align:right}}
.f:last-child{{border-bottom:0}}
.fv.vazio{{color:#b6bece;font-weight:400}}      /* "—": nao veio, e nao foi esquecido */
.f.nq .fv{{white-space:nowrap}}
/* campo com texto CORRIDO: empilha e alinha à esquerda (ver campo() no Python) */
.f.longa{{display:block}}
.f.longa .fv{{display:block;text-align:left;margin-top:3px;font-weight:500;line-height:1.45}}
.total{{margin:8px 12px 12px;background:linear-gradient(100deg,#f5f7ff,#eef1fb);border:1px solid #e3e8f0;border-left:4px solid {AZUL};border-radius:14px;padding:13px 20px;display:flex;align-items:center;justify-content:space-between;gap:20px}}
.total .lbl{{font-size:11px;color:#6b7686;text-transform:uppercase;letter-spacing:.8px}}
.total .val{{font-size:18px;font-weight:800;letter-spacing:-.3px;font-variant-numeric:tabular-nums}}
.total .ext{{font-size:11.5px;color:#6b7686;text-align:right;max-width:52%;text-transform:uppercase;line-height:1.45}}
.bloco{{margin:0 12px 12px;padding:0 13px 11px;background:#fff;border:1px solid #e0e7f3;
  border-radius:12px;box-shadow:0 1px 2px rgba(20,45,130,.05)}}
.obj{{font-size:13px;color:#3a4456;margin:0 0 12px}}
.obs-list{{margin:0;padding-left:20px;font-size:12.5px;line-height:1.6;color:#3a4456}}
.obs-list li{{margin:3px 0}}
/* Limites bem definidos e pontas arredondadas: com border-collapse:collapse o
   border-radius não é aplicado, então usamos separate + overflow:hidden p/ o
   fundo do cabeçalho ser recortado pelos cantos. */
table{{width:100%;border-collapse:separate;border-spacing:0;font-size:11px;line-height:1.4;
  border:1px solid #c6cfe6;border-radius:12px;overflow:hidden}}
/* Cabeçalho da tabela: era um BLOCO AZUL SÓLIDO — a única "caixa" pesada do
   documento, destoando do resto da AF, que usa azul só no texto dos títulos com
   um fio fino embaixo. Agora segue a mesma linguagem: fundo levemente tingido,
   texto na cor da marca e um fio azul firme embaixo separando do corpo. */
th{{background:#eef1fb;color:{AZUL};font-weight:700;text-align:left;padding:6px 7px;border-bottom:2px solid {AZUL}}}
/* A DESCRICAO pode quebrar DENTRO da palavra. Nao e capricho: as descricoes
   vem do PDF do fornecedor com palavras coladas — "extremidadeseumconector",
   "montadoemumadas" — porque o texto original perdeu os espacos. Palavra sem
   espaco nao quebra, e a largura MINIMA da coluna passa a ser o tamanho dela
   inteira: a tabela nao consegue encolher e sai pela borda da folha. Medido na
   AF-E-351/2026-GE: com a folha em 480px a tabela vazava 21px; em 420px, 81px.
   `anywhere` derruba essa largura minima para uma letra. */
td{{padding:5px 7px;border-bottom:1px solid #eceff5;vertical-align:top}}
/* SÓ a descrição. O `th` estava aqui junto e foi um tiro no pé: com o cabeçalho
   podendo quebrar dentro da palavra, a largura MÍNIMA da coluna de preço passou
   a ser UMA LETRA — e como essas colunas pedem `width:1%` (encolher até o
   conteúdo), o navegador deu a elas uma letra de largura. "Unitário" saiu
   escrito na vertical, uma letra por linha. O cabeçalho quebra entre palavras,
   como qualquer texto. */
td.desc{{overflow-wrap:anywhere}}
tbody tr:nth-child(even){{background:#f7f9fc}}
td.c,th.c{{text-align:center}}
/* algarismos de largura fixa: as colunas de preço alinham na vertical.
   O nowrap vale só para os NÚMEROS — quando valia também para o cabeçalho,
   "Preço unitário" não podia quebrar e cada coluna de preço reservava a largura
   do rótulo, espremendo a Descrição (no PDF ela quebrava palavra por palavra). */
td.r,th.r{{text-align:right;font-variant-numeric:tabular-nums}}
tbody td.r{{white-space:nowrap}}
thead th{{white-space:normal}}
/* Cabeçalho em 2 linhas: "Unit. s/imp." e "Unit. c/imp." eram crípticos e quase
   idênticos entre si — por extenso não há como confundir qual é qual. */
/* "sem impostos"/"com impostos" logo ABAIXO de "Unitário" e bem menores; todos os
   rótulos do cabeçalho começam na MESMA altura (vertical-align:top no th). */
.h1l{{display:block;font-weight:600;line-height:1.2}}
/* sem nowrap: o rótulo é UMA frase corrida ("Unitário sem impostos") e fica numa
   linha só quando cabe; se a folha apertar ele quebra, em vez de alargar a coluna
   e espremer a Descrição — que é a que precisa do espaço. */
.h2l{{display:block;font-size:7.5px;font-weight:400;opacity:.72;letter-spacing:.1px;
  text-transform:none;line-height:1.15}}
/* Modelo de larguras: as colunas curtas e as de preço têm teto, e a DESCRIÇÃO
   fica com todo o resto — é a coluna que mais precisa de espaço. Em A4 (bem mais
   estreito que a prévia) sem isso ela era a única a encolher. */
th{{vertical-align:top}}
/* Colunas DINÂMICAS: as curtas encolhem até o conteúdo (nowrap) e a DESCRIÇÃO
   recebe toda a sobra — width:100% numa célula faz ela absorver o espaço livre.
   Assim a descrição é sempre a maior, sem sobra de espaço nas de valor. */
th.desc,td.desc{{width:100%}}
th.ix,td.ix,th.qt,td.qt{{white-space:nowrap;width:1%}}
th.cod,td.cod{{white-space:nowrap;width:1%}}
th.pu,td.pu,th.tot,td.tot{{width:1%}}
/* DIVISÓRIAS entre colunas: sem elas, linha vazia (ou item sem preço) vira um
   borrão e não dá p/ saber onde termina cada coluna. Fio bem claro, só vertical. */
th.sep,td.sep{{border-right:none}}
tbody td + td, thead th + th{{border-left:1px solid #edf0f6}}
thead th + th{{border-left-color:#dbe1f2}}
/* o fio antes do TOTAL é mais forte: separa o que é insumo do que é resultado */
th.tot,td.tot{{border-left:1px solid #ccd3e4 !important}}
td.tot{{font-weight:700;background:#fafbfe}}
thead th.tot{{border-left-color:#c2cbe8 !important}}
/* impostos do item, discretos sob a descrição */
.it-imp{{display:block;margin-top:3px;font-size:9px;color:{AZUL};opacity:.85;
  text-transform:uppercase;letter-spacing:.4px;font-weight:700}}
td.vazio{{color:#b6bece}}                     /* "—" discreto no lugar de célula vazia */
/* O tfoot REPETIA no rodapé de cada página impressa, e o "Valor total" aparecia
   no meio da tabela como se ela tivesse acabado ali. Tratado como grupo normal,
   ele sai só uma vez, no fim de verdade. (O thead segue repetindo — esse deve.) */
tfoot{{display:table-row-group}}
/* Rodapé no mesmo espírito do cabeçalho: sem faixa preenchida, só um fio azul
   firme em cima fechando a tabela — o total já se destaca pelo peso da fonte. */
/* Rodapé: o VALOR FINAL é a informação que o leitor procura — fica maior, na cor
   da marca e com respiro, sem voltar a ser uma faixa preenchida pesada. */
tfoot td{{font-weight:700;border-top:2px solid {AZUL};background:none;white-space:nowrap;
  padding:9px 7px;border-bottom:none;font-size:12px}}
tfoot td.tot{{background:none;color:{AZUL};font-size:15px;letter-spacing:-.3px}}
tfoot .rotulo{{text-transform:uppercase;letter-spacing:.6px;font-size:10px;color:#6b7686}}
.foot{{display:grid;grid-template-columns:1fr 1fr;gap:12px;padding:0 12px 14px}}
/* Sem o faturamento ao lado, a garantia/prazo/pagamento usa a folha inteira e
   os campos se distribuem em duas colunas, em vez de ficar uma coluna magra
   com metade da página vazia à direita. */
.foot.sozinho{{grid-template-columns:1fr}}
/* UMA coluna. Em duas, "Garantia" (valor curto) ficava sozinha na metade
   esquerda e "Prazo de entrega" (frase inteira) empilhava na direita: os fios
   divisorios das duas colunas caiam em alturas diferentes e o bloco parecia
   quebrado. Em coluna unica todas as linhas tem a mesma largura e os fios
   fecham de ponta a ponta. */
.foot.sozinho > div{{display:block}}
.sub{{color:#6b7686;font-size:12px}}
.loc2{{padding:6px 0;border-bottom:1px dashed #e7ebf3}}
.loc2:last-child{{border-bottom:0}}
.loc2-t{{font-weight:600;display:flex;align-items:center;gap:8px;flex-wrap:wrap}}
.loc2-s{{color:#6b7686;font-size:12px;margin-top:1px;line-height:1.4}}
/* Locais de entrega em grade. O pill de UF pulava de linha em nome longo, as
   alturas ficavam desiguais e os tracejados terminavam "esfarrapados". Agora:
   sem borda por card, espaçamento regular e alinhamento pelo TOPO. */
/* mesmo recuo lateral do .bloco (13px): a faixa do título usa margem -13px p/
   sangrar até a borda, e com 12px aqui ela ficava 1px curta de cada lado */
.locais{{padding:0 13px 14px}}
.loc-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(212px,1fr));
           gap:13px 26px;align-items:start}}
.loc-grid .loc2{{padding:0;border-bottom:0;break-inside:avoid;page-break-inside:avoid}}
.loc-grid .loc2-t{{display:block;line-height:1.35}}
.loc-grid .loc2-s{{font-size:11.5px;margin-top:2px}}
.loc-grid .uf{{display:inline-block;margin-left:5px;vertical-align:1px}}
/* Pill LEVE (tinta clara + texto azul): usa menos tinta no papel e para de
   competir com o nome do POP, que é a informação principal. */
.uf{{font-size:9.5px;font-weight:700;background:#eaf1ff;color:{AZUL};border:1px solid #d2e0fb;
     border-radius:20px;padding:1px 8px;letter-spacing:.3px;white-space:nowrap}}
.assin{{display:flex;flex-wrap:wrap;gap:26px 60px;justify-content:center;padding:24px 14px 28px;color:#6b7686}}
.assin div{{border-top:1px solid #98a2b3;margin-top:62px;padding-top:6px;min-width:240px;max-width:320px;text-align:center;font-size:12px}}
.rod{{text-align:center;color:#9aa3b2;font-size:11px;padding:0 0 16px}}
.aviso{{margin:14px 26px 0;background:#fff7e6;border:1px solid #ffd591;border-left:4px solid #fa8c16;border-radius:8px;padding:9px 14px;color:#874d00;font-size:12.5px}}
.aviso strong{{display:block;margin-bottom:2px}}
/* RUBRICA — linha para rubricar a folha, opcional.
   Vai DENTRO do bloco de notas fiscais, à direita do texto, que é onde o
   documento da casa já a tem.

   Por que não é rodapé de página: foi tentado, e no motor do Edge um rodapé
   `position:fixed` é pintado SEMPRE dentro da área de conteúdo — ou seja, ele
   ocupa a última faixa da folha, justamente onde o texto e as bordas dos
   cartões chegam. Medidas as quatro saídas (bottom negativo, translateY,
   margem negativa e top calculado): todas fazem o Chromium tirar a faixa da
   primeira folha e jogá-la no TOPO das seguintes. E aumentar a margem da
   página não adianta: a faixa sobe junto com a área de conteúdo. No fluxo,
   sobreposição deixa de ser possível. */
.rubricas{{display:none}}   /* so aparece se o campo for marcado */
@page{{size:A4;margin:10mm 12mm}}
{css_rubricas}
@media print{{{_PRINT_COMUM}
  /* ----------------------------------------------------- só da AF/AS ----
     QUEBRA DE PAGINA: o que fica junto e o que FLUI. "break-inside: avoid"
     num bloco grande nao e um pedido, e uma ordem: se ele nao couber no resto
     da folha, salta inteiro e deixa o pe em branco. Medido numa AF de 16
     itens: 52% da 1a pagina vazia, so porque a tabela nao cabia.

     `.foot>div` NAO entra aqui, de proposito. Ele e CURTO, e num bloco curto
     o "avoid" e atendivel: atende-lo significa empurrar as duas colunas
     inteiras para a folha seguinte. Medido no AF-E-362: 273pt em branco no pe
     da 1a folha; num teste isolado, o mesmo bloco com "avoid" saltou deixando
     803pt e, sem ele, encheu a folha (sobra de 39pt). Quem continua
     indivisivel e o CAMPO: a coluna pode continuar na folha seguinte, mas
     nunca partindo um rotulo do seu valor. */
  .metagrid>div,.total,.aviso{{break-inside:avoid}}
  .foot .f{{break-inside:avoid}}
  /* RODAPE COMPACTO NO PAPEL — e o que faz ele CABER no pe da folha.
     `.foot` e um grid de UMA linha, e o Chromium nao parte uma linha de grid:
     ou ela cabe, ou salta inteira. Medido no AF-E-362: sobravam 249pt e o
     bloco pedia ~260pt — saltou por ~10pt e deixou 273pt em branco.
     Duas saidas foram medidas na varredura de 8 tamanhos de documento:
       • empilhar os dois cartoes no papel .... pior buraco 23%
       • encolher o respiro deles ............. pior buraco 21%
     A segunda ganha por pouco no numero e por muito no resto: empilhar faria
     o PDF deixar de ser igual a previa da tela, que e o ponto do formato
     "Visual". Aqui so sai respiro: os dois cartoes continuam lado a lado. */
  .foot{{padding-bottom:6px}}
  .foot>div{{padding:8px 10px;line-height:1.35}}
  /* a tabela FLUI: era o "avoid" nela que jogava as 16 linhas inteiras para a
     folha seguinte e deixava 52% da primeira em branco */
  table,.bloco,.foot,.metagrid{{break-inside:auto}}
  /* FATURAMENTO e a excecao: e um bloco CURTO (a Eletronet tem 6 filiais no
     maximo). Partido no meio, a segunda metade cai na folha seguinte sem
     titulo, e le como um bloco novo sem nome. Aqui o "avoid" custa poucos
     centimetros de folha e evita isso — diferente da tabela de itens, que e
     alta e deixava meia folha em branco. */
  .bloco.fat{{break-inside:avoid}}
  /* BLOCO NAO SE PARTE — pedido explicito: o unico divisivel e a tabela de
     objetos fornecidos. Os dois cartoes do rodape (Garantia/prazo/pagamento e
     Faturamento) partiam no meio: "Forma de pagamento" caia sozinha na folha
     seguinte, sem titulo, e do lado dela sobrava uma moldura vazia.
     Isto REVERTE uma decisao anterior minha. Deixa-los partir tapava um
     buraco de 273pt (32%) no pe de uma folha; agora esse buraco volta em
     algumas medidas, e e um preco aceito de proposito — meio cartao sem
     titulo lido como bloco novo confunde mais do que papel em branco. */
  .foot>div{{break-inside:avoid}}
  /* A LISTA DE LOCAIS FLUI. Com 19 POPs o cartao passa de meia folha; sendo
     indivisivel, ele saltava inteiro e deixava ate 55% de papel branco
     (medido na varredura). Cada LOCAL continua indivisivel, entao a lista
     pode continuar na folha seguinte sem nunca separar o nome do POP do seu
     endereco. O titulo orfao, que motivou a indivisibilidade, custa uma
     linha; o buraco custava meia folha. */
  .bloco.locais{{break-inside:auto}}
  /* ASSINATURA NUNCA SOZINHA NUMA FOLHA. Medido no AF-E-362: a folha 3 tinha
     só "Eletronet S.A / NEC Latin America S.A." e 93% de papel branco.
     `break-before:avoid` sozinho NAO resolveu — numa varredura de 8 tamanhos,
     dois ainda deixavam a assinatura orfa. O Chromium ignora break-before e
     break-after; respeita break-inside. Por isso as notas fiscais e a
     assinatura vao dentro de `.fim`, que e indivisivel: ~160pt no total, cabe
     quase sempre, e quando nao cabe os dois descem juntos. */
  /* `.fim` e so da AF: e aqui que as notas fiscais e a assinatura viajam
     juntas. O encolhimento da assinatura no papel ficou no bloco comum, que
     e de onde ele tinha de ter saido desde o comeco. */
  .fim{{break-inside:avoid}}
}}
</style></head><body>
<div class="folha">{abre_pag}
  <div class="top">
    {logo}
    <div class="ti"><div class="tit">{_e(d["titulo"])}</div><div class="tisub">Eletronet S.A. · Documento eletrônico</div></div>
    <div class="idbox"><div class="lbl">Autorização nº</div><div class="num">{_e(d["af_id"])}</div></div>
  </div>
  {avisos_html}
  <div class="metagrid">
    <div>
      <div class="sec">Fornecedor</div>
      {campo("Razão social", d["fornecedor"])}
      {campo("CNPJ", d["cnpj"])}
      {campo("Inscrição Estadual", d["ie"])}
      {campo("Endereço", _end_curto(d["endereco"], d["fornecedor"]))}
      {campo("CEP", d["cep"])}
      {campo("Data da proposta", _data_br(d.get("data_proposta", ""))) if d.get("data_proposta") else ""}
    </div>
    <div>
      <div class="sec">Contratante · Eletronet</div>
      {campo("Razão social", el["razao"])}
      {campo("CNPJ", el["cnpj"])}
      {campo("Inscrição Estadual", el["ie"])}
      {campo("Endereço", el_endereco)}
      {campo("CEP", el["cep"])}
    </div>
    <div>
      <div class="sec">Identificação</div>
      {campo("Originado da Licitação", d["cpm"])}
      {campo("Proposta", d["proposta"])}
      {campo("Data de emissão", _data_br(d["data"]))}
      {campo("Moeda", d["moeda"])}
    </div>
  </div>
  <div class="total">
    <div><div class="lbl">Valor total</div><div class="val">{_f(total, simb)}</div></div>
    <div class="ext">{_e(extenso)}</div>
  </div>
  <div class="bloco tabela">
    <div class="sec">Objeto do fornecimento</div>
    <div class="obj">{_e(d["objeto"])}</div>
    <table>
      <thead><tr>
        <th class="c ix">#</th>
        <th class="cod">Código</th>
        <th class="desc">Descrição do item</th>
        <th class="c qt">Qtd</th>
        <th class="r pu"><span class="h1l">Unitário</span><span class="h2l">sem impostos</span></th>
        <th class="r pu sep"><span class="h1l">Unitário</span><span class="h2l">com impostos</span></th>
        <th class="r tot">Total</th>
      </tr></thead>
      <tbody>{itens}</tbody>
      <tfoot><tr><td colspan="6" class="r rotulo">Valor total</td><td class="r tot">{_f(total, simb)}</td></tr></tfoot>
    </table>
  </div>
  <div class="foot{' sozinho' if fat_solto else ''}">
    <div><div class="sec">Garantia, prazo &amp; pagamento</div>{campo("Garantia", d["garantia"])}{campo("Prazo de entrega", d["prazo"])}{campo("Forma de pagamento", d.get("pagamento", "")) if d.get("pagamento") else ""}</div>
    {'' if fat_solto else f'<div><div class="sec">Faturamento</div>{fat_html}</div>'}
  </div>
  {fat_bloco}
  {locais_html}
  {obs_html}
  <!-- FIM DO DOCUMENTO: notas fiscais e assinatura andam juntas. Separadas,
       a assinatura abria folha sozinha (medido: 93% de papel branco). O
       Chromium ignora break-before/after; o que ele respeita e
       break-inside, entao as duas viram uma peca so. -->
  <div class="fim">
    <div class="bloco">
      <div class="sec">Notas fiscais</div>
      <div class="obj" style="font-size:11.5px;line-height:1.55">
        <b>•</b> Por motivo de fechamento fiscal, a data de recebimento/emissão das notas fiscais será até o dia <b>25 do mês corrente</b>; notas recebidas/emitidas entre os dias 26 a 31 não serão aceitas.<br>
        <b>•</b> Enviar NF para <b>controladoria@eletronet.com</b> e <b>engenharia@eletronet.com</b>.
      </div>
    </div>
    <div class="assin">{assin_af}</div>
  </div>{rubrica_ultima}
  <div class="rod">Pré-visualização HTML da AF</div>{fecha_pag}
</div></body></html>"""
