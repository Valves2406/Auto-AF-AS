# Auto AF/AS — Eletronet

App **desktop** que monta a **Autorização de Fornecimento/Serviço (AF/AS)** e a
**Coleta de Preços (CPM/CPS)** no modelo oficial da Eletronet, a partir da
**proposta do fornecedor** (PDF ou Excel) ou do **catálogo**.

Backend em **Python**; interface em **HTML/CSS/JS** numa janela do navegador.
Sem framework, sem build, sem servidor externo: `python app.py` sobe um servidor
local em `127.0.0.1` e abre a janela.

---

## Modelos oficiais — não vêm no repositório

Antes de rodar, coloque três arquivos em `backend/modelos/`:

```
backend/modelos/modelo_af.xlsm
backend/modelos/modelo_as.xlsm
backend/modelos/modelo_cpm.xlsx
```

**Sem eles o app não sobe**, e não é só porque falta o formulário em branco: o
catálogo de fábrica mora dentro dessas planilhas — 18 fornecedores com razão
social, endereço, CNPJ e inscrição estadual; as 20 filiais da Eletronet; e 182
POPs. É por isso que ficam de fora: o repositório é público, e isso é dado da
empresa.

Peça os três à Engenharia de Redes da Eletronet. O `.gitignore` já os bloqueia,
então não sobem sem querer numa próxima alteração.

---

## Rodar

```
Gerar AF.bat
```

Usa o **Python do sistema** de propósito — venv dentro do OneDrive desidrata e
quebra. Fechar a janela encerra o programa. Os documentos vão para `saída gerador/`.

A janela abre no **navegador padrão do Windows**. Edge, Chrome, Brave, Vivaldi e
Opera abrem em modo aplicativo (sem abas nem barra de endereço); o Firefox abre
uma janela normal, porque não tem esse modo. `GERADORAF_NAVEGADOR=chrome` força um.

---

## Onde fica cada coisa

Separado por **quem executa**: o Python fica em `backend/`, o que o navegador
carrega fica em `frontend/`. Mesma divisão do projeto Nexus.

```
backend/              tudo que roda em Python
  app.py              janela + servidor local (http.server da biblioteca padrão)
  engine.py           a API que o front chama: dados / extrair / preview / gerar
  core/
    caminhos.py       o que é RECURSO (só leitura, vai no .exe) x o que é DADO do usuário
    modelos.py        ItemAF, DadosProposta, moedas, valor por extenso em PT-BR
    dados_eletronet   catálogo (fornecedores, filiais, POPs), cadastro do usuário, migrações
    banco.py          os três cadastros no banco da equipe (Supabase), com cópia local
    extrator.py       lê a proposta: PDF de texto, seções numeradas, tabelas, OCR
    extrator_ciena.py o Excel do DDPTool da CIENA, que tem formato próprio
    aprendizado.py    aprende com as SUAS correções onde cada campo fica na proposta
    gerador.py        preenche o template oficial → Excel / PDF (+ proposta anexada)
    html_render.py    AF e CPM em HTML: a prévia da tela E o PDF "Visual";
                      e a leitura de volta de uma AF em Excel
    leitor_af.py      lê de volta uma AF/AS em PDF (a do app ou a do modelo
                      Excel) pelo DESENHO do documento: título, rótulo e valor
    trava.py          trava entre processos p/ o cadastro compartilhado na rede
    log.py            geradoraf.log, rotativo
  modelos/            modelo_af.xlsm, modelo_as.xlsm, modelo_cpm.xlsx e o logo do
                      DOCUMENTO — o que o Python LÊ (não vem no repositório, ver acima)

frontend/             tudo que o navegador carrega
  index.html          o formulário e a prévia
  app.css  app.js
  fontes/             DM Sans servida localmente (sem depender de rede)
  imagens/            marca, faixa, símbolo, ícone e o logo da INTERFACE

packaging/            AutoAF.spec — receita do PyInstaller
testes/               40 suítes — ver "Testes" abaixo
```

