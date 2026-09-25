# Documentação Técnica — Auto AF/AS (Gerador de AF/AS + CPM/CPS)

> **Eletronet S.A. — Engenharia de Redes**
> App desktop que lê a **proposta do fornecedor** e gera a **Autorização de Fornecimento/Serviço (AF/AS)** e a **Coleta de Preços (CPM/CPS)** no modelo oficial da Eletronet, com a proposta anexada.
> Documento consolidado de arquitetura, decisões, lições aprendidas e recomendações para projetos futuros.
> Última atualização: 2026-07-07.

---

## 1. O que o sistema faz

- **Entrada:** PDF da proposta comercial do fornecedor (e/ou catálogo interno).
- **Saída:**
  - **AF/AS** em **PDF oficial** (fiel ao template, exportado pelo Excel) ou **PDF Visual** (impresso do HTML), **Excel (.xlsx)** e **CSV**, sempre com a **proposta anexada ao final** do PDF.
  - **CPM/CPS** (relatório técnico-comercial que origina a AF), linkada à AF, também em PDF/Excel e com a proposta anexada.
- **Extras:** catálogo de fornecedores/filiais/POPs, cadastros do usuário (individuais e **em massa por planilha**), prévia HTML ao vivo, cortina de alçada/responsáveis, múltiplos clientes na CPM, moedas com conversão cambial.

---

## 2. Arquitetura e tecnologias utilizadas

| Camada | Tecnologia | Papel |
|---|---|---|
| **Janela** | Microsoft **Edge em modo `--app`** | Interface desktop sem framework pesado (abre o HTML local numa janela sem barra de navegador) |
| **Servidor** | Python **`http.server`** (stdlib, `127.0.0.1`, porta aleatória) | Serve o front e a API; encerra ao fechar a janela (heartbeat) |
| **Backend/API** | **`engine.py`** (no mesmo processo) | `dados()`, `extrair()`, `montar_preview()`, `gerar()`, `cpm_*`, `cadastrar()`, `importar_cadastros()` |
| **Front** | **`web/`** (index.html + app.css + app.js) — JS puro, sem framework | Formulário à esquerda + **prévia HTML ao vivo** à direita |
| **Planilha** | **openpyxl** | Preenche o template `.xlsm`; lê o catálogo |
| **Fidelidade Excel→PDF/xlsx** | **Excel COM** via **PowerShell** (subprocess) | Exporta PDF (`ExportAsFixedFormat`) e `.xlsx` (`SaveAs 51`) fiéis ao modelo |
| **HTML→PDF** | **Edge headless** (`--headless=new --print-to-pdf`) | Estilo "Visual" |
| **Leitura de PDF** | **pdfplumber** (texto+tabelas), **pypdfium2** (render/merge), **pytesseract** (OCR reserva), **Docling** (fallback de itens em tabela ruim) | Extração da proposta |
| **Merge PDF** | **pypdfium2** (`PdfDocument.new()/import_pages()`) | AF/CPM + proposta anexada |
| **Persistência do usuário** | **`dados_usuario.json`** (lateral ao projeto) | Cadastros do usuário — **o `.xlsm` oficial NUNCA é alterado** |

**Princípio central:** _usar o Excel oficial da Eletronet como base_ (não recriar do zero) e **sobrescrever as células de exibição com valores finais** — não depender de recálculo de fórmulas.

### Estrutura de arquivos
```
GeradorAF/
├─ backend/
│  ├─ app.py               # servidor + lançador do Edge (heartbeat de ciclo de vida)
│  ├─ engine.py            # API Python (a "ponte" de tudo)
│  ├─ core/
│  │  ├─ extrator.py       # lê a proposta → DadosProposta (calibrado)
│  │  ├─ gerador.py        # preenche template + Excel COM + merge PDF
│  │  ├─ html_render.py    # prévia/estilo Visual (AF e CPM) em HTML + leitura de AF em Excel
│  │  ├─ leitor_af.py      # lê de volta a AF/AS em PDF (visual ou modelo Excel)
│  │  ├─ modelos.py        # DadosProposta, ItemAF, MOEDAS, valor_por_extenso
│  │  └─ dados_eletronet.py # catálogo (do .xlsm) + cadastros do usuário (JSON) + import em massa
│  └─ modelos/ (modelo_af.xlsm, modelo_as.xlsm, modelo_cpm.xlsx, eletronet_logo.jpeg)
├─ frontend/ (index.html, app.css, app.js, fontes/, imagens/)
├─ saída gerador/          # documentos gerados
└─ Gerar AF.bat            # launcher 1-clique (usa o Python do sistema)
```

