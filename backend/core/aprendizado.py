r"""
aprendizado.py — o app aprende a ler a proposta de cada fornecedor.

Não há aprendizado de máquina aqui, e nem precisa. A ideia é simples: quando o
extrator erra um campo e o usuário CORRIGE na tela antes de gerar, procuramos o
valor correto dentro do texto da proposta e guardamos o RÓTULO que vem antes
dele — "Valor Global da Proposta:", "Nossa referência:", "Entrega:". Na próxima
proposta do mesmo fornecedor, esse rótulo é tentado ANTES das regras genéricas.

É por isso que os fornecedores "escritos no código" (FONNET, NEC, PADTEC…)
sempre funcionaram: alguém escreveu a regra à mão. Aqui a regra passa a ser
escrita pelo uso, para qualquer fornecedor, sem ninguém programar.

As lições ficam no mesmo dados_usuario.json, por CNPJ do fornecedor.
"""

from __future__ import annotations

import re
import unicodedata

from .log import get_logger

LOG = get_logger("aprendizado")

# Campos que vale a pena aprender: são os que o usuário mais corrige e que têm
# um valor localizável no texto. Descrição de item e endereço ficam de fora —
# variam demais para um rótulo fixo ajudar.
CAMPOS = ("valor_total", "numero_proposta", "prazo_entrega", "garantia", "condicao_pagamento")

# Quanto rótulo guardar antes do valor. O corte é por PALAVRAS, não por número
# de caracteres: cortar em 42 caracteres partia palavra no meio e guardava coisas
# como "copo valor em r$ sem iss" (rabo de "Escopo") ou "s datas a serem
# disponibilizadas obedecera" — pedaços de prosa que não são rótulo de nada.
_MAX_PALAVRAS = 6
_MAX_ROTULO = 60          # teto duro, depois do corte por palavras
_MIN_ROTULO = 3

# Um rótulo só serve se tiver alguma palavra de verdade. "R$", ":" ou "1.234"
# sozinhos casariam com qualquer coisa na proposta seguinte.
_SO_RUIDO = re.compile(r"^[\W\d_]*$")

# Separadores que encerram o campo anterior: o rótulo começa DEPOIS do último.
_CORTE = re.compile(r"[\n\r;|\t]|(?<=[a-zà-ÿ])\.\s")


def _sem_acento(t: str) -> str:
    return unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode().lower()


def _chave(cnpj: str) -> str:
    return re.sub(r"\D", "", str(cnpj or ""))


def _norm_espacos(t: str) -> str:
    return re.sub(r"\s+", " ", str(t or "")).strip()


def rotulo_antes(texto: str, valor: str) -> str:
    """Devolve o rótulo que antecede `valor` no texto (ou "" se não achar).

    Ex.: em "... Valor Global da Proposta: R$ 1.142.297,80 ..." com valor
    "1.142.297,80", devolve "valor global da proposta".

    O que sai daqui tem de ser um RÓTULO: um punhado de palavras inteiras,
    imediatamente antes do valor. Fragmento de prosa cortado no meio de uma
    palavra não é rótulo — casa com qualquer coisa depois e faz o app preencher
    o campo errado com confiança, que é pior do que não preencher.
    """
    alvo = _norm_espacos(valor)
    if len(alvo) < 2:
        return ""
    # O texto NÃO é achatado antes do corte: a quebra de linha é justamente o
    # limite mais confiável entre um campo e o seguinte. Achatando primeiro,
    # "Resumo de Preços\nValor Total" virava uma coisa só.
    pos = _sem_acento(texto).find(_sem_acento(alvo))
    if pos < 0:
        plano = _norm_espacos(texto)              # 2ª tentativa: valor quebrado em 2 linhas
        pos = _sem_acento(plano).find(_sem_acento(alvo))
        if pos < 0:
            return ""
        texto = plano
    antes = texto[:pos]
    # 1. começa depois do último separador forte (linha, ponto-final, ; | tab)
    cortes = list(_CORTE.finditer(antes))
    if cortes:
        antes = antes[cortes[-1].end():]
    # 2. e depois do último NÚMERO — o que vem antes dele é o valor do campo
    #    anterior, não rótulo ("..... R$ 252.000,00 Entrega em" → "Entrega em")
    numeros = list(re.finditer(r"\d[\d.,]{2,}", antes))
    if numeros:
        antes = antes[numeros[-1].end():]
    antes = _norm_espacos(antes)
    # 3. tira sobras do valor anterior (moeda, pontuação) e os pontinhos do fim
    antes = re.sub(r"^[\s\W\d]+", "", antes)
    antes = re.sub(r"[\s:=._\-–]+$", "", antes)
    # 4. no máximo _MAX_PALAVRAS palavras INTEIRAS, contadas do fim para trás —
    #    o rótulo é o que está colado no valor
    palavras = antes.split()
    if len(palavras) > _MAX_PALAVRAS:
        palavras = palavras[-_MAX_PALAVRAS:]
    antes = " ".join(palavras)[-_MAX_ROTULO:]
    # 5. o teto de caracteres pode ter partido a primeira palavra: descarta ela
    if antes and not antes[0].isspace():
        primeiro_espaco = antes.find(" ")
        if len(antes) == _MAX_ROTULO and primeiro_espaco > 0:
            antes = antes[primeiro_espaco + 1:]
    antes = _norm_espacos(antes)
    if len(antes) < _MIN_ROTULO or _SO_RUIDO.match(antes):
        return ""
    return _sem_acento(antes)