Uma armadilha ao mexer nisto: `core/caminhos.py` acha a raiz do projeto subindo
pastas a partir de si mesmo. Como agora ele é `backend/core/caminhos.py`, são
**três** níveis. Com dois, a "raiz" vira `backend/` e nada de `frontend/` é
encontrado — o app sobe e serve página em branco.

---

## Onde ficam os dados do usuário

O catálogo que vem no app é **só leitura**. O que a pessoa cadastra fica em

```
%APPDATA%\AutoAF\dados_usuario.json      cadastros, padrões, lições aprendidas
%APPDATA%\AutoAF\propostas_lidas.json    texto das últimas propostas, p/ aprender
%APPDATA%\AutoAF\config.json             para onde este computador está apontado
```

Fora do executável de propósito: **trocar a versão do app não apaga cadastro**.
A escrita é atômica, com cópia `.bak`; se o JSON corromper, o app usa o `.bak`.

**Setor inteiro no mesmo cadastro:** aba Cadastros → apontar para uma pasta de
rede. Todos passam a ler e gravar o mesmo arquivo, com trava entre processos.

### Banco da equipe (fornecedores, filiais de faturamento e POPs)

Com o banco configurado, esses **três cadastros** vêm de um banco Supabase, e o
que alguém cadastra aparece para o setor inteiro. **AF, AS e propostas nunca vão
para o banco.** Padrões, agenda e lições continuam no JSON acima.

- A máquina acha o banco em `GERADORAF_BANCO_URL` + `GERADORAF_BANCO_CHAVE`, no
  `config.json` (chave `"banco"`) ou num `banco.json` ao lado do app ou na pasta
  do setor — `{"url": "https://<projeto>.supabase.co", "chave": "sb_publishable_..."}`.
  Achado no `banco.json`, é copiado para o `config.json`.
- A chave publicável só **lê, inclui e altera**: apagar não existe para ela, e
  toda alteração fica em `privado.historico`, que a API não enxerga. Remover na
  tela = ocultar (o ↩ restaura). Mesmo assim, `banco.json` **não vai para o
  repositório** (está no `.gitignore`).
- Sem internet, as listas saem da cópia `%APPDATA%\AutoAF\banco_cache.json`;
  sem cópia, do catálogo do modelo. Gravar exige conexão — nada fica pendente.
- Na 1ª abertura com banco, o arquivo de cadastros da máquina é levado para lá
  **uma vez** (tabela vazia: tudo; senão, só o que o banco não tem) e carimbado.
- Os testes nunca usam o banco de verdade: `rodar.py` liga `GERADORAF_SEM_BANCO`
  e um script da pasta `testes/` ignora o `config.json`.

O arquivo tem **versão de esquema** e um migrador (`dados_eletronet.migrar`).
Mudou o formato? Suba `ESQUEMA_DADOS` e escreva a migração — ver `ATUALIZACAO.md`.

---

## Testes

```
python testes\rodar.py
```

Nenhum encosta no cadastro real: cada um trabalha num arquivo descartável em
`%TEMP%` (via `GERADORAF_DADOS`) ou num perfil falso.

Cada suíte guarda um erro que já aconteceu **uma vez**. O cabeçalho de cada
arquivo conta qual foi — leia antes de mexer na área que ela cobre.

| suíte | o que ela impede de voltar |
|---|---|
| `correcoes` | textos do CPM e o cabeçalho das duas folhas do Excel |
| `aprendizado` | que rótulo o app guarda ao aprender com a correção |
| `licao_coluna` | aprender o valor que está numa TABELA, não num rótulo |
| `ciclo` | ler → corrigir → guardar → aplicar na próxima proposta |
| `atualizacao` | trocar de versão sem duplicar nem perder cadastro |
| `equipe` | cadastro compartilhado entre máquinas do setor |
| `exe_na_rede` | o app numa pasta de rede: todos no mesmo cadastro |
| `valor_total` | o total da proposta manda sobre a soma das linhas |
| `itens_ncm` | tabela com NCM e endereço na mesma linha do produto |
| `secoes_proposta` | proposta em seções numeradas (escopo, pagamento, garantia) |
| `apontar_pasta` | cópia local apontada para a pasta do setor |
| `conta_por_linha` | qtd × unitário c/ imposto = total, e a soma do pedido |
| `quebras_pdf` | quebra de página no PDF e campos sem valor |
| `comodidades` | desfazer o Limpar, rascunho da AF e atalhos de teclado |
| `rubricas` | rodapé de rubrica e o total que não contradiz os itens |
| `capex_opex` | a verba do CPM pode ser CAPEX ou OPEX |
| `navegador` | a janela abre no navegador favorito de cada um |