---

## 3. Fluxos principais

1. **Gerar AF/AS:** ler proposta (upload) → `extrair` → autocompleta o formulário → o usuário revisa/edita → `gerar` (PDF oficial / Visual / Excel / CSV) → salva em `saidas/` e anexa a proposta.
2. **CPM/CPS:** é uma **extensão da AF** — reaproveita fornecedor, valor, moeda, proposta, prazo, pagamento e local. Textos padronizados (finalidade/justificativa/consequências) por cenário (sem cliente / com cliente / vários clientes), alçada por faixa de valor, e a proposta também é anexada.
3. **Cadastros:** individual (formulário) ou **em massa** (planilha Excel-modelo → preencher → importar).
4. **Ler uma AF de volta** (botão Importar): PDF ou Excel → `importar_af` → formulário preenchido para revisar e reexportar. A AF é documento **nosso**, então a leitura segue o desenho dele, não adivinha:
   - **PDF visual** (o que o app gera): título de seção, rótulo e valor têm estilos diferentes (negrito azul / regular cinza / seminegrito escuro) e o PDF os preserva palavra a palavra — é o peso da fonte que separa rótulo de valor, não a posição nem a cor (há PDF em CMYK);
   - **PDF do modelo Excel**: rótulos com dois-pontos, notas numeradas em sequência e borda em cada célula; o texto que o Excel deixa transbordar da célula é devolvido à coluna certa;
   - **Excel**: cada seção achada pelo RÓTULO, não por célula fixa (AF feita à mão tem linhas inseridas);
   - faturamento e local de entrega voltam como o **registro do catálogo** (pelo CNPJ da filial e pela sigla do POP); o texto do PDF só vale quando o registro não existe;
   - a soma dos itens confere a leitura: se não fecha com o valor total, a tela avisa.
   Medido em 93 AFs reais com PDF e Excel da mesma autorização; `testes/ler_af_ida_e_volta.py` gera AFs pelas três rotas e lê de volta.

---

## 4. Lições aprendidas (os "gotchas" que custaram caro)

> Esta é a parte mais valiosa para projetos futuros. Cada item abaixo foi um bug real que consumiu tempo.

### 4.1 Excel / openpyxl
- **`keep_vba=True` + salvar como `.xlsx` = arquivo corrompido.** O template é `.xlsm` (com macro); salvar com extensão `.xlsx` mantendo o VBA faz o Excel recusar ("formato/extensão inválida"). Mesmo com `keep_vba=False`, o openpyxl **deixa resíduo de conteúdo macro** e o Excel ainda recusa. **Solução:** gerar o `.xlsx` **pelo próprio Excel** (COM `SaveAs`, formato **51 = xlOpenXMLWorkbook**), que remove as macros corretamente.
- **openpyxl descarta o logo "imagem-em-célula" (richData)** no save → **re-inserir** como imagem flutuante (`add_image`/OneCellAnchor).
- **openpyxl corrompe `modelo_cpm.xlsx`** (por causa de links externos `[1]dados_base`) a ponto do Excel COM não reabrir → **preencher a CPM via Excel COM**, não via openpyxl-save.
- **O output carregava o catálogo interno inteiro** (abas `dados_base`/`locais`/`POPs`: 18 fornecedores, 20 filiais com CNPJ, 182 POPs) → **inflava o arquivo E vazava dados**. **Solução:** no `SaveAs`, congelar as páginas em valores (`UsedRange.Value = UsedRange.Value`) e **apagar as abas de catálogo**.
- **Sobrescrever as células de exibição com literais** (não confiar em recálculo). Célula de moeda tinha formato dólar herdado → setar `number_format` explícito.

