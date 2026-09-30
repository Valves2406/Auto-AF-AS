# -*- coding: utf-8 -*-
r"""Atualização pela INTERNET (Supabase Storage), com um Storage de mentira local.

O QUE MUDOU
-----------
A versão nova deixou de depender da pasta de rede do setor: quem publica sobe o
.exe para um espaço privado do Supabase, e cada app pergunta ao abrir, baixa em
segundo plano, confere e troca na PRÓXIMA abertura — como um app de loja.

O QUE ESTE TESTE GUARDA
-----------------------
  • publicar exige a chave SECRETA; com a do app, é recusado e nada é anunciado;
  • o .exe sobe em partes (o plano grátis aceita 50 MB por arquivo) e o
    versao.json sobe POR ÚLTIMO; ficam só a versão nova e a anterior;
  • baixar: versão mais nova → partes conferidas, arquivo montado e conferido
    pelo SHA-256; a mesma versão não é baixada duas vezes;
  • parte adulterada é recusada; na volta, só a parte ruim é baixada de novo;
  • versao.json com caminho estranho ("../") é recusado;
  • sem internet: nada quebra, e o app segue na versão que tem;
  • aplicar na abertura troca o executável; o que ficou velho é limpo;
  • o app só baixa pelo .exe (pelo código-fonte não há o que trocar).
"""
import io
import json
import os
import re
import shutil
import sys
import tempfile
import threading
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


# ------------------------------------------------- Storage de mentira ------
CHAVE_APP, CHAVE_SECRETA = "sb_publishable_teste_app", "sb_secret_teste_publicador"
ARQS: dict[str, bytes] = {}
ENVIOS, BAIXADOS = [], []


