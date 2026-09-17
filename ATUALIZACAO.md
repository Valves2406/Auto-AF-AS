# Como lançar uma atualização sem ninguém perder o que cadastrou

## A regra que faz tudo funcionar

**Nada que o usuário cria mora dentro do executável.**

| Onde | O quê | Sobrevive à troca do .exe? |
|---|---|---|
| `%APPDATA%\Roaming\AutoAF\dados_usuario.json` | fornecedores, filiais, POPs, padrões, agenda de assinaturas, ocultos, lições | **sim** |
| `%APPDATA%\Roaming\AutoAF\propostas_lidas.json` | texto das últimas 20 propostas lidas (alimenta o aprendizado) | **sim** |
| `Auto AF-AS.exe` | código, `web/`, `assets/` (modelos .xlsm e catálogo base) | é o que você substitui |
| `saída gerador\` (ao lado do .exe) | AFs e CPMs gerados | fica onde está |

Um `.exe` *onefile* se descompacta num temporário que é apagado ao fechar — por
isso nada gravável pode ficar lá dentro. Trocar o executável é seguro: os dois
JSON do `%APPDATA%` não são tocados.

O caminho aparece no app: aba **Cadastros** → o rodapé mostra a pasta, e o número
da versão fica no aviso do topo (`v1.4.0`).

---

## Lançando uma versão

### 1. Se mudou só código, aparência ou catálogo base
Suba `VERSAO_APP` em `core/dados_eletronet.py`:

```python
VERSAO_APP = "1.4.1"
```

### 2. Se mudou o FORMATO do `dados_usuario.json`
(campo renomeado, estrutura diferente — não é o caso de simplesmente
acrescentar um campo novo, que é retrocompatível)

Suba também `ESQUEMA_DADOS` e escreva o passo da conversão:

```python
ESQUEMA_DADOS = 3

def _mig_3_o_que_mudou(d: dict) -> str:
    ...                       # converte d no lugar
    return "descrição do que foi convertido"

_MIGRACOES = {
    2: ("lições de leitura no formato novo", _mig_2_licoes_saneadas),
    3: ("o que mudou", _mig_3_o_que_mudou),
}
```

`migrar()` roda na abertura do app, aplica só os passos que faltam e **copia o
arquivo antes** para `dados_usuario.json.esquema2` — se a versão nova fizer
besteira, o anterior continua inteiro (o `.bak` rotativo não serve para isso,
porque é sobrescrito na gravação seguinte).

### 3. Gerar o executável

```bash
pyinstaller AutoAF.spec --noconfirm
```

O arquivo sai em `dist\Auto AF-AS.exe`.

### 4. Distribuir
Substituir o `.exe` na Área de Trabalho de quem usa. Só isso — sem
desinstalar, sem limpar nada, sem exportar/importar cadastro.

### 5. Conferir na máquina do usuário
Abrir o app e ver o número da versão no aviso do topo. Se mudou, entrou.

**Compilar não é conferir.** O PyInstaller já empacotou com sucesso um `.exe`
que quebrava na primeira tela porque faltava um arquivo de `assets/`. Antes de
entregar, ABRA o executável e veja se o catálogo carrega — o rodapé da tela diz
quantos fornecedores, filiais e POPs entraram. Se disser zero, o pacote está
incompleto mesmo tendo compilado sem erro.

---

## Histórico de versões

| versão | quando | o que entrou |
|---|---|---|
| 1.5.1 | 01/09/2026 | último build antes desta série |
| 0.6 | 09/09/2026 | numeração reiniciada. Aprendizado por coluna de tabela; leitura de proposta em seções numeradas; leitura 36× mais rápida em proposta de preço fechado (28,6s → 0,8s); item montado a partir do escopo; rodapé de rubrica; CAPEX/OPEX; cálculo automático desligável; conferência do total contra os itens; desfazer/rascunho/atalhos; multinavegador; correções de quebra de página e alinhamento do documento |
| 0.7 | 10/09/2026 | **marca própria** (Auto AF/AS by eletronet) na tela de carregamento, na aba do navegador e no ícone do executável. Prazo de entrega, garantia e código do produto lidos em COLUNA da tabela, com o cabeçalho partido em várias linhas; linha de licença sem código vira "LICENÇA"; quantidade conferida pela aritmética quando a sub-tabela desalinha; linha "Valor Global da Proposta" deixa de virar produto (somava a proposta duas vezes); modo "por produto" liga sozinho quando os itens divergem; UMA regra para reconhecer a moeda (o documento imprimia US$ e a conta usava R$, e a **alçada** saía errada); saldo sempre visível; prévia responsiva; associação volta ao texto quando o número da AF é uma sigla de projeto. O **modelo Visual passou a ser o padrão**: a prévia mostrava sempre o Visual e a cortina começava no Oficial, então o documento gerado não era o que estava na tela — agora são o mesmo, e uma etiqueta avisa quando a escolha difere da prévia. "Condição de pagamento" no singular voltou a ser lida. Proposta em forma de ORÇAMENTO (SEICOM): os produtos deixaram de virar linhas de total, o prazo de entrega e a filial da Eletronet saem da própria folha, "30 DDL" vira a frase por extenso e o frete cobrado fora da tabela explica a diferença da soma. |

> A numeração caiu de 1.5.1 para 0.5/0.6 a pedido, em setembro/2026. O migrador
> compara versão de ESQUEMA por igualdade, não por ordem — então cair de número
> não quebra nada. Mas repare: **o número menor é o mais novo** nesta transição.

---

## O que já está protegido (e por quê custou caro descobrir)

**Item corrigido não volta duplicado.** Quando o usuário corrige um POP do
catálogo oficial, o app oculta o de fábrica e usa o dele. O "ocultar" comparava
por texto exato: bastava a versão nova escrever `Gravataí 3` no lugar de
`Gravatai 3` para o item deixar de ser reconhecido e **voltar duplicado**. Hoje
a comparação é por identidade estável — CNPJ (só dígitos) para fornecedor e
filial, sigla para POP — e, quando não há, por texto sem acento e sem caixa.

**Item ocultado continua ocultado.** Mesmo problema, mesmo remédio: ocultar
`Tucuruí` e a versão seguinte escrever `Tucurui` fazia o POP ressuscitar.

**Sigla repetida não identifica ninguém.** No catálogo real a sigla `BHE` está
em quatro POPs diferentes (e `SDR`, `RJO`, `CTA`, `ALM` em dois cada). Onde a
sigla se repete ela é ignorada como identidade, senão corrigir um apagaria os
outros três.

**O cadastro do usuário sempre vence o de fábrica.** Se os dois descrevem o
mesmo item, fica o do usuário. É o que torna a atualização segura mesmo que o
registro de "ocultos" falhe por qualquer motivo.

---

## Se algo der errado

Na pasta `%APPDATA%\Roaming\AutoAF`:

| Arquivo | O que é |
|---|---|
| `dados_usuario.json` | o atual |
| `dados_usuario.json.bak` | a versão imediatamente anterior (rotativo) |
| `dados_usuario.json.esquema2` | como estava antes da migração para o esquema 2 |

Fechar o app, renomear o arquivo desejado para `dados_usuario.json`, abrir de novo.

---

## O .exe numa pasta de rede (o jeito mais simples)

Copie para a pasta de rede **dois arquivos**:

```
\\servidor\setor\AutoAF\
    Auto AF-AS.exe
    cadastro-da-equipe.json      ← pode começar com apenas:  {}