# Como procurar o valor DEPOIS do rótulo, por campo. `_ENTRE` é o que pode
# separar um do outro: dois-pontos, igual, espaços e os pontinhos de
# preenchimento das tabelas ("Valor Global ........ R$ 1.000,00").
# Atravessa NO MÁXIMO uma quebra de linha: em PDF o rótulo e o valor às vezes
# caem em linhas diferentes, mas duas quebras já são outro campo.
_ENTRE = r"[ \t:=._\-–]*\n?[ \t:=._\-–]*"
_PADRAO = {
    "valor_total": _ENTRE + r"(?:R\$|US\$|\$)?\s*([\d][\d.,]{2,})",
    # O número da proposta costuma ter espaço no meio ("PRPT 6117_26A") — o
    # padrão antigo parava no 1º espaço e devolvia só "PRPT". O ponto só conta
    # como parte do número quando vem seguido de letra/dígito ("PRPT.61"), senão
    # é o ponto final da frase e arrastava as palavras seguintes junto.
    "numero_proposta": _ENTRE + (r"([A-Za-z0-9](?:[\w/-]|\.(?=\w))*"
                                 r"(?:[ /-][A-Za-z0-9](?:[\w/-]|\.(?=\w))*){0,2})"),
    "prazo_entrega": _ENTRE + r"([^\n;|]{2,60})",
    "garantia": _ENTRE + r"([^\n;|]{2,80})",
    "condicao_pagamento": _ENTRE + r"([^\n;|]{2,80})",
}


def _rotulo_em_regex(rotulo: str) -> str:
    """Transforma o rótulo guardado num padrão TOLERANTE.

    O rótulo costuma vir com os pontinhos da tabela no meio ("Valor Global da
    Proposta ....... R$"). Se a próxima proposta tiver 9 pontos em vez de 13,
    a comparação literal falharia — então cada corrida de pontos, traços,
    espaços e dois-pontos vira "qualquer separador"."""
    partes = [re.escape(p) for p in re.split(r"[\s.:=_\-–]+", rotulo) if p]
    # entre as PALAVRAS do rótulo o separador não pode pular linha: são palavras
    # vizinhas na mesma frase. Só entre o rótulo e o VALOR isso é permitido.
    entre_palavras = r"[ \t:=._\-–]*"
    return entre_palavras.join(partes) if partes else ""


def _norm_linhas(t: str) -> str:
    """Junta espaços e tabulações, mas PRESERVA a quebra de linha.

    Achatar tudo era o que fazia o valor de um campo invadir a linha seguinte:
    "Nossa referência: PRPT 6117_26A\\nValor Global..." virava uma linha só e o
    número da proposta saía como "PRPT 6117_26A Valor". A quebra de linha é o
    limite mais confiável que a proposta oferece — não se joga fora."""
    t = re.sub(r"[ \t\xa0]+", " ", str(t or ""))
    return re.sub(r"[ \t]*\n[ \t]*", "\n", t).strip()


