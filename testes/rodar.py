# -*- coding: utf-8 -*-
r"""Roda todos os testes do Auto AF/AS de uma vez.

    python testes\rodar.py

Nenhum deles encosta no seu cadastro real: cada um trabalha num arquivo
descartÃ¡vel em %TEMP% (via GERADORAF_DADOS) ou num perfil falso.

Para que servem: o projeto cresceu a pedidos frequentes, e cada mudanÃ§a nova
tinha o risco de quebrar as anteriores em silÃªncio. Aqui estÃ¡ o que jÃ¡ foi
consertado uma vez â€” se voltar a quebrar, aparece na hora, em vez de aparecer
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
    ("correcoes", "Textos do CPM e cabeÃ§alho das duas folhas do Excel"),
    ("aprendizado", "Que rÃ³tulo o app guarda ao aprender com a correÃ§Ã£o"),
    ("licao_coluna", "Aprender o valor que estÃ¡ numa tabela, nÃ£o num rÃ³tulo"),
    ("ciclo", "Ciclo completo: ler â†’ corrigir â†’ guardar â†’ aplicar na prÃ³xima"),
    ("atualizacao", "Trocar o .exe sem duplicar nem perder cadastro"),
    ("equipe", "Cadastro compartilhado entre mÃ¡quinas do setor"),
    ("exe_na_rede", "O .exe numa pasta de rede: todos no mesmo cadastro"),
    ("valor_total", "O total da proposta manda sobre a soma das linhas"),
    ("itens_ncm", "Tabela com NCM e endereÃ§o na mesma linha do produto"),
    ("secoes_proposta", "Proposta em secoes numeradas: escopo, pagamento, garantia"),
    ("apontar_pasta", "CÃ³pia local do .exe apontada para a pasta do setor"),
    ("conta_por_linha", "Qtd Ã— unitÃ¡rio c/ imposto = total, e a soma do pedido"),
    ("quebras_pdf", "Quebra de pÃ¡gina no PDF e campos sem valor"),
    ("comodidades", "Desfazer o Limpar, rascunho da AF e atalhos de teclado"),
    ("rubricas", "Rodape de rubrica e o total que nao contradiz os itens"),
    ("capex_opex", "A verba do CPM pode ser CAPEX ou OPEX"),
    ("navegador", "A janela abre no navegador favorito de cada um"),
    ("previa_responsiva", "PrÃ©via que acompanha a tela e rÃ³tulo AF/AS certo"),
    ("moeda_uma_regra", "Uma regra sÃ³ p/ a moeda: conversÃ£o, saldo e alÃ§ada"),
    ("colunas_prazo_garantia", "Prazo, garantia e cÃ³digo lidos em COLUNA da tabela"),
    ("marca_e_por_produto", "Marca do app, modo por produto e a associaÃ§Ã£o no texto"),
    ("proposta_orcamento", "Proposta em orÃ§amento: itens, frete e a filial da AF"),
    ("quadro_por_localidade", "Quadro por localidade: entregas, frete e observaÃ§Ãµes"),
    ("planilha_posicionada", "Planilha de preÃ§os sem grade, lida pela posiÃ§Ã£o"),
    ("campo_nao_perde_texto", "O formulÃ¡rio nÃ£o desmonta a frase que o extrator leu"),
    ("proposta_em_partes", "Proposta repartida em vÃ¡rios arquivos, e o fornecedor certo"),
    ("atualizacao_automatica", "VersÃ£o nova chega sozinha na mÃ¡quina de todos"),
    ("pdf_visual", "O PDF Visual nÃ£o troca o layout do documento sozinho"),
    ("paginacao", "Assinatura nunca sozinha e folha sem buraco no pe"),
    ("aritmetica_manda", "A conta arbitra quando os numeros da proposta se contradizem"),
    ("proposta_alg", "ALG: itens com codigo, condicoes do topo e frete"),
    ("divisorias_orcamento", "As divisorias do quadro Orcamento nao somem"),
    ("composicao_financeira", "Composicao financeira: parcela vira item, resultado nao"),
    ("locais_e_subtotais", "Subtotal de secao nao e produto; locais e filiais da proposta"),
    ("colunas_e_estacoes", "Coluna pelo cabecalho e quadro de estacoes como entrega"),
    ("arrastar_proposta", "Arrastar a proposta para a tela le o arquivo"),
    ("orcamento_mei", "Orcamento de MEI e nome de arquivo fora do Latin-1"),
]


def rodar(nome: str):
    arq = os.path.join(AQUI, nome + ".py")
    if not os.path.exists(arq):
        return None, "arquivo nÃ£o encontrado", 0.0
    t0 = time.time()
    r = subprocess.run([sys.executable, arq], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=os.path.dirname(AQUI))
    # stderr traz o log do app e os avisos do openpyxl â€” ruÃ­do, nÃ£o resultado.
    # (Da 1Âª vez o resumo saiu como "UserWarning: Data Validationâ€¦", que nÃ£o diz
    # nada sobre o teste ter passado.)
    return r.returncode == 0, (r.stdout or ""), (r.stderr or ""), time.time() - t0


def _resumo(saida: str) -> str:
    linhas = [l.strip() for l in saida.splitlines() if l.strip()]
    for l in reversed(linhas):                 # a linha que o prÃ³prio teste dÃ¡ como veredito
        if "TUDO OK" in l or l.startswith("FALHAS"):
            return l
    return linhas[-1] if linhas else "(sem saÃ­da)"


def main():
    print("=" * 66)
    print("  Auto AF/AS â€” testes")
    print("=" * 66)
    falharam = []
    for nome, descricao in SUITES:
        print(f"\nâ–¶ {nome}  ({descricao})")
        ok, saida, erro, seg = rodar(nome)
        if ok is None:
            print(f"   PULADO â€” {saida}")
            continue
        if ok:
            print(f"   âœ” {_resumo(saida)}   [{seg:.1f}s]")
        else:
            falharam.append(nome)
            print(f"   âœ˜ FALHOU   [{seg:.1f}s]")
            for l in saida.splitlines():
                if l.startswith("  FALHA") or l.startswith("FALHAS"):
                    print("     " + l.strip()[:150])
            cauda = [l for l in erro.splitlines() if l.strip()][-3:]
            for l in cauda:                      # se quebrou de verdade, o traceback
                if "Warning" not in l:
                    print("     " + l.strip()[:150])

    print("\n" + "=" * 66)
    if falharam:
        print(f"  {len(falharam)} suÃ­te(s) com falha: {', '.join(falharam)}")
        print(f"  Rode a que falhou sozinha para ver tudo:  python testes\\{falharam[0]}.py")
    else:
        print(f"  Tudo passando ({len(SUITES)} suÃ­tes).")
    print("=" * 66)
    return 1 if falharam else 0


if __name__ == "__main__":
    sys.exit(main())
