# -*- coding: utf-8 -*-
r"""A assinatura nunca fica sozinha, e a folha não sai pela metade.

Medido nos documentos que saíram do app (AF-E-362 e RTC-CPM-E-362):

    AF  pág 1: conteúdo até y=569 de 842  -> 273pt em branco no pé
    AF  pág 3: SÓ a assinatura            -> 785pt em branco (93%)
    CPM pág 2: conteúdo até y=692         -> sobravam 122pt até a margem
    CPM pág 3: SÓ a assinatura            -> 718pt em branco (85%)

Três causas, cada uma isolada por medição:

1. NO CPM a assinatura pedia ~110pt e havia 122pt livres: pulou por muito
   pouco, porque o encolhimento que a AF já fazia no papel nunca tinha sido
   copiado para lá.

2. `break-before: avoid` NÃO segura a assinatura. O Chromium ignora
   break-before/break-after e só respeita break-inside — está escrito no
   próprio CSS, descoberto numa correção anterior, e eu tropecei de novo:
   numa varredura de 8 tamanhos, dois ainda deixavam a assinatura órfã. Por
   isso as notas fiscais e a assinatura vão dentro de `.fim`, indivisível.

3. O RODAPÉ (garantia | faturamento) é um grid de UMA linha, e o Chromium não
   parte uma linha de grid: ou cabe, ou salta inteira. Faltavam ~10pt e ele
   saltou, deixando 273pt. Encolher o respiro no papel resolve sem empilhar
   os cartões — empilhar mediu pior (23% contra 21%) e ainda faria o PDF
   deixar de ser igual à prévia.

O teste varre tamanhos de documento porque um caso só não basta: a quebra
precisa cair em posições diferentes. Exige, em todos:
  • assinatura nunca sozinha numa folha;
  • nenhuma folha do MEIO com mais de 25% de papel branco no pé.

Precisa do Edge para imprimir; sem ele, declara-se pulado.
"""
import io
import os
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)

import logging
logging.disable(logging.CRITICAL)

import engine
from core.gerador import _edge_exe, gerar_af_pdf_html
from core.html_render import montar_cpm_html

falhas = []


def ok(nome, cond, extra=""):
    print(("  OK   " if cond else "  FALHA") + " " + nome +
          (("   " + extra) if extra and not cond else ""))
    if not cond:
        falhas.append(nome)


if not _edge_exe():
    print("  (Microsoft Edge não encontrado — teste pulado)")
    print("\nTUDO OK")
    sys.exit(0)

try:
    import pdfplumber
except ImportError:
    print("  (pdfplumber ausente — teste pulado)")
    print("\nTUDO OK")
    sys.exit(0)

LOCAIS = [("POP %02d" % i, "P%02d" % i,
           "Rodovia BR %d, km %d - bairro de exemplo" % (100 + i, i * 7),
           "Municipio %02d" % i, "MG" if i % 2 else "BA") for i in range(1, 20)]
FAT = [{"uf": "MG", "razao": "ELETRONET S.A - FILIAL", "razao_social": "ELETRONET S.A - FILIAL",
        "endereco": "Rua Paraíba, 550, Sala 900 - Savassi - Belo Horizonte",
        "cep": "30.130-141", "cnpj": "03.052.673/0002-64"},
       {"uf": "BA", "razao": "ELETRONET S.A - FILIAL", "razao_social": "ELETRONET S.A - FILIAL",
        "endereco": "Avenida Tancredo Neves, 620, Loja 3.305, Caminho das Árvores - Salvador",
        "cep": "41.820-020", "cnpj": "03.052.673/0020-46"}]


def payload(n_itens, n_locais):
    return {
        "prefixo": "AF-E", "numero": "362", "ano": "2026", "modificacao": "TR",
        "data_emissao": "15/09/2026",
        "fornecedor": "NEC Latin America S.A.", "cnpj": "49.074.412/0002-46",
        "insc_est": "799.721.778.110", "cep": "9.662-030",
        "endereco": "R. Jose Medeiro e Albuquerque, nº 413 - São Bernardo do Campo - SP",
        "objeto": "Fornecimento de Serviço de instalação - Região BA / MG",
        "moeda": "Real", "valor_total": "251.127,20",
        "garantia": ("A garantia para o objeto dessa oferta está sujeita ao prazo "
                     "previsto no Código Civil, a contar da entrega do bem."),
        "prazo_entrega": "30 dias após a assinatura do documento de contratação",
        "condicao_pagamento": ("O pagamento deve ser efetuado 90 dias após a "
                               "emissão da nota fiscal"),
        "itens": [{"codigo": "SERV%02d" % i,
                   "descricao": "Serviço de instalação - Região BA / MG (lote %d)" % i,
                   "quantidade": "1", "preco_unit_com": "1.000,00",
                   "preco_total_com": "1.000,00"} for i in range(1, n_itens + 1)],
        "entregas": [{"nome": n, "sigla": s, "endereco": e, "municipio": m, "uf": u}
                     for n, s, e, m, u in LOCAIS[:n_locais]],
        "faturamentos": FAT,
        "alcada": ("Compras com Concorrência: De R$ 30.000,01 até R$ 500.000,00 "
                   "(Gerente da área + Diretor da área)"),
    }