### 4.2 Excel COM (via PowerShell)
- **pywin32 não instalado**, mas Excel COM disponível → chamar por **`.ps1` em subprocess**.
- O `.ps1` deve ser **utf-8-sig** por causa de caminhos acentuados (OneDrive).
- Sentinela para argumento vazio = **`"NONE"`** (um `-` isolado o PowerShell trata como prefixo de parâmetro → erro).
- `AutomationSecurity = 3` (desliga macro ao abrir); `DisplayAlerts = $false` (sem prompts).

### 4.3 PDF / impressão (HTML→PDF)
- **Quebra de página cortava blocos no meio** (cabeçalho numa página, conteúdo na outra) → **`page-break-inside: avoid`** nos blocos, **`@page { size:A4; margin }`**, **`thead { display:table-header-group }`** (repete cabeçalho em tabela longa) e **`.sec { break-after:avoid }`** (cabeçalho não fica órfão).
- **Rodapé "Pré-visualização HTML" vazava para o PDF** → esconder só na impressão: **`@media print { .rod { display:none } }`** (mantém na prévia da tela).

### 4.4 Extração da proposta (calibração)
- **Docling é PODEROSO mas LENTO** (~3–33 s, carrega modelo ML) → usar **só como fallback de itens** quando pdfplumber/regex falham (ex.: PADTEC com tabela embaralhada). **NÃO** usar Docling para os campos (o markdown separa rótulo/valor em linhas → quebra os regex).
- **pdfplumber abria o PDF 2×** (texto + tabelas) → **passe único** (texto+tabelas no mesmo `open`, com cache): **~2× mais rápido**, saída idêntica.
- **Razão social quebrada em 2 linhas** (ex.: `SKYLANE OPTICS…DE` / `PESQUISA LTDA`) lia só a de baixo → juntar a linha anterior quando o nome é fragmento curto e a de cima termina em preposição.
- **% de imposto era lido como preço** (ex.: "9,75 %IPI") → detectar colunas de imposto pelo cabeçalho e pular.
- **CEP pegava dígitos errados** (data/CNPJ/telefone) → exigir hífen + rótulo + excluir contexto de telefone.
- **Valor pegava a taxa de câmbio** (ex.: "R$ 5,56" da NEC) → priorizar rótulos e linhas com "total"; último recurso, o maior `R$ ≥ 100`.
- **Total autoritativo = o "valor por extenso" / total do topo**, não a soma da coluna de itens (que muitas vezes mistura com/sem imposto → dá o dobro).
- **Itens em anexo** (NEC "descrito no Anexo II") → não vale rodar o Docling (gasta 30 s p/ achar 0) → avisar e seguir.
- **Propostas escaneadas** (fontes quebradas) → Docling reconstrói melhor que o OCR; OCR (Tesseract) como último recurso.

### 4.5 Frontend (HTML/JS)
- **`[hidden]` não escondia a aba** porque `.split{display:grid}` (classe) vencia o `[hidden]` da UA → regra global **`[hidden]{display:none!important}`**.
- **IDs duplicados quebram tudo** (ex.: um container e um input com o mesmo id) — o CAPEX "não subia" por isso.
- Prévia com **debounce** (~250 ms) p/ não refazer a cada tecla.

### 4.6 OneDrive (⚠️ o que mais deu dor de cabeça)
- **Files-On-Demand desidrata/some arquivos** durante o uso (o PDF da proposta sumiu do Desktop entre uma leitura e outra; pastas do projeto já sumiram por sync).
- **NÃO desenvolver dentro do OneDrive.** Manter backup fora (ex.: `C:\Dev\...`) e marcar "Manter sempre neste dispositivo".
- **Caminhos acentuados** (`Área de Trabalho`) quebram em heredoc/shell → escrever scripts em arquivo e computar caminhos por `os.path`, não digitar o acento.

### 4.7 Performance / metodologia
- **Medir antes de otimizar.** O gargalo da leitura era o 2º `open` do pdfplumber (~94 ms), não os regex (<2 ms). O gargalo de tamanho era o **logo de 132 KB** (1901×959), não as planilhas.
- **Imports pesados sob demanda** (pdfplumber/pypdfium2/Docling) → app abre rápido.
- **Imagens embutidas pequenas:** o logo a 600 px/24 KB (aparece com ~165 px) enxugou Excel e PDF-HTML sem perda visível.

