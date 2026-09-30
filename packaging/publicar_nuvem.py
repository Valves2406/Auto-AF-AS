# -*- coding: utf-8 -*-
r"""Publica o .exe como a versão nova — todo mundo recebe pela internet.

    python packaging\publicar_nuvem.py                      (o .exe de packaging\dist)
    python packaging\publicar_nuvem.py "C:\...\Auto AF-AS.exe" --notas "o que mudou"

A versão é a VERSAO_APP do código (core/dados_eletronet.py): gere o .exe DEPOIS
de subir o número, senão as máquinas não veem novidade.

Precisa da CHAVE SECRETA do Supabase (Settings → API Keys → Secret key) na
variável de ambiente SUPABASE_SECRET_KEY desta máquina. Ela NUNCA vai para o
.exe nem para o repositório: é o que impede alguém com o .exe de publicar uma
versão falsa. O endereço do banco é o mesmo que o app já usa.

O que acontece: o .exe sobe em partes de 40 MB (o plano grátis aceita até 50 MB
por arquivo), depois o versao.json que anuncia a versão — por último, para
ninguém ver uma versão cujas partes ainda não chegaram. Ficam no espaço só a
versão nova e a anterior.
"""
import argparse
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "backend"))

from core import atualizador_nuvem as nuvem          # noqa: E402
from core import banco                               # noqa: E402
from core.dados_eletronet import VERSAO_APP          # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="Publica a versão nova do Auto AF/AS.")
    ap.add_argument("exe", nargs="?", default=os.path.join(RAIZ, "packaging", "dist", "Auto AF-AS.exe"))
    ap.add_argument("--notas", default="", help="o que mudou (aparece no versao.json)")
    a = ap.parse_args()

    chave = os.environ.get("SUPABASE_SECRET_KEY", "").strip()
    if not chave:
        print("Falta a chave secreta: defina SUPABASE_SECRET_KEY nesta máquina "
              "(Supabase → Settings → API Keys → Secret key).")
        return 2
    cfg = banco.configuracao()
    if not cfg:
        print("Banco não configurado nesta máquina (config.json / banco.json).")
        return 2
    atual = nuvem.manifesto(cfg).get("versao", "")
    if atual and not nuvem.mais_nova(VERSAO_APP, atual):
        print(f"A versão {VERSAO_APP} não é mais nova que a publicada ({atual}). "
              "Suba VERSAO_APP, gere o .exe de novo e publique.")
        return 1
    print(f"Publicando {os.path.basename(a.exe)} como versão {VERSAO_APP} (publicada hoje: {atual or 'nenhuma'})…")
    r = nuvem.publicar(a.exe, VERSAO_APP, cfg["url"], chave, notas=a.notas)
    if not r.get("ok"):
        print("Falhou:", r.get("erro"))
        return 1
    # confere com a chave do APP, como as máquinas vão ver
    visto = nuvem.manifesto(cfg)
    confere = visto.get("versao") == VERSAO_APP and visto.get("sha256") == r["sha256"]
    print(f"Pronto: versão {r['versao']} em {r['partes']} parte(s), {r['tamanho'] / 1e6:.1f} MB."
          f" As máquinas veem: {'sim' if confere else 'NÃO — confira'}."
          + (f" Versões antigas removidas: {', '.join(r['removidas'])}." if r.get("removidas") else ""))
    return 0 if confere else 1


if __name__ == "__main__":
    sys.exit(main())
