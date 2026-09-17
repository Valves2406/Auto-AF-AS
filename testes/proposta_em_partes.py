# -*- coding: utf-8 -*-
r"""Proposta repartida em vários arquivos, e o fornecedor que era adivinhado.

1. VÁRIAS PARTES
   Precision e SEICOM mandam a proposta repartida — técnica e comercial. A
   comercial da Precision diz, com todas as letras, "Local: Vide Proposta
   Técnica PST260514-01": nenhuma das duas, sozinha, tem tudo. A tela lia UM
   arquivo e a segunda leitura apagava a primeira.

   Regra de junção, por tipo de campo:
   - TEXTO: vale a PRIMEIRA parte que trouxer preenchido; as seguintes
     completam o que falta e não sobrescrevem.
   - ITENS: SOMAM. A AF-E-347 nasceu de quatro propostas da SEICOM (uma por
     estado) e tem 8 itens = 2+2+2+2, com total de R$ 51.958,37 = a soma dos
     quatro. A MESMA PARTE escolhida duas vezes (mesmos itens, mesmo total) não
     entra de novo, para o mesmo arquivo escolhido duas vezes não duplicar.
   - TOTAL: soma das partes, mas só quando a CONTA FECHA com a soma dos itens;
     não fechando, fica o maior e o app avisa.
   - ENTREGAS / FATURAMENTO / OBSERVAÇÕES: somam, sem repetir.
   - A proposta anexada ao PDF é a PRIMEIRA escolhida.

2. FORNECEDOR ADIVINHADO
   A proposta técnica da Precision Solutions era identificada como "ARTEMIS
   RACKS & SOLUTIONS LTDA": as duas têm "solutions" no nome, o desempate era
   "palavra mais longa", empatou em 9 letras e venceu quem vinha antes na
   lista. Fornecedor errado numa AF que vai ser assinada.

   Três mudanças: "solutions" e as outras palavras genéricas em inglês entram
   na lista de vagas; o peso passa a ser QUANTAS palavras batem (duas
   evidências valem mais que uma longa); e EMPATE NÃO ESCOLHE — com dois
   fornecedores no mesmo peso a função devolve nada, e o app avisa que não
   reconheceu.
"""
import io
import os
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
from core.extrator import ExtratorProposta

falhas = []


def ok(nome, cond, extra=""):
    print(("  OK   " if cond else "  FALHA") + " " + nome +
          (("   " + extra) if extra and not cond else ""))
    if not cond:
        falhas.append(nome)


E = ExtratorProposta()
JS = io.open(os.path.join(PROJ, "web", "app.js"), encoding="utf-8").read()
HTML = io.open(os.path.join(PROJ, "web", "index.html"), encoding="utf-8").read()

print("== a tela aceita escolher várias partes ==")
ok("o seletor de arquivo aceita vários", 'id="filePdf"' in HTML and "multiple" in
   HTML[HTML.index('id="filePdf"') - 120: HTML.index('id="filePdf"') + 120])
ok("existe a função que junta as partes", "function juntarPartes(" in JS)
ok("lê todos os escolhidos, não só o primeiro", "for (const f of arquivos)" in JS)
ok("e avisa qual parte está lendo", "Lendo parte" in JS)

print("\n== a regra de junção está escrita como se pretendeu ==")
# a janela cobre a função inteira, que cresceu quando passou a somar
corpo = JS[JS.index("function juntarPartes("):][:4200]
ok("texto: a 1ª parte que trouxer é a que vale",
   'if (junto[k] === undefined || junto[k] === "") junto[k] = v;' in corpo)
ok("itens SOMAM, e item igual em partes diferentes entra de novo",
   "(p.itens || []).forEach(it => junto.itens.push(it));" in corpo)
# A repetição que se quer barrar é a do ARQUIVO, não a do item: a ALG manda
# quatro propostas pedindo os mesmos dois produtos, um por filial da
# Eletronet. Deduplicando item a item, a AF sairia com 2 em vez de 8.
ok("mas a MESMA parte escolhida duas vezes é ignorada",
   "vistasPartes.has(impressao)" in corpo and "vistasPartes.add(impressao)" in corpo)
