# -*- mode: python ; coding: utf-8 -*-
"""
AutoAF.spec — receita do executável (PyInstaller).

Gerar:   pyinstaller AutoAF.spec --noconfirm

Decisões:
  • ONEFILE: um único "Auto AF-AS.exe" para o usuário copiar e rodar.
  • assets/ e web/ vão EMPACOTADOS (só leitura). Os arquivos que o usuário cria
    ("saída gerador") ficam AO LADO do .exe —
    ver core/caminhos.py. Se caíssem no temporário do bundle, sumiriam ao fechar.
  • DOCLING FICA DE FORA: são ~500 MB de modelos e ela só é um fallback de itens
    quando o pdfplumber falha. Incluir inviabilizaria o executável.
  • console=False: a janela é o Edge; um console preto atrás seria ruído.
"""

import os

from PyInstaller.utils.hooks import collect_data_files

# CAMINHOS A PARTIR DO PRÓPRIO SPEC, não do diretório de onde se chama.
# O spec mora em packaging/ e o código em backend/ e frontend/. Com caminhos
# relativos ("../frontend"), o build só funcionava se chamado de dentro de
# packaging/ — de qualquer outro lugar ele não achava nada e gerava um .exe
# que abre e não serve página nenhuma.
RAIZ = os.path.dirname(SPECPATH)            # packaging/ -> raiz do projeto
BACKEND = os.path.join(RAIZ, "backend")
FRONTEND = os.path.join(RAIZ, "frontend")
ICONE = os.path.join(FRONTEND, "imagens", "app.ico")

# dados que precisam viajar junto (origem, destino dentro do bundle)
datas = [
    (os.path.join(BACKEND, "modelos"), "backend/modelos"),
    (FRONTEND, "frontend"),
]
# pdfplumber/pdfminer levam tabelas .txt de codificação que não são detectadas
datas += collect_data_files("pdfminer")
datas += collect_data_files("pdfplumber")

# pesos que NÃO devem entrar (não usados pelo app ou grandes demais)
excluidos = [
    "docling", "torch", "torchvision", "transformers", "huggingface_hub",
    "scipy", "matplotlib", "IPython", "notebook", "pytest", "tkinter",
    "PyQt5", "PySide6", "numpy.distutils",
]

a = Analysis(
    [os.path.join(BACKEND, "app.py")],
    # backend/ no path: é de lá que saem `engine` e o pacote `core`
    pathex=[BACKEND],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "engine",
        "core.caminhos", "core.dados_eletronet", "core.extrator",
        "core.extrator_ciena", "core.gerador", "core.html_render",
        "core.log", "core.modelos", "core.trava",
        # aprendizado e importado DENTRO de funcoes ("from .aprendizado import
        # aplicar"), nao no topo do modulo. Se a analise estatica nao pegar,
        # o app compila e roda — mas para de aprender, em silencio.
        "core.aprendizado",
        # mesma armadilha: atualizar_na_abertura e importado dentro de main().
        # Sem isto o .exe abre normalmente e NUNCA se atualiza, em silencio --
        # que e justamente o defeito que a atualizacao automatica veio corrigir.
        "core.atualizador",
        "openpyxl", "pdfplumber", "pypdfium2", "reportlab",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=excluidos,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Auto AF-AS",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # sem janela preta: quem aparece é o Edge
    disable_windowed_traceback=False,
    icon=ICONE if os.path.exists(ICONE) else None,
)
