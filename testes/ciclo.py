# -*- coding: utf-8 -*-
"""Ciclo completo do aprendizado, num arquivo de dados DESCARTAVEL:
ler -> corrigir -> guardar licao -> proposta nova ja vem certa -> licao ruim cai.
"""
import sys, io, os, json, tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# o FILHO do subprocesso importa `core`, que agora mora em backend/
BACKEND = os.path.join(PROJ, "backend")
# arquivo de dados isolado: o teste NAO toca no cadastro real
TMP = os.path.join(tempfile.gettempdir(), "teste_aprendizado_dados.json")
for f in (TMP, TMP + ".bak", os.path.join(os.path.dirname(TMP), "propostas_lidas.json")):
    if os.path.exists(f):
        os.remove(f)
io.open(TMP, "w", encoding="utf-8").write("{}")
os.environ["GERADORAF_DADOS"] = TMP
sys.path.insert(0, os.path.join(PROJ, "backend"))
sys.path.insert(0, PROJ)
os.chdir(PROJ)
from core import aprendizado as ap
from core import dados_eletronet as de

print("dados do teste:", de.USER_JSON)
assert de.USER_JSON == TMP, "nao redirecionou o arquivo de dados!"

falhas = []


def ok(nome, cond, extra=""):
    print(("  OK   " if cond else "  FALHA") + " " + nome + (("  " + extra) if extra and not cond else ""))
    if not cond:
        falhas.append(nome)


CNPJ = "12.345.678/0001-99"
P1 = ("PROPOSTA COMERCIAL 001\n"
      "Cliente: Eletronet\n"
      "Nossa referencia: PRPT 6117_26A\n"
      "Valor Global da Proposta: R$ 1.142.297,80\n"
      "Prazo de entrega: 45 dias\n")

# ---- 1. o extrator errou o valor; o usuario corrigiu -----------------------
print("\n== 1. aprende com a correcao ==")
extraido = {"valor_total": "6.117,00", "numero_proposta": "001", "prazo_entrega": "",
            "garantia": "", "condicao_pagamento": ""}
final = {"valor_total": "1.142.297,80", "numero_proposta": "PRPT 6117_26A",
         "prazo_entrega": "45 dias", "garantia": "", "condicao_pagamento": ""}
aprendeu = ap.aprender(CNPJ, P1, extraido, final)
print("   aprendeu:", aprendeu)
ok("aprendeu o valor total", "valor_total" in aprendeu)
ok("aprendeu o numero da proposta", "numero_proposta" in aprendeu)
lic = ap.licoes(CNPJ)
print("   licoes:", json.dumps(lic, ensure_ascii=False))
ok("rotulo do valor e limpo", lic.get("valor_total", [{}])[0].get("rotulo", "").startswith("valor global"),
   str(lic.get("valor_total")))

# ---- 2. proposta NOVA do mesmo fornecedor, outros numeros ------------------
print("\n== 2. aplica na proposta seguinte ==")
P2 = ("PROPOSTA COMERCIAL 002\n"
      "Nossa referencia: PRPT 7000_26B\n"
      "Valor Global da Proposta: R$ 987.654,32\n"
      "Prazo de entrega: 60 dias\n")
achou = ap.aplicar(CNPJ, P2)
print("   aplicou:", achou)
ok("leu o valor novo", achou.get("valor_total") == "987.654,32", str(achou))
ok("leu a referencia nova", achou.get("numero_proposta") == "PRPT 7000_26B", str(achou))

# ---- 3. licao que releria errado NAO entra --------------------------------
print("\n== 3. recusa licao que nao confere ==")
P3 = ("As datas a serem disponibilizadas obedecerao o cronograma e o prazo de "
      "entrega sera de 90 dias apos o aceite definitivo.")
antes_n = len(ap.licoes(CNPJ).get("prazo_entrega", []))
ap.aprender(CNPJ, P3, {"prazo_entrega": ""}, {"prazo_entrega": "90 dias"})
depois_n = len(ap.licoes(CNPJ).get("prazo_entrega", []))
ok("nao guardou licao que releria outra coisa", depois_n == antes_n,
   f"antes {antes_n}, depois {depois_n}")

# ---- 4. licao que passa a errar perde ponto e cai -------------------------
print("\n== 4. licao ruim e descartada ==")
# planta uma licao ruim a mao (como as que estavam no cadastro real)
with de._editando() as (d, alvo):
    d.setdefault("licoes", {}).setdefault(ap._chave(CNPJ), {})["condicao_pagamento"] = [
        {"rotulo": "obedecerao o cronograma e o prazo de", "acertos": 1}]
    alvo["salvar"] = True
P4 = "Fornecedor X. obedecerao o cronograma e o prazo de 30 dias liquidos"
errado = ap.ler_com_rotulo(P4, "obedecerao o cronograma e o prazo de", "condicao_pagamento")
print("   a licao ruim leria:", repr(errado))
ap.aprender(CNPJ, P4, {"condicao_pagamento": errado}, {"condicao_pagamento": "NET 60"})
ok("licao ruim saiu do cadastro", not ap.licoes(CNPJ).get("condicao_pagamento"),
   str(ap.licoes(CNPJ).get("condicao_pagamento")))

# ---- 5. persistencia em AppData -------------------------------------------
print("\n== 5. leitura da proposta persiste em disco ==")
falso_pdf = os.path.join(tempfile.gettempdir(), "proposta_teste.pdf")
ap.lembrar_leitura(falso_pdf, P1, extraido)
print("   arquivo:", ap._arquivo_lidas())
ok("guardou ao lado do dados_usuario", os.path.exists(ap._arquivo_lidas()))
ok("fica na mesma pasta dos cadastros",
   os.path.dirname(ap._arquivo_lidas()) == os.path.dirname(de.USER_JSON))
rec = ap.leitura(falso_pdf)
ok("recupera o texto", rec.get("texto") == P1)
ok("recupera o que o extrator entendeu", rec.get("extraido", {}).get("valor_total") == "6.117,00")
ok("some para caminho desconhecido", ap.leitura(os.path.join(tempfile.gettempdir(), "nada.pdf")) == {})

# ---- 6. sobrevive a "reabrir o app" (novo processo le o disco) ------------
print("\n== 6. sobrevive a reabrir o app ==")
import subprocess
codigo = (
    "import os,sys;"
    f"os.environ['GERADORAF_DADOS']=r'{TMP}';"
    f"sys.path.insert(0,r'{BACKEND}');"
    "from core import aprendizado as ap;"
    f"r=ap.leitura(r'{falso_pdf}');"
    "print('TEXTO_OK' if r.get('texto') else 'VAZIO');"
    f"print('LICOES', len(ap.licoes('{CNPJ}')))"
)
out = subprocess.run([sys.executable, "-c", codigo], capture_output=True, text=True, cwd=PROJ)
print("   processo novo:", out.stdout.strip().replace("\n", " | ") or out.stderr[-200:])
ok("outro processo enxerga a leitura", "TEXTO_OK" in out.stdout)
ok("outro processo enxerga as licoes", "LICOES 2" in out.stdout or "LICOES 3" in out.stdout)

print("\n%s" % ("TUDO OK" if not falhas else "FALHAS (%d): %s" % (len(falhas), ", ".join(falhas))))
sys.exit(1 if falhas else 0)
