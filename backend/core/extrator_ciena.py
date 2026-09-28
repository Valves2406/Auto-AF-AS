"""
extrator_ciena.py — lê a PROPOSTA da CIENA (Excel "DDPTool") e separa cada
projeto em dois: AF (equipamento/material = CapEx) e AS (serviço = OpEx). A
CIENA cota em DÓLAR (DDP) — a AF/AS saem em dólar.

Dois formatos
-------------
• UM projeto: abas "Resumo de Preços" + "Detalhamento de Preços" → 1 AF + 1 AS.
• PACOTE ("Bundle"): pares "Resumo X" + "Detalhamento X", um por projeto, e uma
  aba do pacote com o total geral → cada projeto vira 1 AF + 1 AS (3 projetos,
  6 documentos). O formato é o mesmo aba a aba; só se repete.

A aba Detalhamento é uma matriz item × site
-------------------------------------------
    Código | Descrição | preço BA | preço DF | … | site 1 | site 2 | … | Qtde TOTAL
A linha ACIMA do cabeçalho dá a UF de cada site. A AF/AS da CIENA leva o
CÓDIGO, a DESCRIÇÃO, a QUANTIDADE TOTAL e o TOTAL do bloco — SEM preço por
item, conforme definido: o mesmo item custa diferente em SP e em BA, e um
unitário "médio" não bateria com nenhum preço da proposta.

Os preços por estado servem de CONFERÊNCIA: site a site, quantidade × preço do
estado do site, somado, tem de dar o TOTAL da própria planilha. Fechando, a
leitura das quantidades está certa; não fechando, o documento sai com um aviso
("confira as quantidades") em vez de um total que não bate com os itens.
"""

from __future__ import annotations

import re
from datetime import datetime

from .modelos import float_para_brl

IC, ID = 2, 3          # C = código, D = descrição (índices 0-based)
# O nome de site às vezes traz o EQUIPAMENTO junto ("Serra Exemplo WS5", "Vale
# Exemplo 6500") e às vezes é só o equipamento ("WS5", "WL6E"). O lugar é o que sobra.
_EQUIP_NO_NOME = re.compile(r"\b(WS5|WS|6500|WL6E?|WL5E?|WAVESERVER\d*)\b", re.I)
_NAO_E_LUGAR = {"LICENSES", "LICENCAS", "LICENÇAS", "LICENSE"}


def _txt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _resumo(itens: list[dict]) -> str:
    """Objeto = primeiras palavras das descrições DISTINTAS (igual às AF prontas)."""
    partes: list[str] = []
    for it in itens:
        d = " ".join((it.get("descricao") or "").split()[:5]).strip(" ,")
        if d and d.lower() not in [p.lower() for p in partes]:
            partes.append(d)
    if not partes:
        return ""
    if len(partes) > 1:
        txt = ", ".join(partes[:-1]) + " e " + partes[-1] + "."
    else:
        txt = partes[0] + "."
    return (txt[:297] + "…") if len(txt) > 300 else txt


def _uf(v) -> str:
    t = _txt(v).upper()
    return t if len(t) == 2 and t.isalpha() else ""


def _lugar(nome_site: str) -> str:
    """'Serra Exemplo WS5\\n SEX_VEX' → 'Serra Exemplo'; 'WS5' → '' (não é lugar)."""
    primeira = (nome_site or "").strip().splitlines()[0] if (nome_site or "").strip() else ""
    lugar = " ".join(_EQUIP_NO_NOME.sub(" ", primeira).split())
    if not lugar or lugar.upper() in _NAO_E_LUGAR:
        return ""
    return lugar.title()