---

## 5. O que foi feito nesta rodada (changelog)

| # | Entrega |
|---|---|
| 1 | **Prazo "Pronta-entrega"** na cortina (dispensa número; reconhece na proposta) |
| 2 | **Garantia "Livre"** (texto qualquer na cortina de garantia) |
| 3 | **CPM/CPS com vários clientes** — um **card por cliente** com POP origem/destino, banda, serviço, CCS, OS, PSC e produtos próprios; textos padronizados listam cada cliente e agrupam CCS/OS/PSC |
| 4 | **Proporcionalidade do PDF** (`@page`, evita cortar blocos, repete cabeçalho de tabela); **remoção do rodapé "Pré-visualização" no PDF**; **CPM passa a anexar a proposta** como a AF |
| 5 | **Correção do Excel `.xlsx`** — era um `.xlsm` disfarçado (não abria); agora gerado via Excel COM (`SaveAs 51`) |
| 6 | **Leitura ~2× mais rápida** (passe único do pdfplumber) + **razão social multi-linha** corrigida |
| 7 | **Tamanho do arquivo:** logo 132 KB → 24 KB; Excel deixa de carregar o catálogo interno → **AF/AS 208 KB → 50 KB** (e não vaza dados); **bug do título AS** ("FORNECIMENTO - AF" → "SERVIÇO - AS") |
| 8 | **Importação em massa** de fornecedores/faturamento/POPs por planilha Excel-modelo |

### 5.1 Rodada 2026-07-07 — robustez ("boas práticas" da seção 6 aplicadas ao código)

| # | Entrega |
|---|---|
| 1 | **Log central** (`core/log.py` → `geradoraf.log`, rotativo 512 KB × 3): TODO fallback e falha de Excel COM / Edge / OCR / merge agora fica registrado — antes eram `except: pass` silenciosos que custavam horas de diagnóstico |
| 2 | **`dados_usuario.json` blindado contra o OneDrive**: gravação **atômica** (temp + `os.replace`) com backup `.bak` automático; leitura corrompida cai no `.bak` em vez de perder os cadastros |
| 3 | **Sem duplicidade nos cadastros**: cadastrar/importar um registro que já existe (mesmos identificadores) é recusado com aviso — importar a mesma planilha 2× é inofensivo (conta em `duplicadas`) |
| 4 | **Fallbacks visíveis ao usuário**: se o PDF oficial cair no reportlab, o Visual cair no oficial, o CPM sair como `.xlsx` ou a proposta não anexar, a interface mostra o aviso (campo `avisos` no retorno de `gerar`/`gerar_cpm`) |
| 5 | **PowerShell/Excel COM num helper único** (`_run_powershell`): sem flash de janela (`CREATE_NO_WINDOW`), stderr capturado e logado, mensagem específica p/ timeout (Excel travado com diálogo aberto) |
| 6 | **Extração thread-safe**: instância nova do extrator por requisição (o cache de tabelas era compartilhado no servidor multi-thread) + tempo/método de cada extração no log |
| 7 | **`brl_para_float` aceita formato US** ("1,142,297.80" — o último separador é o decimal); antes virava 1.14 |
| 8 | **`GERADORAF_DADOS`** (redireciona o JSON de cadastros p/ testes — recomendação nº 10) e **`GERADORAF_LOG`** (caminho do log); limite de upload de 150 MB na API; handles de arquivo fechados; front avisa se o catálogo não carregar no boot |

### 5.2 Rodada 2026-09 — documento, leitura e continuidade

