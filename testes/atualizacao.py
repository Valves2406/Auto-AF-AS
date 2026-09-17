# -*- coding: utf-8 -*-
"""O que acontece com os dados do usuario quando sai uma versao nova do app.

Simula: usuario edita/oculta itens do catalogo base -> chega um .exe novo cujo
catalogo base mudou de grafia -> o item volta duplicado?
"""
import sys, io, os, json, tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = os.path.join(tempfile.gettempdir(), "teste_atualizacao_dados.json")
for f in (TMP, TMP + ".bak"):
    if os.path.exists(f):
        os.remove(f)
io.open(TMP, "w", encoding="utf-8").write("{}")
os.environ["GERADORAF_DADOS"] = TMP
sys.path.insert(0, PROJ)
os.chdir(PROJ)
from core import dados_eletronet as de

falhas = []


def ok(nome, cond, extra=""):
    print(("  OK   " if cond else "  FALHA") + " " + nome + (("   " + extra) if extra and not cond else ""))
    if not cond:
        falhas.append(nome)


# ---- catalogo BASE falso (faz o papel do que vem dentro do .exe) -----------
BASE_V1 = [
    {"nome": "Gravatai 3", "sigla": "GTI-TRI", "municipio": "Gravataí", "uf": "RS",
     "endereco": "Estrada Madorin", "maps": "", "latitude": "", "longitude": "",
     "cedente": "", "origem": "catalogo"},
    {"nome": "Tucuruí", "sigla": "1TUU-TUU", "municipio": "Tucuruí", "uf": "PA",
     "endereco": "Rodovia PA-263, Km 13", "maps": "", "latitude": "", "longitude": "",
     "cedente": "", "origem": "catalogo"},
]
# a versao NOVA corrige a grafia do nome e acrescenta um POP
BASE_V2 = [
    {"nome": "Gravataí 3", "sigla": "GTI-TRI", "municipio": "Gravataí", "uf": "RS",
     "endereco": "Estrada Madorin, 500", "maps": "", "latitude": "", "longitude": "",
     "cedente": "", "origem": "catalogo"},
    {"nome": "Tucuruí", "sigla": "1TUU-TUU", "municipio": "Tucuruí", "uf": "PA",
     "endereco": "Rodovia PA-263, Km 13", "maps": "", "latitude": "", "longitude": "",
     "cedente": "", "origem": "catalogo"},
    {"nome": "Pacajá", "sigla": "PCJ-PCJ", "municipio": "Pacajá", "uf": "PA",
     "endereco": "Rodovia Transamazônica", "maps": "", "latitude": "", "longitude": "",
     "cedente": "", "origem": "catalogo"},
]

_base_atual = {"v": BASE_V1}
de._pops_base = lambda: list(_base_atual["v"])          # troca o catalogo base


def nomes():
    return [p["nome"] for p in de.pops_entrega()]


de.migrar()                                   # o app carimba a versao na abertura
print("== versao 1 do app ==")
print("   catalogo:", nomes())

# ---- o usuario CORRIGE um item do catalogo (ocultar + recadastrar) --------
print("\n== usuario corrige 'Gravatai 3' e cadastra um POP proprio ==")
import engine
engine.atualizar("pop", {"nome": "Gravatai 3", "sigla": "GTI-TRI", "municipio": "Gravataí"},
                 {"nome": "Gravatai 3", "sigla": "GTI-TRI", "municipio": "Gravataí", "uf": "RS",
                  "endereco": "Estrada Madorin, Subestação Gravatai 3 - RS", "latitude": "29°53'15.21\"S",
                  "longitude": "50°57'43.72\"W", "maps": "", "cedente": ""})
de.adicionar_usuario("pop", {"nome": "POP do Usuario", "sigla": "USR-USR",
                             "municipio": "Belém", "uf": "PA", "endereco": "Rua Teste, 1"})
print("   catalogo:", nomes())
ok("edicao nao duplicou na v1", nomes().count("Gravatai 3") == 1, str(nomes()))
ok("POP proprio esta la", "POP do Usuario" in nomes())

# ---- chega a versao 2 (novo .exe, catalogo base diferente) ----------------
print("\n== CHEGA A VERSAO 2 (mesmo dados_usuario.json) ==")
_base_atual["v"] = BASE_V2
print("   catalogo:", nomes())
ok("POP proprio sobreviveu a atualizacao", "POP do Usuario" in nomes(), str(nomes()))
ok("POP novo da versao 2 apareceu", "Pacajá" in nomes(), str(nomes()))
so_gravatai = [n for n in nomes() if "ravata" in n]
ok("Gravatai NAO duplicou apos a atualizacao", len(so_gravatai) == 1,
   "aparece %d vez(es): %s" % (len(so_gravatai), so_gravatai))

# ---- o usuario tinha OCULTADO um item que a v2 renomeia -------------------
print("\n== usuario oculta 'Tucuruí' e a v2 muda a grafia ==")
engine.remover("pop", {"nome": "Tucuruí", "sigla": "1TUU-TUU", "municipio": "Tucuruí"})
print("   apos ocultar:", nomes())
ok("ocultou de fato", "Tucuruí" not in nomes(), str(nomes()))
_base_atual["v"] = [dict(p, nome="Tucurui") if p["sigla"] == "1TUU-TUU" else p for p in BASE_V2]
print("   v3 escreve 'Tucurui' (sem acento):", nomes())
ok("o item ocultado continua oculto apos a atualizacao",
   not any("ucuru" in n for n in nomes()), str(nomes()))

# ---- versao do esquema ----------------------------------------------------
print("\n== versao do esquema gravada ==")
d = json.load(io.open(TMP, encoding="utf-8"))
print("   chaves:", list(d))
ok("arquivo tem carimbo de versao", "versao" in d, str(list(d)))

print("\n%s" % ("TUDO OK" if not falhas else "FALHAS (%d): %s" % (len(falhas), ", ".join(falhas))))
sys.exit(1 if falhas else 0)