LIMITE = 25.0            # % de papel branco tolerado numa folha do MEIO


def avalia(html, tag):
    alvo = os.path.join(tempfile.gettempdir(), "teste_paginacao.pdf")
    if os.path.exists(alvo):
        os.remove(alvo)
    gerar_af_pdf_html(alvo, html)
    sozinha, pior = False, 0.0
    with pdfplumber.open(alvo) as pdf:
        n = len(pdf.pages)
        for i, pg in enumerate(pdf.pages, 1):
            ws = pg.extract_words()
            if not ws:
                continue
            texto = " ".join(w["text"] for w in ws)
            sobra = pg.height - max(w["bottom"] for w in ws)
            # uma folha com pouquíssimo texto e só nomes de quem assina
            if len(texto) < 70 and ("Eletronet" in texto or "Gerente" in texto
                                    or "NEC" in texto):
                sozinha = True
            if i < n:                       # a última pode acabar onde acabar
                pior = max(pior, 100.0 * sobra / pg.height)
    ok("%s — assinatura acompanhada" % tag, not sozinha)
    ok("%s — folha do meio sem buraco (<%.0f%%)" % (tag, LIMITE), pior <= LIMITE,
       "maior buraco %.0f%%" % pior)
    return alvo


print("== AF/AS: vários tamanhos, para a quebra cair em posições diferentes ==")
for n_it, n_loc in ((1, 19), (3, 19), (10, 19), (16, 19), (20, 4)):
    avalia(engine.montar_preview(payload(n_it, n_loc)), "%2d itens/%2d locais" % (n_it, n_loc))

print("\n== com RUBRICA ligada, a paginação não pode piorar ==")
# A faixa de rubrica é a última coisa que entra no documento, e por isso a que
# mais facilmente empurra uma folha. Medido nos dois modos:
#
#   "todas as folhas" — a tabela-pagina reserva o rodapé em TODA folha, então o
#   conteúdo se redistribui sozinho. Sai limpo em todos os tamanhos (9%).
#
#   "só a última" — a faixa é um bloco no fim do fluxo. Em 10 dos 11 tamanhos
#   medidos, a paginação fica IDÊNTICA à do documento sem rubrica: ela é de
#   graça. A exceção é o documento que termina com a última folha cheia até o
#   limite (medido: tinta até 814pt de 814pt úteis) — aí não cabe 1pt, a folha
#   extra é inevitável e a faixa vai sozinha. Encolher a faixa não resolveria:
#   o espaço livre é ZERO, não é pouco.
#
# O que este teste guarda é a propriedade que importa: a rubrica nunca custa
# MAIS de uma folha, e o modo "todas" nunca deixa buraco.
for n_it, n_loc in ((3, 19), (16, 19)):
    avalia(engine.montar_preview(dict(payload(n_it, n_loc),
                                      rubricas=True, rubricas_todas=True)),
           "todas  %2d itens/%2d locais" % (n_it, n_loc))


def folhas(html):
    p = os.path.join(tempfile.gettempdir(), "teste_pag_rub.pdf")
    if os.path.exists(p):
        os.remove(p)
    gerar_af_pdf_html(p, html)
    with pdfplumber.open(p) as pdf:
        return len(pdf.pages)


for n_it, n_loc in ((3, 19), (10, 19), (16, 19)):
    sem = folhas(engine.montar_preview(payload(n_it, n_loc)))
    com = folhas(engine.montar_preview(dict(payload(n_it, n_loc), rubricas=True)))
    ok("só a última — %2d itens: no máximo 1 folha a mais (%d → %d)"
       % (n_it, sem, com), com <= sem + 1)