| # | Entrega |
|---|---|
| 1 | **Aprendizado passou a funcionar de verdade.** Medido no uso real: 13 propostas lidas, ZERO lições guardadas. A lição de rótulo pressupõe "Rótulo: valor" na mesma linha, e as propostas do setor trazem o valor numa TABELA. Entrou a **lição de coluna** (guarda o cabeçalho e a posição do valor entre os números). Cobertura nas propostas reais: 39% → 64% — os 11 pontos abrindo mão foram de âncoras que só valiam para um documento |
| 2 | **Proposta em seções numeradas** (`3.3 CONDIÇÕES DE PAGAMENTO` + conteúdo embaixo): garantia, condição de pagamento e escopo saíam vazios ou cortados porque as regras liam UMA linha. Descarta o sumário e o rodapé repetido |
| 3 | **Leitura 36× mais rápida** em proposta de preço fechado: 28,6s → 0,8s. O Docling era chamado para procurar itens num documento com **um** preço no total. Corte: menos de 3 preços distintos = não há tabela de itens |
| 4 | **Rodapé de rubrica** (opcional) via `<tfoot>`/`table-footer-group` — repete em toda folha E reserva o espaço. `position:fixed` repete mas não reserva: saía por cima do cartão de locais de entrega |
| 5 | **CAPEX ou OPEX** no CPM/CPS, numa cortina. Muda só o nome da verba; a conta do saldo e o Excel oficial não mudam. **Cotação** some quando a moeda é Real |
| 6 | **Cálculo automático pode ser desligado** — nem toda proposta fecha na conta, e o app "corrigir" o número é atrapalhar |
| 7 | **O total não pode contradizer os itens**: total MENOR que a soma das linhas pergunta antes de gerar (caso real: R$ 4.378,86 impresso sob uma linha de R$ 63.311,60) |
| 8 | **Comodidades**: desfazer o Limpar, rascunho da AF que sobrevive a fechar o app, atalhos de teclado (que também valem com o foco na prévia) |
| 9 | **Multinavegador**: a janela abre no navegador padrão do Windows — Edge, Chrome, Brave, Vivaldi e Opera em modo aplicativo; Firefox em janela normal |
| 10 | **Documento**: caixas do topo empilhadas (o valor era cortado na borda em 201px de largura), Orçamento em grade de 3 colunas, campo vazio vira travessão, quebra de página sem título órfão |
| 11 | **Limpeza**: removidas 3 funções sem chamada, 2 imports mortos e 3 regras de CSS órfãs; regras partidas em duas foram juntadas. Auditoria acusa zero função sem uso |
| 12 | **A prévia acompanha a largura da tela.** Faltava `<meta name="viewport">`: sem ela o navegador finge uma janela de 980px e ENCOLHE a página, então nenhuma `@media` dispara (medido: janela em 380px, `clientWidth` = 980). Com a linha no `<head>`, Orçamento vai de 3 → 2 → 1 coluna, os campos lado a lado empilham e o cabeçalho quebra em duas filas (numa fila só o título saía com uma palavra por linha) |
| 13 | **Orçamento sem buraco e com fio visível.** A célula que faltava para fechar a grade era um retângulo em branco no meio do documento — agora a última célula estica pela sobra (`sp2`/`sp3`, limitado junto com a grade). E o fio entre os campos é o fundo do container aparecendo pelo `gap`: em `#eaeff7` ele sumia no papel; passou a `#c9d2e5` |
| 14 | **Dentro do documento o rótulo segue o tipo**: numa AS lê-se "AS associada" e "Data da CPS", não "AF associada"/"Data da CPM". Fora do documento (abas, botões) "AF/AS" e "CPM/CPS" seguem valendo — ali o par é o nome da função |
| 15 | **A coluna do cabeçalho virou uma letra.** `overflow-wrap:anywhere` tinha sido aplicado a `td.desc,th` — com o cabeçalho podendo quebrar dentro da palavra, a largura MÍNIMA da coluna de preço passou a ser uma letra, e como essas colunas pedem `width:1%` (encolher até o conteúdo) o navegador deu a elas exatamente isso: "Unitário" saiu escrito na vertical. A regra vale só para `td.desc` |
| 16 | **O saldo aparece sempre** (decisão do usuário), e negativo sai em vermelho mesmo sem verba informada — a verba ao lado diz "não informado", então o número não fica sem explicação. Só o documento ainda vazio (sem verba E sem valor) mantém o travessão |
| 17 | **Uma regra só para a moeda — o bug era silencioso e grave.** Havia duas: `moeda_info()` buscava a chave EXATA do catálogo, `_simbolo()` do desenho buscava por pedaço do nome. O extrator devolve "Dólar", que não é a chave ("Dólar Americano"): o documento imprimia "US$ 100.000,00" e a conversão devolvia R$ 100.000,00. Efeito pior que o saldo errado — a **alçada** é escolhida pela faixa EM REAIS, então US$ 100 mil era julgado como R$ 100 mil e ia para um nível de aprovação mais baixo. `moeda_info()` passou a normalizar e aceitar apelido/símbolo, `_simbolo()` delega a ela, e o extrator já devolve a chave do catálogo |
| 18 | **Prazo, garantia e código lidos em COLUNA.** A proposta da DATACOM traz os três por item, e as regras só sabiam ler texto corrido ("Garantia é de 24 meses") — os campos saíam vazios. O cabeçalho da tabela vem PARTIDO em 7 linhas ("Prazo" numa, "Entrega" na seguinte, "(dias)" mais abaixo), então as linhas de cabeçalho são empilhadas por coluna antes da busca, e a unidade sai do próprio rótulo. O código ("800.5304") não passava na heurística de Part Number, que exige uma LETRA no token |
| 19 | **Linha de licença: sub-tabela deslocada.** Ela tem colunas próprias (ISS no lugar de ICMS/IPI) e cai fora do lugar na grade da tabela grande. Decodificada pela posição X: `882,00 \| 6 \| 2 \| 18,00 \| 900,00 \| 5.400,00` é *unit s/imp \| QTD \| ISS% \| valor do ISS \| unit c/imp \| total*. A quantidade era lida como **2** onde 6 × 900,00 = 5.400,00 está impresso na própria linha — AF com quantidade errada é pedido errado. Agora a aritmética confere: `total ÷ unitário` inteiro exato manda. Sem código na proposta, o código vira "LICENÇA" |
| 20 | **"Valor Global da Proposta" virava produto.** Bastava a célula CONTER "#.###,##" para ser preço, e a linha de fecho entrava como item somando a proposta inteira de novo: o total dos itens dava o DOBRO. Agora a célula tem de SER o número (fora símbolo de moeda e o espaço que o pdfplumber enfia no meio, "R$ 5 .462,50") |
| 21 | **Modo "por produto" liga sozinho.** Existia, mas era manual — e reparar que um item entre dez tem 70 dias em vez de 15 é o que não acontece lendo a grade. Com ele ligado, o campo do documento deixa de ser a faixa ("12 a 24 meses") e passa a ser a lista por item ("Itens 1 e 2 têm 24 meses; Item 3 tem 12 meses") |
| 22 | **Marca própria** (Auto AF/AS by eletronet) na tela de carregamento, na aba do navegador e no ícone do executável. O `.ico` leva 7 resoluções no mesmo arquivo — o Windows escolhe conforme o lugar — e só o SÍMBOLO, porque aos 16px o texto vira sujeira |
| 23 | **A associação sumia do texto** quando o número da AF era uma sigla de projeto ("AS-E-BMW/2026-TR"). A regra que separa identificador preenchido de vazio exigia DÍGITOS (`-\d+/`), e tratava a sigla como campo em branco: a frase "Com associação AF-… e CPM-…" desaparecia do documento inteiro, sem aviso |
| 24 | **A prévia mostrava um documento e o app gerava outro.** A prévia é SEMPRE o modelo Visual — medido: o HTML sai idêntico byte a byte com "Oficial" ou "Visual" escolhido — e a cortina "PDF" começava em **Oficial**. Preenchia-se a AF olhando um documento retrato e moderno e recebia-se o modelo do Excel, paisagem, sem nenhum aviso. Pior: a cortina tinha um listener chamando `schedulePreview()`, prometendo um efeito que não existe. O motor nunca teve defeito — pedir Visual devolve Visual, conferido no código-fonte e dentro do executável, com e sem a proposta anexada. **Correção**: o Visual passou a ser o padrão nas duas cortinas (decisão do usuário), e a barra da prévia ganhou uma etiqueta com o modelo que vai sair, em âmbar quando ele difere do que está na tela |
| 25 | **"Condição de pagamento" no singular não era lida.** O padrão era `Condi[çc][õo]es?` — cobre "Condições"/"Condicoes" mas exige um "o"/"õ" onde o singular tem "ão". A DATACOM escreve "Condição de pagamento: 30/60/90 dias." e o campo saía VAZIO numa proposta que trazia o dado escrito com todas as letras |
| 26 | **Proposta em ORÇAMENTO: os produtos viravam linhas de total.** Sem fios horizontais entre as linhas, o pdfplumber FUNDE os itens numa célula só ("001 002", "BTRMT2004 DTEND0107", descrições coladas) e o leitor de tabela devolve as linhas de fecho no lugar dos produtos: "TOTAIS DO ORÇAMENTO" entrava como item. O TEXTO da mesma folha está limpo, um produto por linha — é dele que os itens saem agora, ancorados no par QUANTIDADE + UNIDADE ("1,000 PC"), que separa a descrição (texto livre com números e barras) da fila de valores. A guarda de linha de fecho também não pegava **"TOTAIS"** no plural (`\btotal\b`) |
| 27 | **O unitário do orçamento é SEM imposto**: 4.650,00 + 809,36 de IPI = 5.459,36, que é o total da linha. Gravado como "com impostos" ele iria ao documento sem fechar com o total ao lado. O "com impostos" passa a sair de total ÷ quantidade, e as quatro casas decimais (precisão de sistema do fornecedor) viram duas |
| 28 | **"CONDIÇÃO DE PAGTO.......: 503 - 30 DDL"**: abreviado, com pontinhos até o dois-pontos, um código interno do fornecedor na frente e a coluna da direita começando na mesma linha (folha de 2 colunas). Nada disso casava. E **DDL vira frase**: "O pagamento deve ser efetuado 30 dias após o faturamento" — a sigla é do dia a dia de quem compra, não de quem assina uma AF que sai da empresa |
| 29 | **O frete explica a divergência em vez de só acusá-la.** Itens R$ 6.256,44 x proposta R$ 13.256,44: a diferença é exatamente o frete CIF de R$ 7.000,00, cobrado fora da tabela ("TOTAL + DESPESAS"). Quando a conta fecha com o frete, o aviso diz isso e perde o ⚠ — divergência sem explicação faz duvidar do documento inteiro. Sem frete que explique, o alerta continua igual |
| 30 | **A filial da Eletronet vem da própria proposta.** Muitas trazem a quem foram endereçadas ("ELETRONET S.A ... CNPJ: 03.052.673/0005-07" = filial RS). O casamento é pelo CNPJ e só por ele — 14 dígitos são de um estabelecimento só, enquanto nome e cidade são indício; o CNPJ do próprio fornecedor fica de fora. Antes era procurar a filial certa numa lista de 26 para repetir o que a folha já dizia |
| 31 | **O FORMULÁRIO desmontava o que a leitura acertava.** O campo de garantia/prazo tem dois modos — número+unidade e livre — e usava o par sempre que achasse um número com unidade em QUALQUER lugar da frase, descartando o resto: "90 dias após a assinatura" virava "90 Dias" e "item 1: 3 unidades a pronta entrega, as demais dia 22/09" virava "Pronta-entrega" — o documento prometendo o que ninguém prometeu. O par só vale quando representa a frase inteira. **Lição**: consertar o extrator não é consertar o campo; a verificação tem de ir até a tela e o documento |
| 32 | **Planilha de preços desenhada como TEXTO POSICIONADO** (NEC/Nokia). Sem fios, o `extract_tables()` não acha nada e o `extract_text()` devolve a folha COLUNA A COLUNA ("HWHWHW...", depois todos os itens): 0 itens lidos e o total pegando o primeiro preço (R$ 5.884,56 numa proposta de R$ 1.068.559,59). Lida pela POSIÇÃO das palavras, com duas medidas tiradas da folha — a fonte parte as palavras (vão de 0,0-0,1pt contra ~1,0pt de um espaço real) e a descrição larga invade a coluna de quantidade. Os 33 itens somam exatamente o total impresso |
| 33 | **Padtec: linha de grupo virando item, e "unitário" que era total.** "Equipamentos -" não tem quantidade nem código e o valor é a soma das linhas de baixo — a soma dos itens dava o DOBRO. E `510,14 x 42 = 21.425,88` prova que o 2º preço da linha é o TOTAL sem impostos, não um unitário: sairia R$ 21.425,88 de unitário para uma peça de R$ 679,98 |
| 34 | **Fornecedor adivinhado no empate.** A proposta técnica da Precision Solutions era identificada como ARTEMIS: as duas têm "solutions" no nome, o desempate era "palavra mais longa", empatou em 9 letras e venceu a ordem da lista. Agora o peso é QUANTAS palavras distintivas batem, as genéricas em inglês entraram na lista de vagas, e **empate não escolhe** — melhor o app dizer que não reconheceu do que imprimir o fornecedor errado |
| 35 | **Proposta em VÁRIAS PARTES** (Precision, SEICOM): o seletor aceita vários arquivos e as partes são combinadas — texto vale a 1ª que trouxer, itens ficam com a lista MAIOR (somar duplicaria o pedido), e entregas/faturamento/observações somam sem repetir. A comercial da Precision diz "Local: Vide Proposta Técnica": nenhuma das duas sozinha tem tudo |
| 36 | **Fios do Orçamento sumindo em parte.** A geometria estava certa (1px exato em cada vão); o que falhava era a pintura — faixa de 1px do fundo do container em posição fracionária de pixel some no arredondamento, e some de forma irregular. Cada célula passa a pintar o próprio fio com `box-shadow`, que parte da borda já arredondada dela |

