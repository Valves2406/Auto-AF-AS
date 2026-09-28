# -*- coding: utf-8 -*-
r"""Cadastros no banco da equipe (Supabase), com um banco DE MENTIRA local.

O QUE MUDOU
-----------
Fornecedores, filiais de faturamento e POPs passaram a morar num banco na
nuvem: o que alguém cadastra aparece para o setor inteiro, sem arquivo em pasta
de rede. AF, AS e propostas NÃO vão para o banco — só esses três cadastros.

O QUE ESTE TESTE GUARDA
-----------------------
  • na primeira abertura, o arquivo da máquina SEMEIA o banco vazio: a lista
    que a pessoa enxergava (modelo + cadastros − ocultos) e os ocultos, que
    continuam restauráveis; depois o arquivo fica carimbado e não repete;
  • um segundo arquivo só ACRESCENTA o que o banco não tem — não desfaz uma
    correção feita no banco com um dado velho; e o que a versão antiga do app
    gravar no arquivo DEPOIS (a transição) também chega, sem duplicar;
  • o que outra máquina grava aparece nas listas em segundos, e a conferência
    é uma pergunta leve ("mudou?"), não a lista inteira de novo;
  • cadastrar, editar, ocultar e restaurar vão ao banco, pelo número do item;
    duplicata é recusada; nada é apagado de verdade;
  • sem internet: a tela segue com a cópia local, sem esperar o tempo-limite
    a cada lista; gravar avisa que nada foi salvo; sem cópia, vale o modelo;
  • chave errada não derruba nada — só volta ao modo sem banco;
  • o .exe mandado SOZINHO acha o banco que viaja dentro dele; um banco.json
    ao lado do .exe manda mais que o embutido;
  • um script da pasta testes/ NUNCA acha o banco de verdade pelo config.json.

O banco de mentira responde como a API do Supabase (PostgREST) nos pedidos que
o app faz, com as mesmas regras de acesso: sem apagar, sem incluir oculto.
Os dados são FICTÍCIOS.
"""
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJ, "backend"))

import logging
logging.disable(logging.CRITICAL)

falhas = []


def ok(nome, cond, extra=""):
    print(("  OK   " if cond else "  FALHA") + " " + nome +
          (("   " + extra) if extra and not cond else ""))
    if not cond:
        falhas.append(nome)


# ------------------------------------------------------ banco de mentira --
CHAVE = "sb_publishable_teste"
CAMPOS = {
    "fornecedores": ("apelido", "empresa", "cnpj", "insc_est", "endereco", "cep", "garantia"),
    "faturamento": ("uf", "razao_social", "cnpj", "cnpj2", "endereco", "cep", "insc_est", "insc_mun"),
    "pops": ("nome", "sigla", "endereco", "municipio", "uf", "maps", "latitude", "longitude", "cedente"),
}
NOME = {"fornecedores": ("apelido", "empresa"), "faturamento": ("razao_social",), "pops": ("nome",)}
TABELAS = {t: [] for t in CAMPOS}
PEDIDOS = []
_seq = [0]
_relogio = [0]


def agora():                               # o "now()" do banco: sempre andando
    _relogio[0] += 1
    return "2026-09-25T12:00:00.%06d+00:00" % _relogio[0]


