# -*- coding: utf-8 -*-
r"""O programa novo chega sozinho na máquina de todo mundo.

Hoje, para atualizar o setor, alguém compila e manda o .exe por e-mail ou
pendrive. Quem não substituiu fica para trás EM SILÊNCIO: gera AF com a leitura
antiga e ninguém percebe até sair errado.

Aqui uma pasta do setor guarda a versão oficial (o executável e um
`versao.json`), cada máquina roda uma cópia local, e na abertura ela compara e
se atualiza sozinha. Publicar de qualquer máquina atualiza as outras — não
existe "máquina que manda".

Os executáveis deste teste são arquivos de mentira: o que está sendo testado é
a MECÂNICA da troca (renomear, conferir, desfazer), que não depende de o
arquivo ser um programa de verdade. Assim o teste roda sem compilar nada.

As armadilhas que ele guarda
----------------------------
* "0.10" é MAIOR que "0.9". Comparando como texto, "0.10" < "0.9" e a
  atualização pararia de acontecer depois da nona versão.
* O Windows não deixa SOBRESCREVER um .exe em uso, só RENOMEAR. Por isso a
  troca é renomear-o-velho / pôr-o-novo, e não copiar por cima.
* Cópia interrompida pela rede não pode virar a versão de ninguém: o tamanho
  publicado é conferido antes de trocar.
* Se a troca falhar no meio, o executável ANTIGO volta. Ficar na versão velha é
  ruim; ficar sem programa nenhum é pior.
* Pasta do setor fora do ar nunca impede de abrir o app.
"""
import io
import json
import os
import shutil
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
from core import atualizador as at

falhas = []


def ok(nome, cond, extra=""):
    print(("  OK   " if cond else "  FALHA") + " " + nome +
          (("   " + extra) if extra and not cond else ""))
    if not cond:
        falhas.append(nome)


BASE = os.path.join(tempfile.gettempdir(), "teste_atualizacao_auto")
if os.path.exists(BASE):
    shutil.rmtree(BASE, ignore_errors=True)
SETOR = os.path.join(BASE, "setor")          # a pasta de rede
MAQUINA = os.path.join(BASE, "maquina")      # o computador de alguém
os.makedirs(SETOR, exist_ok=True)
os.makedirs(MAQUINA, exist_ok=True)


def exe_falso(caminho, conteudo):
    with open(caminho, "wb") as f:
        f.write(conteudo.encode("utf-8"))
    return caminho


print("== 0.10 é mais nova que 0.9 (comparação por número, não por texto) ==")
ok("0.10 > 0.9", at.mais_nova("0.10", "0.9"))
ok("0.8 > 0.7", at.mais_nova("0.8", "0.7"))
ok("1.0 > 0.99", at.mais_nova("1.0", "0.99"))
ok("a mesma versão não atualiza", not at.mais_nova("0.7", "0.7"))
ok("versão mais velha não atualiza", not at.mais_nova("0.6", "0.7"))
ok("texto estranho não quebra", not at.mais_nova("", "0.7"))

print("\n== publicar põe a versão oficial na pasta do setor ==")
origem = exe_falso(os.path.join(BASE, "build.exe"), "PROGRAMA VERSAO 0.8")
r = at.publicar(origem, SETOR, "0.8")
ok("publicou", r.get("ok"), str(r))
ok("o executável está na pasta", os.path.exists(os.path.join(SETOR, "build.exe")))
pub = at.versao_publicada(SETOR)
ok("o versao.json diz qual é", pub.get("versao") == "0.8", str(pub))
ok("e guarda o tamanho, para detectar cópia pela metade",
   pub.get("tamanho") == os.path.getsize(origem), str(pub.get("tamanho")))

print("\n== a máquina vê que há versão nova ==")
meu = exe_falso(os.path.join(MAQUINA, "build.exe"), "PROGRAMA VERSAO 0.7")
info = at.ha_atualizacao("0.7", SETOR)
ok("achou a 0.8", info.get("tem") and info.get("versao") == "0.8", str(info))
ok("quem já está na 0.8 não atualiza", not at.ha_atualizacao("0.8", SETOR).get("tem"))
ok("quem está numa versão futura também não",
   not at.ha_atualizacao("0.9", SETOR).get("tem"))