---

## 6. Recomendações para projetos futuros

1. **Não desenvolver em pasta sincronizada (OneDrive/Drive/Dropbox).** Se inevitável, backup fora e "manter neste dispositivo".
2. **Reaproveitar o artefato oficial do cliente** (o Excel dele) em vez de recriar — mas **preencher com valores finais** e, para o output final, **congelar fórmulas em valores** e **remover dados internos** (higiene + tamanho).
3. **Para `.xlsx` a partir de template com macro, use o Excel (COM), não o openpyxl** para o SaveAs final.
4. **Mantenha imagens embutidas pequenas** (dimensione para ~2× do tamanho de exibição).
5. **Meça antes de otimizar** — perfil por fase, não achismo.
6. **Separe dados internos (catálogo) do entregável** — nunca embarque a base inteira num documento que sai da empresa.
7. **Calibre a extração contra amostras reais** e mantenha **fallback em camadas** (nativo → reconstrução → OCR); avise quando cair no fallback.
8. **Guarde dados do usuário num arquivo lateral (JSON)** — nunca mute o template-fonte.
9. **Teste geração com dados sintéticos** e **verifique o render de verdade** (abrir via Excel COM / renderizar o PDF em imagem).
10. **Cuidado com encoding em shell** (heredoc + acentos): escreva scripts em arquivo; para testar cadastro/persistência, **redirecione o arquivo de dados para um temp** (não polua o real).

---

## 7. Como rodar / manter

- **Rodar:** `Gerar AF.bat` (usa o **Python do sistema**, não venv — venv dentro do OneDrive desidrata e quebra).
- **Atualizar o catálogo** (fornecedores/filiais/POPs oficiais): trocar o `assets/modelo_af.xlsm` (abas `dados_base`/`locais`/`POPs`). Cadastros do usuário ficam à parte no `dados_usuario.json`.
- **Cadastro em massa:** aba Cadastros → **📥 Baixar modelo Excel** → preencher → **📤 Importar** (linhas repetidas não duplicam).
- **Diagnóstico:** consultar o `geradoraf.log` na raiz do projeto — toda falha/fallback (Excel COM, Edge, OCR, anexo da proposta) fica registrada lá.
- **Variáveis úteis:** `GERADORAF_DOCLING=0` (desliga o Docling), `GERADORAF_PYTHON` (override do interpretador), `GERADORAF_DADOS` (redireciona o JSON de cadastros — usar em testes), `GERADORAF_LOG` (caminho do arquivo de log).

---

*Este documento é um resumo vivo. A base de conhecimento detalhada (com file:line e histórico) fica na memória do assistente (`gerador-af.md`).*