class Falso(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _resp(self, codigo, corpo, extra=None):
        dados = json.dumps(corpo).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(dados)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(dados)

    def _alvo(self):
        u = urllib.parse.urlsplit(self.path)
        tabela = u.path.rsplit("/", 1)[-1]
        return tabela, urllib.parse.parse_qs(u.query)

    def _autorizado(self):
        PEDIDOS.append((self.command, self.path))
        if self.headers.get("apikey") != CHAVE or self.headers.get("Authorization") != "Bearer " + CHAVE:
            self._resp(401, {"message": "Invalid API key"})
            return False
        return True

    def _corpo(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n).decode("utf-8")) if n else None

    def do_GET(self):
        if not self._autorizado():
            return
        tabela, q = self._alvo()
        linhas = TABELAS[tabela]
        if q.get("select") == ["atualizado_em"]:          # a pergunta leve: "mudou?"
            topo = sorted(linhas, key=lambda r: r["atualizado_em"], reverse=True)[:1]
            faixa = ("0-0/%d" % len(linhas)) if linhas else "*/0"
            return self._resp(200, [{"atualizado_em": r["atualizado_em"]} for r in topo],
                              {"Content-Range": faixa})
        self._resp(200, sorted(linhas, key=lambda r: r["id"]))

    def do_POST(self):
        if not self._autorizado():
            return
        tabela, _ = self._alvo()
        feitos = []
        for reg in self._corpo():
            if reg.get("oculto"):
                return self._resp(403, {"code": "42501", "message": "new row violates row-level security policy"})
            if not any(str(reg.get(k) or "").strip() for k in NOME[tabela]):
                return self._resp(400, {"code": "23514", "message": "violates check constraint"})
            _seq[0] += 1
            quando = agora()
            linha = {"id": _seq[0], **{k: str(reg.get(k) or "") for k in CAMPOS[tabela]},
                     "oculto": False, "criado_em": quando, "atualizado_em": quando}
            feitos.append(linha)
        TABELAS[tabela].extend(feitos)
        self._resp(201, feitos)

    def do_PATCH(self):
        if not self._autorizado():
            return
        tabela, q = self._alvo()
        ids = {int(i) for i in q["id"][0].removeprefix("in.(").rstrip(")").split(",")}
        mudar = self._corpo()
        feitos = []
        for r in TABELAS[tabela]:
            if r["id"] in ids:
                r.update(mudar, atualizado_em=agora())      # o gatilho do banco carimba
                feitos.append(dict(r))
        self._resp(200, feitos)

    def do_DELETE(self):                    # a chave do app não apaga
        if self._autorizado():
            self._resp(403, {"code": "42501", "message": "permission denied"})


srv = ThreadingHTTPServer(("127.0.0.1", 0), Falso)
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = "http://127.0.0.1:%d" % srv.server_address[1]

# ------------------------------------------------ máquina de mentira -------
TMP = tempfile.mkdtemp(prefix="autoaf_banco_")
os.environ["APPDATA"] = TMP                      # perfil falso: config e cópia local aqui
os.environ.pop("GERADORAF_SEM_BANCO", None)      # o rodar.py desliga o banco; aqui ele é o assunto
os.environ.pop("GERADORAF_DADOS", None)
os.environ["GERADORAF_BANCO_URL"] = URL
os.environ["GERADORAF_BANCO_CHAVE"] = CHAVE

PERFIL = os.path.join(TMP, "AutoAF")
os.makedirs(PERFIL, exist_ok=True)
ARQ = os.path.join(PERFIL, "dados_usuario.json")
with open(ARQ, "w", encoding="utf-8") as f:
    json.dump({
        "versao": 2,
        "fornecedores": [{"apelido": "ALFA", "empresa": "ALFA REDES LTDA", "cnpj": "11.111.111/0001-11",
                          "insc_est": "", "endereco": "Rua A, 1", "cep": "01000-000", "garantia": "12 meses",
                          "origem": "usuario"}],
        "pops": [{"nome": "POP NOVO", "sigla": "NOV-NOV", "endereco": "Rua P, 9", "municipio": "Recife",
                  "uf": "PE", "maps": "", "latitude": "", "longitude": "", "cedente": "", "origem": "usuario"}],
        "ocultos": {"faturamento": [{"razao_social": "ELETRONET FILIAL VELHA", "uf": "RJ",
                                     "cnpj": "22.222.222/0002-22"}]},
    }, f, ensure_ascii=False)

from core import banco                                   # noqa: E402
from core import dados_eletronet as de                  # noqa: E402

ok("o arquivo do teste é o do perfil falso", de.USER_JSON == ARQ, de.USER_JSON)

