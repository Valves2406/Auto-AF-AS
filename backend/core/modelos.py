"""
modelos.py — domínio do Gerador de AF (Eletronet).
===================================================
Estruturas de dados (ItemAF, DadosProposta), moedas, conversões e o
"valor por extenso" em PT-BR (validado contra AFs reais da Eletronet).
"""

from __future__ import annotations

import re
import unicodedata
import dataclasses
from dataclasses import dataclass, field

# Opções fixas do identificador.
# A letra do meio segue para o CPM/CPS (AF-M → CPM-M, AS-M → CPS-M):
# ver `_parte()`/`_cpm_de()` em core/gerador.py.
PREFIXOS = ["AF-E", "AF-O", "AF-M", "AS-E", "AS-O", "AS-M"]
# "N/A" = documento SEM modificação: o sufixo simplesmente não entra no
# identificador nem no nome do arquivo (AF-E-444/2026 em vez de .../2026-TR).
MODIFICACOES = ["TR", "GE", "IP", "MV", "N/A"]
SEM_MODIFICACAO = {"", "-", "N/A", "NA", "N/D", "NENHUMA"}
RODAPE = "Vinicius.M.Alves"

# Dados da contratante (Eletronet) — endereço da R. Verbo Divino (matriz/filial SP).
ELETRONET = {
    "razao": "ELETRONET S.A.",
    "endereco": "R. Verbo Divino, 2001, Torre A, andar 14º",
    "bairro": "Granja Julieta - São Paulo-SP",
    "cnpj": "03.052.673/0003-45",
    "cnpj_digitos": "03052673000345",
    "ie": "115920209117",
    "cep": "04719-002",
}


# ----------------------------------------------------------------- moedas --
def _m(simb, sing, plur, sub="centavo", sub_pl="centavos"):
    return {"simb": simb, "fmt": f'"{simb}" #,##0.00',
            "sing": sing, "plur": plur, "sub": sub, "sub_pl": sub_pl}

MOEDAS: dict[str, dict] = {
    "Real":             _m("R$",  "real", "reais"),
    "Dólar Americano":  _m("US$", "dólar americano", "dólares americanos"),
    "Euro":             _m("€",   "euro", "euros"),
    "Yuan (Renminbi)":  _m("CN¥", "yuan", "yuans", "fen", "fen"),
    "Peso Argentino":   _m("$",   "peso argentino", "pesos argentinos"),
    "Peso Chileno":     _m("CLP$", "peso chileno", "pesos chilenos"),
    "Peso Colombiano":  _m("COL$", "peso colombiano", "pesos colombianos"),
    "Sol Peruano":      _m("S/",  "sol", "soles", "céntimo", "céntimos"),
    "Guarani":          _m("₲",   "guarani", "guaranis", "céntimo", "céntimos"),
    "Peso Uruguaio":    _m("$U",  "peso uruguaio", "pesos uruguaios"),
    "Boliviano":        _m("Bs",  "boliviano", "bolivianos"),
}
MOEDAS_ORDEM = list(MOEDAS.keys())


# APELIDOS: o nome da moeda nem sempre chega como a chave do catálogo. O
# extrator lê a proposta e devolve "Dólar"; alguém pode digitar "USD" ou "US$".
# Antes isso caía no default (Real) SEM AVISO, e o efeito era grave: o documento
# imprimia "US$ 100.000,00" — porque o desenho usava outra regra, por pedaço do
# nome — enquanto a conversão para reais e a ALÇADA tratavam o mesmo número como
# R$ 100.000. A cotação digitada não mudava nada e o Saldo saía errado.
_APELIDOS = {
    "dolar": "Dólar Americano", "dolar americano": "Dólar Americano",
    "usd": "Dólar Americano", "us$": "Dólar Americano", "dol": "Dólar Americano",
    "euro": "Euro", "eur": "Euro", "€": "Euro",
    "yuan": "Yuan (Renminbi)", "renminbi": "Yuan (Renminbi)", "cny": "Yuan (Renminbi)",
    "peso argentino": "Peso Argentino", "ars": "Peso Argentino",
    "peso chileno": "Peso Chileno", "clp": "Peso Chileno",
    "peso colombiano": "Peso Colombiano", "cop": "Peso Colombiano",
    "sol": "Sol Peruano", "sol peruano": "Sol Peruano", "pen": "Sol Peruano",
    "guarani": "Guarani", "pyg": "Guarani",
    "peso uruguaio": "Peso Uruguaio", "uyu": "Peso Uruguaio",
    "boliviano": "Boliviano", "bob": "Boliviano",
    "real": "Real", "reais": "Real", "brl": "Real", "r$": "Real",
}


def _sem_acento(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t)
                   if unicodedata.category(c) != "Mn")


def moeda_nome(nome: str) -> str:
    """O nome que o catálogo entende. Devolve "Real" quando não reconhece."""
    bruto = (nome or "").strip()
    if bruto in MOEDAS:                       # o caminho normal: veio da tela
        return bruto
    chave = _sem_acento(bruto).lower()
    if chave in _APELIDOS:
        return _APELIDOS[chave]
    # último recurso: o nome CONTÉM o de uma moeda ("Dólar dos EUA", "em Euros")
    for apelido, oficial in _APELIDOS.items():
        if len(apelido) > 3 and apelido in chave:
            return oficial
    return "Real"


def moeda_info(nome: str) -> dict:
    return MOEDAS[moeda_nome(nome)]


