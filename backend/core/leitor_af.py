# -*- coding: utf-8 -*-
r"""leitor_af.py — lê de volta a AF/AS que o próprio app (ou o modelo Excel) gerou.

ENGENHARIA REVERSA DO NOSSO DOCUMENTO, NÃO ADIVINHAÇÃO
------------------------------------------------------
A proposta do fornecedor tem mil formatos; a AF, não. Quem a desenhou fomos
nós, então cada informação tem um lugar fixo e um TÍTULO que diz o que é. O
leitor antigo tratava a AF como se fosse proposta — procurava pedaços de texto
soltos — e perdia exatamente o que o desenho deixa óbvio:

    faturamento e locais de entrega   0 de 93 AFs lidas
    garantia, prazo, pagamento        cortados na 1ª linha (texto de várias)
    CEP                               o da ELETRONET no lugar do fornecedor
    nº da proposta                    o próprio nº da AF, em 23 de 93

TRÊS DESENHOS, O MESMO PRINCÍPIO
--------------------------------
  visual (v1 e v2)   o PDF que o app monta em HTML. Rótulo e valor têm ESTILOS
                     diferentes e o PDF os preserva palavra a palavra:
                         título de seção   negrito, azul
                         rótulo            regular, cinza
                         valor             seminegrito, escuro
                     O v1 põe o rótulo AO LADO do valor; o v2, EM CIMA. Pelo
                     estilo, os dois se leem igual — a posição deixa de importar.
  modelo             o modelo Excel impresso em PDF (paisagem). Rótulo com
                     dois-pontos e valor à direita; as seções de baixo são
                     numeradas; a tabela tem borda em cada célula, e são as
                     bordas que dizem onde uma linha acaba.

O QUE JÁ SABEMOS NÃO SE LÊ DE NOVO
----------------------------------
Faturamento e local de entrega vêm do catálogo quando a AF é montada. Na volta,
o CNPJ da filial e a sigla do POP identificam o registro inteiro — melhor do que
remontar endereço de um texto quebrado em duas colunas. O texto do PDF só vale
quando o registro não está no catálogo.
"""
from __future__ import annotations

import re
import unicodedata

from .log import get_logger

LOG = get_logger("leitor_af")


# --------------------------------------------------------------- utilidades --
def _semac(s) -> str:
    return unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()


def _chave(s) -> str:
    """"Garantia, prazo & pagamento" -> "GARANTIA PRAZO PAGAMENTO"."""
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]", " ", _semac(s).upper())).strip()


def _junto(s) -> str:
    """A chave SEM espaço. O PDF mais novo perde o espaço dos rótulos: o CSS
    põe espaçamento entre letras, o espaço vira um vão menor que o normal e o
    extrator funde "Razão social" em "Razãosocial". Comparar sem espaço deixa
    as duas grafias iguais."""
    return _chave(s).replace(" ", "")