print("\n== nenhum bloco do rodapé parte entre folhas (medido no papel) ==")
# A prova de que um cartão partiu: os campos dele aparecem numa folha que NÃO é
# a do título. Verificar só o CSS não bastaria — o `avoid` pode existir e ainda
# assim o bloco partir, se ele for mais alto que uma folha.
_CAMPOS_CARTAO = ("Garantia", "Prazo de entrega", "Forma de pagamento")
for n_it, n_loc in ((3, 19), (10, 19), (16, 19)):
    p = os.path.join(tempfile.gettempdir(), "teste_pag_bloco.pdf")
    if os.path.exists(p):
        os.remove(p)
    gerar_af_pdf_html(p, engine.montar_preview(payload(n_it, n_loc)))
    with pdfplumber.open(p) as pdf:
        folha_titulo, folhas_campos = None, set()
        for i, pg in enumerate(pdf.pages, 1):
            txt = " ".join(w["text"] for w in pg.extract_words())
            if "Garantia, prazo" in txt:
                folha_titulo = i
            if any(c in txt for c in _CAMPOS_CARTAO):
                folhas_campos.add(i)
    espalhado = sorted(folhas_campos - {folha_titulo}) if folha_titulo else []
    ok("%2d itens: cartão inteiro numa folha só" % n_it, not espalhado,
       "título na folha %s, campos também em %s" % (folha_titulo, espalhado))

print("\n== CPM/CPS: o mesmo ==")
for n_it, n_loc in ((1, 19), (16, 19)):
    c = engine.cpm_dados(payload(n_it, n_loc))
    avalia(montar_cpm_html(c.get("cpm") or c), "%2d itens/%2d locais" % (n_it, n_loc))

print("\n== as regras estão no CSS dos DOIS documentos ==")
fonte = io.open(os.path.join(PROJ, "core", "html_render.py"), encoding="utf-8").read()
ok("a assinatura e o bloco anterior formam uma peça só (AF)",
   '.fim{{break-inside:avoid}}' in fonte and '<div class="fim">' in fonte)
# A regra vale para os DOIS documentos porque agora é UMA só, num bloco comum.
# Antes eram duas cópias, e a cópia foi o defeito: o encolhimento existia no
# lado da AF e não no do CPM, e por isso a assinatura do CPM saiu órfã. Este
# teste checava "existem duas cópias" — checava a implementação, não a
# propriedade. Agora checa a propriedade: a regra existe uma vez e os dois
# renderizadores a usam.
ok("a regra da assinatura no papel existe uma vez só",
   fonte.count("margin-top:34px") == 1, str(fonte.count("margin-top:34px")))
ok("e os DOIS documentos usam o bloco comum",
   fonte.count("{_PRINT_COMUM}") == 2, str(fonte.count("{_PRINT_COMUM}")))
# `.foot>div` fora da lista de indivisíveis da AF é o que deixa o rodapé
# encher o pé da folha em vez de saltar inteiro (eram 273pt em branco).
# REGRA DO DOCUMENTO: bloco NÃO se parte. O único divisível é a tabela de
# objetos fornecidos — ela é alta e, indivisível, deixava 52% de folha branca.
#
# Isto REVERTE o que este teste exigia antes. A decisão anterior era deixar os
# cartões do rodapé partirem, porque mantê-los inteiros tinha custado um buraco
# de 273pt (32%) no pé de uma folha. O sintoma da decisão antiga: "Forma de
# pagamento" caía sozinha na folha seguinte, sem título, e ao lado dela ficava
# uma moldura vazia — lê-se como um bloco novo sem nome.
#
# Medido DEPOIS de reverter, em 6 tamanhos (1/3/8/10/16/24 itens): nenhum bloco
# partido e o pior vão ficou em 12%. O buraco de 273pt não voltou, então a
# reversão saiu de graça — mas o teste guarda a REGRA, não o custo, porque a
# regra é do documento e vale mesmo que o custo volte.
ok("os campos de um cartão do rodapé andam juntos",
   ".foot>div{{break-inside:avoid}}" in fonte,
   "sem isto 'Forma de pagamento' cai sozinha na folha seguinte, sem título")
ok("as caixas do topo também", ".metagrid>div,.total,.aviso{{break-inside:avoid}}" in fonte)
ok("e a tabela de objetos continua sendo a ÚNICA que flui",
   "table,.bloco,.foot,.metagrid{{break-inside:auto}}" in fonte
   and ".bloco.tabela{{break-inside:avoid}}" not in fonte)

print()
print("FALHAS: " + ", ".join(falhas) if falhas else "TUDO OK")
sys.exit(1 if falhas else 0)