# ----------------------------------------------------- valor por extenso ---
_UNID = ["", "um", "dois", "três", "quatro", "cinco", "seis", "sete", "oito",
         "nove", "dez", "onze", "doze", "treze", "quatorze", "quinze",
         "dezesseis", "dezessete", "dezoito", "dezenove"]
_DEZ = ["", "", "vinte", "trinta", "quarenta", "cinquenta", "sessenta",
        "setenta", "oitenta", "noventa"]
_CEM = ["", "cento", "duzentos", "trezentos", "quatrocentos", "quinhentos",
        "seiscentos", "setecentos", "oitocentos", "novecentos"]
_ESCALA = [("", ""), ("mil", "mil"), ("milhão", "milhões"),
           ("bilhão", "bilhões"), ("trilhão", "trilhões")]


def _ate_999(n: int) -> str:
    if n == 0:
        return ""
    if n == 100:
        return "cem"
    partes = []
    c, resto = divmod(n, 100)
    if c:
        partes.append(_CEM[c])
    if resto:
        if resto < 20:
            partes.append(_UNID[resto])
        else:
            d, u = divmod(resto, 10)
            partes.append(_DEZ[d] + (" e " + _UNID[u] if u else ""))
    return " e ".join(partes)


def _inteiro_extenso(n: int) -> str:
    if n == 0:
        return "zero"
    chunks = []
    while n > 0:
        chunks.append(n % 1000)
        n //= 1000
    out = []
    for idx in range(len(chunks) - 1, -1, -1):
        g = chunks[idx]
        if g == 0:
            continue
        texto = _ate_999(g)
        if idx == 1:
            texto = "mil" if g == 1 else texto + " mil"
        elif idx >= 2:
            sing, plur = _ESCALA[idx]
            texto = texto + " " + (sing if g == 1 else plur)
        out.append(texto)
    return ", ".join(out)


def valor_por_extenso(valor, unidade: str = "real", unidade_pl: str = "reais",
                      sub: str = "centavo", sub_pl: str = "centavos") -> str:
    """Converte um valor monetário em texto por extenso (MAIÚSCULAS).
    Ex.: 488847.76 -> 'QUATROCENTOS E OITENTA E OITO MIL, OITOCENTOS E QUARENTA
    E SETE REAIS E SETENTA E SEIS CENTAVOS'."""
    if valor is None:
        return ""
    valor = round(float(valor) + 1e-9, 2)
    intp = int(valor)
    cent = int(round((valor - intp) * 100))
    if cent >= 100:
        intp += 1
        cent -= 100
    partes = []
    if intp == 0 and cent == 0:
        return ("zero " + unidade_pl).upper()
    if intp > 0:
        partes.append(_inteiro_extenso(intp) + " " + (unidade if intp == 1 else unidade_pl))
    if cent > 0:
        partes.append(_ate_999(cent) + " " + (sub if cent == 1 else sub_pl))
    return " e ".join(partes).upper()


# ------------------------------------------------------------ conversões ---
def brl_para_float(s) -> float | None:
    """Converte texto monetário em float. Aceita BR ("1.142.297,80"), US
    ("1,142,297.80" — o ÚLTIMO separador é o decimal) e número puro ("180099.59").
    Devolve None se não houver número."""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    t = re.sub(r"[^\d,.\-]", "", str(s)).strip()
    if not t:
        return None
    if "," in t and "." in t:          # os dois separadores → o último é o decimal
        if t.rfind(",") > t.rfind("."):
            t = t.replace(".", "").replace(",", ".")   # BR: 1.142.297,80
        else:
            t = t.replace(",", "")                     # US: 1,142,297.80
    elif "," in t:                     # só vírgula → formato BR: 297,80
        t = t.replace(".", "").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def float_para_brl(v) -> str:
    try:
        x = float(v)
    except (ValueError, TypeError):
        return ""
    return f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


# --------------------------------------------------------------- dados -----
@dataclass
class ItemAF:
    codigo: str = ""
    descricao: str = ""
    quantidade: str = ""
    unidade: str = ""
    preco_unit_sem: str = ""
    preco_unit_com: str = ""
    preco_total_com: str = ""
    garantia: str = ""        # cada produto pode ter garantia própria
    prazo: str = ""           # ...e prazo de entrega próprio
    # Impostos do item: [{"nome": "IPI", "aliq": "5"}, …]. Ficam por PRODUTO
    # porque numa mesma proposta o IPI muda de item para item (e serviço leva
    # ISS onde mercadoria leva ICMS). O preço "com impostos" sai daqui.
    impostos: list = dataclasses.field(default_factory=list)


@dataclass
class DadosProposta:
    arquivo: str = ""
    caminho_pdf: str = ""
    fornecedor: str = ""
    cnpj: str = ""
    endereco: str = ""
    cep: str = ""
    insc_est: str = ""
    numero_proposta: str = ""
    data: str = ""
    valor_total: str = ""
    condicao_pagamento: str = ""
    objeto: str = ""
    garantia: str = ""
    prazo_entrega: str = ""
    moeda: str = "Real"
    itens: list[ItemAF] = field(default_factory=list)
    observacoes: list[str] = field(default_factory=list)   # obs. opcionais (fora do escopo padrão)
    # Filial da ELETRONET a quem a proposta foi endereçada, quando ela diz.
    # Vem casada pelo CNPJ com o catálogo de locais de faturamento.
    faturamentos: list = field(default_factory=list)
    # Locais de ENTREGA que a própria proposta lista (um quadro por
    # localidade, por exemplo). Cada um: nome, sigla, município, UF, endereço.
    entregas: list = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    usou_ocr: bool = False
    sug_prefixo: str = ""
    sug_numero: str = ""
    sug_modificacao: str = ""
