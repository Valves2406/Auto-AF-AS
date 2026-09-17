# -*- coding: utf-8 -*-
r"""A lição de COLUNA: aprender o valor que está numa tabela.

Por que esta suíte existe
-------------------------
Medido no uso real: 13 propostas lidas pelo app, ZERO lições guardadas. O
aprendizado não estava quebrado — estava cego para o formato que as propostas
realmente usam.

A lição de RÓTULO pressupõe "Rótulo: valor" na mesma linha. A proposta real vem
em TABELA:

    Escopo  Valor em R$ sem ISS  ISS (%)  Valor em R$ com ISS
    Caracterização de Fibras
    62.045,37   2%   63.311,60

O rótulo de 63.311,60 é "Valor em R$ com ISS", três colunas à direita. O
`rotulo_antes` devolvia "r$ sem iss iss (%) valor" — um pedaço do cabeçalho que,
ao ser relido, não achava nada. A trava do `confere()` recusava a lição (e fazia
bem). Toda vez. Por isso o contador ficava em zero.

A lição de coluna guarda outra coisa: a linha de CABEÇALHO e a POSIÇÃO do valor
entre os números. "O total é o 2º dinheiro da primeira linha de números depois
deste cabeçalho." Isso se repete na proposta seguinte do mesmo fornecedor.

Os textos abaixo reproduzem o layout das propostas reais (PADTEC, FONNET).
"""
import io
import os
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = os.path.join(tempfile.gettempdir(), "teste_licao_coluna.json")
for _f in (TMP, TMP + ".bak"):
    if os.path.exists(_f):
        os.remove(_f)
io.open(TMP, "w", encoding="utf-8").write("{}")
os.environ["GERADORAF_DADOS"] = TMP           # nunca encosta no cadastro real
sys.path.insert(0, PROJ)
from core import aprendizado as ap

falhas = []


def ok(nome, cond, extra=""):
    print(("  OK   " if cond else "  FALHA") + " " + nome + (("   " + extra) if extra and not cond else ""))
    if not cond:
        falhas.append(nome)


# ---------------------------------------------------------------- textos --
# Layout da PADTEC: cabeçalho, linha de descrição, linha de números.
PADTEC_1 = """PROPOSTA COMERCIAL 2026-1626 V2
A seguir, é apresentado o valor referente ao serviço oferecido pela PADTEC nesta
proposta, considerando os valores em Reais e com todos os impostos pertinentes.
Escopo Valor em R$ sem ISS ISS (%) Valor em R$ com ISS
Caracterização de Fibras
62.045,37 2% 63.311,60
Furnas - Brasília
A PADTEC informa que o recolhimento do ISSQN será feito no domicílio tributário.
Validade da proposta: 30 dias. Frete: 4.378,86 incluso.
"""
# a MESMA fornecedora, outro projeto: muda a descrição e os números, o
# cabeçalho não. É aqui que a lição prova que serve para alguma coisa.
PADTEC_2 = """PROPOSTA COMERCIAL 2026-1655 V2
A seguir, é apresentado o valor referente ao serviço oferecido pela PADTEC nesta
proposta, considerando os valores em Reais e com todos os impostos pertinentes.
Escopo Valor em R$ sem ISS ISS (%) Valor em R$ com ISS
Caracterização de Fibras
100.995,32 2% 103.056,45
Samambaia - Imperatriz
Validade da proposta: 30 dias. Frete: 4.378,86 incluso.
"""
CNPJ = "03.549.807/0009-23"

print("== a ancora sai do CABECALHO, nao da descricao ==")
col = ap.ancora_coluna(PADTEC_1, "63.311,60")
ok("achou a coluna", bool(col), str(col))
ok("ancorou no cabecalho de precos",
   col.get("cabecalho", "").startswith("escopo valor em r$ sem iss"),
   repr(col.get("cabecalho")))
ok("NAO ancorou na descricao do escopo", "caracterizacao" not in col.get("cabecalho", ""),
   "a descricao muda a cada proposta; ancorar nela vale para um documento so")
ok("guardou a posicao certa do valor", col.get("ordem") == 2, str(col.get("ordem")))

print("\n== a licao passa na propria prova ==")
ok("rele o mesmo valor no texto de origem",
   ap.ler_com_coluna(PADTEC_1, col["cabecalho"], col["ordem"]) == "63.311,60")
ok("e o confere aprova", ap.confere_licao(PADTEC_1, col, "valor_total", "63.311,60"))