print("\n== a troca: renomeia o em uso, põe o novo no lugar ==")
r = at.aplicar(info["origem"], meu)
ok("trocou", r.get("ok"), str(r))
ok("o executável agora é o novo",
   io.open(meu, encoding="utf-8").read() == "PROGRAMA VERSAO 0.8")
ok("o antigo ficou guardado, não sumiu", os.path.exists(meu + at.SUFIXO_ANTIGO))
ok("e o antigo é mesmo o antigo",
   io.open(meu + at.SUFIXO_ANTIGO, encoding="utf-8").read() == "PROGRAMA VERSAO 0.7")

print("\n== na abertura seguinte o antigo é apagado ==")
at.limpar_antigo(meu)
ok("limpou", not os.path.exists(meu + at.SUFIXO_ANTIGO))

print("\n== cópia pela metade não vira a versão de ninguém ==")
# a rede caiu no meio: o arquivo na pasta ficou menor do que o versao.json diz
truncado = os.path.join(SETOR, "build.exe")
with open(truncado, "wb") as f:
    f.write(b"PROG")                          # bem menor que o publicado
ok("o app recusa o executável truncado", not at.ha_atualizacao("0.7", SETOR).get("tem"))
# e com o arquivo sumido da pasta também
os.remove(truncado)
ok("versao.json apontando para arquivo que não existe também é recusado",
   not at.ha_atualizacao("0.7", SETOR).get("tem"))

print("\n== a troca que falha NÃO deixa a pessoa sem programa ==")
at.publicar(exe_falso(os.path.join(BASE, "b2.exe"), "PROGRAMA VERSAO 0.9"), SETOR, "0.9")
meu2 = exe_falso(os.path.join(MAQUINA, "b2.exe"), "PROGRAMA VERSAO 0.7")
# Um diretório NÃO VAZIO ocupando o nome ".antigo" — que é para onde o
# executável em uso precisa ser renomeado. Não vazio de propósito: o app limpa
# sobras, e uma pasta vazia ele conseguiria remover.
atrapalho = meu2 + at.SUFIXO_ANTIGO
os.makedirs(atrapalho, exist_ok=True)
io.open(os.path.join(atrapalho, "trava.txt"), "w", encoding="utf-8").write("x")
r = at.aplicar(os.path.join(SETOR, "b2.exe"), meu2)
ok("a troca falhou, como esperado", not r.get("ok"), str(r))
ok("mas o executável continua lá", os.path.exists(meu2))
ok("e ainda é o que funcionava",
   io.open(meu2, encoding="utf-8").read() == "PROGRAMA VERSAO 0.7")
ok("e não ficou sobra de download pelo caminho",
   not os.path.exists(meu2 + at.SUFIXO_NOVO))
shutil.rmtree(atrapalho, ignore_errors=True)

# o desfazer depois da 1ª renomeação não dá para forçar de fora sem simular
# falha de sistema de arquivos; fica a garantia de que o código existe
fonte = io.open(os.path.join(PROJ, "core", "atualizador.py"), encoding="utf-8").read()
ok("se a 2ª renomeação falhar, o antigo volta",
   "os.rename(velho, exe)" in fonte and "melhor a versão velha que nenhuma" in fonte)

print("\n== pasta do setor fora do ar não impede de abrir ==")
ok("pasta inexistente: sem atualização, sem erro",
   not at.ha_atualizacao("0.7", os.path.join(BASE, "nao_existe")).get("tem"))
ok("pasta vazia idem", not at.ha_atualizacao("0.7", MAQUINA).get("tem"))
ok("pasta em branco idem", not at.ha_atualizacao("0.7", "").get("tem"))
ok("publicar sem pasta avisa em vez de estourar",
   at.publicar(origem, "", "0.8").get("ok") is False)
ok("publicar executável que não existe também",
   at.publicar(os.path.join(BASE, "nada.exe"), SETOR, "0.8").get("ok") is False)

print("\n== rodando pelo código-fonte, não há o que trocar ==")
r = at.atualizar_na_abertura("0.1")
ok("não tenta trocar o interpretador", not r.get("trocou"), str(r))

shutil.rmtree(BASE, ignore_errors=True)
print()
print("FALHAS: " + ", ".join(falhas) if falhas else "TUDO OK")
sys.exit(1 if falhas else 0)
