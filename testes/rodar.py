# -*- coding: utf-8 -*-
r"""Roda todos os testes do Auto AF/AS de uma vez.

    python testes\rodar.py

Nenhum deles encosta no seu cadastro real: cada um trabalha num arquivo
descartável em %TEMP% (via GERADORAF_DADOS) ou num perfil falso.

Para que servem: o projeto cresceu a pedidos frequentes, e cada mudança nova
tinha o risco de quebrar as anteriores em silêncio. Aqui está o que já foi
consertado uma vez — se voltar a quebrar, aparece na hora, em vez de aparecer
dentro de uma AF assinada.
"""
import io
import os
import subprocess
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
AQUI = os.path.dirname(os.path.abspath(__file__))

SUITES = [
    ("correcoes", "Textos do CPM e cabeçalho das duas folhas do Excel"),
    ("aprendizado", "Que rótulo o app guarda ao aprender com a correção"),
    ("licao_coluna", "Aprender o valor que está numa tabela, não num rótulo"),
    ("ciclo", "Ciclo completo: ler → corrigir → guardar → aplicar na próxima"),
    ("atualizacao", "Trocar o .exe sem duplicar nem perder cadastro"),
    ("equipe", "Cadastro compartilhado entre máquinas do setor"),
    ("exe_na_rede", "O .exe numa pasta de rede: todos no mesmo cadastro"),
    ("valor_total", "O total da proposta manda sobre a soma das linhas"),
    ("itens_ncm", "Tabela com NCM e endereço na mesma linha do produto"),
    ("secoes_proposta", "Proposta em secoes numeradas: escopo, pagamento, garantia"),
    ("apontar_pasta", "Cópia local do .exe apontada para a pasta do setor"),
    ("conta_por_linha", "Qtd × unitário c/ imposto = total, e a soma do pedido"),
    ("quebras_pdf", "Quebra de página no PDF e campos sem valor"),
    ("comodidades", "Desfazer o Limpar, rascunho da AF e atalhos de teclado"),
    ("rubricas", "Rodape de rubrica e o total que nao contradiz os itens"),
    ("capex_opex", "A verba do CPM pode ser CAPEX ou OPEX"),
    ("navegador", "A janela abre no navegador favorito de cada um"),
    ("previa_responsiva", "Prévia que acompanha a tela e rótulo AF/AS certo"),
    ("moeda_uma_regra", "Uma regra só p/ a moeda: conversão, saldo e alçada"),
    ("colunas_prazo_garantia", "Prazo, garantia e código lidos em COLUNA da tabela"),
    ("marca_e_por_produto", "Marca do app, modo por produto e a associação no texto"),
    ("proposta_orcamento", "Proposta em orçamento: itens, frete e a filial da AF"),
    ("quadro_por_localidade", "Quadro por localidade: entregas, frete e observações"),
    ("planilha_posicionada", "Planilha de preços sem grade, lida pela posição"),
    ("campo_nao_perde_texto", "O formulário não desmonta a frase que o extrator leu"),
    ("proposta_em_partes", "Proposta repartida em vários arquivos, e o fornecedor certo"),
    ("atualizacao_automatica", "Versão nova chega sozinha na máquina de todos"),
    ("pdf_visual", "O PDF Visual não troca o layout do documento sozinho"),
    ("paginacao", "Assinatura nunca sozinha e folha sem buraco no pe"),
    ("aritmetica_manda", "A conta arbitra quando os numeros da proposta se contradizem"),
    ("proposta_alg", "ALG: itens com codigo, condicoes do topo e frete"),
    ("divisorias_orcamento", "As divisorias do quadro Orcamento nao somem"),
    ("composicao_financeira", "Composicao financeira: parcela vira item, resultado nao"),
    ("arrastar_proposta", "Arrastar a proposta para a tela le o arquivo"),
]


def rodar(nome: str):
    arq = os.path.join(AQUI, nome + ".py")
    if not os.path.exists(arq):
        return None, "arquivo não encontrado", 0.0
    t0 = time.time()
    r = subprocess.run([sys.executable, arq], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=os.path.dirname(AQUI))
    # stderr traz o log do app e os avisos do openpyxl — ruído, não resultado.
    # (Da 1ª vez o resumo saiu como "UserWarning: Data Validation…", que não diz
    # nada sobre o teste ter passado.)
    return r.returncode == 0, (r.stdout or ""), (r.stderr or ""), time.time() - t0


def _resumo(saida: str) -> str:
    linhas = [l.strip() for l in saida.splitlines() if l.strip()]
    for l in reversed(linhas):                 # a linha que o próprio teste dá como veredito
        if "TUDO OK" in l or l.startswith("FALHAS"):
            return l
    return linhas[-1] if linhas else "(sem saída)"


def main():
    print("=" * 66)
    print("  Auto AF/AS — testes")
    print("=" * 66)
    falharam = []
    for nome, descricao in SUITES:
        print(f"\n▶ {nome}  ({descricao})")
        ok, saida, erro, seg = rodar(nome)
        if ok is None:
            print(f"   PULADO — {saida}")
            continue
        if ok:
            print(f"   ✔ {_resumo(saida)}   [{seg:.1f}s]")
        else:
            falharam.append(nome)
            print(f"   ✘ FALHOU   [{seg:.1f}s]")
            for l in saida.splitlines():
                if l.startswith("  FALHA") or l.startswith("FALHAS"):
                    print("     " + l.strip()[:150])
            cauda = [l for l in erro.splitlines() if l.strip()][-3:]
            for l in cauda:                      # se quebrou de verdade, o traceback
                if "Warning" not in l:
                    print("     " + l.strip()[:150])

    print("\n" + "=" * 66)
    if falharam:
        print(f"  {len(falharam)} suíte(s) com falha: {', '.join(falharam)}")
        print(f"  Rode a que falhou sozinha para ver tudo:  python testes\\{falharam[0]}.py")
    else:
        print(f"  Tudo passando ({len(SUITES)} suítes).")
    print("=" * 66)
    return 1 if falharam else 0


if __name__ == "__main__":
    sys.exit(main())