def _ler_detalhamento(linhas: list[tuple]) -> dict | None:
    """Uma aba Detalhamento → itens de equipamento e de serviço, com valor."""
    i_cab = next((i for i, row in enumerate(linhas)
                  if len(row) > IC and _txt(row[IC]).lower().startswith(("código", "codigo"))), None)
    if i_cab is None:
        return None
    cab = linhas[i_cab]
    acima = linhas[i_cab - 1] if i_cab > 0 else ()
    # "Qtde TOTAL" é a ÚLTIMA célula não-vazia do cabeçalho (varia com o nº de sites)
    iq = next((j for j in range(len(cab) - 1, ID, -1) if _txt(cab[j])), None)
    if iq is None:
        return None
    precos: dict[str, int] = {}          # UF → coluna do preço daquele estado
    sites: list[tuple[int, str, str]] = []   # (coluna, nome do site, UF)
    for j in range(ID + 1, iq):
        nome = _txt(cab[j]) if j < len(cab) else ""
        uf_acima = _uf(acima[j]) if j < len(acima) else ""
        if uf_acima:                                  # site: a UF vem na linha de cima
            sites.append((j, nome, uf_acima))
        elif _uf(nome):                               # coluna de preço do estado
            precos[_uf(nome)] = j

    def _valor(row) -> float | None:
        """Σ quantidade no site × preço do estado do site."""
        tot = 0.0
        for j, _nome, uf in sites:
            q = _num(row[j]) if j < len(row) else None
            if not q:
                continue
            jp = precos.get(uf) if uf in precos else (next(iter(precos.values())) if len(precos) == 1 else None)
            p = _num(row[jp]) if jp is not None and jp < len(row) else None
            if p is None:
                return None
            tot += q * p
        return tot

    blocos = {"equip": [], "serv": []}
    totais = {"equip": None, "serv": None}
    usados: set[int] = set()                          # colunas de site com alguma quantidade
    modo = None
    for row in linhas[i_cab + 1:]:
        cod = _txt(row[IC]) if len(row) > IC else ""
        desc = _txt(row[ID]) if len(row) > ID else ""
        qtd = _num(row[iq]) if len(row) > iq else None
        cu, du = cod.upper(), desc.upper()
        if cu.startswith("TOTAL EQUIP"):
            totais["equip"] = qtd if qtd is not None else totais["equip"]
            modo = None
            continue
        if cu.startswith("TOTAL SERV"):
            totais["serv"] = qtd if qtd is not None else totais["serv"]
            modo = None
            continue
        if not cod:                                   # linha de seção/divisória
            if du == "EQUIPAMENTO":
                modo = "equip"
            elif du.startswith("SERVI"):
                modo = "serv"
            continue
        if cu == "EQUIPAMENTO":                       # (a seção às vezes vem na coluna C)
            modo = "equip"
            continue
        if cu.startswith("SERVI"):
            modo = "serv"
            continue
        if modo and desc and qtd and qtd > 0:         # item de verdade
            for j, _n, _u in sites:
                if j < len(row) and _num(row[j]):
                    usados.add(j)
            # a quantidade do documento é a "Qtde TOTAL"; ela tem de ser a soma
            # dos sites — senão a conta abaixo conferiria um número e o
            # documento mostraria outro
            q_sites = sum(_num(row[j]) or 0 for j, _n, _u in sites if j < len(row))
            v = _valor(row)
            blocos[modo].append({"codigo": cod, "descricao": desc, "quantidade": _txt(qtd),
                                 "unidade": "UN",
                                 "_valor": v if abs(q_sites - qtd) < 1e-9 else None})

    lados = {}
    for modo, itens in blocos.items():
        total = totais[modo]
        soma = sum(it["_valor"] for it in itens) if itens and all(it["_valor"] is not None for it in itens) else None
        # a conta tem de fechar com o TOTAL da planilha (meio por cento de folga
        # para o arredondamento da própria planilha)
        fecha = bool(soma is not None and total and abs(soma - total) <= max(0.01, 0.005 * total))
        for it in itens:
            it.pop("_valor")
            it.update(preco_unit_sem="", preco_unit_com="", preco_total_com="")
        avisos = []
        if itens and total and not fecha:
            avisos.append("As quantidades × preços da planilha não fecham com o total do bloco "
                          f"(US$ {float_para_brl(total)}) — confira as quantidades dos itens.")
        lados[modo] = {"itens": itens,
                       "valor_total": float_para_brl(total) if total is not None else "",
                       "objeto": _resumo(itens),
                       "conta_fecha": fecha, "avisos": avisos}

    # destinos: um por LUGAR (o mesmo site aparece em várias colunas, uma por
    # equipamento), só os que recebem alguma coisa
    entregas, vistos = [], set()
    for j, nome, uf in sites:
        lugar = _lugar(nome)
        if j not in usados or not lugar or (lugar.upper(), uf) in vistos:
            continue
        vistos.add((lugar.upper(), uf))
        entregas.append({"nome": lugar, "sigla": "", "municipio": lugar, "uf": uf, "endereco": ""})
    if not blocos["equip"] and not blocos["serv"]:
        return None
    # as UFs que recebem ALGO — inclusive a coluna das licenças e o site sem
    # nome de lugar ("WS5" em SP): é por elas que sai a filial de faturamento
    ufs = list(dict.fromkeys(uf for j, _n, uf in sites if j in usados))
    return {"af": lados["equip"], "as": lados["serv"], "entregas": entregas,
            "ufs": ufs, "sem_lugar": bool(ufs) and not entregas}


def _titulo(linhas: list[tuple]) -> str:
    """O nome do projeto é o primeiro texto da aba (acima do cabeçalho)."""
    for row in linhas[:6]:
        for v in row:
            t = _txt(v)
            if t and not t.lower().startswith(("código", "codigo", "preços", "precos", "true")) and len(t) > 8:
                return t
    return ""