# o "modelo oficial" também é de mentira: o teste não depende do .xlsm real
de._fornecedores_base = lambda: [
    {"apelido": "BETA", "empresa": "BETA TELECOM S.A.", "endereco": "Av. B, 2", "cep": "02000-000",
     "cnpj": "33.333.333/0001-33", "insc_est": "ISENTO", "garantia": "", "origem": "catalogo"}]
de._faturamento_base = lambda: [
    {"uf": "SP", "razao_social": "ELETRONET FILIAL SP", "cnpj": "44.444.444/0001-44", "endereco": "Rua S, 3",
     "cep": "03000-000", "cnpj2": "", "insc_est": "", "insc_mun": "", "origem": "catalogo"},
    {"uf": "RJ", "razao_social": "ELETRONET FILIAL VELHA", "cnpj": "22.222.222/0002-22", "endereco": "Rua V, 4",
     "cep": "20000-000", "cnpj2": "", "insc_est": "", "insc_mun": "", "origem": "catalogo"}]
de._pops_base = lambda: [
    {"nome": "POP CENTRO", "sigla": "CTR-CTR", "endereco": "Rua C, 5", "municipio": "Brasília", "uf": "DF",
     "maps": "", "latitude": "-15.79", "longitude": "-47.88", "cedente": "", "origem": "catalogo"}]

# --------------------------------------------------------- 1. semear ------
print("\n1. A primeira abertura semeia o banco vazio")
r = de.levar_para_o_banco()
ok("fornecedores: o do modelo e o da equipe", len(TABELAS["fornecedores"]) == 2, str(TABELAS["fornecedores"]))
ok("faturamento: a filial visível e a oculta", len(TABELAS["faturamento"]) == 2)
velha = [x for x in TABELAS["faturamento"] if x["razao_social"] == "ELETRONET FILIAL VELHA"]
ok("a filial que estava oculta entra OCULTA (restaurável)", velha and velha[0]["oculto"] is True, str(velha))
ok("POPs: o do modelo e o novo", len(TABELAS["pops"]) == 2)
ok("o resultado conta o que entrou", r.get("incluidos") == 5 and r.get("ocultados") == 1, str(r))
carimbo = json.load(open(ARQ, encoding="utf-8")).get("banco") or {}
ok("o arquivo fica carimbado com o banco", carimbo.get("projeto") == URL, str(carimbo))
antes = sum(len(v) for v in TABELAS.values())
ok("na abertura seguinte não repete", de.levar_para_o_banco() == {} and
   sum(len(v) for v in TABELAS.values()) == antes)

# --------------------------------------------------------- 2. ler ---------
print("\n2. As listas vêm do banco")
forn = de.catalogo_fornecedores()
ok("fornecedores do banco, em ordem de apelido", [f["apelido"] for f in forn] == ["ALFA", "BETA"],
   str([f["apelido"] for f in forn]))
ok("cada item traz o número do banco e a origem", all(f.get("_id") and f.get("origem") == "banco" for f in forn))
ok("a filial oculta não aparece na lista", [f["razao_social"] for f in de.locais_faturamento()] == ["ELETRONET FILIAL SP"])
oc = de.ocultos().get("faturamento") or []
ok("...mas aparece em ocultos, com o número para restaurar", len(oc) == 1 and oc[0].get("_id"), str(oc))
n = len(PEDIDOS)
de.pops_entrega(); de.pops_entrega(); de.catalogo_fornecedores()
ok("ler de novo não pergunta ao banco a cada lista", len(PEDIDOS) == n, str(PEDIDOS[n:]))

# --------------------------------------------------------- 3. gravar ------
print("\n3. Cadastrar, editar, ocultar e restaurar")
de.adicionar_usuario("pop", {"nome": "POP SUL", "sigla": "SUL-SUL", "endereco": "Rua Sul, 7",
                             "municipio": "Porto Alegre", "uf": "RS"})
ok("cadastrar inclui no banco", any(p["nome"] == "POP SUL" for p in TABELAS["pops"]))
ok("...e a lista já mostra", any(p["nome"] == "POP SUL" for p in de.pops_entrega()))
try:
    de.adicionar_usuario("pop", {"nome": "Pop Sul", "sigla": "sul sul", "municipio": "Porto Alegre"})
    ok("duplicata é recusada", False, "aceitou")
