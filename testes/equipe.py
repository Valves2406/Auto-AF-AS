# -*- coding: utf-8 -*-
"""Cadastro compartilhado: uma pessoa cadastra, o setor inteiro enxerga."""
import sys, io, os, json, tempfile, shutil, subprocess

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# o FILHO do subprocesso importa `core`, que agora mora em backend/
BACKEND = os.path.join(PROJ, "backend")

# perfil FALSO para as duas "maquinas" — nao encosta no APPDATA real
BASE = os.path.join(tempfile.gettempdir(), "teste_equipe")
if os.path.exists(BASE):
    shutil.rmtree(BASE)
MAQ_A = os.path.join(BASE, "maquinaA")
MAQ_B = os.path.join(BASE, "maquinaB")
REDE = os.path.join(BASE, "servidor", "setor")
for d in (MAQ_A, MAQ_B, REDE):
    os.makedirs(d, exist_ok=True)

falhas = []


def ok(nome, cond, extra=""):
    print(("  OK   " if cond else "  FALHA") + " " + nome + (("   " + extra) if extra and not cond else ""))
    if not cond:
        falhas.append(nome)


def rodar(perfil, codigo):
    """Roda um trecho como se fosse uma maquina com o seu proprio %APPDATA%."""
    env = dict(os.environ, APPDATA=perfil)
    env.pop("GERADORAF_DADOS", None)
    r = subprocess.run([sys.executable, "-c", codigo], capture_output=True, text=True,
                       cwd=PROJ, env=env, encoding="utf-8", errors="replace")
    saida = [l for l in (r.stdout or "").splitlines() if l.startswith(">>")]
    if r.returncode != 0:
        print("      erro:", (r.stderr or "")[-400:])
    return saida


CAB = ("import sys,os,json;sys.path.insert(0,r'%s');"
       "from core import dados_eletronet as de;" % BACKEND)

print("== A e B começam separadas ==")
a = rodar(MAQ_A, CAB + "print('>>', de.USER_JSON)")
b = rodar(MAQ_B, CAB + "print('>>', de.USER_JSON)")
print("   A:", a, "\n   B:", b)
ok("cada máquina tem o seu arquivo", a != b and MAQ_A.lower() in a[0].lower().replace("\\\\", "\\"))

print("\n== A cadastra um POP e aponta para a pasta de rede ==")
# apontar para a PASTA cria (ou reusa) o cadastro-da-equipe.json — o mesmo nome
# que o .exe rodando de dentro da pasta procura, para os dois caminhos caírem no
# mesmo arquivo em vez de dividir o setor em dois grupos
rede_arq = os.path.join(REDE, "cadastro-da-equipe.json")
a = rodar(MAQ_A, CAB +
          "de.adicionar_usuario('pop', {'nome':'POP DA EQUIPE','sigla':'EQP-EQP',"
          "'municipio':'Belém','uf':'PA','endereco':'Rua Compartilhada, 1'});"
          "r=de.usar_dados_em(r'%s');"
          "print('>>', json.dumps({'ok':r['ok'],'criado':r.get('criado'),'arquivo':r['arquivo'],"
          "'compartilhado':r['compartilhado']}, ensure_ascii=False))" % REDE)
print("   ", a)
ok("A passou a usar a pasta de rede", a and '"ok": true' in a[0].lower().replace("true", "true"))
ok("arquivo criado na rede", os.path.exists(rede_arq), rede_arq)
if os.path.exists(rede_arq):
    d = json.load(io.open(rede_arq, encoding="utf-8"))
    nomes = [p.get("nome") for p in d.get("pops", [])]
    ok("o que A já tinha foi semeado na rede", "POP DA EQUIPE" in nomes, str(nomes))

print("\n== B aponta para a MESMA pasta ==")
b = rodar(MAQ_B, CAB +
          "r=de.usar_dados_em(r'%s');"
          "nomes=[p['nome'] for p in de.pops_entrega() if p.get('origem')=='usuario'];"
          "print('>>', json.dumps({'criado':r.get('criado'),'vejo':nomes}, ensure_ascii=False))" % REDE)
print("   ", b)
ok("B não recriou o arquivo (já existia)", b and '"criado": false' in b[0])
ok("B enxerga o POP que A cadastrou", b and "POP DA EQUIPE" in b[0], str(b))

print("\n== B cadastra e A enxerga na hora ==")
b = rodar(MAQ_B, CAB +
          "de.adicionar_usuario('pop', {'nome':'POP DO B','sigla':'BBB-BBB',"
          "'municipio':'Recife','uf':'PE','endereco':'Rua B, 2'});print('>> ok')")
a = rodar(MAQ_A, CAB +
          "nomes=[p['nome'] for p in de.pops_entrega() if p.get('origem')=='usuario'];"
          "print('>>', json.dumps(nomes, ensure_ascii=False))")
print("   A vê:", a)
ok("A enxerga o que B cadastrou", a and "POP DO B" in a[0], str(a))
ok("e o dele continua lá", a and "POP DA EQUIPE" in a[0], str(a))

print("\n== a escolha sobrevive a fechar e abrir o app ==")
a = rodar(MAQ_A, CAB + "print('>>', de.USER_JSON)")
ok("A continua apontada para a rede", a and REDE.lower() in a[0].lower().replace("\\\\", "\\"), str(a))
cfg = os.path.join(MAQ_A, "AutoAF", "config.json")
ok("config.json fica no perfil da máquina", os.path.exists(cfg), cfg)

print("\n== A volta ao cadastro local ==")
a = rodar(MAQ_A, CAB +
          "de.usar_dados_em('');"
          "nomes=[p['nome'] for p in de.pops_entrega() if p.get('origem')=='usuario'];"
          "print('>>', json.dumps({'arquivo':de.USER_JSON,'vejo':nomes}, ensure_ascii=False))")
print("   ", a)
nu = lambda t: t.lower().replace("\\\\", "\\")
ok("A voltou para o arquivo local", a and nu(MAQ_A) in nu(a[0]), str(a))
ok("não vê mais o POP do B", a and "POP DO B" not in a[0], str(a))
ok("o cadastro da equipe continua intacto",
   "POP DO B" in json.dumps(json.load(io.open(rede_arq, encoding="utf-8")), ensure_ascii=False))

print("\n%s" % ("TUDO OK" if not falhas else "FALHAS (%d): %s" % (len(falhas), ", ".join(falhas))))
sys.exit(1 if falhas else 0)