def _categorias(r_linhas: list[tuple]) -> dict:
    """As linhas de CapEx e de OpEx da aba Resumo ("Equipamento 6500 (HW, SW)",
    "Serviços de Instalação"…): o que a própria CIENA diz que está vendendo,
    em poucas palavras — objeto melhor que emendar descrição de item."""
    out, bloco = {"af": [], "as": []}, None
    for row in r_linhas:
        for j, v in enumerate(row):
            t = _txt(v)
            if not t:
                continue
            tu = t.upper()
            if tu == "CAPEX":
                bloco = "af"
            elif tu == "OPEX":
                bloco = "as"
            elif tu.startswith(("TOTAL", "GRAN TOTAL", "INFORMATIVO")):
                bloco = None
            elif bloco and _num(row[j + 1] if j + 1 < len(row) else None) is not None:
                out[bloco].append(t)
            break                                     # uma célula de texto por linha
    return out


def _objeto(titulo: str, categorias: list[str], itens: list[dict]) -> str:
    if not categorias:
        return _resumo(itens)
    lista = categorias[0] if len(categorias) == 1 else ", ".join(categorias[:-1]) + " e " + categorias[-1]
    return f"{titulo}: {lista}." if titulo else lista + "."


def _data(ws_linhas: list[tuple]) -> str:
    """A data que vem logo abaixo de 'DATA:' na aba Resumo."""
    for i, row in enumerate(ws_linhas):
        for j, v in enumerate(row):
            if _txt(v).upper().startswith("DATA"):
                for prox in ws_linhas[i + 1:i + 3]:
                    d = prox[j] if j < len(prox) else None
                    if isinstance(d, datetime):
                        return d.strftime("%d/%m/%Y")
    return ""


def ler_ciena(caminho: str) -> dict | None:
    """Proposta CIENA → {projetos: [{projeto, data, entregas, af, as}, …]}.

    Os campos de sempre (projeto, entregas, af, as) continuam no topo, com o
    PRIMEIRO projeto — quem lia o formato de um projeto só segue funcionando.
    Não sendo proposta CIENA, devolve None."""
    try:
        from openpyxl import load_workbook
        wb = load_workbook(caminho, data_only=True, read_only=True)
    except Exception:
        return None
    try:
        nomes = list(wb.sheetnames)
        dets = [s for s in nomes if s.lower().startswith("detalhamento")]
        if not dets:
            return None
        resumo_unico = next((s for s in nomes if "resumo de pre" in s.lower()), None)
        projetos = []
        for aba in dets:
            linhas = list(wb[aba].iter_rows(values_only=True))
            p = _ler_detalhamento(linhas)
            if not p:
                continue
            sufixo = aba[len("detalhamento"):].strip().lower()
            if sufixo.startswith("de pre"):                       # formato de um projeto só
                resumo = resumo_unico
            else:
                resumo = next((s for s in nomes if s.lower().startswith("resumo")
                               and s[len("resumo"):].strip().lower() == sufixo), None)
            r_linhas = list(wb[resumo].iter_rows(values_only=True)) if resumo else []
            titulo = _titulo(linhas)
            if not titulo and r_linhas:                           # formato antigo: "Projeto ..."
                titulo = next((_txt(v) for row in r_linhas for v in row
                               if _txt(v).lower().startswith("projeto")), "")
            p.update(projeto=titulo, data=_data(r_linhas), aba=aba)
            cats = _categorias(r_linhas)
            for lado in ("af", "as"):
                p[lado]["objeto"] = _objeto(titulo, cats[lado], p[lado]["itens"])
            projetos.append(p)
        if not projetos:
            return None
        aba_pacote = next((s for s in nomes if s.lower().startswith("bundle")), None)
        pacote, data_pacote = "", ""
        if aba_pacote:
            pl = list(wb[aba_pacote].iter_rows(values_only=True))
            pacote = next((_txt(v) for row in pl for v in row if _txt(v).lower().startswith("bundle")), "")
            data_pacote = _data(pl)
    finally:
        wb.close()

    p0 = projetos[0]
    return {
        "ok": True, "eh_ciena": True,
        "moeda": "Dólar Americano",
        "prazo_entrega": "24~28 semanas",
        "pacote": pacote, "data_proposta": data_pacote or p0["data"],
        # cada projeto: os destinos valem para os DOIS lados (o serviço é
        # executado onde o equipamento é entregue)
        "projetos": projetos,
        "projeto": p0["projeto"], "entregas": p0["entregas"],
        "af": p0["af"], "as": p0["as"],
    }