ok("o total só vira soma quando a conta fecha com os itens",
   "Math.abs(somaItens - somaPartes)" in corpo)
ok("e os números das propostas entram todos",
   "junto.numero_proposta = propostas.length > 1" in corpo)
ok("entregas/faturamento/observações somam sem repetir",
   'for (const campo of ["entregas", "faturamentos", "observacoes"])' in corpo
   and "vistos[campo].has(c)" in corpo)
ok("a proposta anexada é a 1ª escolhida",
   "junto.caminho_pdf = partes[0].caminho_pdf" in corpo)
ok("os avisos dizem de que parte vieram", "[parte ${i + 1}]" in corpo)
ok("CIENA não se combina (é um caso à parte)",
   "if (um.eh_ciena) { aplicarCienaEStatus(um); return; }" in JS)

print("\n== o fornecedor não é adivinhado no empate ==")
# "solutions" está no nome da ARTEMIS e no da Precision
ok("'solutions' é palavra vaga", "solutions" in E._PALAVRAS_VAGAS)
ok("e as outras genéricas em inglês também",
   {"systems", "technology", "services", "networks"} <= E._PALAVRAS_VAGAS)

# MAIS PALAVRAS BATENDO VENCE. Um texto que cita "racks ARTEMIS" e só
# "PRECISION" dá duas evidências para uma e uma para a outra — e a de duas tem
# de ganhar. (Era este o caso que eu tinha escrito como se fosse empate: não é.)
duas_contra_uma = ("Proposta da PRECISION para o cliente, com racks ARTEMIS "
                   "fornecidos conforme catálogo.")
r = E.identificar_do_catalogo(duas_contra_uma, com_confianca=True)
achado = r[0] if isinstance(r, tuple) else r
ok("duas palavras batendo vencem uma",
   achado is not None and "artemis" in (achado.get("empresa", "")).lower(),
   str((achado or {}).get("empresa")))

# e a guarda de empate existe: peso igual não escolhe
fonte = io.open(os.path.join(PROJ, "core", "extrator.py"), encoding="utf-8").read()
ok("empate devolve nada, em vez de chutar",
   "if len(pesos) > 1 and pesos[0][0] == pesos[1][0]:" in fonte)
ok("e o peso é (nº de palavras, tamanho da maior)",
   "pesos.append(((len(achadas), max(len(p) for p in achadas)), f))" in fonte)

# e um texto que cita só uma continua identificando
r2 = E.identificar_do_catalogo("Proposta comercial da PRECISION SOLUTIONS Ltda.",
                               com_confianca=True)
achado2 = r2[0] if isinstance(r2, tuple) else r2
ok("uma empresa só: identifica normalmente",
   achado2 is not None and "precision" in (achado2.get("empresa", "")).lower(),
   str((achado2 or {}).get("empresa")))

print("\n== e o caso real que deu o erro ==")
# o e-mail "info@precisionsolutions.com.br" mais a assinatura "da Precision
# Solutions" no rodapé: o nome da Precision aparece, o da ARTEMIS não
texto_precision = ("PST260514-01 Proposta Técnica Caracterização de fibras. "
                   "info@precisionsolutions.com.br - fone: (11) 5103-3260. "
                   "Este documento só pode ser reproduzido mediante prévia "
                   "autorização da Precision Solutions.")
r3 = E.identificar_do_catalogo(texto_precision, com_confianca=True)
achado3 = r3[0] if isinstance(r3, tuple) else r3
ok("a proposta técnica da Precision não vira ARTEMIS",
   achado3 is None or "artemis" not in (achado3.get("empresa", "")).lower(),
   str((achado3 or {}).get("empresa")))

print()
print("FALHAS: " + ", ".join(falhas) if falhas else "TUDO OK")
sys.exit(1 if falhas else 0)