# ===========================================================================
# LIÇÃO DE COLUNA — para proposta em TABELA.
#
# Por que existe: a lição de rótulo pressupõe "Rótulo: valor" na mesma linha.
# Nas propostas reais deste setor o valor quase nunca está assim; está numa
# TABELA, com o cabeçalho numa linha e os números em outra:
#
#     Escopo  Valor em R$ sem ISS  ISS (%)  Valor em R$ com ISS
#     Caracterização de Fibras
#     62.045,37   2%   63.311,60
#
# O rótulo de 63.311,60 é "Valor em R$ com ISS", três colunas à direita — não
# o texto imediatamente antes dele. `rotulo_antes` devolvia "r$ sem iss iss (%)
# valor", um pedaço do cabeçalho que ao ser relido não achava nada, e a lição
# era recusada pela trava do confere(). Resultado medido no uso real: 13
# propostas lidas, ZERO lições guardadas.
#
# A lição de coluna guarda outra coisa: a LINHA DE CABEÇALHO inteira e a POSIÇÃO
# do valor entre os números da linha de valores. "O total é o 2º dinheiro da
# primeira linha de números depois deste cabeçalho." Isso sobrevive à próxima
# proposta do mesmo fornecedor, que vem no mesmo modelo.
# ===========================================================================
_DINHEIRO = re.compile(r"\d{1,3}(?:\.\d{3})+,\d{2}|\d+,\d{2}")
_MAX_LINHAS_ABAIXO = 6        # quantas linhas procurar os números após o cabeçalho
_MIN_PALAVRAS_CAB = 3         # cabeçalho curto demais casa com qualquer coisa
_MIN_MARCAS_CAB = 2           # quantas marcas de tabela de precos a ancora precisa ter


# Palavras que denunciam um CABEÇALHO de tabela de preços. Servem para separar
# o cabeçalho ("Escopo | Valor em R$ sem ISS | ISS (%) | Valor em R$ com ISS")
# da linha de DESCRIÇÃO logo acima dos números ("Caracterização de Fibras").
# A diferença importa: a descrição muda a cada proposta, o cabeçalho não — uma
# lição ancorada na descrição vale para uma proposta só.
_MARCA_CAB = re.compile(r"r\$|%|\bvalor|\bpreco|\btotal|\bunit|\bqtd|\bquant|\bimposto|\biss|\bipi",
                        re.I)


def _eh_cabecalho(linha: str) -> bool:
    """A linha parece uma linha de TEXTO (não de números) com palavras de verdade."""
    if len(_DINHEIRO.findall(linha)) > 1:
        return False
    return len(re.findall(r"[A-Za-zÀ-ÿ]{2,}", linha)) >= _MIN_PALAVRAS_CAB


def _forca_cabecalho(linha: str) -> int:
    """Quanto esta linha parece cabeçalho de tabela de preços (0 = nada)."""
    return len(_MARCA_CAB.findall(_sem_acento(linha)))


def ancora_coluna(texto: str, valor: str) -> dict:
    """Descreve `valor` como "o N-ésimo dinheiro depois de tal cabeçalho".

    Devolve {"cabecalho": ..., "ordem": n} ou {} quando o valor não está numa
    linha de números precedida por cabeçalho — aí não é caso de tabela.
    """
    alvo = _norm_espacos(valor)
    if not _DINHEIRO.fullmatch(alvo):
        return {}                      # só vale para valor em dinheiro
    linhas = _norm_linhas(texto).split("\n")
    sem = [_sem_acento(l) for l in linhas]
    alvo_sem = _sem_acento(alvo)
    for i, l in enumerate(sem):
        numeros = _DINHEIRO.findall(l)
        if alvo_sem not in numeros:
            continue
        ordem = numeros.index(alvo_sem) + 1
        # Sobe procurando a âncora. Entre as linhas de texto acima dos números,
        # prefere a que MAIS parece cabeçalho de tabela de preços; só cai na
        # linha de descrição mais próxima se nenhuma tiver cara de cabeçalho.
        candidatas = [linhas[j] for j in range(i - 1, max(-1, i - _MAX_LINHAS_ABAIXO) - 1, -1)
                      if _eh_cabecalho(linhas[j])]
        if not candidatas:
            return {}
        melhor = max(candidatas, key=_forca_cabecalho)
        # Sem cara de cabeçalho de PREÇOS, não vira lição. Medido nas propostas
        # reais: sem esta trava a âncora saía como "solicitante : <nome> data de
        # solicitação" — passa na prova no próprio texto e não se repete em
        # proposta nenhuma. Lição que só vale para um documento não é lição.
        if _forca_cabecalho(melhor) < _MIN_MARCAS_CAB:
            return {}
        return {"cabecalho": _sem_acento(_norm_espacos(melhor)), "ordem": ordem}
    return {}


