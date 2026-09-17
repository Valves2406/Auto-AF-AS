# -*- coding: utf-8 -*-
r"""O .exe numa pasta de rede: todos usam o MESMO cadastro, sem configurar nada.

A regra: um arquivo "cadastro-da-equipe.json" ao lado do executável vale para
quem rodar aquele executável. Sem ela, o antigo dados_usuario.json ao lado do
app era COPIADO para o perfil de cada um na 1ª execução — e a partir dali cada
máquina seguia com a sua cópia, divergindo sem ninguém notar.
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

BASE = os.path.join(tempfile.gettempdir(), "teste_exe_rede")
if os.path.exists(BASE):
    shutil.rmtree(BASE)
REDE = os.path.join(BASE, "servidor", "AutoAF")      # onde ficaria o .exe
MAQ_A = os.path.join(BASE, "perfilA")
MAQ_B = os.path.join(BASE, "perfilB")
for d in (REDE, MAQ_A, MAQ_B):
    os.makedirs(d, exist_ok=True)

falhas = []


def ok(nome, cond, extra=""):
    print(("  OK   " if cond else "  FALHA") + " " + nome + (("   " + extra) if extra and not cond else ""))
    if not cond:
        falhas.append(nome)


def rodar(perfil, codigo):
    """Roda como se fosse uma máquina: %APPDATA% próprio e o app 'instalado' na rede."""
    env = dict(os.environ, APPDATA=perfil)
    env.pop("GERADORAF_DADOS", None)
    env["GERADORAF_RAIZ"] = REDE          # faz o dado() apontar para a pasta de rede
    r = subprocess.run([sys.executable, "-c", codigo], capture_output=True, text=True,
                       cwd=PROJ, env=env, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print("      erro:", (r.stderr or "")[-300:])
    return [l for l in (r.stdout or "").splitlines() if l.startswith(">>")]


CAB = ("import sys,os,json;sys.path.insert(0,r'%s');"
       "from core import dados_eletronet as de;" % BACKEND)

print("== sem o arquivo da equipe: cada um no seu perfil ==")
a = rodar(MAQ_A, CAB + "print('>>', de.USER_JSON)")
b = rodar(MAQ_B, CAB + "print('>>', de.USER_JSON)")
print("   A:", a, "\n   B:", b)
ok("A e B separados", a and b and a != b)
ok("A no perfil dele", a and "perfilA" in a[0])

print("\n== com o cadastro-da-equipe.json ao lado do .exe ==")
equipe = os.path.join(REDE, "cadastro-da-equipe.json")
io.open(equipe, "w", encoding="utf-8").write("{}")
a = rodar(MAQ_A, CAB + "print('>>', de.USER_JSON)")
b = rodar(MAQ_B, CAB + "print('>>', de.USER_JSON)")
print("   A:", a, "\n   B:", b)
ok("A usa o arquivo da rede", a and "cadastro-da-equipe.json" in a[0], str(a))
ok("B usa o MESMO arquivo", b and a and a[0] == b[0], str(b))
ok("ninguém copiou para o perfil",
   not os.path.exists(os.path.join(MAQ_A, "AutoAF", "dados_usuario.json")))

print("\n== A cadastra, B enxerga na hora ==")
rodar(MAQ_A, CAB + "de.adicionar_usuario('pop', {'nome':'POP DA REDE','sigla':'RDE-RDE',"
                   "'municipio':'Goiânia','uf':'GO','endereco':'Rua da Rede, 1'});print('>> ok')")
b = rodar(MAQ_B, CAB + "print('>>', json.dumps([p['nome'] for p in de.pops_entrega() "
                       "if p.get('origem')=='usuario'], ensure_ascii=False))")
print("   B vê:", b)
ok("B enxerga o que A cadastrou", b and "POP DA REDE" in b[0], str(b))

print("\n== a tela sabe dizer que é da equipe ==")
a = rodar(MAQ_A, CAB + "d=de.onde_estao_os_dados();"
                       "print('>>', json.dumps({'compartilhado':d['compartilhado'],"
                       "'por_colocacao':d['por_colocacao']}))")
print("   ", a)
ok("marcado como compartilhado", a and '"compartilhado": true' in a[0], str(a))
ok("e sabe que veio da colocação do arquivo", a and '"por_colocacao": true' in a[0], str(a))

print("\n== atualizar o .exe não mexe no cadastro ==")
antes = json.load(io.open(equipe, encoding="utf-8"))
n_antes = len(antes.get("pops", []))
# "nova versão do .exe": o arquivo do app muda, o cadastro ao lado permanece
io.open(os.path.join(REDE, "Auto AF-AS.exe"), "w").write("v2")
a = rodar(MAQ_A, CAB + "print('>>', len([p for p in de.pops_entrega() if p.get('origem')=='usuario']))")
ok("o cadastro continua lá depois da troca", a and str(n_antes) in a[0], f"antes {n_antes}, {a}")

print("\n== pasta somente-leitura não trava o app ==")
somenteleitura = os.path.join(BASE, "readonly")
os.makedirs(somenteleitura, exist_ok=True)
ro = os.path.join(somenteleitura, "cadastro-da-equipe.json")
io.open(ro, "w", encoding="utf-8").write("{}")
os.chmod(ro, 0o444)
env_ro = dict(os.environ, APPDATA=MAQ_B, GERADORAF_RAIZ=somenteleitura)
env_ro.pop("GERADORAF_DADOS", None)
r = subprocess.run([sys.executable, "-c", CAB + "print('>>', de.USER_JSON)"],
                   capture_output=True, text=True, cwd=PROJ, env=env_ro,
                   encoding="utf-8", errors="replace")
saida = [l for l in (r.stdout or "").splitlines() if l.startswith(">>")]
print("   ", saida)
ok("cai no perfil local em vez de quebrar", saida and "perfilB" in saida[0], str(saida))
os.chmod(ro, 0o666)

print("\n%s" % ("TUDO OK" if not falhas else "FALHAS (%d): %s" % (len(falhas), ", ".join(falhas))))
sys.exit(1 if falhas else 0)