```

Pronto. Quem abrir o `.exe` de lá usa esse cadastro — **sem configurar nada em
máquina nenhuma**. Cadastrou um POP, todo mundo tem.

**Por que o arquivo precisa existir:** o app só compartilha quando encontra esse
nome ao lado do executável. É o interruptor, e é explícito de propósito — o `.exe`
copiado para a Área de Trabalho de alguém continua com o cadastro pessoal, sem
surpresa.

**A armadilha que isso evita:** antes, um `dados_usuario.json` ao lado do app era
**copiado** para o perfil de cada pessoa na primeira execução. Colocar o `.exe` na
rede daria a impressão de estar compartilhando, mas cada máquina seguiria com a
sua cópia, divergindo em silêncio. Agora o arquivo é usado no lugar, nunca copiado.

**Se a pasta for somente-leitura**, o app avisa no log e volta ao cadastro
pessoal em vez de quebrar.

**Ao atualizar:** troque só o `.exe`. O `cadastro-da-equipe.json` fica onde está.

### E quem copiou o .exe para a própria máquina?

Funciona igual: **Cadastros → "Onde ficam estes cadastros"** → escrever a pasta
do setor → **Usar esta pasta**. A pessoa passa a ler e gravar no mesmo cadastro,
edita normalmente, e o que ela cadastrar aparece para quem roda o `.exe` da rede.

Apontar para a **pasta** entra no `cadastro-da-equipe.json` que já estiver lá.
Antes criava um `dados_usuario.json` ao lado dele: a pessoa via o cadastro
vazio, ninguém via o que ela cadastrava, e o setor ficava dividido em dois
grupos sem sinal nenhum. Se a pasta estiver vazia, o `cadastro-da-equipe.json` é
criado — assim ela serve para os dois jeitos de usar.

---

## O setor inteiro sobre o mesmo cadastro

**Aba Cadastros → "Onde ficam estes cadastros"**: escrever a pasta de rede do
setor (`\\servidor\setor\AutoAF`) e clicar **Usar esta pasta**.

O que acontece:

- **Na primeira máquina**, o arquivo ainda não existe na rede: o que já está
  cadastrado ali é **copiado** para lá. Quem configura primeiro semeia a base.
- **Nas demais**, o arquivo já existe: nada é sobrescrito — a máquina passa a
  ler e escrever no cadastro que a equipe construiu.
- A partir daí, POP, fornecedor, filial, padrões e agenda de assinaturas que
  **uma** pessoa cadastrar aparecem para **todas**.
- **Voltar ao local** desfaz só naquela máquina; o cadastro da equipe fica
  intacto.

A escolha fica em `%APPDATA%\Roaming\AutoAF\config.json` — é uma configuração
**da máquina**, não do cadastro. Precisa ser assim: é ela que diz onde o
cadastro está, então não pode morar dentro dele. E é por isso que trocar o
`.exe` não desfaz a configuração.

Escrita simultânea é segura: o app trava o arquivo entre processos e **relê
dentro da trava** antes de gravar. Sem isso, o padrão ler→modificar→gravar
perderia atualização — A lê, B lê, A grava, B grava, e o cadastro de A somia.

> A variável de ambiente `GERADORAF_DADOS` continua funcionando e tem
> **precedência** sobre a tela (útil para fixar por GPO/script de logon). Quando
> ela está definida, o app avisa e desabilita os botões, em vez de fingir que a
> troca pela tela funcionou.

### Onde isso não chega

O compartilhamento vale para o **cadastro**. Não é um banco de dados: não há
histórico de quem alterou o quê, nem trava de edição simultânea do mesmo
registro (o último a salvar vence, no nível do arquivo inteiro). Para um setor
de poucas pessoas cadastrando POPs e fornecedores, é o suficiente; para dezenas
de pessoas editando ao mesmo tempo, o caminho seria um banco de verdade.