except ValueError as exc:
    ok("duplicata é recusada", "já existe" in str(exc), str(exc))
try:
    de.adicionar_usuario("faturamento", {"razao_social": "   ", "uf": "MG"})
    ok("sem razão social o banco recusa com mensagem clara", False, "aceitou")
except ValueError as exc:
    ok("sem razão social o banco recusa com mensagem clara", "nada foi salvo" in str(exc), str(exc))

beta = next(f for f in de.catalogo_fornecedores() if f["apelido"] == "BETA")
res = de.atualizar_usuario("fornecedor", {"_id": beta["_id"], "empresa": beta["empresa"]},
                           dict(beta, endereco="Av. B, 200 — sala 3"))
linha = next(x for x in TABELAS["fornecedores"] if x["id"] == beta["_id"])
ok("editar um item que era do modelo altera ESSE item no banco",
   res == {"atualizados": 1} and linha["endereco"] == "Av. B, 200 — sala 3", str(linha))
ok("...sem criar outro", len(TABELAS["fornecedores"]) == 2)
alfa = next(f for f in de.catalogo_fornecedores() if f["apelido"] == "ALFA")
try:           # (a regra de duplicata é a de sempre: apelido, empresa e CNPJ iguais)
    de.atualizar_usuario("fornecedor", {"_id": alfa["_id"]},
                         dict(alfa, apelido="beta", empresa="Beta Telecom S.A.", cnpj="33333333000133"))
    ok("editar até ficar igual a outro é recusado", False, "aceitou")
except ValueError as exc:
    ok("editar até ficar igual a outro é recusado", "outro cadastro" in str(exc), str(exc))

r = de.remover_usuario("fornecedor", {"_id": alfa["_id"], "empresa": alfa["empresa"]})
ok("remover OCULTA (não apaga)", r == {"removidos": 0, "ocultados": 1} and len(TABELAS["fornecedores"]) == 2, str(r))
ok("nenhum DELETE foi pedido ao banco", not any(m == "DELETE" for m, _ in PEDIDOS))
ok("o oculto some da lista", all(f["apelido"] != "ALFA" for f in de.catalogo_fornecedores()))
ok("restaurar devolve", de.restaurar_usuario("fornecedor", {"_id": alfa["_id"]}) == 1 and
   any(f["apelido"] == "ALFA" for f in de.catalogo_fornecedores()))

# ------------------------------------------------ 3b. listas vivas ---------
print("\n3b. O que outra máquina grava aparece em segundos")


def vencer():                  # como se os segundos da leitura em memória tivessem passado
    for t, g in list(banco._memoria.items()):
        banco._memoria[t] = (g[0] - banco.VALIDADE - 1,) + tuple(g[1:])


v1 = de.versao_cadastros()
vencer()
n = len(PEDIDOS)
ok("sem mudança, a versão continua a mesma", de.versao_cadastros() == v1)
ok("...e o app só fez a pergunta leve, sem baixar lista",
   len(PEDIDOS) > n and all("select=atualizado_em" in p for _, p in PEDIDOS[n:]), str(PEDIDOS[n:]))
_seq[0] += 1
q = agora()
TABELAS["pops"].append({"id": _seq[0], "nome": "POP DE OUTRA MAQUINA", "sigla": "OUT-OUT", "endereco": "",
                        "municipio": "Natal", "uf": "RN", "maps": "", "latitude": "", "longitude": "",
                        "cedente": "", "oculto": False, "criado_em": q, "atualizado_em": q})