print("\n== e o rotulo sozinho NAO daria conta (o caso que falhava) ==")
rot = ap.rotulo_antes(PADTEC_1, "63.311,60")
ok("o rotulo extraido nao rele o valor", not ap.confere(PADTEC_1, rot, "valor_total", "63.311,60"),
   "se este passar, a licao de coluna deixou de ser necessaria para este caso")

print("\n== ciclo completo: corrigir numa proposta, acertar na seguinte ==")
extraido = {"valor_total": "4.378,86"}          # o que o extrator leu errado
campos = ap.aprender(CNPJ, PADTEC_1, extraido, {"valor_total": "63.311,60"})
ok("aprendeu com a correcao", campos == ["valor_total"], str(campos))

guardadas = ap.licoes(CNPJ).get("valor_total") or []
ok("guardou UMA licao", len(guardadas) == 1, str(guardadas))
ok("guardou como licao de coluna", bool(guardadas and guardadas[0].get("cabecalho")))

aplicado = ap.aplicar(CNPJ, PADTEC_2)
ok("aplica na OUTRA proposta da mesma fornecedora",
   aplicado.get("valor_total") == "103.056,45",
   "%r (o certo e 103.056,45, o total com ISS de Samambaia-Imperatriz)" % aplicado.get("valor_total"))
ok("nao confunde com o frete de 4.378,86", aplicado.get("valor_total") != "4.378,86")

print("\n== a licao sobrevive ao saneamento ==")
ok("licao de coluna e aceitavel", ap._licao_aceitavel(guardadas[0]))
ok("sanear() nao apaga a licao boa", ap.sanear() == 0 and ap.licoes(CNPJ).get("valor_total"))

print("\n== o que NAO deve virar licao ==")
# ancora sem cara de tabela de precos: passa na prova no proprio texto e nao se
# repete em proposta nenhuma
SEM_TABELA = """Pedido de cotacao
Solicitante : Mateus Gabriel Vieira Data de solicitacao : 08/01/2026
131.781,58
"""
ok("ancora que nao e cabecalho de precos e recusada",
   not ap.ancora_coluna(SEM_TABELA, "131.781,58"),
   "ancorar em nome de pessoa e data faz uma licao que so vale para um documento")

ok("valor que nao e dinheiro nao vira licao de coluna",
   not ap.ancora_coluna(PADTEC_1, "30 dias"))
ok("valor ausente do texto nao vira licao", not ap.ancora_coluna(PADTEC_1, "9.999.999,99"))

print("\n== a licao de ROTULO continua funcionando ==")
FORMULARIO = """Nossa referencia: PRPT 9363_26A
Valor Global da Proposta ......... R$ 140.474,70
Prazo de entrega: 45 dias
"""
CNPJ2 = "02.820.966/0001-09"
r = ap.rotulo_antes(FORMULARIO, "140.474,70")
ok("le o rotulo de um layout de formulario", "valor global da proposta" in r, repr(r))
ok("e ele passa na prova", ap.confere(FORMULARIO, r, "valor_total", "140.474,70"))
campos2 = ap.aprender(CNPJ2, FORMULARIO, {"valor_total": "1,00"},
                      {"valor_total": "140.474,70"})
ok("aprendeu por rotulo", campos2 == ["valor_total"], str(campos2))
g2 = (ap.licoes(CNPJ2).get("valor_total") or [{}])[0]
ok("guardou como licao de ROTULO (nao de coluna)", bool(g2.get("rotulo")) and not g2.get("cabecalho"),
   str(g2))

print("\n== licao ruim perde ponto e cai ==")
# a lição de coluna acerta na PADTEC_1; se um dia ler errado e o usuário
# corrigir, ela tem de perder ponto — senão fica para sempre
antes = len(ap.licoes(CNPJ).get("valor_total") or [])
ap.aprender(CNPJ, PADTEC_1, {"valor_total": "63.311,60"}, {"valor_total": "62.045,37"})
depois = ap.licoes(CNPJ).get("valor_total") or []
ok("a licao que errou perdeu o ponto e saiu",
   len(depois) < antes or all(x.get("ordem") != 2 for x in depois),
   "antes %d, agora %s" % (antes, depois))

print("\n%s" % ("TUDO OK" if not falhas else "FALHAS (%d): %s" % (len(falhas), ", ".join(falhas))))
sys.exit(1 if falhas else 0)