def ler_com_coluna(texto: str, cabecalho: str, ordem: int) -> str:
    """Relê o valor pela lição de coluna: N-ésimo dinheiro depois do cabeçalho."""
    if not cabecalho or not ordem:
        return ""
    linhas = _norm_linhas(texto).split("\n")
    cab = _sem_acento(_norm_espacos(cabecalho))
    for i, l in enumerate(linhas):
        if cab not in _sem_acento(_norm_espacos(l)):
            continue
        for k in range(i + 1, min(len(linhas), i + 1 + _MAX_LINHAS_ABAIXO)):
            numeros = _DINHEIRO.findall(linhas[k])
            if len(numeros) >= ordem:
                return numeros[ordem - 1]
    return ""


def ler_licao(texto: str, licao: dict, campo: str) -> str:
    """Lê pelo tipo de lição que foi guardada: rótulo ou coluna de tabela."""
    if licao.get("cabecalho"):
        return ler_com_coluna(texto, licao["cabecalho"], int(licao.get("ordem") or 0))
    return ler_com_rotulo(texto, licao.get("rotulo", ""), campo)


def ler_com_rotulo(texto: str, rotulo: str, campo: str) -> str:
    """Procura no texto o valor que vem logo depois de `rotulo`."""
    if not rotulo or campo not in _PADRAO:
        return ""
    alvo = _rotulo_em_regex(rotulo)
    if not alvo:
        return ""
    # casa no texto SEM acento, mas recorta do texto ORIGINAL p/ não perder acento
    plano = _norm_linhas(texto)
    m = re.search(alvo + _PADRAO[campo], _sem_acento(plano), re.I)
    if not m:
        return ""
    # tira pontuação de fim de frase colada no valor ("PRPT 6117_26A." → sem o ponto)
    return _norm_espacos(plano[m.start(1):m.end(1)]).rstrip(".,;:")


# ===========================================================================
# PROPOSTAS LIDAS — em disco, no perfil do usuário.
#
# O aprendizado precisa de duas coisas separadas no tempo: o TEXTO da proposta
# (na hora de ler) e a CORREÇÃO do usuário (na hora de gerar). Isso vivia só na
# memória do processo, então ler a proposta hoje e gerar a AF amanhã — ou ler,
# fechar o app por engano e reabrir — jogava a lição fora. Vai para
# %APPDATA%\AutoAF junto com o resto, que é o único lugar que sobrevive à troca
# do .exe.
# ===========================================================================
_MAX_LIDAS = 20                   # quantas propostas manter
_DIAS_LIDAS = 120                 # e por quanto tempo


def _arquivo_lidas() -> str:
    from .dados_eletronet import USER_JSON

    import os as _os
    return _os.path.join(_os.path.dirname(USER_JSON), "propostas_lidas.json")


def _carrega_lidas() -> dict:
    import json
    import os as _os

    caminho = _arquivo_lidas()
    for alvo in (caminho, caminho + ".bak"):
        try:
            if _os.path.exists(alvo):
                with open(alvo, encoding="utf-8") as fh:
                    d = json.load(fh)
                return d if isinstance(d, dict) else {}
        except Exception as exc:                       # arquivo corrompido: tenta o .bak
            LOG.warning("propostas_lidas ilegível (%s): %s", _os.path.basename(alvo), exc)
    return {}


def lembrar_leitura(caminho: str, texto: str, extraido: dict) -> None:
    """Guarda em disco o texto lido e o que o extrator entendeu."""
    import json
    import os as _os
    import time

    if not caminho or not texto:
        return
    try:
        d = _carrega_lidas()
        d[_os.path.abspath(caminho)] = {"texto": texto, "extraido": dict(extraido or {}),
                                        "quando": time.time()}
        # poda: o que envelheceu e o que passou do teto (mais antigo primeiro)
        limite = time.time() - _DIAS_LIDAS * 86400
        d = {k: v for k, v in d.items() if float(v.get("quando", 0)) >= limite}
        if len(d) > _MAX_LIDAS:
            ordem = sorted(d, key=lambda k: float(d[k].get("quando", 0)), reverse=True)
            d = {k: d[k] for k in ordem[:_MAX_LIDAS]}
        alvo = _arquivo_lidas()
        tmp = f"{alvo}.{_os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(d, fh, ensure_ascii=False)
        if _os.path.exists(alvo):
            try:
                import shutil
                shutil.copyfile(alvo, alvo + ".bak")
            except Exception:
                pass
        _os.replace(tmp, alvo)                          # troca atômica
    except Exception as exc:
        LOG.warning("não consegui guardar a proposta lida: %s", exc)