vencer()
v2 = de.versao_cadastros()
ok("outra máquina incluiu: a versão muda", v2 != v1, v2)
ok("...e a lista já traz o novo", any(p["nome"] == "POP DE OUTRA MAQUINA" for p in de.pops_entrega()))
sul = next(p for p in TABELAS["pops"] if p["nome"] == "POP SUL")
sul.update(endereco="Rua Sul, 700", atualizado_em=agora())      # alguém corrigiu pelo painel
vencer()
ok("corrigir pelo painel do Supabase também muda a versão", de.versao_cadastros() != v2)
ok("...e a lista traz a correção", any(p["endereco"] == "Rua Sul, 700" for p in de.pops_entrega()))

# ------------------------------------------------ 4. arquivo de outra máquina
print("\n4. O arquivo de outra máquina só acrescenta")
ARQ2 = os.path.join(TMP, "outra_maquina.json")
with open(ARQ2, "w", encoding="utf-8") as f:
    json.dump({"versao": 2, "pops": [
        {"nome": "POP NOVO", "sigla": "NOV-NOV", "endereco": "Endereço ANTIGO", "municipio": "Recife", "uf": "PE"},
        {"nome": "POP NORTE", "sigla": "NRT-NRT", "endereco": "Rua N, 8", "municipio": "Belém", "uf": "PA"}]},
        f, ensure_ascii=False)
de.USER_JSON = ARQ2
r = de.levar_para_o_banco()
ok("entra só o que o banco não tinha", r.get("incluidos") == 1 and
   any(p["nome"] == "POP NORTE" for p in TABELAS["pops"]), str(r))
novo = next(p for p in TABELAS["pops"] if p["nome"] == "POP NOVO")
ok("o que já estava no banco NÃO é trocado pelo dado velho", novo["endereco"] == "Rua P, 9", str(novo))
ok("a diferença fica registrada", r.get("diferentes") == ["POP NOVO"], str(r))
carimbo2 = json.load(open(ARQ2, encoding="utf-8")).get("banco") or {}
ok("...no carimbo do próprio arquivo (o log não existe por padrão)",
   carimbo2.get("diferentes_mantido_o_do_banco") == ["POP NOVO"], str(carimbo2))

# a transição: alguém ainda na versão antiga do app grava um POP no arquivo
with open(ARQ2, encoding="utf-8") as f:
    d2 = json.load(f)
d2["pops"].append({"nome": "POP OESTE", "sigla": "OES-OES", "endereco": "Rua O, 1",
                   "municipio": "Cuiabá", "uf": "MT"})
with open(ARQ2, "w", encoding="utf-8") as f:
    json.dump(d2, f, ensure_ascii=False)
de.versao_cadastros()                       # a olhada de meio em meio minuto da tela
ok("o que a versão antiga grava no arquivo DEPOIS também chega ao banco",
   any(p["nome"] == "POP OESTE" for p in TABELAS["pops"]))
ok("...sem duplicar o que já tinha levado",
   sum(1 for p in TABELAS["pops"] if p["nome"] == "POP NORTE") == 1)
n = len(PEDIDOS)
ok("olhar de novo sem novidade no arquivo não pergunta nada ao banco",
   de.levar_para_o_banco() == {} and len(PEDIDOS) == n, str(PEDIDOS[n:]))
de.USER_JSON = ARQ

# ------------------------------------------------------- 5. sem internet --
print("\n5. Sem internet")
com_rede = [p["nome"] for p in de.pops_entrega()]
srv.shutdown()
srv.server_close()
banco.esquecer()
t0 = time.time()
sem_rede = [p["nome"] for p in de.pops_entrega()]
ok("a lista vem da cópia local, igual", sem_rede == com_rede, str(sem_rede))
t1 = time.time()
de.catalogo_fornecedores(); de.locais_faturamento(); de.ocultos()
ok("depois da 1ª falha, as outras listas não esperam o tempo-limite", time.time() - t1 < 1.0,
   "%.1fs" % (time.time() - t1))
ok("a tela sabe que está sem conexão", banco.estado().get("online") is False and banco.estado().get("copia_em"),
   str(banco.estado()))
try:
    de.adicionar_usuario("pop", {"nome": "POP OFFLINE", "sigla": "OFF-OFF", "municipio": "Natal"})
    ok("gravar sem conexão avisa que nada foi salvo", False, "aceitou")