class Storage(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _resp(self, codigo, corpo, tipo="application/json"):
        dados = corpo if isinstance(corpo, bytes) else json.dumps(corpo).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)

    def _chave(self):
        return (self.headers.get("Authorization") or "").removeprefix("Bearer ")

    def _corpo(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def do_GET(self):
        if self.path == "/storage/v1/bucket/versoes":   # só a secreta enxerga o espaço
            if self._chave() == CHAVE_SECRETA:
                return self._resp(200, {"id": "versoes", "name": "versoes", "public": False})
            return self._resp(400, {"statusCode": "404", "error": "Bucket not found"})
        pre = "/storage/v1/object/authenticated/versoes/"
        if not self.path.startswith(pre) or self._chave() not in (CHAVE_APP, CHAVE_SECRETA):
            return self._resp(400, {"statusCode": "403", "error": "Unauthorized"})
        nome = self.path[len(pre):]
        if nome not in ARQS:          # o Storage de verdade responde assim
            return self._resp(400, {"statusCode": "404", "error": "not_found", "code": "NoSuchKey"})
        BAIXADOS.append(nome)
        self._resp(200, ARQS[nome], "application/octet-stream")

    def do_POST(self):
        if self._chave() != CHAVE_SECRETA:              # só a secreta envia/lista
            self._corpo()
            return self._resp(400, {"statusCode": "403", "error": "Unauthorized"})
        if self.path == "/storage/v1/object/list/versoes":
            prefixo = json.loads(self._corpo() or b"{}").get("prefix", "")
            itens = {}
            for n in ARQS:
                if not n.startswith(prefixo):
                    continue
                resto = n[len(prefixo):]
                if "/" in resto:
                    itens[resto.split("/")[0]] = {"name": resto.split("/")[0], "id": None}
                else:
                    itens[resto] = {"name": resto, "id": "x"}
            return self._resp(200, list(itens.values()))
        pre = "/storage/v1/object/versoes/"
        nome = self.path[len(pre):]
        ARQS[nome] = self._corpo()
        ENVIOS.append(nome)
        self._resp(200, {"Key": "versoes/" + nome})

    def do_DELETE(self):
        if self._chave() != CHAVE_SECRETA:
            return self._resp(400, {"error": "Unauthorized"})
        for n in json.loads(self._corpo() or b"{}").get("prefixes", []):
            ARQS.pop(n, None)
        self._resp(200, [])


srv = ThreadingHTTPServer(("127.0.0.1", 0), Storage)
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = "http://127.0.0.1:%d" % srv.server_address[1]

TMP = tempfile.mkdtemp(prefix="autoaf_nuvem_")
os.environ.update(LOCALAPPDATA=os.path.join(TMP, "local"), APPDATA=os.path.join(TMP, "roaming"),
                  GERADORAF_BANCO_URL=URL, GERADORAF_BANCO_CHAVE=CHAVE_APP)
os.environ.pop("GERADORAF_SEM_BANCO", None)
os.environ.pop("GERADORAF_DADOS", None)

from core import atualizador_nuvem as nuvem          # noqa: E402

cfg = {"url": URL, "chave": CHAVE_APP}


def exe_falso(nome, conteudo):
    p = os.path.join(TMP, nome)
    with open(p, "wb") as f:
        f.write(conteudo)
    return p


V09 = os.urandom(2500)             # "o .exe" da 0.9: 3 partes de até 1000 bytes

# ---------------------------------------------------- 0. conferir a chave --
print("\n0. Conferir a chave de quem publica (sem publicar nada)")
ok("sem chave: diz que não está definida", "não está definida" in nuvem.verificar_chave(URL, "")["erro"])
ok("a chave PÚBLICA (do app) colada por engano é reconhecida",
   "PÚBLICA" in nuvem.verificar_chave(URL, "sb_publishable_qualquer")["erro"])
ok("chave errada: o Supabase recusa, com o que fazer",
   "recusou" in nuvem.verificar_chave(URL, "sb_secret_de_outro_projeto")["erro"])
ok("a chave secreta certa: OK", nuvem.verificar_chave(URL, CHAVE_SECRETA) == {"ok": True})
ok("e nada foi publicado ao conferir", not ARQS)

# ---------------------------------------------------------- 1. publicar ----
print("\n1. Publicar")
r = nuvem.publicar(exe_falso("pub.exe", V09), "0.9", URL, CHAVE_APP, tam_parte=1000)
ok("com a chave do APP, é recusado e nada é anunciado",
   not r["ok"] and "chave" in r["erro"] and "versao.json" not in ARQS, str(r))
ENVIOS.clear()
r = nuvem.publicar(exe_falso("Auto AF-AS.exe", V09), "0.9", URL, CHAVE_SECRETA, tam_parte=1000, notas="teste")
ok("com a chave secreta, publica em partes", r["ok"] and r["partes"] == 3, str(r))
ok("cada parte dentro do limite", all(len(ARQS[n]) <= 1000 for n in ARQS if n.endswith(".bin")))
ok("o versao.json sobe POR ÚLTIMO", ENVIOS[-1] == "versao.json", str(ENVIOS))
man = json.loads(ARQS["versao.json"])
ok("o anúncio traz versão, tamanho e assinatura", man["versao"] == "0.9" and man["tamanho"] == 2500
   and re.fullmatch(r"[0-9a-f]{64}", man["sha256"]))

# ---------------------------------------------------------- 2. baixar ------
print("\n2. Baixar em segundo plano")
ok("sem nada novo para quem já está na 0.9", "nada" in nuvem.baixar("0.9", cfg))
r = nuvem.baixar("0.8", cfg)
ok("a 0.8 baixa a 0.9", r == {"pronta": "0.9"}, str(r))
p = nuvem.pronta("0.8")
ok("o arquivo montado é idêntico ao publicado",
   p and open(p["exe"], "rb").read() == V09, str(p))
BAIXADOS.clear()
ok("baixar de novo não baixa nada (já está pronta)", nuvem.baixar("0.8", cfg) == {"pronta": "0.9"}
   and not [b for b in BAIXADOS if b.endswith(".bin")], str(BAIXADOS))
ok("o estado para a tela mostra a versão pronta", nuvem.estado("0.8")["pronta"] == "0.9")

# ---------------------------------------------------------- 3. adulterada --
print("\n3. Parte adulterada e anúncio estranho")
V10 = os.urandom(2500)
nuvem.publicar(exe_falso("Auto AF-AS.exe", V10), "1.0", URL, CHAVE_SECRETA, tam_parte=1000)
bom = ARQS["1.0/parte-2.bin"]
ARQS["1.0/parte-2.bin"] = b"X" * len(bom)             # alguém trocou os bytes no caminho
r = nuvem.baixar("0.9", cfg)
ok("parte que não confere é recusada", "erro" in r and "diferente" in r["erro"], str(r))
ok("...e a versão NÃO fica pronta", nuvem.pronta("0.9") == {})
ARQS["1.0/parte-2.bin"] = bom
BAIXADOS.clear()
r = nuvem.baixar("0.9", cfg)
ok("na volta, só a parte ruim e as que faltavam são baixadas (a 1ª já conferida fica)",
   r == {"pronta": "1.0"} and "1.0/parte-1.bin" not in BAIXADOS, str(BAIXADOS))
ARQS["versao.json"] = json.dumps(dict(json.loads(ARQS["versao.json"]), versao="9.9",
                                      partes=[{"nome": "../../fora.bin", "tamanho": 2500,
                                               "sha256": "0" * 64}])).encode()
r = nuvem.baixar("1.0", cfg)
ok("anúncio com caminho estranho ('../') é recusado", "erro" in r and "inválida" in r["erro"], str(r))

# ---------------------------------------------------------- 4. aplicar -----
print("\n4. Aplicar na abertura")
nuvem.publicar(exe_falso("Auto AF-AS.exe", V10), "1.0", URL, CHAVE_SECRETA, tam_parte=1000)
nuvem.baixar("0.9", cfg)
instalado = exe_falso("instalado.exe", b"versao velha 0.9")
r = nuvem.aplicar_pronta("0.9", instalado, reabrir=False)
ok("troca o executável pelo baixado", r.get("trocou") and open(instalado, "rb").read() == V10, str(r))
ok("o antigo fica ao lado para ser apagado depois", os.path.exists(instalado + ".antigo"))
r = nuvem.aplicar_pronta("1.0", instalado, reabrir=False)
ok("já na versão nova: não troca de novo", not r.get("trocou"))
ok("...e limpa o que foi baixado", not os.path.exists(os.path.join(nuvem.pasta_local(), "1.0"))
   and not os.path.exists(os.path.join(nuvem.pasta_local(), "pronta.json")))

# ---------------------------------------------------------- 5. poda --------
print("\n5. No espaço ficam só a nova e a anterior")
nuvem.publicar(exe_falso("Auto AF-AS.exe", os.urandom(1500)), "1.1", URL, CHAVE_SECRETA, tam_parte=1000)
pastas = sorted({n.split("/")[0] for n in ARQS if "/" in n})
ok("versões antigas apagadas do espaço", pastas == ["1.0", "1.1"], str(pastas))

# ---------------------------------------------------------- 6. sem internet
print("\n6. Sem internet")
srv.shutdown(); srv.server_close()
r = nuvem.baixar("1.0", cfg)
ok("sem conexão: avisa e não quebra", "erro" in r, str(r))
nuvem.em_segundo_plano("1.0")                      # a thread do app: não pode levantar exceção
ok("a thread de segundo plano termina sozinha", nuvem.estado("1.0")["baixando"] is False)

# ---------------------------------------------------------- 7. o app ------
print("\n7. Ligado no app")
fonte = lambda *p: io.open(os.path.join(PROJ, *p), encoding="utf-8").read()   # noqa: E731
app, at, spec = fonte("backend", "app.py"), fonte("backend", "core", "atualizador.py"), \
    fonte("packaging", "AutoAF.spec")
js, html = fonte("frontend", "app.js"), fonte("frontend", "index.html")
pub = fonte("packaging", "publicar_nuvem.py")
ok("o download só começa no .exe (pelo fonte não há o que trocar)",
   "if EMPACOTADO:" in app and "atualizador_nuvem.em_segundo_plano" in app)
ok("na abertura, a versão da internet é aplicada antes da pasta do setor",
   at.index("aplicar_pronta") < at.index("info = ha_atualizacao(versao_atual)"))
ok("o .exe leva o módulo", '"core.atualizador_nuvem"' in spec)
ok("a tela avisa e oferece reiniciar", 'id="avisoAtt"' in html and "/api/atualizacao" in js
   and "/api/reiniciar" in js and "/api/reiniciar" in app)
ok("publicar lê a chave secreta da variável, nunca do código",
   "SUPABASE_SECRET_KEY" in pub and not re.search(r"sb_secret_[A-Za-z0-9]{10,}", pub))

shutil.rmtree(TMP, ignore_errors=True)
print("FALHAS: " + ", ".join(falhas) if falhas else "TUDO OK")
sys.exit(1 if falhas else 0)