def leitura(caminho: str) -> dict:
    """Recupera a leitura guardada de uma proposta ({} se não houver)."""
    import os as _os

    if not caminho:
        return {}
    return _carrega_lidas().get(_os.path.abspath(caminho)) or {}


def licoes(cnpj: str) -> dict:
    """Lições já aprendidas para um fornecedor: {campo: [rótulos, do melhor p/ o pior]}."""
    from .dados_eletronet import _usuario

    return (_usuario().get("licoes", {}) or {}).get(_chave(cnpj), {}) or {}


def aplicar(cnpj: str, texto: str) -> dict:
    """O que as lições conseguem ler nesta proposta: {campo: valor}."""
    achados = {}
    for campo, guardadas in licoes(cnpj).items():
        for r in guardadas:
            valor = ler_licao(texto, r, campo)
            if valor:
                achados[campo] = valor
                LOG.info("lição aplicada (%s): '%s' -> %s", campo,
                         r.get("rotulo") or r.get("cabecalho"), valor[:40])
                break
    return achados


def confere(texto: str, rotulo: str, campo: str, esperado: str) -> bool:
    """A lição vale? Relê o próprio texto de onde ela saiu e exige o MESMO valor.

    É a trava que faltava. Sem ela entraram no cadastro rótulos como
    "a do projeto e o prazo de entrega sera de", que relia
    "90 dias apos o aceite" onde o usuário tinha escrito "90 dias" — e depois
    aplicava isso com toda a confiança na proposta seguinte. Uma lição que nem
    no texto de origem acerta não tem por que ser guardada.
    """
    lido = ler_com_rotulo(texto, rotulo, campo)
    return bool(lido) and _sem_acento(_norm_espacos(lido)) == _sem_acento(_norm_espacos(esperado))


def confere_licao(texto: str, licao: dict, campo: str, esperado: str) -> bool:
    """Mesma trava do confere(), para qualquer tipo de lição."""
    lido = ler_licao(texto, licao, campo)
    return bool(lido) and _sem_acento(_norm_espacos(lido)) == _sem_acento(_norm_espacos(esperado))


def _mesma_licao(a: dict, b: dict) -> bool:
    """Duas lições apontam para o mesmo lugar?"""
    if a.get("cabecalho") or b.get("cabecalho"):
        return (a.get("cabecalho") == b.get("cabecalho")
                and int(a.get("ordem") or 0) == int(b.get("ordem") or 0))
    return a.get("rotulo") == b.get("rotulo")


def _demote(forn: dict, campo: str, texto: str, errado: str) -> int:
    """Tira de circulação a lição que produziu o valor que o usuário acabou de
    corrigir. Sem isto um rótulo ruim ficava para sempre, ganhando "acertos" a
    cada correção — o contrário do que a contagem deveria significar."""
    lista = forn.get(campo) or []
    sobrou, caidas = [], 0
    for x in lista:
        rot = x.get("rotulo") or x.get("cabecalho") or ""
        lido = ler_licao(texto, x, campo)
        # só pune a lição que REALMENTE leu o valor errado nesta proposta
        if lido and _sem_acento(_norm_espacos(lido)) == _sem_acento(_norm_espacos(errado)):
            x["acertos"] = int(x.get("acertos", 0)) - 1
            caidas += 1
            if x["acertos"] <= 0:
                LOG.info("lição descartada (%s): '%s' vinha errando", campo, rot[:40])
                continue
        sobrou.append(x)
    forn[campo] = sobrou
    return caidas


