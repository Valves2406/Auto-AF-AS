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

from PyInstaller.utils.hooks import collect_data_files

# dados que precisam viajar junto (origem, destino dentro do bundle)
datas = [
    ("../backend/modelos", "backend/modelos"),
    ("../frontend", "frontend"),
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
    ["app.py"],
    pathex=[],
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
    icon="../frontend/imagens/app.ico" if __import__("os").path.exists("../frontend/imagens/app.ico") else None,
)
