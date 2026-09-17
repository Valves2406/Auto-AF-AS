r"""
caminhos.py — resolve onde ficam os arquivos, rodando como script OU como .exe.

Dentro de um executável PyInstaller há DOIS lugares diferentes, e confundi-los
quebra o app:

  • RECURSO — o que vem EMPACOTADO e é só leitura (assets/, web/). No .exe
    "onefile" isso é extraído numa pasta TEMPORÁRIA (`sys._MEIPASS`) que o
    Windows apaga quando o programa fecha.

  • DADO — o que o usuário CRIA e precisa sobreviver (a pasta "saída
    gerador"). Tem de ficar AO LADO do .exe; se cair no temporário, o
    usuário perde os documentos a cada fechamento.

    Exceção: os CADASTROS (dados_usuario.json) ficam em %APPDATA%\AutoAF — ver
    `dados_eletronet._arquivo_dados()`. Assim o .exe pode ser movido, copiado
    ou substituído sem levar os POPs e fornecedores embora.

Rodando como script (python app.py) os dois apontam para a pasta do projeto,
então o comportamento continua exatamente o mesmo de hoje.
"""

from __future__ import annotations

import os
import sys

# Empacotado? O PyInstaller marca com sys.frozen e expõe sys._MEIPASS.
EMPACOTADO = getattr(sys, "frozen", False)

_PROJETO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# leitura: pasta temporária do bundle (onefile) ou a pasta do .exe (onedir)
BASE_RECURSO = getattr(sys, "_MEIPASS", None) or (
    os.path.dirname(os.path.abspath(sys.executable)) if EMPACOTADO else _PROJETO)
# escrita: SEMPRE ao lado do executável.
# GERADORAF_RAIZ finge outra pasta — usado pelos testes para simular o .exe
# instalado numa pasta de rede sem precisar de rede nem de gerar o executável.
BASE_DADOS = os.environ.get("GERADORAF_RAIZ") or (
    os.path.dirname(os.path.abspath(sys.executable)) if EMPACOTADO else _PROJETO)


def recurso(*partes: str) -> str:
    """Arquivo empacotado (só leitura): assets/, web/."""
    return os.path.join(BASE_RECURSO, *partes)


def dado(*partes: str) -> str:
    """Arquivo do usuário (leitura e escrita), ao lado do executável."""
    return os.path.join(BASE_DADOS, *partes)