def aprender(cnpj: str, texto: str, extraido: dict, final: dict) -> list[str]:
    """Compara o que foi EXTRAÍDO com o que o usuário deixou no FINAL e guarda o
    rótulo dos campos corrigidos. Devolve a lista de campos aprendidos."""
    ch = _chave(cnpj)
    if not ch or not texto:
        return []

    novos, corrigidos = {}, {}
    for campo in CAMPOS:
        antes, depois = _norm_espacos(extraido.get(campo)), _norm_espacos(final.get(campo))
        if not depois or _sem_acento(antes) == _sem_acento(depois):
            continue                                   # não mexeu: nada a aprender
        corrigidos[campo] = antes                      # o que estava errado
        # Duas formas de descrever ONDE está o valor, tentadas nesta ordem:
        #   1. RÓTULO — "Valor Global: R$ 1.000,00". Mais preciso quando existe.
        #   2. COLUNA — o valor numa tabela, sob um cabeçalho. É o formato das
        #      propostas reais deste setor, e era o caso que não se aprendia.
        # SÓ entra o que passa na prova: reler o próprio texto e chegar
        # exatamente no valor que o usuário escreveu.
        rot = rotulo_antes(texto, depois)
        if rot and confere(texto, rot, campo, depois):
            novos[campo] = {"rotulo": rot}
            continue
        col = ancora_coluna(texto, depois)
        if col and confere_licao(texto, col, campo, depois):
            novos[campo] = col
            LOG.info("lição de coluna (%s): %r, %dº valor",
                     campo, col["cabecalho"][:40], col["ordem"])
        elif rot:
            LOG.info("lição recusada (%s): rótulo '%s' releria outra coisa", campo, rot[:40])

    if not novos and not corrigidos:
        return []

    from .dados_eletronet import _editando

    with _editando() as (d, alvo):
        forn = d.setdefault("licoes", {}).setdefault(ch, {})
        # 1. o que errou perde ponto (e some quando zera)
        for campo, errado in corrigidos.items():
            if errado:
                _demote(forn, campo, texto, errado)
        # 2. o que acertou entra ou sobe
        for campo, licao in novos.items():
            lista = forn.setdefault(campo, [])
            existente = next((x for x in lista if _mesma_licao(x, licao)), None)
            if existente:
                existente["acertos"] = int(existente.get("acertos", 0)) + 1
            else:
                lista.append(dict(licao, acertos=1))
            # o que mais acertou vai na frente; guarda no máximo 4 por campo
            lista.sort(key=lambda x: -int(x.get("acertos", 0)))
            forn[campo] = lista[:4]
        for campo in [c for c, v in forn.items() if not v]:
            forn.pop(campo, None)                       # não deixa campo vazio no arquivo
        if not forn:
            d["licoes"].pop(ch, None)
        alvo["salvar"] = True
    if novos:
        LOG.info("aprendi com a correção (%s): %s", ch, ", ".join(novos))
    return sorted(novos)


def _rotulo_aceitavel(rotulo: str) -> bool:
    """Um rótulo guardado ainda vale pelas regras de hoje?

    Serve para varrer o que foi aprendido pela versão antiga, que cortava em 42
    caracteres e guardava pedaço de prosa começando no meio de uma palavra
    ("copo valor em r$ sem iss…", rabo de "Escopo"). Rótulo assim casa com
    qualquer coisa e preenche o campo errado com cara de certeza.
    """
    r = _norm_espacos(rotulo)
    if len(r) < _MIN_ROTULO or _SO_RUIDO.match(r):
        return False
    if len(r.split()) > _MAX_PALAVRAS:
        return False
    if len(r) >= 40:                       # marca do corte antigo em 42 caracteres
        return False
    if re.search(r"[a-zà-ÿ]\.\s", r):      # ponto final no meio = prosa, não rótulo
        return False
    return True


def _licao_aceitavel(x: dict) -> bool:
    """Uma lição guardada ainda vale pelas regras de hoje?

    A de COLUNA tem regras próprias: cabeçalho com palavras de verdade e uma
    posição plausível. Passá-la pelo crivo de rótulo a reprovaria sempre — ela
    não tem rótulo — e o saneamento apagaria justamente o que passou a funcionar.
    """
    if x.get("cabecalho"):
        cab = _norm_espacos(x["cabecalho"])
        ordem = int(x.get("ordem") or 0)
        return (len(re.findall(r"[a-zà-ÿ]{2,}", cab)) >= _MIN_PALAVRAS_CAB
                and 1 <= ordem <= 12)
    return _rotulo_aceitavel(x.get("rotulo", ""))


def sanear() -> int:
    """Descarta as lições que não passam mais nas regras. Devolve quantas caíram."""
    from .dados_eletronet import _editando

    caidas = 0
    with _editando() as (d, alvo):
        licoes_ = d.get("licoes") or {}
        for ch in list(licoes_):
            forn = licoes_[ch] or {}
            for campo in list(forn):
                boas = [x for x in (forn.get(campo) or []) if _licao_aceitavel(x)]
                caidas += len(forn.get(campo) or []) - len(boas)
                if boas:
                    forn[campo] = boas
                else:
                    forn.pop(campo, None)
            if not forn:
                licoes_.pop(ch, None)
        if caidas:
            alvo["salvar"] = True
    if caidas:
        LOG.info("saneamento: %d lição(ões) antiga(s) descartada(s)", caidas)
    return caidas