def _so_num(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


def _rgb(c) -> tuple:
    if c is None:
        return (0.0, 0.0, 0.0)
    if isinstance(c, (int, float)):
        return (float(c),) * 3
    try:
        c = tuple(float(x) for x in c)
    except (TypeError, ValueError):
        return (0.0, 0.0, 0.0)          # cor de padrão (pattern): trata como texto comum
    if len(c) == 1:
        return c * 3
    if len(c) == 3:
        return c
    if len(c) == 4:                     # CMYK
        C, M, Y, K = c
        return ((1 - C) * (1 - K), (1 - M) * (1 - K), (1 - Y) * (1 - K))
    return (0.0, 0.0, 0.0)


class _P:
    """Uma palavra do PDF com o que importa: onde está e COMO está escrita."""
    __slots__ = ("t", "x0", "x1", "top", "bot", "pag", "tam", "fonte", "rgb")

    def __init__(self, w: dict, pag: int):
        self.t = w["text"]
        self.x0, self.x1 = float(w["x0"]), float(w["x1"])
        self.top, self.bot = float(w["top"]), float(w["bottom"])
        self.pag = pag
        self.tam = round(float(w.get("size") or 0), 1)
        self.fonte = str(w.get("fontname") or "")
        self.rgb = _rgb(w.get("non_stroking_color"))

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def peso(self) -> str:
        f = self.fonte.lower()
        if "black" in f or "heavy" in f:
            return "black"
        if "semibold" in f or "demibold" in f or "semi" in f or "medium" in f:
            return "semi"
        if "bold" in f:
            return "bold"
        return "reg"

    @property
    def azul(self) -> bool:
        r, g, b = self.rgb
        return b >= 0.7 and r <= 0.35 and g <= 0.45

    @property
    def claro(self) -> bool:
        return sum(self.rgb) / 3 > 0.66 and not self.azul

    @property
    def rotulo(self) -> bool:
        """Rótulo = texto REGULAR, nem azul nem claro. O PESO decide, não a cor:
        o valor é sempre seminegrito, e peso de fonte não muda com CMYK."""
        return self.peso == "reg" and not self.azul and not self.claro and not self.branco

    @property
    def branco(self) -> bool:
        """Texto branco: o cabeçalho da tabela do v1 é branco sobre azul."""
        return min(self.rgb) >= 0.95


def _linhas(ps, tol: float = 2.6) -> list[list[_P]]:
    """Palavras em linhas de leitura (mesma folha, mesma altura)."""
    linhas: list[list[_P]] = []
    for p in sorted(ps, key=lambda p: (p.pag, p.top, p.x0)):
        if linhas and linhas[-1][0].pag == p.pag and abs(linhas[-1][0].top - p.top) <= tol:
            linhas[-1].append(p)
        else:
            linhas.append([p])
    return [sorted(l, key=lambda p: p.x0) for l in linhas]


def _juntar_linhas(textos) -> str:
    """Junta linhas de uma célula. Hífen no FIM da linha é quebra do HTML e
    não espaço: "CPM-E-" + "302/2026-GE", "03.052.673/0020-" + "46"."""
    out = ""
    for s in textos:
        s = (s or "").strip()
        if not s:
            continue
        if not out:
            out = s
        elif re.search(r"\S-$", out):
            out += s
        else:
            out += " " + s
    return out


def _texto(ps) -> str:
    return _juntar_linhas(" ".join(p.t for p in l) for l in _linhas(ps))


_MOEDA_SIMB = re.compile(r"^(?:R\$|US\$|U\$|\$|€|EUR|USD|BRL|CN¥|¥|£)$", re.I)


def _dinheiro(txt: str) -> str:
    """"R$ 19.131,20" -> "19.131,20"; "—" -> "". Tira também o espaço que o
    PDF enfia no meio do número ("R$ 2 5.520,44")."""
    s = str(txt or "").replace("—", "").replace("–", "")
    s = re.sub(r"(R\$|US\$|U\$|€|EUR|USD|BRL|CN¥|¥|£|\$)", " ", s, flags=re.I)
    s = re.sub(r"(?<=[\d.,])\s+(?=[\d.,])", "", s.strip())
    s = re.sub(r"(?<=-)\s+(?=\d)", "", s)
    return s.strip()


def _valor_rotulado(txt: str) -> str:
    """Tira o "—" de campo vazio e espaços sobrando."""
    s = re.sub(r"\s+", " ", str(txt or "")).strip()
    return "" if s in ("—", "-", "–") else s


_RE_AF_ID = re.compile(r"\b(A[FS]-[A-Z0-9]+-\d+/\d{4}(?:-(?!REV)[A-Z0-9]+)?(?:-REV\d+)?)\b", re.I)
_RE_CPM_ID = re.compile(r"\b(CP[MS]-[A-Z0-9]+-\d+/\d{4}(?:-(?!REV)[A-Z0-9]+)?(?:-REV\d+)?)\b", re.I)
_RE_CNPJ = re.compile(r"\d{2}\.?\d{3}\.?\d{3}\s?/\s?\d{4}\s?-\s?\d{2}")
_RE_DATA = re.compile(r"\b\d{2}/\d{2}/\d{4}\b")


def _cnpj_fmt(s: str) -> str:
    n = _so_num(s)
    return f"{n[:2]}.{n[2:5]}.{n[5:8]}/{n[8:12]}-{n[12:]}" if len(n) == 14 else str(s or "").strip()


# ------------------------------------------------------------- o catálogo --
def _catalogo():
    """Filiais (por CNPJ) e POPs (por sigla) — o que o app já conhece."""
    try:
        from . import dados_eletronet as de
        fat = {_so_num(f.get("cnpj")): dict(f) for f in de.locais_faturamento() if f.get("cnpj")}
        pops = de.pops_entrega()
    except Exception as exc:                     # catálogo é ajuda, não pode travar a leitura
        LOG.warning("catálogo indisponível ao ler a AF: %s", exc)
        fat, pops = {}, []
    return fat, pops


def _faturamento_do_catalogo(achado: dict, fat_cat: dict) -> dict:
    reg = fat_cat.get(_so_num(achado.get("cnpj")))
    if reg:
        return dict(reg)
    return {"uf": achado.get("uf", ""), "razao_social": achado.get("razao_social", ""),
            "cnpj": achado.get("cnpj", ""), "endereco": achado.get("endereco", ""),
            "cep": achado.get("cep", ""), "cnpj2": achado.get("cnpj", ""),
            "insc_est": "", "insc_mun": ""}


def _tokens_endereco(s) -> set:
    return {t for t in _chave(s).split() if len(t) >= 3 or t.isdigit()}


def _pop_por_endereco(txt: str, pops: list) -> dict | None:
    """POP cujo endereço de cadastro está contido no texto livre da AF.

    O modelo antigo (2025) escreve o local de entrega como uma linha de
    endereço, sem sigla: "Av. Alfredo Egídio de Souza Aranha, 100 / 13ºA
    Bloco D...". O número da rua tem de bater — rua sozinha não identifica."""
    alvo = _tokens_endereco(txt)
    melhor, nota = None, 0.0
    for p in pops:
        tk = _tokens_endereco(p.get("endereco"))
        nums = [t for t in tk if t.isdigit()]
        if len(tk) < 3 or not nums or nums[0] not in alvo:
            continue
        n = len(tk & alvo) / len(tk)
        if n > nota:
            melhor, nota = p, n
    return dict(melhor) if melhor and nota >= 0.75 else None


def _entrega_do_catalogo(achado: dict, pops: list) -> dict:
    """POP pela SIGLA (identidade forte do cadastro); sem sigla, pelo nome +
    município. Duas estações com a mesma sigla (raro) desempatam pelo nome."""
    sig = _chave(achado.get("sigla"))
    nome, mun = _chave(achado.get("nome")), _chave(achado.get("municipio"))
    cands = [p for p in pops if sig and _chave(p.get("sigla")) == sig]
    if len(cands) > 1 and nome:
        cands = [p for p in cands if _chave(p.get("nome")) == nome] or cands
    if not cands and nome:
        cands = [p for p in pops if _chave(p.get("nome")) == nome
                 and (not mun or _chave(p.get("municipio")) == mun)]
    if cands:
        return dict(cands[0])
    return {"nome": achado.get("nome", ""), "sigla": achado.get("sigla", ""),
            "endereco": achado.get("endereco", ""), "municipio": achado.get("municipio", ""),
            "uf": achado.get("uf", "")}


# ======================================================== LAYOUT VISUAL ======
# Os títulos de seção que o app escreve (html_render.montar_html), já na forma
# de `_chave`. "Objeto do ..." varia entre AF e AS e é tratado à parte.
_SECOES = {"FORNECEDOR": "forn", "CONTRATANTEELETRONET": "contr",
           "IDENTIFICACAO": "ident", "GARANTIAPRAZOPAGAMENTO": "cond",
           "FATURAMENTO": "fat", "LOCAISDEENTREGA": "ent",
           # uma geração juntou os dois num cartão só, com subtítulos em
           # negrito ESCURO dentro dele (AF-E-242)
           "FATURAMENTOENTREGA": "fatent",
           "OBSERVACOES": "obs", "NOTASFISCAIS": "nf"}
_SUBTITULOS = {"FATURAMENTO", "LOCAISDEENTREGA"}
# Os rótulos (`campo(...)`), para juntar o que o v1 quebra em duas linhas
# ("Razão" / "social") sem juntar dois rótulos vizinhos.
_ROTULOS = ("RAZAO SOCIAL", "CNPJ", "INSCRICAO ESTADUAL", "ENDERECO", "CEP",
            "DATA DA PROPOSTA", "ORIGINADO DA LICITACAO", "PROPOSTA", "DATA DE EMISSAO",
            "MOEDA", "GARANTIA", "PRAZO DE ENTREGA", "FORMA DE PAGAMENTO", "VALOR TOTAL")
_ROTULO_CANON = {r.replace(" ", ""): r for r in _ROTULOS}


def _rotulo(txt: str) -> str:
    """A grafia canônica do rótulo, com ou sem os espaços que o PDF perdeu."""
    j = _junto(txt)
    return _ROTULO_CANON.get(j, _chave(txt))


class _Titulo:
    __slots__ = ("sec", "pag", "top", "bot", "x0", "xr", "ws")

    def __init__(self, sec, pag, top, bot, x0, ws=()):
        self.sec, self.pag, self.top, self.bot, self.x0, self.xr = sec, pag, top, bot, x0, 1e9
        self.ws = list(ws)


def _titulos(ps, larguras) -> list[_Titulo]:
    """Os títulos de seção: palavras azuis em negrito formando um nome conhecido
    (e os subtítulos escuros do cartão combinado "Faturamento & entrega")."""
    cand = [p for p in ps if p.peso in ("bold", "black")]
    tits = []
    for lin in _linhas(cand):
        grupo = [lin[0]]
        for p in lin[1:] + [None]:
            if p is not None and p.x0 - grupo[-1].x1 <= 12 and p.azul == grupo[-1].azul:
                grupo.append(p)
                continue
            k = _junto(" ".join(g.t for g in grupo))
            if grupo[0].azul:
                sec = _SECOES.get(k) or ("objeto" if k.startswith("OBJETOD") else None)
            else:
                sec = _SECOES.get(k) if k in _SUBTITULOS else None
            if sec:
                tits.append(_Titulo(sec, grupo[0].pag, min(g.top for g in grupo),
                                    max(g.bot for g in grupo), grupo[0].x0, grupo))
            if p is not None:
                grupo = [p]
    # "VALOR TOTAL" do quadro do topo: cinza, sem negrito, logo acima do objeto.
    # Vira fronteira: sem ela, o total e o extenso caíam dentro dos cartões de
    # cima (estão debaixo deles na folha) e viravam rótulo de Identificação.
    obj = next((t for t in tits if t.sec == "objeto"), None)
    for lin in _linhas([p for p in ps if p.rotulo and p.pag == 0]):
        if _junto(" ".join(p.t for p in lin)).startswith("VALORTOTAL") \
                and (obj is None or lin[0].top < obj.top):
            tits.append(_Titulo("total", 0, lin[0].top, lin[0].bot, 0.0))
            break
    # largura de cada título: até o próximo título NA MESMA ALTURA, à direita
    for t in tits:
        viz = [u.x0 for u in tits if u is not t and u.pag == t.pag
               and abs(u.top - t.top) < 4 and u.x0 > t.x0 + 5]
        t.xr = (min(viz) - 3) if viz else larguras[t.pag] + 1
        if t.sec == "total":
            t.x0, t.xr = 0.0, larguras[t.pag] + 1
    return sorted(tits, key=lambda t: (t.pag, t.top, t.x0))


def _repartir(ps, tits) -> dict:
    """Cada palavra vai para a seção cujo título está ACIMA dela e cuja faixa
    horizontal a contém. Sem título acima na folha, é continuação da folha
    anterior (a tabela de itens que passou de folha)."""
    secoes: dict[str, list[_P]] = {}
    marcadas = {id(p) for t in tits for p in t.ws}   # o título não é conteúdo
    for p in ps:
        if id(p) in marcadas:
            continue
        dono = None
        for t in tits:
            if t.x0 - 4 <= p.cx < t.xr and (t.pag < p.pag or (t.pag == p.pag and t.top <= p.top + 1)):
                if dono is None or (t.pag, t.top) >= (dono.pag, dono.top):
                    dono = t
        secoes.setdefault(dono.sec if dono else "cab", []).append(p)
    return secoes


def _rotulos_valores(ps) -> dict:
    """Dentro de um cartão: rótulo (cinza, sem peso) -> valor (o que vem ao
    lado ou embaixo dele, até o próximo rótulo)."""
    rot = sorted([p for p in ps if p.rotulo], key=lambda p: (p.pag, p.top, p.x0))
    frases: list[list[_P]] = []
    for p in rot:
        if frases:
            f = frases[-1]
            ult = f[-1]
            mesma_linha = ult.pag == p.pag and abs(ult.top - p.top) <= 2.5 and 0 <= p.x0 - ult.x1 <= 9
            desceu = (ult.pag == p.pag and 0 < p.top - ult.top <= 2.0 * max(p.tam, 6)
                      and abs(p.x0 - f[0].x0) <= 3)
            junto = _junto(" ".join(q.t for q in f) + " " + p.t)
            if mesma_linha or (desceu and any(r.startswith(junto) for r in _ROTULO_CANON)):
                f.append(p)
                continue
        frases.append([p])
    valores = [p for p in ps if not p.rotulo and not p.azul
               and not (p.claro and p.t in ("—", "-", "–"))]
    out: dict[str, list[_P]] = {}
    ordem = []
    for p in valores:
        # Dono = o rótulo mais recente ACIMA ou À ESQUERDA do valor — nunca um
        # à direita. Há cartão que põe "Garantia" e "Prazo de entrega" lado a
        # lado na mesma linha, e "Não a garantia." ia parar no prazo.
        dono = None
        for f in frases:
            if (f[0].pag, f[0].top) <= (p.pag, p.top + 2.5) and f[0].x0 <= p.x0 + 3:
                if dono is None or (f[0].pag, round(f[0].top, 1), f[0].x0) >= \
                        (dono[0].pag, round(dono[0].top, 1), dono[0].x0):
                    dono = f
        if dono is None:
            continue
        k = _rotulo(" ".join(q.t for q in dono))
        if k not in out:
            ordem.append(k)
        out.setdefault(k, []).append(p)
    res = {k: _valor_rotulado(_texto(out[k])) for k in ordem}
    for f in frases:                        # rótulo presente e valor "—"
        res.setdefault(_rotulo(" ".join(q.t for q in f)), "")
    return res


# ---- tabela de itens --------------------------------------------------------
def _cabecalhos_itens(ps, larguras) -> list[dict]:
    """Um cabeçalho de tabela por folha (o thead se repete)."""
    cabs = []
    # azul no v2; BRANCO sobre fundo azul no v1
    cor = [p for p in ps if p.azul or p.branco]
    for desc in [p for p in cor if _junto(p.t).startswith("DESCRICAO")]:
        grupo = [p for p in cor if p.pag == desc.pag and desc.top - 16 <= p.top <= desc.top + 26]
        cols = {}
        # setdefault: a PRIMEIRA palavra de cada tipo, da esquerda para a
        # direita. No v1 o cabeçalho do Total é "Total do item — quantidade ×
        # unitário", e esse "quantidade" tomava o lugar da coluna Qtd.
        for p in sorted(grupo, key=lambda p: p.x0):
            k = _junto(p.t)
            if p.t.strip() == "#":
                cols.setdefault("ix", p)
            elif k.startswith("CODIGO"):
                cols.setdefault("cod", p)
            elif k.startswith("DESCRICAO"):
                cols.setdefault("desc", p)
            elif k in ("QTD", "QUANT", "QTDE"):
                cols.setdefault("qtd", p)
            elif k in ("UN", "UNID", "UNIDADE"):
                cols.setdefault("un", p)
            elif k.startswith("UNIT"):             # "Unitário" ou "Unit. s/imp."
                cols.setdefault("uc" if "us" in cols else "us", p)
        if not {"desc", "qtd"} <= set(cols):
            continue
        # Cada coluna medida pelo GRUPO de palavras do título na mesma linha
        # ("Unit." + "s/imp."): é a borda direita do grupo que alinha com os
        # valores, e com só a 1ª palavra o unitário ia parar na coluna Total.
        chaves = {id(p) for p in cols.values()}
        bordas_dir = {}
        for k, p in cols.items():
            fim = p.x1
            for q in sorted(grupo, key=lambda q: q.x0):
                if abs(q.top - p.top) <= 2 and q.x0 > fim and q.x0 - fim <= 6 and id(q) not in chaves:
                    fim = q.x1
            bordas_dir[k] = fim
        direita = max(p.x1 for p in grupo)           # a coluna Total fecha a tabela
        cabs.append({"pag": desc.pag, "top": min(p.top for p in grupo),
                     "bot": max(p.bot for p in grupo), "cols": cols, "direita": direita,
                     "bordas_dir": bordas_dir, "esq": min(p.x0 for p in grupo) - 6})
    return cabs


def _fim_da_tabela(ps, cab, tits, altura) -> float:
    fim = altura
    for lin in _linhas([p for p in ps if p.pag == cab["pag"] and p.top > cab["bot"]]):
        k = _junto(" ".join(p.t for p in lin))
        if "VALORTOTAL" in k and lin[0].x0 > cab["cols"]["desc"].x0:
            fim = min(fim, lin[0].top - 1)
            break
    for t in tits:
        if t.pag == cab["pag"] and t.top > cab["bot"]:
            fim = min(fim, t.top - 1)
    return fim


def _celulas(ps) -> list[list[_P]]:
    """Junta "R$" + "19.131,20" (e "R$ 2" + "5.520,44") numa célula só.

    Célula nova quando vem outro "R$", ou um número depois de outro número
    com vão de espaço entre eles. Só a distância não bastava: no v1 as colunas
    "com impostos" e "Total" ficam coladas, e o total voltava "93,06558,36"."""
    cel = []
    for lin in _linhas(ps):
        g = [lin[0]]
        for p in lin[1:]:
            vao = p.x0 - g[-1].x1
            tem_num = any(re.search(r"\d", q.t) for q in g)
            nova = (vao > 5 or (_MOEDA_SIMB.match(p.t) and tem_num)
                    or (re.search(r"\d", p.t) and re.search(r"\d", g[-1].t) and vao > 1.5))
            if nova:
                cel.append(g)
                g = [p]
            else:
                g.append(p)
        cel.append(g)
    return cel


def _impostos_da_linha(txt: str) -> list[dict]:
    """"IPI 5% · ICMS 18%" -> [{"nome": "IPI", "aliq": "5"}, ...]."""
    out = []
    for parte in re.split(r"\s*·\s*", txt or ""):
        m = re.match(r"\s*([A-Za-zÀ-ÿ/ ]+?)\s*([\d.,]+)?\s*%?\s*$", parte)
        if m and m.group(1).strip():
            out.append({"nome": m.group(1).strip(), "aliq": (m.group(2) or "").strip()})
    return out


def _itens_visual(ps, tits, larguras, alturas) -> list[dict]:
    itens = []
    for cab in _cabecalhos_itens(ps, larguras):
        cols, pag = cab["cols"], cab["pag"]
        fim = _fim_da_tabela(ps, cab, tits, alturas[pag])
        corpo = [p for p in ps if p.pag == pag and cab["bot"] < p.top < fim and p.x1 > cab["esq"]]
        x_cod = cols["cod"].x0 if "cod" in cols else cols["desc"].x0
        x_desc = cols["desc"].x0
        x_num = cols["qtd"].cx - 10               # daqui para a direita, números
        inicios = sorted([p for p in corpo if p.cx < x_cod - 2 and re.fullmatch(r"\d{1,3}", p.t)],
                         key=lambda p: p.top)
        # âncoras das colunas numéricas: centralizada compara o centro;
        # alinhada à direita, a borda direita
        ancoras = []
        for k, al in (("qtd", "c"), ("un", "c"), ("us", "r"), ("uc", "r")):
            if k in cols:
                ancoras.append((k, al, cols[k].cx if al == "c" else cab["bordas_dir"][k]))
        ancoras.append(("tot", "r", cab["direita"]))
        for i, ini in enumerate(inicios):
            fim_l = inicios[i + 1].top - 2 if i + 1 < len(inicios) else fim
            ws = [p for p in corpo if ini.top - 2 <= p.top < fim_l]
            cod = [p for p in ws if x_cod - 3 <= p.x0 < x_desc - 3 and p.cx >= x_cod - 2]
            desc = [p for p in ws if p.x0 >= x_desc - 3 and p.cx < x_num]
            # a linha "IPI 5% · ICMS 18%" é a única coisa AZUL na coluna da
            # descrição (miúda e em negrito); o texto do produto é escuro
            imp = [p for p in desc if p.azul]
            desc = [p for p in desc if p not in imp]
            num = {k: [] for k, _, _ in ancoras}
            for c in _celulas([p for p in ws if p.cx >= x_num]):
                c0, c1 = c[0].x0, c[-1].x1
                cx = (c0 + c1) / 2
                k = min(ancoras, key=lambda a: abs((cx if a[1] == "c" else c1) - a[2]))[0]
                num[k].append(" ".join(p.t for p in c))
            it = {"codigo": _texto(cod), "descricao": _texto(desc),
                  "quantidade": _dinheiro(" ".join(num.get("qtd", []))),
                  "unidade": _valor_rotulado(" ".join(num.get("un", []))),
                  "preco_unit_sem": _dinheiro(" ".join(num.get("us", []))),
                  "preco_unit_com": _dinheiro(" ".join(num.get("uc", []))),
                  "preco_total_com": _dinheiro(" ".join(num.get("tot", []))),
                  "impostos": _impostos_da_linha(_texto(imp))}
            itens.append(it)
    return itens


# ---- faturamento e locais (cartões em grade) --------------------------------
def _cartoes(ps) -> list[dict]:
    """Cartões da grade: título (seminegrito escuro) + etiqueta azul + texto
    cinza embaixo. A grade tem colunas; cada cartão fica na sua."""
    # a etiqueta (UF, município/UF) é azul — ou BRANCA sobre fundo azul numa
    # geração do desenho; tratada como título, "Governador Valadares/MG" que
    # quebrou de linha virava um local de entrega à parte
    tit = [p for p in ps if p.peso in ("semi", "bold", "black") and not p.azul and not p.branco]
    tag = [p for p in ps if p.azul or p.branco]
    sub = [p for p in ps if p.rotulo]
    # colunas da grade: onde as linhas de título começam
    linhas_t = []
    for lin in _linhas(tit):
        g = [lin[0]]
        for p in lin[1:]:
            if p.x0 - g[-1].x1 <= 14:
                g.append(p)
            else:
                linhas_t.append(g)
                g = [p]
        linhas_t.append(g)
    xs = sorted({round(g[0].x0) for g in linhas_t})
    colunas = []
    for x in xs:
        if not colunas or x - colunas[-1] > 20:
            colunas.append(x)
    def col(x):
        c = 0
        for i, cx in enumerate(colunas):
            if x >= cx - 4:
                c = i
        return c
    cartoes = []
    for g in linhas_t:
        cartoes.append({"col": col(g[0].x0), "pag": g[0].pag, "top": g[0].top, "tit": g})
    cartoes.sort(key=lambda c: (c["pag"], c["top"], c["col"]))
    # um título que é continuação do anterior (quebrou em 2 linhas) não abre cartão
    unidos = []
    for c in cartoes:
        ant = next((u for u in reversed(unidos) if u["col"] == c["col"] and u["pag"] == c["pag"]), None)
        entre = ant and [p for p in sub if p.pag == c["pag"] and col(p.cx) == c["col"]
                         and ant["top"] < p.top < c["top"]]
        if ant and not entre and c["top"] - ant["top"] < 16:
            ant["tit"] += c["tit"]
        else:
            unidos.append(c)
    out = []
    for c in unidos:
        prox = [u["top"] for u in unidos if u["col"] == c["col"] and u["pag"] == c["pag"]
                and u["top"] > c["top"]]
        lim = min(prox) - 1 if prox else 1e9
        meu_sub = [p for p in sub if p.pag == c["pag"] and col(p.cx) == c["col"]
                   and c["top"] + 1 < p.top < lim]
        tit_top = c["tit"][0].top
        # a etiqueta pode quebrar para a linha de baixo, antes do endereço
        lim_tag = min([p.top for p in meu_sub] + [tit_top + 22]) - 1
        meu_tag = [p for p in tag if p.pag == c["pag"] and col(p.cx) == c["col"]
                   and tit_top - 4 <= p.top <= max(tit_top + 4, lim_tag)]
        out.append({"titulo": _texto(c["tit"]), "tag": " ".join(p.t for p in meu_tag).strip(),
                    "texto": _texto(meu_sub)})
    return out


def _faturamentos_visual(ps, fat_cat) -> list[dict]:
    out = []
    for c in _cartoes(ps):
        partes = [x.strip() for x in c["texto"].split("·")]
        cnpj = next((m.group(0) for m in _RE_CNPJ.finditer(c["texto"])), "")
        cep = ""
        mcep = re.search(r"CEP\s*([\d.\s-]{8,11})", c["texto"])
        if mcep:
            cep = re.sub(r"\s+", "", mcep.group(1)).strip(" -")
        end = " · ".join(x for x in partes if not re.match(r"(CEP|CNPJ)\b", x))
        achado = {"uf": c["tag"], "razao_social": c["titulo"], "cnpj": _cnpj_fmt(cnpj),
                  "endereco": end, "cep": cep}
        if not (cnpj or c["titulo"]):
            continue
        out.append(_faturamento_do_catalogo(achado, fat_cat))
    return out


def _entregas_visual(ps, pops) -> list[dict]:
    out = []
    for c in _cartoes(ps):
        m = re.match(r"^(.*?)\s*\(([^()]*)\)\s*$", c["titulo"])
        nome, sigla = (m.group(1), m.group(2)) if m else (c["titulo"], "")
        mun, uf = c["tag"], ""
        mm = re.match(r"^(.*)/([A-Z]{2})$", c["tag"])
        if mm:
            mun, uf = mm.group(1), mm.group(2)
        achado = {"nome": nome.strip(), "sigla": sigla.strip(), "endereco": c["texto"],
                  "municipio": mun.strip(), "uf": uf}
        if achado["nome"] or achado["sigla"]:
            out.append(_entrega_do_catalogo(achado, pops))
    return out


def _ler_visual(ps, larguras, alturas) -> dict:
    tits = _titulos(ps, larguras)
    sec = _repartir(ps, tits)
    forn = _rotulos_valores(sec.get("forn", []))
    ident = _rotulos_valores(sec.get("ident", []))
    cond = _rotulos_valores(sec.get("cond", []))
    fat_cat, pops = _catalogo()

    # o nº da AF fica na caixa do cabeçalho
    cab_txt = " ".join(p.t for p in sec.get("cab", []))
    m = _RE_AF_ID.search(cab_txt.replace(" ", "")) or _RE_AF_ID.search(cab_txt)
    af_id = m.group(1) if m else ""
    titulo = _texto([p for p in sec.get("cab", []) if p.peso in ("bold", "black") and not p.azul])

    # total: o maior valor do quadro "Valor total"
    tot_ps = [p for p in sec.get("total", []) if re.search(r"\d", p.t) and not p.rotulo]
    tot_ps.sort(key=lambda p: -p.tam)
    valor_total = ""
    if tot_ps:
        grande = [p for p in tot_ps if p.tam == tot_ps[0].tam]
        valor_total = _dinheiro(" ".join(p.t for p in sorted(grande, key=lambda p: p.x0)))

    # objeto: o texto entre o título e o cabeçalho da tabela
    cabs = _cabecalhos_itens(ps, larguras)
    obj_ps = sec.get("objeto", [])
    if cabs:
        c0 = cabs[0]
        obj_ps = [p for p in obj_ps if (p.pag, p.top) < (c0["pag"], c0["top"] - 1)]
    objeto = _texto(obj_ps)

    itens = _itens_visual(ps, tits, larguras, alturas)
    if not valor_total:                      # rodapé da tabela: "VALOR TOTAL R$ x"
        for lin in _linhas(ps):
            k = _junto(" ".join(p.t for p in lin))
            if k.startswith("VALORTOTAL") and any(re.search(r"\d,\d{2}", p.t) for p in lin):
                valor_total = _dinheiro(" ".join(p.t for p in lin if not p.rotulo))
                break

    # Observações: um item de lista por observação. O marcador da lista é
    # DESENHO, não texto — o que separa um item do outro é o respiro entre
    # eles, maior que o entre as linhas de um mesmo item (17pt contra 15pt).
    obs, atual, ult = [], [], None
    for lin in _linhas(sec.get("obs", [])):
        if ult is not None and lin[0].top - ult.top > max(p.tam for p in lin) * 1.72:
            obs.append(_juntar_linhas(atual))
            atual = []
        atual.append(" ".join(p.t for p in lin))
        ult = lin[0]
    if atual:
        obs.append(_juntar_linhas(atual))
    obs = [x.strip(" •") for x in obs if x.strip(" •")]

    return {
        "layout": "visual", "titulo": titulo, "af_id": af_id,
        "fornecedor": forn.get("RAZAO SOCIAL", ""), "cnpj": forn.get("CNPJ", ""),
        "insc_est": forn.get("INSCRICAO ESTADUAL", ""), "endereco": forn.get("ENDERECO", ""),
        "cep": forn.get("CEP", ""), "data_proposta": forn.get("DATA DA PROPOSTA", ""),
        "cpm": ident.get("ORIGINADO DA LICITACAO", ""), "numero_proposta": ident.get("PROPOSTA", ""),
        "data_emissao": ident.get("DATA DE EMISSAO", ""), "moeda": ident.get("MOEDA", ""),
        "valor_total": valor_total, "objeto": objeto,
        "garantia": cond.get("GARANTIA", ""), "prazo_entrega": cond.get("PRAZO DE ENTREGA", ""),
        "condicao_pagamento": cond.get("FORMA DE PAGAMENTO", ""),
        "itens": itens,
        "faturamentos": _faturamentos_visual(sec.get("fat", []), fat_cat),
        "entregas": _entregas_visual(sec.get("ent", []), pops),
        "observacoes": obs,
    }


# ======================================================= LAYOUT DO MODELO ====
# O modelo Excel (modelo_af.xlsm) impresso em PDF. Os rótulos são os da
# planilha, com dois-pontos, e o valor fica à DIREITA deles.
_ROT_MODELO = [("fornecedor", r"Fornecedor:"), ("endereco", r"Endere[çc]o:"),
               ("cep", r"Cep:"), ("cnpj", r"CNPJ:?"), ("insc_est", r"Insc\.")]


def _cabecalho_modelo(ps, larg) -> dict:
    """Fornecedor, endereço, CEP, CNPJ e IE: coluna de rótulos à esquerda."""
    p0 = [p for p in ps if p.pag == 0]
    esq = larg * 0.16                      # os rótulos moram na 1ª coluna da folha
    # onde começa o bloco de identificação. "AUTORIZAÇÃO" NÃO serve: o título
    # da folha tem a mesma palavra, no meio, e cortava o endereço ("– ES" sumia)
    ident = [p for p in p0 if _junto(p.t) in ("ORIGINADO", "PROPOSTA", "INSPECAO")
             and p.x0 > larg * 0.4]
    lim_dir = (min(p.x0 for p in ident) - 3) if ident else larg * 0.55
    rots = []
    for campo, rx in _ROT_MODELO:
        for p in p0:
            m = re.match(rx + r"(.*)$", p.t, re.I)
            if m and p.x0 < esq:
                resto = m.group(1)
                if campo == "insc_est":                  # "Insc." + "Est." (+ valor grudado)
                    prox = next((q for q in p0 if abs(q.top - p.top) < 2 and 0 <= q.x0 - p.x1 < 4), None)
                    if not prox or not re.match(r"Est\.?", prox.t, re.I):
                        continue
                    resto = re.sub(r"^Est\.?:?", "", prox.t, flags=re.I)
                    p = prox
                rots.append((campo, p, resto))
                break
    rots.sort(key=lambda r: r[1].top)
    moeda = next((p for p in p0 if _junto(p.t) == "MOEDA"), None)
    out = {}
    for i, (campo, rot, resto) in enumerate(rots):
        # O último rótulo (Insc. Est.) fica numa linha só: logo abaixo dele o
        # número da proposta, quando é longo, TRANSBORDA da célula para a
        # esquerda e entrava na inscrição estadual.
        fim = rots[i + 1][1].top - 3 if i + 1 < len(rots) else rot.top + 6
        ws = [p for p in p0 if p is not rot and p.x0 >= rot.x1 - 0.5 and p.x1 <= lim_dir
              and rot.top - 5 <= p.top < fim]
        txt = _texto(ws)
        out[campo] = re.sub(r"\s+", " ", ((resto + " " + txt) if resto else txt)).strip()
    return out


def _abaixo_de(ps, rot: _P, largura: float = 75, altura: float = 16) -> str:
    """O valor que o modelo escreve EMBAIXO do rótulo.

    A célula do valor vai até o PRÓXIMO rótulo da mesma linha, não até uma
    largura fixa: "Moeda" é alinhado à esquerda e "Real" vem centralizado na
    célula, 130pt à direita."""
    viz = [p.x0 for p in ps if p.pag == rot.pag and abs(p.top - rot.top) < 2 and p.x0 > rot.x1 + 2]
    dir_ = min(min(viz) - 3, rot.x0 + max(largura, 40) * 3) if viz else rot.x0 + largura
    ws = [p for p in ps if p.pag == rot.pag and rot.bot - 1 < p.top <= rot.bot + altura
          and rot.x0 - 30 <= p.cx <= dir_]
    if not ws:
        return ""
    lin = _linhas(ws)[0]
    return " ".join(p.t for p in lin)


def _intervalos(xs: list[float]) -> list[float]:
    out = []
    for x in sorted(xs):
        if not out or x - out[-1] > 1.6:
            out.append(x)
    return out


def _cab_itens_modelo(pp) -> list[_P] | None:
    """A linha "Item · [Código] · Descrição · Quant." do cabeçalho da tabela.
    O modelo antigo da AS não tem a coluna Código, e um de 2025 escreve
    "Quant" uma linha acima do resto."""
    for lin in _linhas(pp):
        ks = [_junto(p.t) for p in lin]
        if "ITEM" not in ks or not any(k.startswith(("CODIGO", "DESCRI")) for k in ks):
            continue
        perto = [_junto(p.t) for p in pp if abs(p.top - lin[0].top) <= 12]
        if any(k.startswith("QUANT") for k in perto):
            return lin
    return None


def _itens_modelo(ps, bordas, alturas) -> tuple[list[dict], str, tuple]:
    """Itens da tabela do modelo. Devolve também ONDE a tabela acabou — é dali
    que começam as notas (nem toda AF escreve o rótulo "NOTAS:")."""
    itens, total_forn, fim_tab = [], "", None
    for pag in sorted({p.pag for p in ps}):
        pp = [p for p in ps if p.pag == pag]
        cab = _cab_itens_modelo(pp)
        if not cab:
            continue
        cab_top = min(p.top for p in cab)
        # O cabeçalho tem de 1 a 3 linhas (os títulos de preço quebram). Ele
        # acaba na primeira linha que começa com o NÚMERO DE UM ITEM — uma
        # faixa de altura fixa engolia o item 1 quando o cabeçalho é baixo
        # (AF-E-152 voltava sem o "FIBER STORAGE TRAY").
        x_cod = next((p.x0 for p in cab if _junto(p.t).startswith(("CODIGO", "DESCRI"))), 1e9)
        cab_ws = []
        for lin in _linhas([p for p in pp if cab_top - 12 <= p.top <= cab_top + 14]):
            if lin[0].top > cab_top + 1 and re.fullmatch(r"\d{1,3}", lin[0].t) and lin[0].x1 < x_cod:
                break
            cab_ws += lin
        cab_bot = max(p.bot for p in cab_ws)
        fim = alturas[pag]
        # o fecho da tabela: "TOTAL FORNECIMENTO:", "VALOR TOTAL:", "TOTAL
        # SERVIÇOS:"... Cada modelo de época escreveu de um jeito.
        for lin in _linhas([p for p in pp if p.top > cab_bot]):
            k = _junto(" ".join(p.t for p in lin))
            if k.startswith(("TOTAL", "VALORTOTAL", "NOTAS")):
                fim = lin[0].top - 1
                fim_tab = (pag, max(p.bot for p in lin) if not k.startswith("NOTAS") else lin[0].top - 1)
                if not k.startswith("NOTAS"):
                    total_forn = _dinheiro(" ".join(p.t for p in lin if re.search(r"[\d$]", p.t)))
                break
        achar = lambda pref: next((p for p in cab_ws if _junto(p.t).startswith(pref)), None)  # noqa: E731
        h = {"ix": achar("ITEM"), "cod": achar("CODIGO"), "desc": achar("DESCRI"),
             "qtd": achar("QUANT"), "un": achar("UNID"), "icms": achar("ICMS")}
        # colunas: as bordas verticais da tabela, e o começo de cada título
        vs = [e["x0"] for e in bordas.get(pag, []) if e.get("orientation") == "v"
              and e["top"] <= cab_bot + 2 and e["bottom"] >= cab_top - 2]
        vs += [p.x0 - 2 for p in cab_ws if _junto(p.t).startswith("PRECO")]
        cortes = _intervalos(vs)
        if len(cortes) < 4 or not h["qtd"] or not (h["cod"] or h["desc"]):
            continue

        def coluna(x):
            for i in range(len(cortes) - 1):
                if cortes[i] <= x < cortes[i + 1]:
                    return i
            return len(cortes) if x >= cortes[-1] else -1
        c_ix = coluna(h["ix"].cx) if h["ix"] else -2
        c_cod = coluna(h["cod"].cx) if h["cod"] else None
        c_qtd = coluna(h["qtd"].cx)
        c_desc = coluna(h["desc"].cx) if h["desc"] else c_cod + 1
        c_un = coluna(h["un"].cx) if h["un"] else c_qtd + 1
        c_icms = coluna(h["icms"].cx) if h["icms"] else 10 ** 6
        # linhas da tabela: as bordas horizontais entre o cabeçalho e o total
        hs = _intervalos([e["top"] for e in bordas.get(pag, []) if e.get("orientation") == "h"
                          and cab_bot - 1 <= e["top"] <= fim + 2 and (e["x1"] - e["x0"]) > 60])
        corpo = [p for p in pp if cab_bot < p.top < fim]
        faixas = list(zip([cab_bot] + hs, hs + [fim])) if hs else [(cab_bot, fim)]

        def abre_item(l):
            """Linha que COMEÇA um item: tem o nº do item, ou preço, ou código
            com quantidade. A que não tem nada disso é descrição que quebrou.
            (Preço sozinho não basta: há AF da CIENA com as linhas SEM preço —
            só a quantidade, e o valor apenas no total.)"""
            cols = [coluna(p.cx) for p in l]
            if any(c == c_ix and re.fullmatch(r"\d{1,3}", p.t) for c, p in zip(cols, l)):
                return True
            if any(c_un < c < c_icms and re.search(r"\d", p.t) for c, p in zip(cols, l)):
                return True
            return c_cod is not None and c_cod in cols and c_qtd in cols

        linhas_itens = []
        for a, b in faixas:
            ws = [p for p in corpo if a - 0.5 <= p.top < b - 0.5]
            if not ws:
                continue
            # BORDA NÃO BASTA: quem acrescenta linha no Excel nem sempre desenha
            # a borda (AF-E-118: só 13 das 28 linhas têm), e uma faixa engolia
            # 16 itens. Cada linha que abre item é um item; a que não abre é a
            # descrição que quebrou, e fica com o item mais perto.
            anc = [l[0].top for l in _linhas(ws) if abre_item(l)]
            if len(anc) >= 2:
                lims = [a] + [(anc[i] + anc[i + 1]) / 2 for i in range(len(anc) - 1)] + [b]
                linhas_itens += [[p for p in ws if lims[i] - 0.5 <= p.top < lims[i + 1] - 0.5]
                                 for i in range(len(lims) - 1)]
            else:
                linhas_itens.append(ws)
        for ws in linhas_itens:
            if not ws:
                continue
            por = {}
            for p in ws:
                por.setdefault(coluna(p.cx), []).append(p)
            # TRANSBORDO: o Excel não quebra a descrição longa; ela passa da
            # célula e o fim ("(lote" + "5)") fica escondido atrás da coluna
            # de quantidade — no papel é cortado, no PDF continua lá, e virava
            # a quantidade "25)". A quantidade é o número mais perto do CENTRO
            # da coluna; o que estiver à esquerda dele é descrição que vazou.
            q_ws = por.get(c_qtd, [])
            if len(q_ws) > 1 or (q_ws and not re.fullmatch(r"[\d.,]+", q_ws[0].t)):
                centro = (cortes[c_qtd] + cortes[c_qtd + 1]) / 2 if c_qtd + 1 < len(cortes) else q_ws[-1].cx
                nums = [p for p in q_ws if re.fullmatch(r"[\d.,]+", p.t)]
                alvo = min(nums, key=lambda p: abs(p.cx - centro)) if nums else None
                vaza = [p for p in q_ws if p is not alvo and (alvo is None or p.x1 <= alvo.x0 + 0.5)]
                por[c_qtd] = [p for p in q_ws if p not in vaza]
                por.setdefault(c_qtd - 1, []).extend(vaza)
            precos = [c for c in _celulas([p for p in ws if c_un < coluna(p.cx) < c_icms])]
            precos = [(coluna((c[0].x0 + c[-1].x1) / 2), " ".join(p.t for p in c)) for c in precos]
            # "R$ -" é ZERO no formato contábil do Excel. Descartá-lo fazia o
            # unitário (último valor com dígito) virar o total do item. O "R$"
            # fica na borda ESQUERDA da célula, longe do "-": vêm separados.
            precos = [(c, "0,00" if re.fullmatch(r"(R\$|US\$|\$|€)?\s*-", v.strip()) else _dinheiro(v))
                      for c, v in precos]
            precos = [(c, v) for c, v in precos if re.search(r"\d", v)]
            cod = _texto(por.get(c_cod, []))
            desc = _texto([p for c in range(c_desc, c_qtd) for p in por.get(c, [])])
            qtd = _dinheiro(" ".join(p.t for p in por.get(c_qtd, [])))
            if not (cod or desc or precos):
                continue
            n_item = _texto(por.get(c_ix, []))
            if not (cod or precos or qtd or re.fullmatch(r"\d{1,3}", n_item)) and itens:
                # continuação da descrição do item de cima
                itens[-1]["descricao"] = (itens[-1]["descricao"] + " " + desc).strip()
                continue
            us = uc = tot = ""
            if precos:
                tot = precos[-1][1]
                unit = [v for _, v in precos[:-1]]
                if len(unit) >= 2:
                    us, uc = unit[0], unit[1]
                elif unit:
                    from .modelos import brl_para_float
                    u, q, t = brl_para_float(unit[0]), brl_para_float(qtd), brl_para_float(tot)
                    # total = qtd × unitário COM imposto; se a conta fecha, é ele
                    if u is not None and q and t is not None and abs(u * q - t) <= max(0.05, t * 0.001):
                        uc = unit[0]
                    else:
                        us = unit[0]
            itens.append({"codigo": cod, "descricao": desc, "quantidade": qtd,
                          "unidade": _valor_rotulado(_texto(por.get(c_un, []))),
                          "preco_unit_sem": us, "preco_unit_com": uc, "preco_total_com": tot,
                          "impostos": []})
    return itens, total_forn, fim_tab


def _linhas_das_notas(ps, fim_tab) -> list[list[_P]]:
    """As linhas de texto das notas, sem o cabeçalho que se repete em cada folha.

    Começam onde a TABELA acaba, não no rótulo "NOTAS:" — há AF sem ele (a da
    ARTEMIS 178 vai direto do "VALOR TOTAL:" para "1 A Proposta..."), e ali a
    condição de pagamento inteira sumia."""
    out = []
    pag0, y0 = fim_tab if fim_tab else (0, None)
    for pag in sorted({p.pag for p in ps}):
        if pag < pag0:
            continue
        ls = _linhas([p for p in ps if p.pag == pag])
        if pag == pag0:
            if y0 is not None:
                ls = [l for l in ls if l[0].top > y0 + 0.5]
            else:
                i = next((j for j, l in enumerate(ls) if _junto(" ".join(p.t for p in l)).startswith("NOTAS")), None)
                ls = ls[i + 1:] if i is not None else []
            if ls and _junto(" ".join(p.t for p in ls[0])).startswith("NOTAS"):
                ls = ls[1:]
        else:
            i = next((j for j, l in enumerate(ls) if "CONTINUA" in _junto(" ".join(p.t for p in l))
                      and "NOTAS" in _junto(" ".join(p.t for p in l))), None)
            if i is None:       # sem "NOTAS (Continuação)": pula até a linha da folha "2/2"
                i = next((j for j, l in enumerate(ls[:12]) if re.search(r"\b\d+/\d+\s*$", " ".join(p.t for p in l))
                          and _RE_DATA.search(" ".join(p.t for p in l))), -1)
            ls = ls[i + 1:]
        out += ls
    return out


def _secao_da_nota(k: str) -> str | None:
    return ("pag" if "PAGAMENTO" in k else "gar" if k.startswith("GARANTIA")
            else "prazo" if k.startswith("PRAZODEENTREGA") else "fat" if "FATURAMENTO" in k
            else "ent" if k.startswith("LOCAISDEENTREGA") else None)


def _secoes_das_notas(linhas) -> dict[str, list[list[_P]]]:
    """Notas numeradas: "4 GARANTIA", "5 PRAZO DE ENTREGA"...

    Nota nova é o PRÓXIMO NÚMERO DA SEQUÊNCIA, não "linha que começa com
    número": "9 Fazem parte desta Proposta..." vem em minúsculas e entrava nos
    locais de entrega; e um pagamento que diga "30 dias após..." não pode
    virar nota 30."""
    secs, atual, ult = {}, None, 0
    for l in linhas:
        txt = " ".join(p.t for p in l).strip()
        m = re.match(r"^(\d{1,2})(?:\s+(.*))?$", txt)
        k = _junto(m.group(2) or "") if m else ""
        if m and (int(m.group(1)) in (ult + 1, ult + 2) or (_secao_da_nota(k) and int(m.group(1)) > ult)):
            ult = int(m.group(1))
            atual = _secao_da_nota(k)
            if atual:
                secs[atual] = []
            continue
        if re.match(r"Enviar\s+NF", txt, re.I):
            atual = None
            continue
        if atual:
            secs[atual].append(l)
    return secs


def _ler_modelo(ps, larguras, alturas, bordas) -> dict:
    larg = larguras[0]
    p0 = [p for p in ps if p.pag == 0]
    txt0 = " ".join(p.t for l in _linhas(p0) for p in l)
    txt0 = re.sub(r"\b((?:A[FS]|CP[MS])-[A-Z0-9]+-)\s+(\d)", r"\1\2", txt0)   # "AF-E- 240/2025"
    cab = _cabecalho_modelo(ps, larg)
    m = _RE_AF_ID.search(txt0)
    af_id = m.group(1) if m else ""
    m = _RE_CPM_ID.search(txt0)
    cpm = m.group(1) if m else ""
    emis = next((p for p in p0 if _junto(p.t).startswith("EMISSAO")), None)
    data_emis = ""
    if emis:
        ws = [p for p in p0 if emis.bot - 1 < p.top <= emis.bot + 18 and _RE_DATA.fullmatch(p.t)
              and abs(p.cx - emis.cx) < 100]
        data_emis = ws[0].t if ws else ""
    if not data_emis:
        m = _RE_DATA.search(txt0)
        data_emis = m.group(0) if m else ""
    prop = next((p for p in p0 if _junto(p.t) == "PROPOSTA" and p.x0 > larg * 0.3), None)
    moeda_r = next((p for p in p0 if _junto(p.t) == "MOEDA"), None)
    proposta = ""
    if prop:
        # o número pode quebrar em várias linhas ("176/2026, 174/2026 e" /
        # "175/2026."), e a última cai NA LINHA dos rótulos Moeda/Frete/ICMS
        rotulos = {"MOEDA", "EMBALAGEM", "ENTREGA", "DOS", "EQUIPAMENTOS", "FRETE", "ICMS", "TOTAL"}
        # O valor é a SEQUÊNCIA CONTÍNUA de palavras que passa pela coluna do
        # rótulo — mesmo que transborde para os lados (número longo centrado
        # vaza da célula). O endereço de entrega, à direita, é outra
        # sequência, separada por um vão.
        lim = (moeda_r.top + 3) if moeda_r and moeda_r.top > prop.top else prop.bot + 30
        pedacos = []
        for lin in _linhas([p for p in p0 if prop.bot - 1 < p.top <= lim]):
            corridas, cor = [], [lin[0]]
            for p in lin[1:]:
                if p.x0 - cor[-1].x1 <= 6:
                    cor.append(p)
                else:
                    corridas.append(cor)
                    cor = [p]
            corridas.append(cor)
            a, b = prop.x0 - 5, prop.x0 + 60
            melhor = max(corridas, key=lambda c: min(b, c[-1].x1) - max(a, c[0].x0))
            if min(b, melhor[-1].x1) - max(a, melhor[0].x0) > 0:
                pedacos.append(" ".join(p.t for p in melhor if _junto(p.t) not in rotulos))
        proposta = _juntar_linhas(pedacos)
    moeda = _abaixo_de(p0, moeda_r, 40, 14) if moeda_r else ""
    titulo = next((" ".join(p.t for p in l) for l in _linhas(p0)[:4]
                   if _junto(" ".join(p.t for p in l)).startswith("AUTORIZACAODE")), "")

    # objeto: entre o rótulo e o cabeçalho da tabela
    objeto = ""
    lins0 = _linhas(p0)
    io = next((i for i, l in enumerate(lins0) if _junto(" ".join(p.t for p in l)).startswith("OBJETODO")), None)
    if io is not None:
        c = _cab_itens_modelo(p0)
        # o cabeçalho da tabela ocupa 2-3 linhas ("Preço unitário" em cima)
        corte = (min(p.top for p in c) - 6) if c else 1e9
        pedacos = []
        for l in lins0[io + 1:]:
            k = _junto(" ".join(p.t for p in l))
            if l[0].top >= corte or "PRECOUNITARIO" in k or "PRECOTOTAL" in k:
                break
            pedacos.append(" ".join(p.t for p in l))
        objeto = _juntar_linhas(pedacos)

    itens, total_forn, fim_tab = _itens_modelo(ps, bordas, alturas)
    valor_total = total_forn
    if not valor_total:
        tot = next((p for p in p0 if _junto(p.t) == "TOTAL" and moeda_r and abs(p.top - moeda_r.top) < 3), None)
        if tot:
            valor_total = _dinheiro(_abaixo_de(p0, tot, 90, 14))

    secs = _secoes_das_notas(_linhas_das_notas(ps, fim_tab))

    def bloco(k, pular_ate=None):
        ls = [" ".join(p.t for p in l) for l in secs.get(k, [])]
        if pular_ate:                     # "As importâncias ... conforme segue:"
            j = next((i for i, s in enumerate(ls) if re.search(pular_ate, s, re.I)), None)
            if j is not None:
                ls = ls[j + 1:]
        # linha que é SÓ numeração ("3.1") ou "0" não é texto: é célula de
        # fórmula vazia do modelo (AF-E-226 imprimiu "0" como pagamento)
        return "\n".join(s.strip() for s in ls
                         if s.strip() and not re.fullmatch(r"\d+(?:[.,]\d+)*[.:)]?", s.strip()))

    fat_cat, pops = _catalogo()
    fats, vistos = [], set()
    for l in secs.get("fat", []):
        t = " ".join(p.t for p in l)
        for m in _RE_CNPJ.finditer(t):
            n = _so_num(m.group(0))
            if n in vistos or not n.startswith("03052673"):
                continue
            vistos.add(n)
            uf = l[0].t if re.fullmatch(r"[A-Z]{2}", l[0].t) else ""
            fats.append(_faturamento_do_catalogo({"uf": uf, "cnpj": _cnpj_fmt(n),
                                                  "razao_social": "ELETRONET S.A"}, fat_cat))
    ents = []
    lent = secs.get("ent", [])
    hdr = next((l for l in lent if any(_junto(p.t) == "SIGLA" for p in l)), None)
    if hdr:
        pos = {}
        for p in hdr:
            k = _junto(p.t)
            for chave, pref in (("nome", "NOME"), ("sigla", "SIGLA"), ("end", "ENDERECO"),
                                ("mun", "MUNICIPIO"), ("uf", "UF"), ("link", "LINK")):
                if k == pref or (chave in ("nome", "end", "mun") and k.startswith(pref)):
                    pos.setdefault(chave, p.x0)
        ordem = sorted(pos.items(), key=lambda kv: kv[1])
        lim = {k: (x - 8, (ordem[i + 1][1] - 8) if i + 1 < len(ordem) else 1e9)
               for i, (k, x) in enumerate(ordem)}
        for l in lent[lent.index(hdr) + 1:]:
            cel = {k: " ".join(p.t for p in l if a <= p.cx < b) for k, (a, b) in lim.items()}
            sigla = (cel.get("sigla", "").split() or [""])[0]
            uf = cel.get("uf", "").strip()[:2]
            # Uma estação = a linha que tem SIGLA ou UF. O endereço quebra em
            # várias linhas dentro da célula ("Av. Alfredo Egídio" / ... /
            # "100") e cada pedaço virava um local de entrega.
            if not (re.fullmatch(r"[A-Z0-9][A-Z0-9-]{1,11}", sigla) or re.fullmatch(r"[A-Z]{2}", uf)):
                continue
            achado = {"nome": cel.get("nome", ""), "sigla": sigla, "endereco": cel.get("end", ""),
                      "municipio": cel.get("mun", ""), "uf": uf}
            ents.append(_entrega_do_catalogo(achado, pops))
    avisos = []
    if not hdr and lent:
        # Modelo antigo: o local é uma linha de ENDEREÇO, sem sigla. Ou, em AF
        # feita à mão, uma FILIAL posta na seção de locais. O que casar com o
        # endereço de um POP do catálogo entra; o resto vira aviso — local de
        # entrega inventado é pior que local nenhum.
        linhas = [" ".join(p.t for p in l).strip() for l in lent]
        linhas = [t for t in linhas if len(t) >= 8 and "RAZAOSOCIAL" not in _junto(t)]
        for t in linhas:
            pop = _pop_por_endereco(t, pops)
            if pop and all(pop.get("sigla") != e.get("sigla") for e in ents):
                ents.append(pop)
        if not ents and linhas:
            cnpj = next((m.group(0) for t in linhas for m in _RE_CNPJ.finditer(t)), "")
            if cnpj:
                avisos.append(f"O local de entrega desta AF é uma filial da Eletronet (CNPJ "
                              f"{_cnpj_fmt(cnpj)}), não um POP — escolha o POP na lista.")
            else:
                avisos.append(f'Local de entrega escrito à mão na AF: "{" ".join(linhas)[:140]}" '
                              "— escolha o POP na lista.")

    return {
        "layout": "modelo", "titulo": titulo, "af_id": af_id, "cpm": cpm,
        "fornecedor": cab.get("fornecedor", ""), "cnpj": cab.get("cnpj", ""),
        "insc_est": cab.get("insc_est", ""), "endereco": cab.get("endereco", ""),
        "cep": cab.get("cep", ""), "data_proposta": "",
        "numero_proposta": proposta, "data_emissao": data_emis, "moeda": moeda,
        "valor_total": valor_total, "objeto": objeto,
        "garantia": bloco("gar"), "prazo_entrega": bloco("prazo"),
        "condicao_pagamento": bloco("pag", r"conforme\s+segue"),
        "itens": itens, "faturamentos": fats, "entregas": ents, "observacoes": [],
        "avisos": avisos,
    }


# ============================================================ ponto de entrada
def _paginas_da_af(pdf) -> tuple[list[int], str]:
    """As folhas da AF — a proposta anexada vem depois e fica de fora.

    O fim da AF é a folha das notas fiscais ("Enviar NF para ..."), que vem
    colada na assinatura. Pelo TÍTULO não dá: o desenho visual só escreve
    "AUTORIZAÇÃO DE..." na primeira folha, e o leitor antigo parava ali —
    por isso faturamento e locais (folha 2) nunca eram lidos."""
    primeira = pdf.pages[0].extract_text() or ""
    layout = "visual" if "DOCUMENTO ELETR" in primeira.upper() else "modelo"
    pags, ilegivel, fechou = [], None, False
    for i, pg in enumerate(pdf.pages[:15]):
        t = primeira if i == 0 else (pg.extract_text() or "")
        if i > 0 and layout == "modelo" and "AUTORIZA" not in t.upper():
            # FONTE QUEBRADA: o texto sai como "(cid:5)(cid:17)..." e nenhuma
            # leitura recupera. Se a AF ainda não tinha chegado ao fim, esta
            # folha provavelmente era dela — e quem importa precisa saber.
            if len(re.findall(r"\(cid:\d+\)", t)) > 20:
                ilegivel = i + 1
            break
        pags.append(i)
        if re.search(r"Enviar\s+NF|controladoria@eletronet", t, re.I):
            fechou = True
            break
    return pags, layout, (ilegivel if not fechou else None)


def ler_af_pdf(caminho: str) -> dict:
    import pdfplumber

    with pdfplumber.open(caminho) as pdf:
        pags, layout, ilegivel = _paginas_da_af(pdf)
        ps, larguras, alturas, bordas = [], {}, {}, {}
        for i in pags:
            pg = pdf.pages[i]
            larguras[i], alturas[i] = float(pg.width), float(pg.height)
            ws = pg.extract_words(extra_attrs=["fontname", "size", "non_stroking_color"])
            ps += [_P(w, i) for w in ws]
            if layout == "modelo":
                bordas[i] = [e for e in pg.edges if (e["x1"] - e["x0"]) > 8 or (e["bottom"] - e["top"]) > 4]
    if not ps:
        return {"ok": False, "erro": "Não encontrei texto neste PDF."}
    d = _ler_visual(ps, larguras, alturas) if layout == "visual" else \
        _ler_modelo(ps, larguras, alturas, bordas)
    d.setdefault("avisos", [])
    if ilegivel:
        d["avisos"].append(f"A folha {ilegivel} deste PDF está com a fonte quebrada (o texto não "
                           "pode ser lido). Se ela é da AF, garantia, prazo, faturamento e locais "
                           "de entrega podem ter ficado de fora — confira.")
    d["ok"] = True
    d["paginas_af"] = len(pags)
    return d