---

## O que morde (aprendido no caminho, medindo)

**OneDrive.** Não põe venv aqui dentro — Files-On-Demand desidrata e quebra. O
`.bat` usa o Python do sistema por isso.

**openpyxl x `modelo_cpm.xlsx`.** Salvar por openpyxl corrompe esse template. O
CPM é preenchido pelo **Excel via COM**. A AF/AS, essa sim, vai por openpyxl.

**`break-inside: avoid` não é pedido, é ordem.** Num bloco alto, ele salta a
folha inteira e deixa o pé em branco — mediu-se 52% da 1ª folha vazia numa AF de
16 itens. Só é indivisível o que é atômico: uma linha de tabela, uma assinatura,
uma caixa de campo.

**Rodapé de página em impressão.** `position:fixed` repete em toda folha mas
**não reserva espaço**: é pintado dentro da área de conteúdo e sai por cima do
texto. Rodapé de verdade é `<tfoot>` com `display:table-footer-group`, que
repete E reserva. Dentro de célula de tabela o Chromium ignora `break-after` e
`break-before`; respeita `break-inside`.

**Arredondamento.** O `round()` do Python é bancário (5735,625 → 5735,62); a
praxe fiscal e o JavaScript arredondam meio para cima (5735,63). O app usa o
comercial. Espelhar a regra errada num teste acusa o app de um erro que é do teste.

**Docling custa dezenas de segundos.** Só vale quando os itens saem fracos e há
tabela para achar. Proposta de preço fechado (um valor no documento inteiro) o
dispensa: a leitura caiu de 28,6s para 0,8s.

**Medir, não achar.** Prévia dentro de `<iframe>`, painel de navegador com
largura zero, servidor Python servindo o módulo antigo — tudo isso já produziu
"defeito" que não existia. Quando o número surpreender, desconfie da medição
primeiro.

---

## Diagnóstico

`geradoraf.log` na raiz, rotativo: toda falha e todo caminho alternativo (Excel
COM, Edge headless, OCR, anexo da proposta, lições aplicadas) fica registrado.
**Olhe ele primeiro.**

| variável | para quê |
|---|---|
| `GERADORAF_NAVEGADOR` | força o navegador (`edge`, `chrome`, `firefox`, …) |
| `GERADORAF_DADOS` | redireciona o JSON de cadastros — usado pelos testes (desliga o banco) |
| `GERADORAF_SEM_BANCO=1` | ignora o banco da equipe: listas do modelo + JSON |
| `GERADORAF_BANCO_URL` / `_CHAVE` | aponta o banco da equipe sem mexer no `config.json` |
| `GERADORAF_RAIZ` | finge outra pasta de dados — simula o app instalado na rede |
| `GERADORAF_DOCLING=0` | desliga o Docling |
| `GERADORAF_LOG` | muda o destino do log |

---

## Em aberto

- 12 POPs sem CEP — o dado não existe em nenhuma das fontes disponíveis.
- "Bom Nome" (PE) sem município — mesmo caso.
- O projeto **não tem controle de versão**. Cada alteração depende de backup
  manual. `git init` resolveria.
- `dist/Auto AF-AS.exe` é de 01/09/2026 e **não tem** nada do que veio depois.
  Recompilar só quando for pedido — ver `ATUALIZACAO.md`.

---

## Documentos irmãos

- `DOCUMENTACAO_TECNICA.md` — arquitetura, fluxos e o histórico das rodadas.
- `ATUALIZACAO.md` — como lançar uma versão sem ninguém perder o que cadastrou.
