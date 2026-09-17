# -*- coding: utf-8 -*-
r"""Cópia do .exe na máquina, apontando para a pasta da equipe pela tela.

O caso: a pessoa não roda o .exe da rede — copiou para a máquina dela e usou
Cadastros → "Onde ficam estes cadastros" para apontar a pasta do setor.

O que isto trava: apontar para a PASTA criava um "dados_usuario.json" AO LADO do
"cadastro-da-equipe.json" que já estava lá. Ela veria o cadastro vazio, os
outros não veriam o que ela cadastrasse, e o setor ficaria dividido em dois
grupos sem ninguém perceber.
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# o FILHO do subprocesso importa `core`, que agora mora em backend/
BACKEND = os.path.join(PROJ, "backend")

BASE = os.path.join(tempfile.gettempdir(), "teste_apontar_pasta")
falhas = []


def ok(nome, cond, extra=""):
    print(("  OK   " if cond else "  FALHA") + " " + nome + (("   " + extra) if extra and not cond else ""))
    if not cond:
        falhas.append(nome)


def rodar(perfil, codigo):
    env = dict(os.environ, APPDATA=perfil)
    env.pop("GERADORAF_DADOS", None)
    env.pop("GERADORAF_RAIZ", None)
    r = subprocess.run([sys.executable, "-c", codigo], capture_output=True, text=True,
                       cwd=PROJ, env=env, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print("      erro:", (r.stderr or "")[-300:])
    return [l for l in (r.stdout or "").splitlines() if l.startswith(">>")]


CAB = ("import sys,os,json;sys.path.insert(0,r'%s');"
       "from core import dados_eletronet as de;" % BACKEND)


def preparar():
    if os.path.exists(BASE):
        shutil.rmtree(BASE)
    rede = os.path.join(BASE, "servidor", "AutoAF")
    perfil = os.path.join(BASE, "perfil")
    for d in (rede, perfil):
        os.makedirs(d, exist_ok=True)
    return rede, perfil


# ---- 1. a pasta JÁ tem o cadastro da equipe -------------------------------
print("== a pasta do setor já tem o cadastro da equipe ==")
REDE, PERFIL = preparar()
equipe = os.path.join(REDE, "cadastro-da-equipe.json")
json.dump({"pops": [{"nome": "POP DA EQUIPE", "sigla": "EQP-EQP", "municipio": "Goiânia",
                     "uf": "GO", "endereco": "Rua da Equipe, 1", "origem": "usuario"}]},
          io.open(equipe, "w", encoding="utf-8"), ensure_ascii=False)

a = rodar(PERFIL, CAB + "r=de.usar_dados_em(r'%s');"
                        "nomes=[p['nome'] for p in de.pops_entrega() if p.get('origem')=='usuario'];"
                        "print('>>', json.dumps({'arquivo':os.path.basename(de.USER_JSON),"
                        "'criado':r.get('criado'),'vejo':nomes}, ensure_ascii=False))" % REDE)
print("   ", a)
ok("entra no arquivo DA EQUIPE, não num novo", a and '"cadastro-da-equipe.json"' in a[0], str(a))
ok("não criou um segundo arquivo", sorted(os.listdir(REDE)) == ["cadastro-da-equipe.json"],
   str(sorted(os.listdir(REDE))))
ok("enxerga o que a equipe cadastrou", a and "POP DA EQUIPE" in a[0], str(a))

# ---- 2. ela EDITA e o resto do setor vê ------------------------------------
print("\n== ela cadastra e edita normalmente ==")
a = rodar(PERFIL, CAB + "de.usar_dados_em(r'%s');"
                        "de.adicionar_usuario('pop', {'nome':'POP DELA','sigla':'DEL-DEL',"
                        "'municipio':'Palmas','uf':'TO','endereco':'Rua Dela, 2'});print('>> ok')" % REDE)
d = json.load(io.open(equipe, encoding="utf-8"))
nomes = [p.get("nome") for p in d.get("pops", [])]
ok("o cadastro dela foi para o arquivo da equipe", "POP DELA" in nomes, str(nomes))
ok("e o da equipe continua lá", "POP DA EQUIPE" in nomes, str(nomes))

# quem roda o .exe DA REDE vê o que ela cadastrou
env = dict(os.environ, APPDATA=os.path.join(BASE, "outro"), GERADORAF_RAIZ=REDE)
env.pop("GERADORAF_DADOS", None)
os.makedirs(os.path.join(BASE, "outro"), exist_ok=True)
r = subprocess.run([sys.executable, "-c", CAB +
                    "print('>>', json.dumps([p['nome'] for p in de.pops_entrega() "
                    "if p.get('origem')=='usuario'], ensure_ascii=False))"],
                   capture_output=True, text=True, cwd=PROJ, env=env,
                   encoding="utf-8", errors="replace")
b = [l for l in (r.stdout or "").splitlines() if l.startswith(">>")]
print("   quem roda o .exe da rede vê:", b)
ok("os dois caminhos caem no mesmo cadastro", b and "POP DELA" in b[0] and "POP DA EQUIPE" in b[0], str(b))

# ---- 3. pasta vazia: cria o arquivo da equipe (serve para os dois jeitos) --
print("\n== apontando para uma pasta VAZIA ==")
REDE2, PERFIL2 = preparar()
a = rodar(PERFIL2, CAB + "de.adicionar_usuario('pop', {'nome':'MEU POP','sigla':'MEU-MEU',"
                         "'municipio':'Recife','uf':'PE','endereco':'Rua Minha, 3'});"
                         "r=de.usar_dados_em(r'%s');"
                         "print('>>', json.dumps({'arquivo':os.path.basename(de.USER_JSON),"
                         "'criado':r.get('criado')}))" % REDE2)
print("   ", a)
ok("cria o cadastro-da-equipe.json", a and '"cadastro-da-equipe.json"' in a[0], str(a))
novo = os.path.join(REDE2, "cadastro-da-equipe.json")
ok("arquivo existe na pasta", os.path.exists(novo))
if os.path.exists(novo):
    d = json.load(io.open(novo, encoding="utf-8"))
    ok("semeado com o que ela já tinha",
       "MEU POP" in [p.get("nome") for p in d.get("pops", [])], str(d.get("pops")))

# ---- 4. pasta com o arquivo ANTIGO respeita o que está lá ------------------
print("\n== pasta com um dados_usuario.json antigo ==")
REDE3, PERFIL3 = preparar()
antigo = os.path.join(REDE3, "dados_usuario.json")
json.dump({"pops": [{"nome": "POP ANTIGO", "sigla": "ANT-ANT", "municipio": "Belém",
                     "uf": "PA", "endereco": "Rua Antiga, 4", "origem": "usuario"}]},
          io.open(antigo, "w", encoding="utf-8"), ensure_ascii=False)
a = rodar(PERFIL3, CAB + "de.usar_dados_em(r'%s');"
                         "nomes=[p['nome'] for p in de.pops_entrega() if p.get('origem')=='usuario'];"
                         "print('>>', json.dumps({'arquivo':os.path.basename(de.USER_JSON),"
                         "'vejo':nomes}, ensure_ascii=False))" % REDE3)
print("   ", a)
ok("usa o arquivo que já estava lá", a and '"dados_usuario.json"' in a[0], str(a))
ok("e enxerga o conteúdo dele", a and "POP ANTIGO" in a[0], str(a))
ok("sem criar um segundo arquivo", sorted(os.listdir(REDE3)) == ["dados_usuario.json"],
   str(sorted(os.listdir(REDE3))))

print("\n%s" % ("TUDO OK" if not falhas else "FALHAS (%d): %s" % (len(falhas), ", ".join(falhas))))
sys.exit(1 if falhas else 0)