except ValueError as exc:
    ok("gravar sem conexão avisa que nada foi salvo", "nada foi salvo" in str(exc), str(exc))
ok("...e não guarda o cadastro no arquivo, escondido", "POP OFFLINE" not in open(ARQ, encoding="utf-8").read())

os.remove(os.path.join(PERFIL, "banco_cache.json"))
banco.esquecer()
ok("sem conexão e sem cópia, vale o modelo + arquivo",
   [p["nome"] for p in de.pops_entrega()] == [p["nome"] for p in de._lista_local("pops")])

# ------------------------------------------------------- 6. chave errada --
print("\n6. Chave errada e o banco de verdade")
srv2 = ThreadingHTTPServer(("127.0.0.1", 0), Falso)
threading.Thread(target=srv2.serve_forever, daemon=True).start()
os.environ["GERADORAF_BANCO_URL"] = "http://127.0.0.1:%d" % srv2.server_address[1]
os.environ["GERADORAF_BANCO_CHAVE"] = "chave-errada"
banco._cfg.update(lida=False, valor=None)
banco._estado.update(falhou_em=0.0)
banco.esquecer()
ok("chave recusada: a lista cai no modelo, sem erro na tela",
   [p["nome"] for p in de.pops_entrega()] == [p["nome"] for p in de._lista_local("pops")])
srv2.shutdown()

with open(os.path.join(PERFIL, "config.json"), "w", encoding="utf-8") as f:
    json.dump({"banco": {"url": "https://nao-e-para-usar.supabase.co", "chave": "x"}}, f)
for k in ("GERADORAF_BANCO_URL", "GERADORAF_BANCO_CHAVE"):
    os.environ.pop(k)
banco._cfg.update(lida=False, valor=None)
ok("um script de testes/ não usa o banco do config.json", banco.configuracao() is None)

# o .exe mandado sozinho: sem config.json, sem pasta do setor, sem banco.json
# ao lado — só o que viaja DENTRO dele (recurso backend/banco.json)
from core import caminhos                                # noqa: E402
EXE = os.path.join(TMP, "dentro_do_exe")
os.makedirs(os.path.join(EXE, "backend"))
with open(os.path.join(EXE, "backend", "banco.json"), "w", encoding="utf-8") as f:
    json.dump({"url": "https://embutido.supabase.co", "chave": "sb_publishable_embutida"}, f)
os.remove(os.path.join(PERFIL, "config.json"))
caminhos.BASE_RECURSO = EXE
caminhos.BASE_DADOS = os.path.join(TMP, "ao_lado_do_exe_vazio")
banco._rodando_teste = lambda: False                    # agora é "o .exe", não um teste
banco._cfg.update(lida=False, valor=None)
cfg = banco.configuracao() or {}
ok("o .exe mandado sozinho acha o banco que viaja dentro dele",
   cfg.get("url") == "https://embutido.supabase.co", str(cfg))
guardado = json.load(open(os.path.join(PERFIL, "config.json"), encoding="utf-8")).get("banco") or {}
ok("...e guarda na máquina, como faz com o da pasta do setor",
   guardado.get("url") == "https://embutido.supabase.co", str(guardado))
os.makedirs(caminhos.BASE_DADOS)
with open(os.path.join(caminhos.BASE_DADOS, "banco.json"), "w", encoding="utf-8") as f:
    json.dump({"url": "https://ao-lado.supabase.co", "chave": "sb_publishable_ao_lado"}, f)
os.remove(os.path.join(PERFIL, "config.json"))
banco._cfg.update(lida=False, valor=None)
ok("um banco.json ao lado do .exe manda mais que o embutido (trocar de banco sem outro .exe)",
   (banco.configuracao() or {}).get("url") == "https://ao-lado.supabase.co")

shutil.rmtree(TMP, ignore_errors=True)
print("FALHAS: " + ", ".join(falhas) if falhas else "TUDO OK")
sys.exit(1 if falhas else 0)
