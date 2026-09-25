"use strict";
let DATA = null;
let caminhoPdf = "";
let items = [novoItem()];
let faturamentos = [];   // locais de faturamento escolhidos (vários por AF)
let entregas = [];       // locais de entrega (POP) escolhidos (vários por AF)
let perItemGarantia = false;  // garantia por produto (cada item o seu)
let perItemPrazo = false;     // prazo de entrega por produto (cada item o seu)
let gpSel = new Set();        // itens marcados p/ aplicar a MESMA garantia/prazo

function novoItem() {
  return { codigo: "", descricao: "", quantidade: "", unidade: "",
           preco_unit_sem: "", preco_unit_com: "", preco_total_com: "", garantia: "", prazo: "",
           impostos: [],     // [{nome:"IPI", aliq:"5"}, …] — por produto
           ucAuto: false };  // o unitário c/ imposto foi calculado (true) ou digitado (false)
}
const $ = (id) => document.getElementById(id);
const val = (id) => $(id).value;
/* BARRA DE STATUS — uma mensagem por linha.
   Vários pontos do app juntam avisos numa string só, separados por "⚠" e "•", e
   o resultado era uma linha corrida do tipo "Proposta lida. ⚠ Fornecedor não
   está no catálogo — … ⚠ Fornecedor não identificado — … • ⚠ Soma dos itens
   difere do total da proposta". Ninguém lê isso.
   Em vez de mexer em cada chamada, a quebra é feita AQUI: qualquer setStatus
   com vários avisos passa a sair empilhado, cada um com o seu ícone e cor. */
const _ICONE = { aviso: "⚠", ok: "✔", erro: "✕", info: "›" };

function _partesStatus(txt) {
  const bruto = String(txt || "").replace(/\s*•\s*/g, " ").trim();
  if (!bruto) return [];
  // mantém o ⚠ colado na mensagem dele, para saber qual pedaço é aviso
  return bruto.split(/(?=⚠)/).map(t => t.trim()).filter(Boolean).map(t => {
    const aviso = t.startsWith("⚠");
    return { aviso, texto: t.replace(/^[⚠✔✕›]\s*/, "").trim() };
  });
}

function setStatus(msg, cls) {
  const s = $("status");
  s.className = "status " + (cls || "");
  const partes = _partesStatus(msg);
  if (partes.length <= 1) {                    // caso comum: uma linha, como antes
    s.textContent = partes.length ? partes[0].texto : "";
    s.classList.toggle("multi", false);
    return;
  }
  s.classList.add("multi");
  s.innerHTML = partes.map(p => {
    const tipo = p.aviso ? "aviso" : (cls === "erro" ? "erro" : cls === "ok" ? "ok" : "info");
    return `<span class="st-linha st-${tipo}"><i>${_ICONE[tipo] || "›"}</i>${escapeHtml(p.texto)}</span>`;
  }).join("");
}

async function api(path, opts) {
  const r = await fetch(path, Object.assign({ method: "POST" }, opts || {}));
  return r;
}
// Cabeçalho HTTP só aceita Latin-1: um nome com travessão "–", aspas curvas
// ou emoji fazia o fetch estourar ANTES de sair. Codificado, vira ASCII puro;
// o servidor desfaz com unquote.
function comNome(nome) {
  return { "X-Filename": encodeURIComponent(nome || "") };
}
// Abre a subpasta onde o arquivo foi salvo (AF-pdf, CPS-excel, …); sem pasta, a base.
function abrirPasta(pasta) {
  api("/api/abrir", { headers: { "Content-Type": "application/json" }, body: JSON.stringify({ pasta: pasta || "" }) });
}

// ---------------------------------------------------------------- init ----
// Id desta janela: o servidor só encerra quando a ÚLTIMA sair — antes, fechar
// uma janela derrubava o motor das outras que estivessem abertas.
const CLIENTE = (crypto.randomUUID ? crypto.randomUUID() : String(Math.random()).slice(2));
function iniciarHeartbeat() {
  // Mantém o processo Python vivo enquanto esta janela existir; ao fechar a
  // janela, o sendBeacon avisa o servidor.
  setInterval(() => {
    api("/api/ping", { headers: { "X-Cliente": CLIENTE } }).catch(() => {});
  }, 3000);
  window.addEventListener("pagehide", () => {
    // sendBeacon não manda cabeçalho — o id vai no corpo (o servidor aceita os dois)
    try {
      navigator.sendBeacon("/api/fechar", new Blob([JSON.stringify({ cli: CLIENTE })],
                                                   { type: "application/json" }));
    } catch (e) { /* ignore */ }
  });
}

/* A tela de carregamento fica no ar por pelo menos isto. Com o motor já
   aquecido a preparação termina em milissegundos, e a tela piscava — rápido
   demais para ler o que está escrito nela. É PISO: preparação mais longa
   manda, e ninguém espera além do necessário depois dos 5s. */
const SPLASH_MINIMO = 5000;
const SPLASH_T0 = Date.now();

/** Segura o fecho até completar o piso. O botão "Continuar mesmo assim" não
    passa por aqui: quem clicou nele quer sair agora. */
async function esperarPisoDoSplash() {
  const falta = SPLASH_MINIMO - (Date.now() - SPLASH_T0);
  if (falta > 0) await new Promise(r => setTimeout(r, falta));
}

// Tela de carregamento: acompanha o aquecimento do motor (/api/preparar) para
// que a lentidão do 1º uso — importar pdfplumber/openpyxl, ler o .xlsm, hidratar
// arquivo do OneDrive — aconteça AQUI, e não no meio do trabalho do usuário.
async function aguardarPreparo() {
  const lista = $("splashLista"), barra = $("splashBarra"), passoEl = $("splashPasso");
  const LIMITE = 45000;              // teto de segurança: nunca prende o usuário
  const t0 = Date.now();
  let passos = null;
  $("splashPular").onclick = fecharSplash;

  while (Date.now() - t0 < LIMITE) {
    let e;
    try { e = await (await fetch("/api/preparar")).json(); }
    catch (err) { return; }          // motor mudo: segue e o init reporta o erro
    if (!passos) {                   // desenha a lista de etapas uma única vez
      passos = e.passos || [];
      lista.innerHTML = passos.map(p => `<li data-k="${p.chave}">${escapeHtml(p.rotulo)}</li>`).join("");
    }
    const feitos = e.feitos || [];
    passos.forEach(p => {
      const li = lista.querySelector(`li[data-k="${p.chave}"]`);
      if (!li) return;
      // a etapa entra em "feitos" quando COMEÇA → só vira ✓ quando sai de "passo"
      li.classList.toggle("ativo", !e.pronto && p.chave === e.passo);
      li.classList.toggle("ok", feitos.includes(p.chave) && (e.pronto || p.chave !== e.passo));
    });
    barra.style.width = (e.pronto ? 100 : Math.round((feitos.length / (e.total || 1)) * 100)) + "%";
    const at = passos.find(p => p.chave === e.passo);
    passoEl.textContent = e.pronto ? "Tudo pronto." : (at ? at.rotulo + "…" : "Preparando…");
    if (e.pronto) { if (e.erro) console.warn("preparação incompleta:", e.erro); return; }
    if (Date.now() - t0 > 8000) $("splashPular").hidden = false;   // demorou: oferece saída
    await new Promise(r => setTimeout(r, 250));
  }
}

function fecharSplash() {
  const s = $("splash");
  if (!s || s.classList.contains("fim")) return;
  s.classList.add("fim");
  setTimeout(() => { s.hidden = true; }, 500);   // só some depois do fade
}

async function init() {
  bindTopbar();
  iniciarHeartbeat();
  await aguardarPreparo();
  try {
    DATA = await (await api("/api/dados")).json();
  } catch (e) { setStatus("Falha ao falar com o motor Python: " + e, "erro"); fecharSplash(); return; }
  if (DATA && DATA.ok === false) {   // motor respondeu mas o catálogo não carregou (ex.: .xlsm ausente)
    setStatus("Falha ao carregar o catálogo: " + (DATA.erro || "?"), "erro");
    fecharSplash();
    return;
  }

  fillSelect("moeda", DATA.moedas);
  fillSelect("prefixo", DATA.prefixos);
  fillSelect("mod", DATA.modificacoes);
  popularAlcadas();
  optionList("catalogo", DATA.fornecedores.map(f => f.apelido ? `${f.apelido} — ${f.empresa}` : f.empresa));
  $("catCount").textContent = `${DATA.fornecedores.length} fornecedores no catálogo`;

  const hoje = new Date();
  $("ano").value = hoje.getFullYear();
  $("dataEmis").value = hoje.toLocaleDateString("pt-BR");
  $("moeda").value = "Real";
  const sp = DATA.faturamento.find(l => l.uf === "SP");   // matriz SP por padrão
  if (sp) faturamentos.push(sp);

  bindForm();
  bindTabs();
  bindCadastros();
  bindExcluir();
  bindCPM();
  renderItems();
  renderFaturamentos();
  renderEntregas();
  atualizarPreferencias();   // popula as listas já priorizando o estado da matriz SP
  atualizarStats();
  if (DATA.versao) $("versaoApp").textContent = "v" + DATA.versao;
  renderExcluir();
  // "info" e não "ok": o catálogo carregar não é um SUCESSO — é o estado de
  // repouso do app, a primeira coisa que se lê ao abrir. Em verde ela
  // competia com os avisos de verdade, e o verde está fora da marca desde o
  // rebrand da Axia. O verde fica para o que realmente concluiu (documento
  // gerado, cadastro salvo).
  setStatus(`Catálogo carregado: ${DATA.fornecedores.length} fornecedores · ${DATA.faturamento.length} filiais · ${DATA.pops.length} POPs.`, "info");
  if (location.hash === "#cadastros") switchTab("cadastros");
  else if (location.hash === "#excluir") switchTab("excluir");
  ligarAtalhos();
  ofereceRascunho();       // uma AF que ficou pela metade continua disponível
  // AS DUAS PRÉVIAS já montadas ao abrir. A da AF sempre foi; a do CPM/CPS só
  // era pedida ao entrar na aba, então quem trocava de aba encontrava uma
  // moldura branca e esperava sem saber o quê.
  // `cpmPreview()` só pinta o iframe — NÃO liga o `cpmIniciado`. Isso importa:
  // se ligasse, entrar na aba depois deixaria de puxar os dados da AF, e a
  // CPM sairia vazia justamente na hora de usar.
  schedulePreview();
  cpmPreview();
  await esperarPisoDoSplash();
  fecharSplash();          // interface montada e motor aquecido → libera a tela
}

function fillSelect(id, arr) { $(id).innerHTML = arr.map(v => `<option>${v}</option>`).join(""); }
function optionList(id, arr) {
  const keep = id === "catalogo" ? '<option value="-1">— selecione —</option>' : "";   // fat/ent viraram autocomplete
  $(id).innerHTML = keep + arr.map((v, i) => `<option value="${i}">${escapeHtml(v)}</option>`).join("");
}
function escapeHtml(s) { return (s || "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }

// ----------------------------------------------------------- topbar/form --
function bindTopbar() {
  $("btnTema").onclick = () => document.body.classList.toggle("light") | document.body.classList.toggle("dark");
  iniciarPreviaLateral();
  $("btnLer").onclick = () => $("filePdf").click();
  // `() => lerProposta()` e não `lerProposta`: passada direto, ela receberia o
  // Event como primeiro argumento e o trataria como lista de arquivos.
  $("filePdf").onchange = () => lerProposta();
  ligarArrastar();
  $("btnCienaTrocar").onclick = () => mostrarLadoCiena(_ciena && _ciena.atual === "af" ? "as" : "af");
  $("btnImportarAF").onclick = () => $("fileAF").click();
  $("fileAF").onchange = importarAF;
  $("btnPdf").onclick = () => gerar("pdf");
  $("btnExcel").onclick = () => gerar("excel");
  $("btnAddItem").onclick = () => { items.push(novoItem()); renderItems(); renderImpItens(); schedulePreview(); };
  $("btnAddObs").onclick = () => { addObsRow("", true); };
  bindAC("fat"); bindAC("ent");                       // busca com sugestões visíveis
  $("btnAddFat").onclick = () => acEscolher("fat");   // botão adiciona o destacado
  $("btnAddEnt").onclick = () => acEscolher("ent");
  $("btnResumir").onclick = () => { $("objeto").value = resumoItens(); schedulePreview(); };
  $("btnSomar").onclick = () => { const s = somaItens(); if (s) { $("valor").value = s; schedulePreview(); } };
  $("ckImpostos").onchange = toggleImpostos;
  $("ckCalcular").onchange = toggleCalcular;
  $("ckRubricas").onchange = () => { if ($("ckRubricas").checked) abrirRubPop(); else fecharRubPop(); pintarRubModo(); schedulePreview(); };
  ligarRubrica();
  try {
    if (localStorage.getItem(CALC_PREF) === "0") {
      $("ckCalcular").checked = false;
      document.body.classList.add("sem-calculo");
    }
  } catch (e) {}
  $("btnPorItemGarantia").onclick = togglePerItemGarantia;
  $("btnPorItemPrazo").onclick = togglePerItemPrazo;
  $("prazoUn").addEventListener("change", syncPronta);        // "Pronta-entrega" dispensa o número
  $("garantiaUn").addEventListener("change", onGarantiaUn);   // "Livre" → escrever qualquer coisa
  // A prévia NÃO muda com esta cortina — ela mostra sempre o modelo Visual.
  // O que muda é o PDF que vai sair, então o que se atualiza é a etiqueta.
  $("pdfEstilo").addEventListener("change", marcarModelo);
  if ($("cpmEstilo")) $("cpmEstilo").addEventListener("change", marcarModelo);
  marcarModelo();                       // e já na abertura, sem esperar troca
}

// A prévia é uma ferramenta de conferência, não pode roubar a largura de quem
// está preenchendo. Em notebook ela começa recolhida; a régua na lateral abre
// e fecha sem mudar de aba, e a escolha fica guardada nesta cópia do app.
const PREVIA_PREF = "autoaf.previa.recolhida.v1";
function setPreviaRecolhida(recolhida, salvar) {
  document.body.classList.toggle("preview-collapsed", !!recolhida);
  document.querySelectorAll("[data-preview-toggle]").forEach(btn => {
    btn.setAttribute("aria-pressed", String(!recolhida));
    btn.title = recolhida ? "Abrir prévia" : "Recolher prévia";
    const t = btn.querySelector(".preview-rail-text");
    if (t) t.textContent = recolhida ? "Abrir prévia" : "Prévia";
    const i = btn.querySelector(".preview-rail-icon");
    if (i) i.textContent = recolhida ? "▣" : "◫";
  });
  if (salvar) {
    try { localStorage.setItem(PREVIA_PREF, recolhida ? "1" : "0"); } catch (e) {}
  }
}
function iniciarPreviaLateral() {
  let salvo = null;
  try { salvo = localStorage.getItem(PREVIA_PREF); } catch (e) {}
  // A regra é em pixels CSS — portanto respeita escala do Windows e zoom do Edge.
  const estreito = window.matchMedia("(max-width: 1180px)");
  setPreviaRecolhida(salvo === null ? estreito.matches : salvo === "1", false);
  // O PADRÃO ACOMPANHA A JANELA até alguém escolher. Antes a decisão era tomada
  // uma única vez, no carregamento: abrir o app com a janela pequena e depois
  // maximizar deixava a prévia escondida para sempre — e como nada tinha sido
  // salvo, não havia escolha do usuário ali, só um padrão que ficou preso.
  // Assim que a pessoa clica na régua, a preferência dela é gravada e este
  // acompanhamento sai de cena.
  // `resize` e não o `change` do matchMedia: o `change` não dispara em todos os
  // modos de redimensionamento (medido — zero disparos enquanto o `matches`
  // virava), e uma correção que não dá para verificar não é correção. A guarda
  // abaixo faz o trabalho só na TRAVESSIA do limite, não a cada pixel.
  let eraEstreito = estreito.matches;
  window.addEventListener("resize", () => {
    const agoraEstreito = window.matchMedia("(max-width: 1180px)").matches;
    if (agoraEstreito === eraEstreito) return;
    eraEstreito = agoraEstreito;
    let pref = null;
    try { pref = localStorage.getItem(PREVIA_PREF); } catch (e) {}
    if (pref === null) setPreviaRecolhida(agoraEstreito, false);
  });
  document.querySelectorAll("[data-preview-toggle]").forEach(btn => {
    btn.onclick = () => setPreviaRecolhida(!document.body.classList.contains("preview-collapsed"), true);
  });
}

// "Pronta-entrega" = entrega imediata: limpa e trava o campo de número (não há prazo em dias).
function syncPronta() {
  const un = val("prazoUn");
  const pronta = /pronta/i.test(un), livre = /^livre$/i.test(un);
  const num = $("prazoNum");
  if (pronta) num.value = "";                 // entrega imediata dispensa número
  num.disabled = pronta || perItemPrazo;
  num.placeholder = pronta ? "—" : (livre ? "escreva o prazo (ex.: a combinar)" : "45");
  schedulePreview();
}
// "Livre" = escrever a garantia à vontade (ex.: "conforme fabricante", "vitalícia").
function onGarantiaUn() {
  const livre = /^livre$/i.test(val("garantiaUn"));
  $("garantiaNum").placeholder = livre ? "escreva a garantia (ex.: conforme fabricante)" : "12";
  schedulePreview();
}

// ------------------------------- garantia/prazo POR PRODUTO ---------------
function setPerItemGarantia(v) {
  perItemGarantia = !!v;
  $("btnPorItemGarantia").classList.toggle("on", perItemGarantia);
  ["garantiaNum", "garantiaUn"].forEach(id => { $(id).disabled = perItemGarantia; });
  renderGPItens();
  schedulePreview();
}
function setPerItemPrazo(v) {
  perItemPrazo = !!v;
  $("btnPorItemPrazo").classList.toggle("on", perItemPrazo);
  $("prazoUn").disabled = perItemPrazo;
  syncPronta();                 // reconcilia o campo de número (respeita "Pronta-entrega")
  renderGPItens();
}
function togglePerItemGarantia() { setPerItemGarantia(!perItemGarantia); }
function togglePerItemPrazo() { setPerItemPrazo(!perItemPrazo); }

/* A proposta trouxe valores DIFERENTES entre os itens? Então o modo por produto
   é o certo, e ligar sozinho poupa a pessoa de reparar. Reparar é o que não
   acontece: numa proposta de dez itens, é uma fonte que tem 70 dias em vez de
   15 e outra que tem 12 meses em vez de 24 — passa batido lendo a grade.
   Com o modo ligado, o campo do documento vira a lista por item (gpResumo),
   que é mais útil que a faixa "12 a 24 meses".
   Só liga com valores diferentes: todos iguais, um campo só resolve. */
function ligarPorProdutoSeDiferir() {
  const distintos = (campo) =>
    new Set(items.map(it => (it[campo] || "").trim()).filter(Boolean)).size;
  const g = distintos("garantia") > 1, p = distintos("prazo") > 1;
  if (g) setPerItemGarantia(true);
  if (p) setPerItemPrazo(true);
  if (g || p) {
    const quais = g && p ? "garantia e prazo de entrega" : (g ? "garantia" : "prazo de entrega");
    setStatus(`A proposta traz ${quais} diferente por produto — liguei o modo `
              + `"por produto"; confira item a item.`, "aviso");
  }
  return g || p;
}
function renderGPItens() {
  const el = $("gpItens");
  const ativo = perItemGarantia || perItemPrazo;
  el.hidden = !ativo;
  if (!ativo) return;
  gpSel = new Set([...gpSel].filter(i => i < items.length));   // limpa índices inválidos
  const titulo = perItemGarantia && perItemPrazo ? "Garantia e prazo por produto"
    : perItemGarantia ? "Garantia por produto" : "Prazo de entrega por produto";
  const campos =
    (perItemGarantia ? '<input id="gpGarantia" placeholder="garantia (ex.: 12 meses)">' : "") +
    (perItemPrazo ? '<input id="gpPrazo" placeholder="prazo (ex.: 45 dias)">' : "");
  el.innerHTML =
    `<div class="gp-h">${titulo} — marque os itens iguais, preencha e clique Aplicar</div>` +
    `<div class="gp-aplicar">${campos}<button type="button" class="btn primary sm" id="gpAplicar">Aplicar aos marcados</button></div>` +
    `<div class="gp-tools"><button type="button" class="lnkmini" id="gpAll">marcar todos</button>` +
    `<button type="button" class="lnkmini" id="gpNone">limpar seleção</button></div>` +
    items.map((it, i) => {
      const cur = [perItemGarantia ? `🛠 ${it.garantia || "—"}` : null,
                   perItemPrazo ? `🚚 ${it.prazo || "—"}` : null].filter(Boolean).join("  ·  ");
      return `<label class="gp-pick"><input type="checkbox" data-i="${i}"${gpSel.has(i) ? " checked" : ""}>` +
        `<span class="gp-lbl">${i + 1}. ${escapeHtml(it.codigo || it.descricao || "item")}</span>` +
        `<span class="gp-cur">${escapeHtml(cur)}</span></label>`;
    }).join("");

  el.querySelectorAll("input[type=checkbox][data-i]").forEach(cb => {
    cb.onchange = () => { const i = +cb.dataset.i; cb.checked ? gpSel.add(i) : gpSel.delete(i); };
  });
  const marcar = (v) => el.querySelectorAll("input[type=checkbox][data-i]").forEach(cb => {
    cb.checked = v; v ? gpSel.add(+cb.dataset.i) : gpSel.delete(+cb.dataset.i);
  });
  $("gpAll").onclick = () => marcar(true);
  $("gpNone").onclick = () => marcar(false);
  $("gpAplicar").onclick = () => {
    if (!gpSel.size) { setStatus("Marque ao menos um item para aplicar a garantia/prazo.", "aviso"); return; }
    const g = perItemGarantia ? ($("gpGarantia").value || "") : null;
    const p = perItemPrazo ? ($("gpPrazo").value || "") : null;
    gpSel.forEach(i => {
      if (g !== null) items[i].garantia = g;
      if (p !== null) items[i].prazo = p;
    });
    renderGPItens(); schedulePreview();
  };
}
/* ===========================================================================
   IMPOSTOS POR PRODUTO
   Numa mesma proposta o IPI muda de item para item, e serviço leva ISS onde
   mercadoria leva ICMS — por isso o imposto mora no PRODUTO, não na AF. Marcar
   os itens iguais e aplicar de uma vez resolve a proposta grande sem obrigar a
   digitar alíquota linha por linha.
   O preço "com impostos" e o total passam a ser CALCULADOS: era onde entrava o
   erro de conta feito na mão.
   =========================================================================== */
const IMPOSTOS_COMUNS = ["IPI", "ICMS", "ISS", "PIS", "COFINS", "ST", "Frete"];
// O que cada sigla é, em uma linha. Quem monta AF não é da área fiscal: saber
// que ISS é de serviço e ICMS é de mercadoria evita lançar o errado — e é a
// pergunta que se faz na hora, não depois.
const IMPOSTOS_INFO = {
  IPI: "Imposto sobre Produtos Industrializados — federal, incide sobre o produto industrializado. Aparece na nota do fabricante ou importador.",
  ICMS: "Imposto sobre Circulação de Mercadorias e Serviços — estadual, incide sobre a venda de MERCADORIA (e sobre transporte e comunicação). A alíquota muda por estado.",
  ISS: "Imposto Sobre Serviços — municipal, incide sobre PRESTAÇÃO DE SERVIÇO, não sobre mercadoria. Costuma ficar entre 2% e 5%.",
  PIS: "Programa de Integração Social — contribuição federal sobre a receita. No regime cumulativo, 0,65%.",
  COFINS: "Contribuição para o Financiamento da Seguridade Social — federal, sobre a receita. No regime cumulativo, 3%.",
  ST: "Substituição Tributária — o ICMS de toda a cadeia é recolhido de uma vez por um único contribuinte, normalmente o fabricante.",
  Frete: "Não é imposto: é o valor do transporte somado ao produto. Fica aqui porque entra na mesma conta do preço final.",
};
function descImposto(nome) {
  return IMPOSTOS_INFO[String(nome || "").trim().toUpperCase()] ||
         IMPOSTOS_INFO[String(nome || "").trim()] || "";
}
function dicaDosImpostos(it) {
  const l = impostosDe(it).filter(x => x.nome);
  if (!l.length) return "";
  return l.map(x => {
    const d = descImposto(x.nome);
    return `${x.nome}${x.aliq ? " " + x.aliq + "%" : ""}${d ? " — " + d : ""}`;
  }).join(String.fromCharCode(10, 10));   // uma linha em branco entre um imposto e outro
}
let impSel = new Set();          // itens marcados p/ receber a mesma alíquota
let impLinhas = [{ nome: "IPI", aliq: "" }];   // o que será aplicado

function impostosDe(it) { return Array.isArray(it.impostos) ? it.impostos : []; }
function somaAliq(it) {
  return impostosDe(it).reduce((s, x) => s + (parseBRL(x.aliq) || 0), 0);
}
function rotuloImpostos(it) {
  // a alíquota sai como foi digitada, só sem zero à toa: 2,5% (e não 2,50%),
  // igual ao que vai para o documento — duas grafias do mesmo número confundem
  const pct = (v) => String(v || "").trim().replace(/[.,]0+$/, "").replace(/^$/, "");
  return impostosDe(it).filter(x => x.nome || x.aliq)
    .map(x => `${x.nome || "imposto"} ${pct(x.aliq)}%`.replace(/\s+%/, "%").trim())
    .join(" · ");
}
// unit c/ impostos e total saem do unit SEM impostos + as alíquotas do item
/* A conta de UMA linha, sempre a mesma ordem:
     COM imposto:  unitário s/ imposto + alíquotas = unitário c/ imposto
     depois, nos dois casos:  unitário c/ imposto × QTD = total da linha
   E o valor do pedido é a soma dos totais de linha (ver somaItens).
   Antes só a metade "com imposto" era calculada: sem imposto, quem digitasse
   quantidade e preço unitário ficava com o total em branco e a soma não fechava. */
/* CALCULAR ligado/desligado.

   Nem toda proposta fecha na conta. Chega planilha com arredondamento próprio,
   desconto embutido numa linha só, unitário já com frete rateado — e aí o app
   "corrigir" o número é ATRAPALHAR: a AF tem de sair com o que o fornecedor
   escreveu, não com o que a aritmética diz. Desligado, nenhum campo é tocado;
   quem digita manda. A escolha fica guardada para a próxima abertura. */
const CALC_PREF = "autoaf:calcular";

function calcLigado() {
  const ck = $("ckCalcular");
  return !ck || ck.checked;        // sem o marcador na tela, calcula (padrão)
}

function toggleCalcular() {
  const on = calcLigado();
  try { localStorage.setItem(CALC_PREF, on ? "1" : "0"); } catch (e) {}
  document.body.classList.toggle("sem-calculo", !on);
  // religar recalcula tudo de uma vez: os valores digitados enquanto estava
  // desligado voltam a bater com a regra qtd x unitario
  if (on) items.forEach(recalcularItem);
  renderItems();
  atualizarValorTotal();
  schedulePreview();
  setStatus(on ? "Cálculo automático ligado — unitário c/ imposto e total são preenchidos pelo app."
               : "Cálculo automático desligado — os valores dos itens ficam como você digitar.", "ok");
}

function recalcularItem(it) {
  if (!calcLigado()) return;       // desligado: nao encosta em campo nenhum
  const q = parseBRL(it.quantidade);
  const semImp = parseBRL(it.preco_unit_sem);
  const temImp = impostosDe(it).length > 0;

  // 1. UNITÁRIO COM IMPOSTO
  if (semImp != null && temImp) {
    it.preco_unit_com = fmtBRL(semImp * (1 + somaAliq(it) / 100));
    it.ucAuto = true;
  } else if (semImp != null && !temImp && (it.ucAuto || !(it.preco_unit_com || "").trim())) {
    // Sem imposto, o unitário c/ imposto É o unitário s/ imposto.
    // `ucAuto` marca que este campo foi CALCULADO, não digitado: sem essa
    // marca, quem preenchia 100,00 e depois corrigia para 200,00 ficava com o
    // unitário c/ imposto parado em 100,00 (a regra antiga só preenchia
    // enquanto o campo estivesse vazio) e o total saía errado. Um valor
    // digitado à mão continua sendo respeitado.
    it.preco_unit_com = fmtBRL(semImp);
    it.ucAuto = true;
  }

  // 2. TOTAL DA LINHA = unitário c/ imposto × quantidade
  const unit = parseBRL(it.preco_unit_com) ?? semImp;
  if (unit != null && q) it.preco_total_com = fmtBRL(unit * q);
}
function toggleImpostos() {
  renderImpItens();
  schedulePreview();
}

/* ---------------------------------------------------------------- rubrica --
   ONDE a rubrica sai. O padrao e SO A ULTIMA FOLHA; "todas as folhas" e
   escolha explicita, porque muda o documento inteiro (no modo "todas" ele vira
   uma tabela com rodape repetido em cada pagina).

   A pergunta aparece ao MARCAR a caixa, ancorada nela. O modo escolhido fica
   visivel numa pastilha ao lado — o balao fecha, e sem a pastilha ninguem
   saberia o que ficou valendo nem como trocar.

   Quem guarda o modo e o interruptor escondido #ckRubTodas, nao uma variavel:
   assim ele entra sozinho na foto do rascunho e volta com a AF. */
function rubTodas() { const e = $("ckRubTodas"); return !!(e && e.checked); }

function pintarRubModo() {
  const chip = $("btnRubModo");
  if (!chip) return;
  const ligada = $("ckRubricas").checked;
  chip.hidden = !ligada;
  chip.textContent = rubTodas() ? "todas as folhas" : "última folha";
  // ao reabrir, a opcao em vigor tem de se ler de relance
  document.querySelectorAll("#rubPop .rub-op").forEach(b => {
    b.setAttribute("aria-pressed", (b.dataset.todas === "1") === rubTodas() ? "true" : "false");
  });
}

/* ------------------------------------------------- arrastar e soltar -----
   Soltar a proposta em qualquer ponto da janela.

   Duas armadilhas conhecidas deste recurso, as duas tratadas aqui:

   1. SEM `preventDefault` no `dragover`, o `drop` nunca acontece — e pior: o
      navegador ABRE o arquivo solto, trocando a página e levando junto tudo o
      que estava preenchido na AF. Por isso o `preventDefault` vale para a
      janela inteira, inclusive fora da área útil.

   2. `dragleave` dispara ao passar por CADA elemento filho. Escondendo a capa
      nele, ela pisca sem parar enquanto o arquivo atravessa a tela. O contador
      resolve: só some quando as saídas alcançam as entradas. */
const _EXT_PROPOSTA = /\.(pdf|xlsx|xlsm)$/i;

function ligarArrastar() {
  const capa = $("dropCapa");
  if (!capa) return;
  let dentro = 0;
  const temArquivo = ev => {
    const t = ev.dataTransfer && ev.dataTransfer.types;
    return !!t && [...t].includes("Files");
  };
  const fechar = () => { dentro = 0; capa.hidden = true; };

  window.addEventListener("dragenter", ev => {
    if (!temArquivo(ev)) return;
    ev.preventDefault();
    dentro++;
    capa.hidden = false;
  });
  window.addEventListener("dragover", ev => {
    if (!temArquivo(ev)) return;
    ev.preventDefault();
    ev.dataTransfer.dropEffect = "copy";
  });
  window.addEventListener("dragleave", ev => {
    if (!temArquivo(ev)) return;
    dentro = Math.max(0, dentro - 1);
    if (!dentro) capa.hidden = true;
  });
  window.addEventListener("drop", ev => {
    if (!temArquivo(ev)) return;
    ev.preventDefault();
    fechar();
    const todos = [...ev.dataTransfer.files];
    const aceitos = todos.filter(f => _EXT_PROPOSTA.test(f.name));
    if (!aceitos.length) {
      setStatus("Só leio proposta em PDF ou Excel (.pdf, .xlsx, .xlsm). "
                + "Recebi: " + todos.map(f => f.name).join(", "), "aviso");
      return;
    }
    if (aceitos.length < todos.length) {
      setStatus("Ignorei " + (todos.length - aceitos.length)
                + " arquivo(s) que não são proposta.", "aviso");
    }
    lerProposta(aceitos);
  });
  // arrastar para fora da janela não deixa a capa presa na tela
  window.addEventListener("blur", fechar);
  document.addEventListener("visibilitychange", () => { if (document.hidden) fechar(); });
}

function abrirRubPop() { const p = $("rubPop"); if (p) p.hidden = false; }
function fecharRubPop() { const p = $("rubPop"); if (p) p.hidden = true; }

function ligarRubrica() {
  const pop = $("rubPop");
  if (!pop) return;
  pop.querySelectorAll(".rub-op").forEach(b => {
    b.onclick = () => {
      $("ckRubTodas").checked = b.dataset.todas === "1";
      fecharRubPop();
      pintarRubModo();
      schedulePreview();
    };
  });
  $("btnRubModo").onclick = () => {
    if ($("rubPop").hidden) abrirRubPop(); else fecharRubPop();
  };
  // fechar clicando fora e no Esc: um balao que so fecha escolhendo prende a
  // pessoa numa decisao que ela ja tomou (o padrao vale se ela nao mexer)
  document.addEventListener("click", ev => {
    const dentro = ev.target.closest(".rub-wrap");
    if (!dentro) fecharRubPop();
  });
  document.addEventListener("keydown", ev => {
    if (ev.key === "Escape" && !$("rubPop").hidden) fecharRubPop();
  });
  pintarRubModo();
}
function renderImpItens() {
  const el = $("impItens"), ativo = $("ckImpostos").checked;
  el.hidden = !ativo;
  if (!ativo) return;
  impSel = new Set([...impSel].filter(i => i < items.length));
  // O campo do imposto era um input com datalist: sem seta, ninguém via que
  // havia opções nem conseguia TROCAR de imposto. Vira cortina de verdade, com
  // "Outro…" para o que não está na lista.
  const cortina = (x, n) => {
    const nomes = [...IMPOSTOS_COMUNS];
    if (x.nome && !nomes.includes(x.nome)) nomes.unshift(x.nome);   // nome digitado antes
    const dica = descImposto(x.nome) || "Escolha o imposto — passe o mouse para ver o que cada um é.";
    return `<select class="imp-nome" data-n="${n}" title="${escapeAttr(dica)}">` +
      `<option value=""${!x.nome ? " selected" : ""}>— escolha o imposto —</option>` +
      nomes.map(nm => `<option${nm === x.nome ? " selected" : ""} title="${escapeAttr(descImposto(nm))}">${escapeHtml(nm)}</option>`).join("") +
      `<option value="__outro">Outro…</option></select>`;
  };
  const livre = (x, n) =>
    `<div class="imp-livre"><input class="imp-nome-livre" data-n="${n}" placeholder="nome do imposto"` +
    ` value="${escapeAttr(x.nome || "")}" autofocus>` +
    `<button type="button" class="imp-volta" data-volta="${n}" title="Voltar para a lista">☰</button></div>`;
  const linhas = impLinhas.map((x, n) => {
    const a = parseBRL(x.aliq);
    return `
    <div class="imp-linha${a != null && a > 100 ? " alto" : ""}">
      ${x.livre ? livre(x, n) : cortina(x, n)}
      <div class="imp-pct"><input class="imp-aliq" data-n="${n}" inputmode="decimal" placeholder="0,00" value="${escapeAttr(x.aliq || "")}"><span>%</span></div>
      <button type="button" class="imp-del" data-n="${n}" title="Tirar este imposto da lista">✕</button>
    </div>`;
  }).join("");
  // alíquota absurda é quase sempre dígito a mais (204% no lugar de 20,4%)
  const altas = impLinhas.filter(x => (parseBRL(x.aliq) || 0) > 100);
  const aviso = altas.length
    ? `<div class="imp-aviso">⚠ ${escapeHtml(altas.map(x => (x.nome || "imposto") + " " + x.aliq + "%").join(", "))} — alíquota acima de 100%. Confira a vírgula.</div>`
    : "";
  const comImposto = items.filter(it => impostosDe(it).length).length;

  el.innerHTML =
    `<div class="gp-h">Impostos por produto</div>` +
    `<div class="imp-passo"><b>1.</b> Quais impostos e quanto</div>` +
    `<div class="imp-linhas">${linhas}</div>${aviso}` +
    `<button type="button" class="btn ghost sm imp-mais" id="impAdd">＋ outro imposto</button>` +
    `<div class="imp-passo"><b>2.</b> Em quais produtos` +
    `<span class="imp-conta">${impSel.size} marcado(s) · ${comImposto} com imposto</span></div>` +
    `<div class="imp-tools">` +
      `<button type="button" class="btn ghost sm" id="impAll">Marcar todos</button>` +
      `<button type="button" class="btn ghost sm" id="impNone">Desmarcar todos</button>` +
    `</div>` +
    `<div class="imp-lista">` + items.map((it, i) => {
      const cur = rotuloImpostos(it), tem = impostosDe(it).length > 0;
      const marcado = impSel.has(i);
      const vazio = !(it.codigo || it.descricao || it.preco_unit_sem);
      const nome = it.codigo || it.descricao || (vazio ? "(linha em branco)" : "item");
      // o EFEITO da conta, à vista: o que vai virar o unitário c/ imposto e o
      // total daquela linha. Antes só dava para ver depois de aplicar e voltar
      // à tabela — agora a pessoa confere antes.
      const efeito = (() => {
        const base = parseBRL(it.preco_unit_sem), qt = parseBRL(it.quantidade);
        if (base == null) return "";
        const u = base * (1 + somaAliq(it) / 100);
        const uu = parseBRL(fmtBRL(u));                   // como será impresso
        return `<span class="imp-efeito">${fmtBRL(u)}${qt ? ` × ${it.quantidade} = <b>${fmtBRL(uu * qt)}</b>` : ""}</span>`;
      })();
      return `<div class="imp-item${marcado ? " sel" : ""}${vazio ? " vazio" : ""}">` +
        `<label class="imp-marca"><input type="checkbox" data-i="${i}"${marcado ? " checked" : ""}>` +
        `<span class="imp-n">${i + 1}</span>` +
        `<span class="imp-nomeit">${escapeHtml(nome)}</span></label>` +
        efeito +
        (tem ? `<span class="imp-chip" title="${escapeAttr(dicaDosImpostos(it))}">${escapeHtml(cur)}` +
               `<button type="button" class="imp-tira" data-tira="${i}" title="Tirar os impostos deste produto">✕</button></span>`
             : `<span class="imp-sem">sem imposto</span>`) +
        `</div>`;
    }).join("") + `</div>` +
    `<div class="imp-acoes">` +
      `<button type="button" class="btn primary imp-aplicar" id="impAplicar">Aplicar aos ${impSel.size} marcado(s)</button>` +
      `<button type="button" class="btn soft" id="impTodos" title="Mesmo imposto em todos os produtos da AF">Aplicar a todos</button>` +
      `<button type="button" class="btn ghost" id="impLimpar"${comImposto ? "" : " disabled"}` +
        ` title="Tirar o imposto de TODOS os produtos de uma vez">Limpar impostos${comImposto ? ` (${comImposto})` : ""}</button>` +
    `</div>`;

  el.querySelectorAll("select.imp-nome").forEach(sel => {
    sel.onchange = () => {
      const n = +sel.dataset.n;
      if (sel.value === "__outro") {          // digitar um imposto fora da lista
        impLinhas[n].livre = true;
        impLinhas[n].nome = "";
      } else {
        impLinhas[n].nome = sel.value;
      }
      renderImpItens();
    };
  });
  el.querySelectorAll(".imp-nome-livre").forEach(inp => {
    inp.oninput = () => { impLinhas[+inp.dataset.n].nome = inp.value; atualizarBotaoImp(); };
  });
  el.querySelectorAll("[data-volta]").forEach(b => {
    b.onclick = () => {                       // volta da digitação livre para a lista
      const n = +b.dataset.volta;
      impLinhas[n].livre = false;
      renderImpItens();
    };
  });
  const focoLivre = el.querySelector(".imp-nome-livre[value='']");
  if (focoLivre) focoLivre.focus();
  el.querySelectorAll(".imp-aliq").forEach(inp => {
    inp.oninput = () => { impLinhas[+inp.dataset.n].aliq = inp.value; atualizarBotaoImp(); };
    inp.onblur = () => renderImpItens();          // reavalia o aviso de alíquota alta
  });
  el.querySelectorAll(".imp-del").forEach(b => {
    b.onclick = () => {
      impLinhas.splice(+b.dataset.n, 1);
      if (!impLinhas.length) impLinhas.push({ nome: "", aliq: "" });
      renderImpItens();
    };
  });
  // ✕ no chip: tira o imposto DAQUELE produto na hora — é o que se espera ao
  // querer desfazer, e não depende de marcar/aplicar de novo
  el.querySelectorAll("[data-tira]").forEach(b => {
    b.onclick = () => {
      items[+b.dataset.tira].impostos = [];
      renderItems(); renderImpItens(); atualizarValorTotal(); schedulePreview();
    };
  });
  el.querySelectorAll("input[type=checkbox][data-i]").forEach(cb => {
    cb.onchange = () => {
      const i = +cb.dataset.i;
      cb.checked ? impSel.add(i) : impSel.delete(i);
      cb.closest(".imp-item").classList.toggle("sel", cb.checked);
      atualizarBotaoImp();
    };
  });
  const marcar = (v) => {
    el.querySelectorAll("input[type=checkbox][data-i]").forEach(cb => {
      cb.checked = v; v ? impSel.add(+cb.dataset.i) : impSel.delete(+cb.dataset.i);
      cb.closest(".imp-item").classList.toggle("sel", v);
    });
    atualizarBotaoImp();
  };
  $("impAdd").onclick = () => { impLinhas.push({ nome: "", aliq: "" }); renderImpItens(); };
  $("impAll").onclick = () => marcar(true);
  $("impNone").onclick = () => marcar(false);
  const aplicarEm = (indices) => {
    const val = impLinhas.filter(x => (x.nome || "").trim() && parseBRL(x.aliq) != null)
                         .map(x => ({ nome: x.nome.trim(), aliq: x.aliq }));
    if (!val.length) { setStatus("Informe o nome e a alíquota do imposto (ex.: IPI 5).", "aviso"); return; }
    // linha em branco no fim da grade não recebe imposto: não é produto
    const alvos = indices.filter(i => (items[i].codigo || items[i].descricao || items[i].preco_unit_sem));
    if (!alvos.length) { setStatus("Não há produto preenchido para receber o imposto.", "aviso"); return; }
    let semBase = 0;
    alvos.forEach(i => {
      items[i].impostos = val.map(x => ({ ...x }));
      if (parseBRL(items[i].preco_unit_sem) == null) semBase++;
      recalcularItem(items[i]);
    });
    renderItems(); renderImpItens(); atualizarValorTotal(); schedulePreview();
    setStatus(semBase
      ? `Impostos aplicados a ${alvos.length} produto(s) — ${semBase} sem preço unitário sem impostos, então o preço com impostos não pôde ser calculado.`
      : `Impostos aplicados a ${alvos.length} produto(s): ${val.map(x => x.nome + " " + x.aliq + "%").join(" · ")}.`,
      semBase ? "aviso" : "ok");
  };
  $("impAplicar").onclick = () => {
    if (!impSel.size) { setStatus("Marque os produtos que vão receber estes impostos.", "aviso"); return; }
    aplicarEm([...impSel]);
  };
  $("impTodos").onclick = () => aplicarEm(items.map((_, i) => i));
  // Tirar o imposto de TUDO de uma vez. O ✕ da etiqueta resolve um produto; sem
  // este botão, desfazer uma aplicação errada em 16 itens era clicar 16 vezes.
  $("impLimpar").onclick = () => {
    const n = items.filter(it => impostosDe(it).length).length;
    if (!n) return;
    if (!confirm(`Tirar os impostos de ${n} produto(s)? Os preços voltam ao valor sem imposto.`)) return;
    items.forEach(it => { it.impostos = []; recalcularItem(it); });
    renderItems(); renderImpItens(); atualizarValorTotal(); schedulePreview();
    setStatus(`Impostos removidos de ${n} produto(s).`, "ok");
  };
  atualizarBotaoImp();
}
// só o rótulo do botão e o contador — re-render inteiro a cada clique tirava o
// foco de quem estava digitando a alíquota
function atualizarBotaoImp() {
  const b = $("impAplicar"), c = document.querySelector(".imp-conta");
  if (b) {
    b.textContent = `Aplicar aos ${impSel.size} marcado(s)`;
    b.disabled = !impSel.size;
  }
  if (c) {
    const comImposto = items.filter(it => impostosDe(it).length).length;
    c.textContent = `${impSel.size} marcado(s) · ${comImposto} com imposto`;
  }
}

// Resumo p/ o campo único do documento, AGRUPANDO itens por valor:
// "Itens 1, 2 e 4 têm 5 Anos; Itens 3 e 5 têm 2 Anos". Todos iguais → só o valor.
function _listaNums(nums) {
  return nums.length === 1 ? `${nums[0]}`
    : nums.slice(0, -1).join(", ") + " e " + nums[nums.length - 1];
}
function gpResumo(campo) {
  const grupos = new Map();   // valor → [nº do item]
  items.forEach((it, i) => {
    const v = (it[campo] || "").trim();
    if (!v) return;
    if (!grupos.has(v)) grupos.set(v, []);
    grupos.get(v).push(i + 1);
  });
  if (!grupos.size) return "";
  if (grupos.size === 1) {
    const [v, nums] = [...grupos][0];
    if (nums.length === items.length) return v;   // todos iguais → só o valor
  }
  return [...grupos].map(([v, nums]) =>
    (nums.length === 1 ? `Item ${nums[0]} tem` : `Itens ${_listaNums(nums)} têm`) + ` ${v}`
  ).join("; ");
}

// Objeto = resumo BREVE e legível: junta as descrições DISTINTAS dos itens
// (primeiras palavras de cada uma) → melhor entendimento sem ficar gigante.
function resumoItens() {
  const tipos = [];
  for (const it of items) {
    const desc = (it.descricao || it.codigo || "").trim().replace(/\s+/g, " ");
    if (!desc) continue;
    const curto = desc.split(" ").slice(0, 6).join(" ");   // até 6 primeiras palavras de cada item
    if (!tipos.some(t => t.toLowerCase() === curto.toLowerCase())) tipos.push(curto);
  }
  if (!tipos.length) return "";
  const txt = "Fornecimento de " + tipos.join("; ");
  return txt.length > 200 ? txt.slice(0, 197) + "…" : txt;
}

// Valor total = soma do TOTAL (c/ impostos) de cada item.
function parseBRL(s) {
  s = String(s == null ? "" : s).replace(/[^\d,.-]/g, "");
  if (!s) return null;
  if (s.includes(",")) s = s.replace(/\./g, "").replace(",", ".");
  const v = parseFloat(s);
  return isNaN(v) ? null : v;
}
function fmtBRL(v) { return v.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
function somaItens() {
  let total = 0, achou = false;
  for (const it of items) {
    let v = parseBRL(it.preco_total_com);
    if (v == null) {                                   // sem total → unit × qtd
      const u = parseBRL(it.preco_unit_com) ?? parseBRL(it.preco_unit_sem), q = parseBRL(it.quantidade);
      if (u != null && q) v = u * q;
    }
    if (v != null) { total += v; achou = true; }
  }
  return achou ? fmtBRL(total) : "";
}
/* O que a proposta cobra ALÉM das linhas (frete, seguro, desconto).
   Fica guardado ao ler a proposta e é somado de volta a cada recálculo: sem
   isto, editar uma quantidade fazia a soma das linhas apagar o frete de
   R$ 14.938,50 que a proposta cobrava, e a AF saía barata demais. */
let extraDaProposta = 0;

function atualizarValorTotal() {
  if (!calcLigado()) return;       // o valor total tambem e digitado a mao
  const s = parseBRL(somaItens());
  if (s == null) return;
  $("valor").value = fmtBRL(s + extraDaProposta);
}

/* O total da PROPOSTA x a soma das LINHAS.
   Não são a mesma coisa: frete, seguro e desconto costumam ficar fora da tabela
   de itens. Quando o fornecedor declarou um total, ele vale — a soma das linhas
   é só uma conferência. A diferença é dita em voz alta, porque é exatamente o
   tipo de coisa que ninguém confere e vai assinada na AF. */
function conciliarValorTotal(daProposta) {
  const total = parseBRL(daProposta), soma = parseBRL(somaItens());
  if (total == null) {                    // proposta sem total: a soma é o que há
    extraDaProposta = 0;
    atualizarValorTotal();
    return;
  }
  $("valor").value = daProposta;
  if (soma == null || Math.abs(total - soma) < 0.01) { extraDaProposta = 0; return; }
  const dif = total - soma;
  extraDaProposta = dif;                  // acompanha as edições seguintes
  setStatus(`Atenção: a proposta declara ${fmtBRL(total)} e a soma dos itens dá ${fmtBRL(soma)} ` +
    `(${dif > 0 ? "+" : "−"} ${fmtBRL(Math.abs(dif))}). Usei o total da proposta. ` +
    `A diferença costuma ser frete ou desconto fora da tabela — confira antes de gerar.`, "aviso");
}

/* Fornecedor que não está no texto do PDF.
   Em proposta cujo cabeçalho é uma IMAGEM (logotipo), nome e CNPJ simplesmente
   não existem como texto — não há o que extrair. Antes o campo ficava em branco
   e parecia que o cadastro tinha falhado; agora o app diz o que houve e o que
   fazer. */
function avisarFornecedorNaoIdentificado(p) {
  if ((p.fornecedor || "").trim() || (p.cnpj || "").trim()) return;   // veio algo, só não casou
  setStatus("Não achei o nome nem o CNPJ do fornecedor no texto desta proposta — " +
    "o cabeçalho dela é imagem (logotipo), e imagem não tem texto para ler. " +
    "Escolha o fornecedor na busca do catálogo que o resto é preenchido.", "aviso");
  const busca = $("catBusca");
  if (busca) busca.focus();
}

// ---------------------------------------------------- locais (vários) -----
// PREFERÊNCIA por estado (sem bloquear): ao escolher um faturamento, os POPs do
// mesmo estado sobem para o topo da lista — e vice-versa. Tudo continua
// selecionável (qualquer estado), só fica priorizado e mais rápido de achar.
function _ufsDe(arr) { return new Set(arr.map(x => x.uf).filter(Boolean)); }
// ------------------------------------------------- busca de locais (autocomplete)
// Antes era um <select> filtrado: o filtro FUNCIONAVA, mas como a lista fica
// fechada o usuário não via nada acontecer. Agora as sugestões aparecem embaixo
// da caixa, como numa busca comum: digita → escolhe → Enter/Adicionar. O foco
// PERMANECE na caixa p/ incluir vários seguidos; sai só ao clicar fora ou Esc.
const _AC = {
  fat: { inp: "fatBusca", lista: "fatLista", idx: 0, itens: [] },
  ent: { inp: "entBusca", lista: "entLista", idx: 0, itens: [] },
};

// Relevância: quem digita "SP" quer o SP4 Data Center, não os 40 POPs do estado
// de São Paulo. Quanto MENOR a nota, mais alto na lista; -1 é "não casa".
function _nota(c, q, ufPrimeiro) {
  const sig = _semAcento(c.sigla), nome = _semAcento(c.nome), mun = _semAcento(c.municipio);
  // Nas FILIAIS a razão social é a mesma em todas ("ELETRONET S.A - FILIAL"), então
  // a UF é o único diferenciador e tem de vir na frente. Sem isto, procurar "RO"
  // trazia AC/AL/AM antes de Rondônia — porque "eletronet" contém "ro".
  if (ufPrimeiro && _semAcento(c.uf) === q) return 0;
  const inicioDePalavra = t => new RegExp("(^|[\\s(\\-/])" + q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).test(t);
  if (sig && sig === q) return 0;                                    // sigla exata
  if (sig && sig.startsWith(q)) return 1;                            // sigla começa com
  if (nome.startsWith(q) || mun.startsWith(q)) return 2;             // nome/município começa com
  if (inicioDePalavra(nome) || inicioDePalavra(mun)) return 3;       // começo de qualquer palavra
  if (nome.includes(q) || mun.includes(q) || (sig && sig.includes(q))) return 4;   // no meio
  if (_semAcento(c.uf) === q) return 5;                              // só o estado: por último
  return -1;
}
function _acItens(qual) {
  const q = _semAcento(($(_AC[qual].inp) || {}).value || "");
  const arr = qual === "fat" ? DATA.faturamento : DATA.pops;
  const rot = qual === "fat"
    ? l => `${l.uf} — ${l.razao_social}`
    : p => p.sigla ? `${p.nome} (${p.sigla}) — ${p.municipio}/${p.uf}` : `${p.nome} — ${p.municipio}/${p.uf}`;
  const campos = qual === "fat"
    ? l => ({ sigla: "", nome: l.razao_social || "", municipio: "", uf: l.uf || "" })
    : p => ({ sigla: p.sigla || "", nome: p.nome || "", municipio: p.municipio || "", uf: p.uf || "" });
  const prefUF = qual === "fat" ? _ufsDe(entregas) : _ufsDe(faturamentos);
  // o que já virou chip SAI da cortina: não adianta oferecer de novo, o app
  // recusaria a duplicata e a lista só ficaria mais longa
  const jaTem = qual === "fat"
    ? x => faturamentos.some(f => f.razao_social === x.razao_social && f.uf === x.uf)
    : x => entregas.some(e => e.nome === x.nome && e.sigla === x.sigla && e.municipio === x.municipio);
  let itens = arr.map((x, i) => ({ i, uf: x.uf || "", txt: rot(x), c: campos(x) }))    // i = índice ORIGINAL
                 .filter(o => !jaTem(arr[o.i]));
  if (q) {
    itens = itens.map(o => Object.assign(o, { n: _nota(o.c, q, qual === "fat") })).filter(o => o.n >= 0);
    // nota, depois o estado que já está na AF, depois alfabético
    itens.sort((a, b) => a.n - b.n || (prefUF.has(b.uf) - prefUF.has(a.uf)) || a.txt.localeCompare(b.txt, "pt-BR"));
    return itens.slice(0, 40);
  }
  // sem busca: do mesmo estado primeiro (mesma regra de antes), depois o resto
  const pref = itens.filter(o => prefUF.has(o.uf)), resto = itens.filter(o => !prefUF.has(o.uf));
  return [...pref, ...resto].slice(0, 40);
}

function acRender(qual) {
  const st = _AC[qual], lista = $(st.lista);
  if (!lista) return;
  st.itens = _acItens(qual);
  if (st.idx >= st.itens.length) st.idx = 0;
  if (!st.itens.length) {
    lista.innerHTML = '<div class="ac-vazio">nada encontrado</div>';
  } else {
    lista.innerHTML = st.itens.map((o, n) =>
      `<div class="ac-item${n === st.idx ? " sel" : ""}" data-n="${n}">${escapeHtml(o.txt)}</div>`).join("");
  }
  lista.hidden = false;
  const sel = lista.querySelector(".ac-item.sel");
  if (sel) sel.scrollIntoView({ block: "nearest" });
}

function acFechar(qual) { const l = $(_AC[qual].lista); if (l) l.hidden = true; }

function acEscolher(qual) {
  const st = _AC[qual], o = st.itens[st.idx];
  if (!o) return;
  (qual === "fat" ? addFaturamento : addEntrega)(o.i);
  $(st.inp).value = "";        // limpa p/ a próxima busca
  st.idx = 0;
  $(st.inp).focus();           // continua na caixa: dá p/ incluir vários seguidos
  acRender(qual);
}

function bindAC(qual) {
  const st = _AC[qual], inp = $(st.inp), lista = $(st.lista);
  if (!inp) return;
  inp.oninput = () => { st.idx = 0; acRender(qual); };
  inp.onfocus = () => acRender(qual);
  inp.onkeydown = (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); st.idx = Math.min(st.idx + 1, st.itens.length - 1); acRender(qual); }
    else if (e.key === "ArrowUp") { e.preventDefault(); st.idx = Math.max(st.idx - 1, 0); acRender(qual); }
    else if (e.key === "Enter") { e.preventDefault(); acEscolher(qual); }
    else if (e.key === "Escape") { acFechar(qual); inp.blur(); }
  };
  lista.onmousedown = (e) => {          // mousedown: age antes do blur fechar a lista
    const it = e.target.closest(".ac-item");
    if (!it) return;
    e.preventDefault();
    st.idx = +it.dataset.n;
    acEscolher(qual);
  };
  inp.onblur = () => setTimeout(() => acFechar(qual), 120);   // sai ao clicar fora
}

function atualizarPreferencias() {      // mantém o nome: é chamado de vários pontos
  ["fat", "ent"].forEach(q => { if (!$(_AC[q].lista).hidden) acRender(q); });
}

function _semAcento(t) {
  return (t || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().trim();
}
function addFaturamento(i) {          // i = índice ORIGINAL em DATA.faturamento
  if (!DATA || !(i >= 0)) return;
  const f = DATA.faturamento[i];
  if (!faturamentos.some(x => x.razao_social === f.razao_social && x.uf === f.uf)) {
    faturamentos.push(f); renderFaturamentos();
  }
  atualizarPreferencias();   // POPs do mesmo estado sobem ao topo (sem bloquear)
  schedulePreview();
}
function addEntrega(i) {              // i = índice ORIGINAL em DATA.pops
  if (!DATA || !(i >= 0)) return;
  const p = DATA.pops[i];
  if (!entregas.some(x => x.nome === p.nome && x.sigla === p.sigla && x.municipio === p.municipio)) {
    entregas.push(p); renderEntregas();
  }
  atualizarPreferencias();   // filiais do mesmo estado sobem ao topo (sem bloquear)
  schedulePreview();
}
function renderFaturamentos() {
  $("fatList").innerHTML = faturamentos.map((f, i) =>
    `<span class="chip">${escapeHtml(`${f.uf} — ${f.razao_social}`)}` +
    `<button class="chipx" data-delfat="${i}">✕</button></span>`).join("") ||
    '<span class="muted">Nenhum faturamento adicionado.</span>';
  $("fatList").onclick = (e) => {
    const d = e.target.dataset.delfat;
    if (d !== undefined) { faturamentos.splice(+d, 1); renderFaturamentos(); atualizarPreferencias(); schedulePreview(); }
  };
}
function renderEntregas() {
  $("entList").innerHTML = entregas.map((p, i) =>
    `<span class="chip">${escapeHtml(p.sigla ? `${p.nome} (${p.sigla}) — ${p.municipio}/${p.uf}` : `${p.nome} — ${p.municipio}/${p.uf}`)}` +
    `<button class="chipx" data-delent="${i}">✕</button></span>`).join("") ||
    '<span class="muted">Nenhum local de entrega adicionado.</span>';
  $("entList").onclick = (e) => {
    const d = e.target.dataset.delent;
    if (d !== undefined) { entregas.splice(+d, 1); renderEntregas(); atualizarPreferencias(); schedulePreview(); }
  };
}

function bindForm() {
  bindAssinantesAF();
  $("btnLimparAF").onclick = () => limparAF();
  const col = document.querySelector(".form-col");
  col.addEventListener("input", schedulePreview);
  col.addEventListener("change", schedulePreview);
  col.addEventListener("input", atualizarIdPrev);
  col.addEventListener("change", atualizarIdPrev);
  $("catalogo").addEventListener("change", onCatalogo);
  bindCatalogoBusca();
  bindConferenciaAF();
  atualizarIdPrev();

  // Barra de etapas: dá uma rota curta para as partes longas do formulário e
  // também mostra em qual bloco a pessoa está digitando. Não altera campo nem
  // o payload enviado ao Python; só guia a navegação na coluna rolável.
  const passos = [...document.querySelectorAll(".form-steps [data-jump]")];
  const marcarPasso = (id) => passos.forEach(b => b.classList.toggle("active", b.dataset.jump === id));
  passos.forEach(btn => {
    btn.onclick = () => {
      const alvo = $(btn.dataset.jump);
      if (!alvo) return;
      marcarPasso(btn.dataset.jump);
      alvo.scrollIntoView({ behavior: "smooth", block: "start" });
    };
  });
  col.addEventListener("focusin", (e) => {
    const card = e.target.closest(".card[id]");
    if (!card) return;
    const passo = passos.find(b => b.dataset.jump === card.id);
    if (passo) marcarPasso(card.id);
  });
}

function onCatalogo() {
  const i = +$("catalogo").value;
  refletirCatalogo();
  if (!DATA || i < 0) return;
  const f = DATA.fornecedores[i];
  $("fornecedor").value = f.empresa; $("cnpj").value = f.cnpj; $("ie").value = f.insc_est;
  $("endereco").value = f.endereco; $("cep").value = f.cep;
  if (f.garantia) setDur("garantia", f.garantia, "Meses");
  dica("cnpj", ""); dica("cep", "");     // veio do catálogo: não é digitação
  atualizarIdPrev();
  schedulePreview();
}

/* --------------------------------------------- catálogo: busca no lugar da
   cortina. Com 22 fornecedores (e crescendo) percorrer o <select> item a item
   era o passo mais lento do formulário. O <select> segue existindo — escondido
   — porque é o índice dele que o resto do app lê e escreve. ------------- */
const _CAT = { idx: 0, itens: [] };
function _catItens() {
  if (!DATA) return [];
  const q = _semAcento(val("catBusca")), qd = q.replace(/\D/g, "");
  let arr = DATA.fornecedores.map((f, i) => ({ i, f }));
  if (q) {
    arr = arr.filter(o => {
      const ap = _semAcento(o.f.apelido), em = _semAcento(o.f.empresa);
      const cn = (o.f.cnpj || "").replace(/\D/g, "");
      return ap.includes(q) || em.includes(q) || (qd.length >= 3 && cn.includes(qd));
    });
    const nota = o => _semAcento(o.f.apelido).startsWith(q) ? 0
                    : _semAcento(o.f.empresa).startsWith(q) ? 1 : 2;
    arr.sort((a, b) => nota(a) - nota(b) ||
      (a.f.apelido || a.f.empresa || "").localeCompare(b.f.apelido || b.f.empresa || "", "pt-BR"));
  }
  return arr.slice(0, 40);
}
function catRender() {
  const lista = $("catLista");
  _CAT.itens = _catItens();
  if (_CAT.idx >= _CAT.itens.length) _CAT.idx = 0;
  lista.innerHTML = _CAT.itens.length
    ? _CAT.itens.map((o, n) => {
        const t = o.f.apelido ? `${o.f.apelido} — ${o.f.empresa}` : (o.f.empresa || "(sem nome)");
        const sub = o.f.cnpj ? `<span class="ac-sub">${escapeHtml(o.f.cnpj)}</span>` : "";
        return `<div class="ac-item${n === _CAT.idx ? " sel" : ""}" data-n="${n}">${escapeHtml(t)} ${sub}</div>`;
      }).join("")
    : '<div class="ac-vazio">nenhum fornecedor com esse nome — preencha os campos à mão ou cadastre em Cadastros</div>';
  lista.hidden = false;
  const sel = lista.querySelector(".ac-item.sel");
  if (sel) sel.scrollIntoView({ block: "nearest" });
}
function catEscolher() {
  const o = _CAT.itens[_CAT.idx];
  if (!o) return;
  $("catalogo").value = o.i;
  $("catBusca").value = "";
  $("catLista").hidden = true;
  onCatalogo();
}
// mostra QUAL fornecedor do catálogo está preso ao formulário no momento
function refletirCatalogo() {
  const marca = $("catMarca");
  if (!marca) return;
  const i = +$("catalogo").value;
  if (!DATA || !(i >= 0)) { marca.hidden = true; return; }
  const f = DATA.fornecedores[i];
  $("catMarcaNome").textContent = f.apelido ? `${f.apelido} — ${f.empresa}` : f.empresa;
  marca.hidden = false;
}
function bindCatalogoBusca() {
  const inp = $("catBusca"), lista = $("catLista");
  if (!inp) return;
  inp.oninput = () => { _CAT.idx = 0; catRender(); };
  inp.onfocus = () => catRender();
  inp.onkeydown = (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); _CAT.idx = Math.min(_CAT.idx + 1, _CAT.itens.length - 1); catRender(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); _CAT.idx = Math.max(_CAT.idx - 1, 0); catRender(); }
    else if (e.key === "Enter") { e.preventDefault(); catEscolher(); }
    else if (e.key === "Escape") { lista.hidden = true; inp.blur(); }
  };
  lista.onmousedown = (e) => {
    const it = e.target.closest(".ac-item");
    if (!it) return;
    e.preventDefault();
    _CAT.idx = +it.dataset.n;
    catEscolher();
  };
  inp.onblur = () => setTimeout(() => { lista.hidden = true; }, 120);
  // ✕ solta do catálogo sem apagar o que já foi preenchido
  $("catMarcaX").onclick = () => { $("catalogo").value = "-1"; refletirCatalogo(); };
  refletirCatalogo();
}

// mesma conferência da aba Cadastros, agora no formulário da AF
function bindConferenciaAF() {
  $("cnpj").onblur = () => {
    const v = val("cnpj").trim();
    if (!v) { dica("cnpj", ""); return; }
    $("cnpj").value = fmtCNPJ(v);
    const d = soDig(v);
    if (d.length !== 14) dica("cnpj", `CNPJ tem 14 dígitos — este tem ${d.length}.`, "ruim");
    else if (!cnpjValido(v)) dica("cnpj", "Os dígitos verificadores não fecham — confira o número.", "ruim");
    else dica("cnpj", "");
  };
  $("cep").onblur = () => {
    const v = val("cep").trim();
    if (!v) { dica("cep", ""); return; }
    $("cep").value = fmtCEP(v);
    const d = soDig(v);
    if (d.length !== 8) dica("cep", `CEP tem 8 dígitos — este tem ${d.length}.`, "ruim");
    else dica("cep", "");
  };
}

// Identificador e nome do arquivo montados ao vivo — mesma regra do gerar().
function atualizarIdPrev() {
  const doc = $("idPrevDoc");
  if (!doc) return;
  const numero = val("numero").trim(), ano = val("ano").trim();
  const rev = (val("rev") || "").trim(), revP = (rev && rev !== "0") ? `-REV${rev}` : "";
  doc.textContent = `${val("prefixo")}-${numero || "___"}/${ano}${modSufixo("-")}${revP}`;
  const forn = val("fornecedor").split(/[ /-]/)[0] || "FORNECEDOR";
  // sem número não há nome de arquivo — e o gerar() também não deixa passar
  $("idPrevArq").textContent = numero
    ? `${val("prefixo")}-${numero}_${ano}${modSufixo("_")}${revP}_${forn}.pdf`
    : "falta o número";
  $("idPrevArq").classList.toggle("vazio", !numero);
}

// ---------------------------------------- duração (número + unidade) ------
// Garantia/Prazo viram NÚMERO + cortina (Dias/Meses/Anos). Lê textos como
// "12 meses" / "45 dias" / "2 anos" e devolve "12 Meses" para o documento.
/* A frase é ESSENCIALMENTE "N unidade"? Tirando o número, a unidade e as
   palavras de ligação ("de", "até", "úteis", "corridos"), sobra alguma coisa
   com significado? Se sobra, o par número+unidade não representa a frase e o
   campo tem de ir inteiro para o modo LIVRE.
   Sem isto, "90 dias após a assinatura do documento de contratação" virava
   "90 Dias" e "item 1: 3 unidades a pronta entrega, as demais dia 22/09"
   virava "Pronta-entrega" — o documento prometendo o que ninguém prometeu. */
function soDuracao(str, m) {
  const resto = String(str || "")
    .replace(m[0], " ")
    .replace(/\b(de|até|ate|em|no|na|aprox(imadamente)?|cerca|uteis|úteis|corridos|corridas|prazo|entrega)\b/gi, " ")
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim();
  return resto.length < 3;
}
function splitDur(str) {
  const s = String(str || "");
  // "Pronta-entrega" só vale se a frase for ISSO — e não se apenas contiver a
  // expressão no meio de um texto que fala de entregas parciais.
  if (/pronta[\s-]*entrega/i.test(s)) {
    const limpo = s.replace(/[^\p{L}\p{N}]+/gu, " ").trim();
    if (/^(a\s+)?pronta\s*entrega$/i.test(limpo)) return { num: "", un: "Pronta-entrega" };
    return { num: "", un: "" };            // texto maior: vai para o modo livre
  }
  // A UNIDADE é obrigatória. Com ela opcional, o primeiro número de um texto
  // corrido virava a duração: "O período de garantia será de 5 (cinco) anos a
  // contar da notificação de conclusão da obra" saía como 5 + a unidade padrão
  // do campo, ou seja "5 Meses" — cinco anos viraram cinco meses no documento.
  // Sem unidade colada ao número, o texto inteiro vai para a opção "Livre".
  const m = s.match(/(\d+(?:[.,]\d+)?)\s*(dias?|m[eê]s(?:es)?|anos?)\b/i);
  if (!m) return { num: "", un: "" };
  // o par só representa a frase quando não sobra texto com significado
  if (!soDuracao(s, m)) return { num: "", un: "" };
  let un = (m[2] || "").toLowerCase();
  if (un.startsWith("dia")) un = "Dias";
  else if (un === "ano") un = "Ano";          // singular
  else if (un.startsWith("ano")) un = "Anos";
  else if (un.startsWith("m")) un = "Meses";
  else un = "";
  return { num: m[1] || "", un };
}
function setDur(prefix, str, defUn) {
  const { num, un } = splitDur(str);
  const raw = String(str || "").trim();
  // garantia/prazo: texto que o par número+unidade não representa → opção "Livre".
  // A ressalva "e não contém 'pronta'" saiu daqui: quem decide se a frase É
  // pronta-entrega agora é o splitDur, que devolve a unidade nesse caso. Com a
  // ressalva, um texto que só MENCIONA pronta entrega ("item 1: 3 unidades a
  // pronta entrega, as demais dia 22/09") não entrava no modo livre e o campo
  // ficava vazio.
  if ((prefix === "garantia" || prefix === "prazo") && raw && !num && !un) {
    $(prefix + "Num").value = raw;
    $(prefix + "Un").value = "Livre";
    if (prefix === "garantia") onGarantiaUn(); else syncPronta();
    return;
  }
  $(prefix + "Num").value = num;
  $(prefix + "Un").value = un || defUn || $(prefix + "Un").value;
  if (prefix === "prazo") syncPronta();     // trava o número se veio "Pronta-entrega"
  if (prefix === "garantia") onGarantiaUn(); // ajusta o placeholder p/ modo livre
}
function joinDur(prefix) {
  const un = val(prefix + "Un");
  if (/pronta/i.test(un)) return "Pronta-entrega";   // entrega imediata: dispensa número
  if (/^livre$/i.test(un)) return (val(prefix + "Num") || "").trim();  // garantia livre: texto qualquer
  const num = (val(prefix + "Num") || "").trim();
  return num ? `${num} ${un}` : "";
}

// ----------------------------------------------------- abas (tabs) --------
const _ABAS = { gerar: ["viewGerar", "tabGerar"], cpm: ["viewCPM", "tabCPM"],
                cadastros: ["viewCadastros", "tabCadastros"], excluir: ["viewExcluir", "tabExcluir"] };
function bindTabs() {
  $("tabGerar").onclick = () => switchTab("gerar");
  $("tabCPM").onclick = () => switchTab("cpm");
  $("tabCadastros").onclick = () => switchTab("cadastros");
  $("tabExcluir").onclick = () => switchTab("excluir");
}
function switchTab(aba) {
  // [hidden] é autoritativo no CSS (display:none!important), senão .split{display:grid} venceria.
  for (const [t, [view, btn]] of Object.entries(_ABAS)) {
    $(view).hidden = (t !== aba);
    $(btn).classList.toggle("active", t === aba);
  }
  $("acoesGerar").style.display = aba === "gerar" ? "" : "none";
  if (aba === "cpm") onEnterCPM();
}

// --------------------------------------------------- cadastros (aba) ------
// Só os cargos que trocam de gente. CFO e Presidência vêm sempre da planilha
// oficial, então não entram aqui.
const _PAD_G = { padGerente: "gerente", padGerenteGeral: "gerente_geral", padDiretor: "diretor" };
async function carregarPadroes() {
  try {
    const r = await (await api("/api/padroes")).json();
    const p = r.padroes || {};
    const g = p.gestores || {};
    for (const id in _PAD_G) $(id).value = g[_PAD_G[id]] || "";
    pessoas = (p.pessoas || []).map(x => ({ papel: x.papel || "", nome: x.nome || "" }));
    renderPessoas();
  } catch (e) { /* sem padrões salvos ainda */ }
}

// ------------------------------------------- agenda de assinaturas --------
// Lista PERMANENTE de quem assina (papel + nome). Fica no dados_usuario.json e
// abastece as sugestões dos campos de responsável — trocar de setor passa a ser
// escolher da lista, em vez de redigitar o nome toda vez.
let pessoas = [];
function renderPessoas() {
  $("pessoasLista").innerHTML = pessoas.map((p, i) =>
    `<div class="pessoa">` +
    `<input class="p-papel" data-pi="${i}" data-pk="papel" value="${escapeHtml(p.papel)}" placeholder="Cargo / setor" />` +
    `<input class="p-nome" data-pi="${i}" data-pk="nome" value="${escapeHtml(p.nome)}" placeholder="Nome de quem assina" />` +
    `<button class="chipx" data-delp="${i}" title="Tirar da agenda">✕</button></div>`).join("");
  renderSugestoes();
}
function renderSugestoes() {          // <datalist> usado por TODOS os campos de nome
  const nomes = [...new Set(pessoas.map(p => p.nome).filter(Boolean))];
  $("dlPessoas").innerHTML = nomes.map(n => {
    const quem = pessoas.find(p => p.nome === n && p.papel);
    return `<option value="${escapeHtml(n)}">${escapeHtml(quem ? quem.papel : "")}</option>`;
  }).join("");
}
function bindPessoas() {
  $("btnAddPessoa").onclick = () => { pessoas.push({ papel: "", nome: "" }); renderPessoas();
                                      const c = $("pessoasLista").lastElementChild;
                                      if (c) c.querySelector(".p-papel").focus(); };
  $("pessoasLista").oninput = (e) => {
    const t = e.target;
    if (t.dataset.pi !== undefined) { pessoas[+t.dataset.pi][t.dataset.pk] = t.value; renderSugestoes(); }
  };
  $("pessoasLista").onclick = (e) => {
    const d = e.target.dataset.delp;
    if (d !== undefined) { pessoas.splice(+d, 1); renderPessoas(); }
  };
}
async function salvarPadroes() {
  const gestores = {};
  for (const id in _PAD_G) gestores[_PAD_G[id]] = val(id).trim();
  // só os responsáveis: o texto da Finalidade é fixo no modelo (não se edita aqui)
  const body = { gestores };
  const s = $("padStatus");
  try {
    const r = await (await api("/api/salvar_padroes", { headers: { "Content-Type": "application/json" },
                                                        body: JSON.stringify(body) })).json();
    // a agenda vai no MESMO botão: um "Salvar" só p/ o card inteiro
    const rp = await (await api("/api/salvar_pessoas", { headers: { "Content-Type": "application/json" },
                                                         body: JSON.stringify({ pessoas }) })).json();
    if (rp.ok) { pessoas = rp.pessoas || pessoas; renderPessoas(); }
    const ok = r.ok && rp.ok;
    s.textContent = ok ? `✔ Salvo — responsáveis padrão e ${pessoas.length} pessoa(s) na agenda.`
                       : "Falha: " + (r.erro || rp.erro || "?");
    s.className = "cad-status " + (ok ? "ok" : "erro");
    if (ok) { if (DATA) DATA.pessoas = pessoas; cpmPreview(); }
  } catch (e) { s.textContent = "Falha: " + e; s.className = "cad-status erro"; }
}
function bindCadastros() {
  $("btnSalvarPadroes").onclick = salvarPadroes;
  bindPessoas();
  carregarPadroes();
  $("btnSalvarForn").onclick = () => salvarCadastro("fornecedor", {
    apelido: val("nf_apelido"), empresa: val("nf_empresa"), cnpj: val("nf_cnpj"),
    insc_est: val("nf_ie"), endereco: val("nf_endereco"), cep: val("nf_cep"), garantia: val("nf_garantia"),
  }, ["nf_apelido", "nf_empresa", "nf_cnpj", "nf_ie", "nf_endereco", "nf_cep", "nf_garantia"]);
  $("btnSalvarFat").onclick = () => salvarCadastro("faturamento", {
    uf: val("nl_uf"), razao_social: val("nl_razao"), cnpj: val("nl_cnpj"), cnpj2: val("nl_cnpj2"),
    endereco: val("nl_endereco"), cep: val("nl_cep"), insc_est: val("nl_ie"), insc_mun: val("nl_im"),
  }, ["nl_uf", "nl_razao", "nl_cnpj", "nl_cnpj2", "nl_endereco", "nl_cep", "nl_ie", "nl_im"]);
  $("btnSalvarPop").onclick = () => salvarCadastro("pop", {
    nome: val("np_nome"), sigla: val("np_sigla"), endereco: val("np_endereco"), municipio: val("np_municipio"),
    uf: val("np_uf"), maps: val("np_maps"), latitude: val("np_lat"), longitude: val("np_lon"), cedente: val("np_cedente"),
  }, ["np_nome", "np_sigla", "np_endereco", "np_municipio", "np_uf", "np_maps", "np_lat", "np_lon", "np_cedente"]);
  // importação em massa (planilha Excel)
  $("btnModeloCad").onclick = baixarModeloCad;
  $("btnImportCad").onclick = () => $("fileCad").click();
  $("fileCad").onchange = importarCadastros;
  bindCadNovo();
}
function setCad(msg, cls) { const s = $("cadStatus"); s.textContent = msg; s.className = "cad-status " + (cls || ""); }

/* ===========================================================================
   ABA CADASTROS — um tipo por vez, com conferência na hora de digitar.
   As três listas do app nasceram de planilhas cheias de erro de digitação
   (CNPJ com um dígito trocado, CEP de outro estado, latitude na coluna da
   longitude). Conferir no momento em que a pessoa digita é mais barato do que
   descobrir o problema depois, dentro de uma AF já emitida.
   ========================================================================= */
const _CAD_TIPOS = ["fornecedor", "faturamento", "pop"];
const soDig = (s) => String(s || "").replace(/\D/g, "");
function normTxt(s) {
  return String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "")
    .toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
}
// faixas de CEP por UF (Correios) — pega CEP colado na filial errada
const _FAIXA_CEP = {
  AC: [69900, 69999], AL: [57000, 57999], AM: [69000, 69299], AP: [68900, 68999],
  BA: [40000, 48999], CE: [60000, 63999], DF: [70000, 73699], ES: [29000, 29999],
  GO: [72800, 76799], MA: [65000, 65999], MG: [30000, 39999], MS: [79000, 79999],
  MT: [78000, 78899], PA: [66000, 68899], PB: [58000, 58999], PE: [50000, 56999],
  PI: [64000, 64999], PR: [80000, 87999], RJ: [20000, 28999], RN: [59000, 59999],
  RO: [76800, 76999], RR: [69300, 69399], RS: [90000, 99999], SC: [88000, 89999],
  SE: [49000, 49999], SP: [1000, 19999], TO: [77000, 77999],
};
function ufsDoCep(cep) {
  const n = parseInt(soDig(cep).slice(0, 5), 10);
  if (!n) return [];
  return Object.keys(_FAIXA_CEP).filter(uf => n >= _FAIXA_CEP[uf][0] && n <= _FAIXA_CEP[uf][1]);
}
function fmtCNPJ(v) {
  const d = soDig(v).slice(0, 14);
  if (d.length !== 14) return v.trim();
  return `${d.slice(0, 2)}.${d.slice(2, 5)}.${d.slice(5, 8)}/${d.slice(8, 12)}-${d.slice(12)}`;
}
// dígitos verificadores: 90% dos erros de CNPJ são digitação, e essa conta pega
function cnpjValido(v) {
  const d = soDig(v);
  if (d.length !== 14 || /^(\d)\1{13}$/.test(d)) return false;
  const dv = (base) => {
    let peso = base.length - 7, soma = 0;
    for (let i = 0; i < base.length; i++) {
      soma += Number(base[i]) * peso--;
      if (peso < 2) peso = 9;
    }
    const r = soma % 11;
    return r < 2 ? 0 : 11 - r;
  };
  return dv(d.slice(0, 12)) === Number(d[12]) && dv(d.slice(0, 13)) === Number(d[13]);
}
function fmtCEP(v) {
  const d = soDig(v).slice(0, 8);
  return d.length === 8 ? `${d.slice(0, 5)}-${d.slice(5)}` : v.trim();
}

// dica embaixo do campo; sem mensagem, ela some e o campo volta ao normal
function dica(id, msg, cls) {
  const campo = $(id), caixa = campo && campo.closest(".f");
  if (!caixa) return;
  let h = caixa.querySelector(".hint");
  if (!msg) {
    if (h) h.remove();
    caixa.classList.remove("ruim", "atencao");
    return;
  }
  if (!h) { h = document.createElement("small"); caixa.appendChild(h); }
  h.className = "hint " + (cls || "");
  h.innerHTML = msg;
  caixa.classList.toggle("ruim", cls === "ruim");
  caixa.classList.toggle("atencao", cls === "atencao");
}
function limparDicas(tipo) {
  document.querySelectorAll(`#painel_${tipo} .hint`).forEach(h => h.remove());
  document.querySelectorAll(`#painel_${tipo} .f`).forEach(f => f.classList.remove("ruim", "atencao"));
}

function mostrarCadPainel(tipo) {
  if (!_CAD_TIPOS.includes(tipo)) return;
  _CAD_TIPOS.forEach(t => { $("painel_" + t).hidden = t !== tipo; });
  document.querySelectorAll("#cadSeg .seg").forEach(b =>
    b.classList.toggle("active", b.dataset.alvo === tipo));
}
function atualizarStats() {
  if (!DATA) return;
  const poe = (id, n) => { const e = $(id); if (e) e.textContent = n; };
  poe("stForn", DATA.fornecedores.length);
  poe("stFat", DATA.faturamento.length);
  poe("stPop", DATA.pops.length);
}

// ---- avisos de duplicata: o mesmo site cadastrado duas vezes vira dois POPs
//      "incompletos", cada um com metade da informação.
function _jaExiste(tipo, campo) {
  if (!DATA || _editCad[tipo]) return null;          // editando, o "igual" é ele mesmo
  if (tipo === "fornecedor") {
    const cn = soDig(val("nf_cnpj")), nome = normTxt(val("nf_empresa")), ap = normTxt(val("nf_apelido"));
    return DATA.fornecedores.find(f =>
      (cn.length === 14 && soDig(f.cnpj) === cn) ||
      (nome && normTxt(f.empresa) === nome) ||
      (ap && normTxt(f.apelido) === ap)) || null;
  }
  if (tipo === "faturamento") {
    const cn = soDig(val("nl_cnpj")), nome = normTxt(val("nl_razao")), uf = val("nl_uf").toUpperCase();
    return DATA.faturamento.find(l =>
      (cn.length === 14 && soDig(l.cnpj) === cn) ||
      (nome && normTxt(l.razao_social) === nome && (!uf || l.uf === uf))) || null;
  }
  const sig = normTxt(val("np_sigla")), nome = normTxt(val("np_nome")), mun = normTxt(val("np_municipio"));
  return DATA.pops.find(p =>
    (sig && normTxt(p.sigla) === sig) ||
    (nome && normTxt(p.nome) === nome && (!mun || normTxt(p.municipio) === mun))) || null;
}
const _ROTULO_DUP = {
  fornecedor: f => f.apelido ? `${f.apelido} — ${f.empresa}` : f.empresa,
  faturamento: l => `${l.uf} — ${l.razao_social}`,
  pop: p => (p.sigla ? `${p.nome} (${p.sigla})` : p.nome) + (p.municipio ? ` — ${p.municipio}/${p.uf || ""}` : ""),
};
function conferirDuplicata(tipo, campo) {
  const achado = _jaExiste(tipo, campo);
  if (!achado) { dica(campo, ""); return; }
  dica(campo, `Já existe: <b>${escapeHtml(_ROTULO_DUP[tipo](achado))}</b> — ` +
    `<button type="button" class="lnkmini" data-editar="${tipo}">editar o existente</button>`, "atencao");
  const b = $(campo).closest(".f").querySelector("[data-editar]");
  if (b) b.onclick = () => editarCadastro(tipo, achado);
}

// ---- coordenadas -----------------------------------------------------------
// O link do Google Maps carrega a coordenada; digitá-la à mão é onde nascem os
// erros de hemisfério que já apareceram no cadastro.
function coordsDoLink(url) {
  const pares = [/@(-?\d+\.\d+),\s*(-?\d+\.\d+)/, /!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)/,
                 /[?&](?:q|ll|daddr|destination)=(-?\d+\.\d+),\s*(-?\d+\.\d+)/,
                 /(-?\d{1,2}\.\d{4,}),\s*(-?\d{1,3}\.\d{4,})/];
  for (const re of pares) {
    const m = String(url || "").match(re);
    if (m) return { lat: m[1], lon: m[2] };
  }
  return null;
}
const _GRAU = /[º°˚]/g;          // "º" masculino ordinal → "°" grau
const _FIM_LAT = /[SsNn]\s*$/, _FIM_LON = /[WwOoLlEe]\s*$/;
function conferirCoords() {
  const lat = val("np_lat").trim(), lon = val("np_lon").trim();
  dica("np_lat", ""); dica("np_lon", "");
  if (lat && _FIM_LON.test(lat) && !_FIM_LAT.test(lat))
    dica("np_lat", "Isso termina em W/O — parece a <b>longitude</b>. No Brasil a latitude termina em S.", "ruim");
  if (lon && _FIM_LAT.test(lon) && !_FIM_LON.test(lon))
    dica("np_lon", "Isso termina em S/N — parece a <b>latitude</b>. A longitude termina em W (ou O).", "ruim");
  if (lat && lon && normTxt(lat) === normTxt(lon))
    dica("np_lon", "Igual à latitude — uma das duas está errada.", "ruim");
}

function bindCadNovo() {
  document.querySelectorAll("#cadSeg .seg").forEach(b => {
    b.onclick = () => mostrarCadPainel(b.dataset.alvo);
  });
  document.querySelectorAll("[data-limpar]").forEach(b => {
    b.onclick = () => {
      const tipo = b.dataset.limpar;
      if (_editCad[tipo]) { cancelarEdicaoCad(tipo); }
      else { Object.keys(_CAD_CFG[tipo].campos).forEach(id => { $(id).value = ""; }); }
      if (tipo === "pop") $("np_cep_aux").value = "";
      limparDicas(tipo);
      setCad("", "");
    };
  });

  // CNPJ: formata ao sair do campo e confere os dígitos verificadores
  [["nf_cnpj", "fornecedor"], ["nl_cnpj", "faturamento"], ["nl_cnpj2", "faturamento"]].forEach(([id, tipo]) => {
    $(id).onblur = () => {
      const v = val(id).trim();
      if (!v) { dica(id, ""); return; }
      $(id).value = fmtCNPJ(v);
      if (soDig(v).length !== 14) dica(id, `CNPJ tem 14 dígitos — este tem ${soDig(v).length}.`, "ruim");
      else if (!cnpjValido(v)) dica(id, "Os dígitos verificadores não fecham — confira o número.", "ruim");
      else if (id !== "nl_cnpj2") conferirDuplicata(tipo, id);
      else dica(id, "");
    };
  });

  // CEP: formata e confere se a faixa bate com a UF informada
  [["nf_cep", null], ["nl_cep", "nl_uf"], ["np_cep_aux", "np_uf"]].forEach(([id, idUf]) => {
    $(id).onblur = () => {
      const v = val(id).trim();
      if (!v) { dica(id, ""); if (id === "np_cep_aux") juntarCepNoEndereco(); return; }
      $(id).value = fmtCEP(v);
      const d = soDig(v);
      if (d.length !== 8) { dica(id, `CEP tem 8 dígitos — este tem ${d.length}.`, "ruim"); }
      else {
        const donos = ufsDoCep(v), uf = idUf ? val(idUf).trim().toUpperCase() : "";
        if (uf && donos.length && !donos.includes(uf))
          dica(id, `Esse CEP é de <b>${donos.join("/")}</b>, e a UF aqui é <b>${escapeHtml(uf)}</b>.`, "ruim");
        else dica(id, "");
      }
      if (id === "np_cep_aux") juntarCepNoEndereco();
    };
  });

  // UF em caixa alta, sempre
  ["nl_uf", "np_uf"].forEach(id => {
    $(id).onblur = () => { $(id).value = val(id).trim().toUpperCase().slice(0, 2); };
  });
  $("np_sigla").onblur = () => {
    $("np_sigla").value = val("np_sigla").trim().toUpperCase();
    conferirDuplicata("pop", "np_sigla");
  };

  // duplicatas pelos campos de nome
  $("nf_empresa").onblur = () => conferirDuplicata("fornecedor", "nf_empresa");
  $("nl_razao").onblur = () => conferirDuplicata("faturamento", "nl_razao");
  $("np_nome").onblur = () => conferirDuplicata("pop", "np_nome");

  // coordenadas: normaliza o símbolo de grau, aceita "lat, lon" colado de uma vez
  ["np_lat", "np_lon"].forEach(id => {
    $(id).onblur = () => {
      let v = val(id).trim().replace(_GRAU, "°");
      const par = v.match(/^(-?\d{1,3}[.,]\d+)\s*[,;]\s*(-?\d{1,3}[.,]\d+)$/);
      if (par) { $("np_lat").value = par[1]; $("np_lon").value = par[2]; }
      else { $(id).value = v; }
      conferirCoords();
    };
  });
  $("np_maps").onblur = () => {
    const c = coordsDoLink(val("np_maps"));
    if (c && !val("np_lat") && !val("np_lon")) {
      $("np_lat").value = c.lat; $("np_lon").value = c.lon;
      dica("np_maps", "Latitude e longitude preenchidas a partir do link.", "bom");
      conferirCoords();
    }
  };
  $("btnCoordsDoMaps").onclick = () => {
    const link = val("np_maps").trim();
    if (!link) { dica("np_maps", "Cole o link do Google Maps aqui primeiro.", "atencao"); return; }
    const c = coordsDoLink(link);
    if (!c) {
      dica("np_maps", "Esse link não traz a coordenada dentro dele (os links curtos " +
        "<code>maps.app.goo.gl</code> não trazem). Abra o link, clique com o botão direito no ponto " +
        "e copie o par de números que aparece.", "atencao");
      return;
    }
    $("np_lat").value = c.lat; $("np_lon").value = c.lon;
    dica("np_maps", "Latitude e longitude preenchidas a partir do link.", "bom");
    conferirCoords();
  };
}

// O CEP não é campo do POP — ele mora dentro do endereço. Digitar num campo
// próprio e ver o endereço se montar é mais claro do que lembrar de escrever
// "CEP 00000-000" no fim da linha.
function juntarCepNoEndereco() {
  const cep = val("np_cep_aux").trim();
  let end = val("np_endereco").replace(/,?\s*CEP\s*\d{5}-?\d{3}\s*$/i, "").trim().replace(/,\s*$/, "");
  $("np_endereco").value = cep ? (end ? `${end}, CEP ${fmtCEP(cep)}` : `CEP ${fmtCEP(cep)}`) : end;
}
function setCadMassa(msg, cls) { const s = $("cadMassaStatus"); s.textContent = msg; s.className = "cad-status " + (cls || ""); }
async function baixarModeloCad() {
  setCadMassa("Gerando o modelo…", "info");
  try {
    const res = await (await api("/api/modelo_cadastro")).json();
    if (res.ok) setCadMassa(`✔ Modelo aberto no Excel — preencha e importe. (salvo em ${res.pasta})`, "ok");
    else setCadMassa("Falha ao gerar o modelo: " + (res.erro || "?"), "erro");
  } catch (e) { setCadMassa("Erro: " + e, "erro"); }
}
async function importarCadastros() {
  const file = $("fileCad").files[0];
  if (!file) return;
  setCadMassa("Importando a planilha…", "info");
  try {
    const buf = await file.arrayBuffer();
    const res = await (await api("/api/importar_cadastros", { headers: comNome(file.name), body: buf })).json();
    if (res.ok) {
      const p = [];
      if (res.fornecedor) p.push(`${res.fornecedor} fornecedor(es)`);
      if (res.faturamento) p.push(`${res.faturamento} faturamento(s)`);
      if (res.pop) p.push(`${res.pop} POP(s)`);
      const extras = [];
      if (res.ignoradas) extras.push(`${res.ignoradas} linha(s) sem nome ignorada(s)`);
      if (res.duplicadas) extras.push(`${res.duplicadas} já cadastrada(s) — não duplicou`);
      const ign = extras.length ? `  (${extras.join(" · ")})` : "";
      setCadMassa(`✔ Importado: ${p.join(" · ")}.${ign}`, "ok");
      await recarregarDados();     // atualiza as listas da aba Gerar AF/AS
    } else {
      setCadMassa("Não importou: " + (res.erro || "?"), "aviso");
    }
  } catch (e) { setCadMassa("Erro ao importar: " + e, "erro"); }
  $("fileCad").value = "";
}
// ---- EDITAR cadastros do usuário -----------------------------------------
// Mapa: campo do form → chave do registro; ids() = identificadores p/ casar no backend.
const _CAD_CFG = {
  fornecedor: { btn: "btnSalvarForn",
    campos: { nf_apelido: "apelido", nf_empresa: "empresa", nf_cnpj: "cnpj", nf_ie: "insc_est", nf_endereco: "endereco", nf_cep: "cep", nf_garantia: "garantia" },
    ids: x => ({ empresa: x.empresa, apelido: x.apelido, cnpj: x.cnpj }) },
  faturamento: { btn: "btnSalvarFat",
    campos: { nl_uf: "uf", nl_razao: "razao_social", nl_cnpj: "cnpj", nl_cnpj2: "cnpj2", nl_endereco: "endereco", nl_cep: "cep", nl_ie: "insc_est", nl_im: "insc_mun" },
    ids: x => ({ razao_social: x.razao_social, uf: x.uf, cnpj: x.cnpj }) },
  pop: { btn: "btnSalvarPop",
    campos: { np_nome: "nome", np_sigla: "sigla", np_endereco: "endereco", np_municipio: "municipio", np_uf: "uf", np_maps: "maps", np_lat: "latitude", np_lon: "longitude", np_cedente: "cedente" },
    ids: x => ({ nome: x.nome, sigla: x.sigla, municipio: x.municipio }) },
};
const _editCad = { fornecedor: null, faturamento: null, pop: null };
const _btnCadTxt = { fornecedor: "💾 Salvar fornecedor", faturamento: "💾 Salvar faturamento", pop: "💾 Salvar POP" };

function atualizarBtnCad(tipo) {
  const cfg = _CAD_CFG[tipo], b = $(cfg.btn), editando = !!_editCad[tipo];
  b.textContent = editando ? "🔄 Atualizar" : _btnCadTxt[tipo];
  b.classList.toggle("success", editando);
  // O próprio "Limpar campos" da barra vira a saída da edição — dois botões
  // vizinhos ("Limpar" e "Cancelar edição") fazendo quase a mesma coisa confunde.
  const limpar = b.parentElement && b.parentElement.querySelector("[data-limpar]");
  if (limpar) limpar.textContent = editando ? "✖ Cancelar edição" : "✕ Limpar campos";
}
function editarCadastro(tipo, item) {
  const cfg = _CAD_CFG[tipo];
  _editCad[tipo] = cfg.ids(item);                       // guarda o id ANTIGO
  for (const id in cfg.campos) $(id).value = item[cfg.campos[id]] || "";
  if (tipo === "pop") {                                 // o CEP vem de dentro do endereço
    const m = (item.endereco || "").match(/CEP\s*(\d{5}-?\d{3})/i);
    $("np_cep_aux").value = m ? m[1] : "";
  }
  limparDicas(tipo);
  atualizarBtnCad(tipo);
  switchTab("cadastros");
  mostrarCadPainel(tipo);
  const nome = item.empresa || item.razao_social || item.nome || "";
  setCad(`✏️ Editando "${nome}". Altere e clique em Atualizar (ou ✖ Cancelar).`, "info");
  $(cfg.btn).scrollIntoView({ block: "center" });
}
function cancelarEdicaoCad(tipo) {
  const cfg = _CAD_CFG[tipo];
  _editCad[tipo] = null;
  for (const id in cfg.campos) $(id).value = "";
  if (tipo === "pop") $("np_cep_aux").value = "";
  limparDicas(tipo);
  atualizarBtnCad(tipo);
  setCad("Edição cancelada.", "");
}
async function salvarCadastro(tipo, dados, idsLimpar) {
  const nome = (dados.empresa || dados.razao_social || dados.nome || "").trim();
  if (!nome) { setCad("Preencha pelo menos o nome / razão social.", "erro"); return; }
  // Erro apontado no formulário não impede de salvar — às vezes o dado esquisito
  // é o certo —, mas exige um "sim" explícito. É o passo que faltava para um CEP
  // de outro estado não entrar no cadastro sem ninguém perceber.
  const ruins = [...document.querySelectorAll(`#painel_${tipo} .hint.ruim`)].map(h => "• " + h.textContent.trim());
  if (ruins.length && !confirm(`Ainda há ${ruins.length} aviso(s) neste cadastro:\n\n${ruins.join("\n")}\n\nSalvar assim mesmo?`))
    return;
  const editId = _editCad[tipo];
  try {
    const url = editId ? "/api/atualizar" : "/api/cadastrar";
    const body = editId ? { tipo, id: editId, dados } : { tipo, dados };
    const r = await api(url, { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const res = await r.json();
    if (!res.ok) { setCad((editId ? "Falha ao atualizar: " : "Falha ao salvar: ") + (res.erro || "?"), "erro"); return; }
    idsLimpar.forEach(id => { $(id).value = ""; });
    if (tipo === "pop") $("np_cep_aux").value = "";
    limparDicas(tipo);
    _editCad[tipo] = null; atualizarBtnCad(tipo);
    await recarregarDados();
    setCad(`✔ "${nome}" ${editId ? "atualizado" : "salvo"} — já aparece nas listas da aba Gerar AF/AS.`, "ok");
  } catch (e) { setCad("Erro ao salvar: " + e, "erro"); }
}
async function recarregarDados() {
  DATA = await (await api("/api/dados")).json();
  const catSel = $("catalogo").value;
  optionList("catalogo", DATA.fornecedores.map(f => f.apelido ? `${f.apelido} — ${f.empresa}` : f.empresa));
  atualizarPreferencias();
  $("catCount").textContent = `${DATA.fornecedores.length} fornecedores no catálogo`;
  $("catalogo").value = catSel;
  atualizarStats();
  renderExcluir();
}

// ------------------------------- aba Excluir: TODOS + apagar/ocultar ------
function escapeAttr(s) { return escapeHtml(s).replace(/'/g, "&#39;"); }
const _EX = [
  { tipo: "fornecedor", chave: "fornecedores", list: "listForn", busca: "buscaForn", oc: "ocForn", count: "countForn",
    arr: () => DATA.fornecedores, label: f => f.apelido ? `${f.apelido} — ${f.empresa}` : f.empresa,
    ids: f => ({ empresa: f.empresa, apelido: f.apelido, cnpj: f.cnpj }) },
  { tipo: "faturamento", chave: "faturamento", list: "listFat", busca: "buscaFat", oc: "ocFat", count: "countFat",
    arr: () => DATA.faturamento, label: l => `${l.uf} — ${l.razao_social}`,
    ids: l => ({ razao_social: l.razao_social, uf: l.uf, cnpj: l.cnpj }) },
  { tipo: "pop", chave: "pops", list: "listPop", busca: "buscaPop", oc: "ocPop", count: "countPop",
    arr: () => DATA.pops, label: p => (p.sigla ? `${p.nome} (${p.sigla})` : p.nome) + (p.municipio ? ` — ${p.municipio}/${p.uf || ""}` : ""),
    ids: p => ({ nome: p.nome, sigla: p.sigla, municipio: p.municipio }) },
];
function renderExcluir() {
  if (!DATA) return;
  for (const c of _EX) {
    const filtro = (val(c.busca) || "").toLowerCase().trim();
    const arr = c.arr().filter(x => !filtro || c.label(x).toLowerCase().includes(filtro));
    const contador = $(c.count);
    if (contador) contador.textContent = `${arr.length} ${filtro ? "encontrado" : "ativos"}`;
    $(c.list).innerHTML = arr.length ? arr.map(x => {
      const u = x.origem === "usuario";
      // Editar vale p/ TODO item, inclusive os do modelo oficial: o .xlsm não é
      // alterado — a versão do catálogo é ocultada e a sua entra no lugar (o ↩
      // aqui embaixo devolve a original quando quiser).
      const acaoEditar = u ? "Editar cadastro" : "Corrigir este item do modelo oficial";
      const acaoRemover = u ? "Apagar cadastro seu" : "Ocultar item do catálogo";
      const edit = `<button class="editcad" data-tipo="${c.tipo}" data-item='${escapeAttr(JSON.stringify(x))}' title="${acaoEditar}" aria-label="${acaoEditar}">✏️</button>`;
      return `<div class="cad-row"><span>${escapeHtml(c.label(x))}${u ? ' <i class="bdg">seu</i>' : ''}</span>` +
        `<span class="cad-acts">${edit}<button class="delcad" data-tipo="${c.tipo}" data-ids='${escapeAttr(JSON.stringify(c.ids(x)))}' title="${acaoRemover}" aria-label="${acaoRemover}">${u ? '🗑' : '🚫'}</button></span></div>`;
    }).join("") : '<div class="cad-vazio">Nada encontrado.</div>';
    const ocs = (DATA.ocultos && DATA.ocultos[c.chave]) || [];
    $(c.oc).innerHTML = ocs.length
      ? '<div class="cad-h">Ocultos — clique ↩ para restaurar:</div>' + ocs.map(o =>
          `<div class="cad-row oc"><span>${escapeHtml(Object.values(o).filter(Boolean).join(" · "))}</span>` +
          `<button class="restcad" data-tipo="${c.tipo}" data-ids='${escapeAttr(JSON.stringify(o))}' title="Restaurar" aria-label="Restaurar item">↩</button></div>`).join("")
      : "";
  }
}
function bindExcluir() {
  _EX.forEach(c => { $(c.busca).oninput = renderExcluir; });
  $("viewExcluir").addEventListener("click", async (e) => {
    const edit = e.target.closest(".editcad");
    if (edit) { editarCadastro(edit.dataset.tipo, JSON.parse(edit.dataset.item)); return; }
    const del = e.target.closest(".delcad"), rest = e.target.closest(".restcad");
    if (!del && !rest) return;
    const b = del || rest;
    if (del && !confirm("Remover/ocultar este item da sua lista? (o modelo .xlsm não é alterado)")) return;
    const tipo = b.dataset.tipo, dados = JSON.parse(b.dataset.ids);
    try {
      const r = await api("/api/" + (del ? "remover" : "restaurar"), { headers: { "Content-Type": "application/json" }, body: JSON.stringify({ tipo, dados }) });
      const res = await r.json();
      if (res.ok) { await recarregarDados(); setStatus(del ? "✔ Item removido/ocultado." : "✔ Item restaurado.", "ok"); }
      else setStatus("Não foi possível: " + (res.erro || "?"), "erro");
    } catch (err) { setStatus("Erro: " + err, "erro"); }
  });
}

// --------------------------------------------------------------- itens ----
function tamanhoPadrao(el) {       // volta a descrição ao tamanho de fábrica
  el.style.width = "";
  el.style.height = "";
}
function renderItems() {
  const tb = $("itensBody");
  // "unidade" saiu da grade: a coluna Un. não existe mais na AF. O campo continua
  // no objeto do item (compatível com AF antiga importada), só não é editável aqui.
  const cols = ["codigo", "descricao", "quantidade", "preco_unit_sem", "preco_unit_com", "preco_total_com"];
  const ph = {
    codigo: ' placeholder="Cód./PN" title="Código do produto · Part Number (PN) · Referência · SKU"',
    descricao: ' placeholder="Descrição do item"',
  };
  // A DESCRIÇÃO é textarea (como no CPM): dá p/ arrastar a alça e ler o texto
  // inteiro, que costuma ser longo. Os demais campos seguem input de uma linha.
  tb.innerHTML = items.map((it, i) =>
    `<tr><td class="ix">${i + 1}</td>` +
    cols.map(k => k === "descricao"
      ? `<td><textarea class="it-desc" rows="1" data-k="${k}" data-i="${i}"${ph[k] || ""}>${escapeHtml(it[k])}</textarea></td>`
      : `<td><input data-k="${k}" data-i="${i}" value="${escapeHtml(it[k])}"${ph[k] || ""}></td>`).join("") +
    `<td><button class="it-reset" data-reset="${i}" title="Voltar a descrição ao tamanho original">⤢</button>` +
    `<button class="delitem" data-del="${i}">✕</button></td></tr>`).join("");
  tb.oninput = (e) => {
    const t = e.target;
    if (t.dataset.k) {
      items[+t.dataset.i][t.dataset.k] = t.value;
      // digitou no unitário c/ imposto: a partir daqui o valor é DELE, o app
      // não sobrescreve mais (até entrar um imposto, que refaz a conta)
      if (t.dataset.k === "preco_unit_com") items[+t.dataset.i].ucAuto = false;
      // mexeu no preço sem impostos (ou na quantidade) e o item tem imposto:
      // recalcula e ESCREVE nas células, senão o modelo e a tela divergiam
      // mexer no unitário C/ imposto também refaz o total da linha — antes só
      // o "sem imposto" e a quantidade disparavam a conta, então digitar direto
      // no unitário com imposto deixava o total parado no valor antigo
      if (["preco_unit_sem", "preco_unit_com", "quantidade"].includes(t.dataset.k)) {
        const i = +t.dataset.i;
        recalcularItem(items[i]);
        ["preco_unit_com", "preco_total_com"].forEach(k => {
          const cel = tb.querySelector(`[data-k="${k}"][data-i="${i}"]`);
          if (cel && cel !== t) cel.value = items[i][k];
        });
      }
      atualizarValorTotal(); schedulePreview();
    }
  };
  // ENTER anda p/ a célula de BAIXO na mesma coluna, como no Excel (Shift+Enter
  // sobe). Na descrição o texto é multilinha: o 1º Enter quebra a linha e o 2º
  // seguido (ou Ctrl+Enter) desce, apagando a linha em branco que sobrou.
  tb.onkeydown = (e) => {
    if (e.key !== "Enter" || !e.target.dataset.k) return;
    const ta = e.target;
    if (ta.classList.contains("it-desc") && !e.ctrlKey) {
      const fim = ta.selectionStart === ta.value.length && ta.selectionStart === ta.selectionEnd;
      if (!(fim && /\n$/.test(ta.value))) return;      // 1º Enter: só quebra a linha
      ta.value = ta.value.replace(/\n+$/, "");         // 2º Enter: tira o branco e desce
      ta.dispatchEvent(new Event("input", { bubbles: true }));
    }
    e.preventDefault();
    const col = e.target.dataset.k, lin = +e.target.dataset.i;
    const alvo = lin + (e.shiftKey ? -1 : 1);
    if (alvo < 0) return;
    if (alvo >= items.length) { items.push(novoItem()); renderItems(); }   // última linha → cria outra
    const prox = tb.querySelector(`[data-k="${col}"][data-i="${alvo}"]`);
    if (prox) { prox.focus(); if (prox.select) prox.select(); }
  };
  tb.onclick = (e) => {
    if (e.target.dataset.reset !== undefined) {      // desfaz o arraste do usuário
      const ta = tb.querySelector(`.it-desc[data-i="${e.target.dataset.reset}"]`);
      if (ta) tamanhoPadrao(ta);
      return;
    }
    if (e.target.dataset.del !== undefined) {
      items.splice(+e.target.dataset.del, 1);
      if (!items.length) items.push(novoItem());
      renderItems(); atualizarValorTotal(); schedulePreview();
    }
  };
  renderGPItens();
  renderImpItens();      // a lista de itens do painel de impostos acompanha
}

/* ---------------------------------------------------- modelo do PDF -------
   A prévia mostra SEMPRE o modelo Visual (HTML). A cortina "PDF" escolhe o que
   vai ser GERADO, e começa em "Oficial" — o modelo do Excel, paisagem, com
   outra cara. Quem não reparasse na cortina preenchia a AF olhando um
   documento e recebia outro, sem nenhum aviso. A etiqueta na barra da prévia
   diz qual vai sair e destaca quando ele difere do que está na tela. */
function marcarModelo() {
  const casos = [["pdfEstilo", "tagModeloAF"], ["cpmEstilo", "tagModeloCPM"]];
  for (const [sel, tag] of casos) {
    const el = $(tag), sl = $(sel);
    if (!el || !sl) continue;
    const visual = sl.value === "html";
    el.textContent = visual
      ? "o PDF sai assim (modelo Visual)"
      : "atenção: o PDF sai no modelo Oficial, diferente desta prévia";
    el.classList.toggle("difere", !visual);
    el.title = visual
      ? "A prévia e o PDF são o mesmo documento."
      : "Esta prévia é o modelo Visual. O PDF será gerado no modelo oficial "
        + "(planilha da Eletronet), com layout diferente. Troque a cortina PDF "
        + "para \"Visual (HTML)\" se quiser o documento que está vendo.";
  }
}

// --------------------------------------------------------------- coleta ---
function collectForm() {
  return {
    fornecedor: val("fornecedor"), cnpj: val("cnpj"), insc_est: val("ie"),
    endereco: val("endereco"), cep: val("cep"), numero_proposta: val("numProp"),
    data: val("dataProp"), valor_total: val("valor"), condicao_pagamento: val("pagto"),
    prazo_entrega: perItemPrazo ? (gpResumo("prazo") || joinDur("prazo")) : joinDur("prazo"),
    objeto: val("objeto"),
    garantia: perItemGarantia ? (gpResumo("garantia") || joinDur("garantia")) : joinDur("garantia"),
    moeda: val("moeda"), prefixo: val("prefixo"), numero: val("numero"), ano: val("ano"),
    modificacao: val("mod"), data_emissao: val("dataEmis"), revisao: val("rev"),
    caminho_pdf: caminhoPdf, anexar_proposta: true, pdf_estilo: val("pdfEstilo"),
    rubricas: !!($("ckRubricas") && $("ckRubricas").checked),
    // sem isto, a escolha do balão morria na tela e a AF saía sempre no padrão
    rubricas_todas: !!($("ckRubTodas") && $("ckRubTodas").checked),
    faturamentos: faturamentos.slice(),
    entregas: entregas.slice(),
    itens: items,
    observacoes: obsRows().map(i => i.value.trim()).filter(Boolean),
    // linha sem nome é descartada — não vira assinatura em branco no documento
    assinantes: assinantesAF.filter(x => (x.nome || "").trim())
                            .map(x => ({ papel: (x.papel || "").trim(), nome: x.nome.trim() })),
  };
}

// ------------------------------------------------ limpar formulários ------
// Volta a tela ao estado de recém-aberta, sem precisar fechar o app: mesmos
// padrões do arranque (ano, data de hoje, moeda Real, matriz SP no faturamento).
function limparAF(perguntar = true) {
  if (perguntar && !confirm("Limpar TODOS os campos da AF? O que estiver preenchido será perdido.")) return;
  // guarda como estava ANTES de apagar: o confirm() protege de clique errado,
  // não de arrependimento — quem disse "sim" e se deu conta depois precisa de volta
  _antesDeLimpar = fotoAF();
  ["fornecedor", "cnpj", "ie", "endereco", "cep", "dataProp", "numProp", "valor",
   "pagto", "objeto", "numero", "garantiaNum", "prazoNum"].forEach(id => { if ($(id)) $(id).value = ""; });
  $("catalogo").value = "-1";
  extraDaProposta = 0;
  $("catBusca").value = "";
  refletirCatalogo();
  dica("cnpj", ""); dica("cep", "");
  $("rev").value = "0";
  $("garantiaUn").value = "Meses";
  $("prazoUn").value = "Dias";
  $("moeda").value = "Real";
  if (DATA) { $("prefixo").value = DATA.prefixos[0]; $("mod").value = DATA.modificacoes[0]; }
  const hoje = new Date();
  $("ano").value = hoje.getFullYear();
  $("dataEmis").value = hoje.toLocaleDateString("pt-BR");

  faturamentos.length = 0;
  entregas.length = 0;
  const sp = DATA && DATA.faturamento.find(l => l.uf === "SP");   // mesmo padrão do arranque
  if (sp) faturamentos.push(sp);
  renderFaturamentos(); renderEntregas();

  items.length = 0; items.push(novoItem()); renderItems();
  assinantesAF.length = 0; renderAssinantesAF();
  $("obsList").innerHTML = ""; renderObsVazio();
  perItemGarantia = perItemPrazo = false;
  caminhoPdf = "";
  $("cienaBar").hidden = true;
  atualizarValorTotal();
  atualizarIdPrev();
  schedulePreview();
  setStatus("✔ Formulário da AF limpo. Ctrl+Z desfaz.", "ok");
}

function limparCPM(perguntar = true) {
  if (perguntar && !confirm("Limpar os campos do CPM/CPS? O que estiver preenchido será perdido.")) return;
  for (const id in _CPM_CAMPOS) { const e = $(id); if (e && e.tagName !== "SELECT") e.value = ""; }
  extras.length = 0; renderExtras();
  document.querySelectorAll(".ass input[type=checkbox]").forEach(ck => { ck.checked = true; });
  const cli = $("cpmClientes");
  if (cli) cli.innerHTML = "";                       // cards de cliente
  for (let i = 1; i <= 4; i++) {                     // fornecedores consultados
    ["cpmForn", "cpmPrazo", "cpmVal"].forEach(pre => { const e = $(pre + i); if (e) e.value = ""; });
  }
  cpmIdsReadonly();
  cpmPreview();
  setCpm("✔ Formulário do CPM/CPS limpo.", "ok");
}

// ---- Observações opcionais (fora do escopo padrão) -----------------------
function obsRows() { return [...document.querySelectorAll("#obsList .obs-input")]; }
/* Põe na tela as observações que vieram de fora (proposta lida ou AF
   importada). Existe porque o campo só era LIDO — o extrator devolvia a
   ESPECIFICAÇÃO TÉCNICA e ela era descartada no caminho, com o quadro de
   observações ficando vazio. Não apaga o que a pessoa já tinha escrito: as
   novas entram depois, sem repetir as que já estão lá. */
function porObservacoes(lista) {
  if (!lista || !lista.length) return;
  const jaTem = new Set(obsRows().map(i => i.value.trim()).filter(Boolean));
  lista.map(x => String(x || "").trim()).filter(Boolean).forEach(txt => {
    if (jaTem.has(txt)) return;
    jaTem.add(txt);
    addObsRow(txt, false);
  });
}
function renderObsVazio() { $("obsVazio").hidden = obsRows().length > 0; }
function addObsRow(value, foco) {
  const row = document.createElement("div");
  row.className = "obs-row";
  const inp = document.createElement("input");
  inp.className = "obs-input"; inp.placeholder = "Ex.: Entrega em horário comercial; instalação por conta do fornecedor…";
  inp.value = value || "";
  inp.addEventListener("input", schedulePreview);
  const del = document.createElement("button");
  del.type = "button"; del.className = "obs-del"; del.title = "remover"; del.textContent = "✕";
  del.onclick = () => { row.remove(); renderObsVazio(); schedulePreview(); };
  row.append(inp, del);
  $("obsList").appendChild(row);
  renderObsVazio();
  if (foco) inp.focus();
  return inp;
}
// -------------------------------------------------------------- preview ---
let _tmr = null, _ultimoPayload = "";
function schedulePreview() {
  clearTimeout(_tmr);
  _tmr = setTimeout(doPreview, 250);
  guardarRascunho();     // toda mudança que redesenha a prévia também vira rascunho
}
async function doPreview() {
  const payload = JSON.stringify(collectForm());
  if (payload === _ultimoPayload) return;   // nada relevante mudou → não refaz a prévia
  _ultimoPayload = payload;
  try {
    const r = await api("/api/preview", { headers: { "Content-Type": "application/json" }, body: payload });
    $("preview").srcdoc = await r.text();
  } catch (e) { _ultimoPayload = ""; console.warn("prévia falhou:", e); /* permite tentar de novo */ }
}

/* Junta as partes de uma proposta repartida num dicionário só.
   Regra por tipo de campo:
   - TEXTO: vale a primeira parte que trouxer preenchido. Quem vem depois
     completa o que falta e não sobrescreve o que já veio — a parte que a
     pessoa escolheu primeiro é a principal.
   - ITENS: fica a lista MAIOR, não a soma. A técnica costuma vir sem tabela e
     a comercial com ela; somar as duas duplicaria o pedido.
   - ENTREGAS / FATURAMENTO / OBSERVAÇÕES: somam, sem repetir, porque cada
     parte traz um pedaço (a comercial da Precision manda "Vide Proposta
     Técnica" justamente para os locais). */
function juntarPartes(partes) {
  const fora = new Set(["itens", "entregas", "faturamentos", "observacoes",
                        "avisos", "ok", "arquivo", "caminho_pdf", "valor_total",
                        "numero_proposta"]);
  const junto = {ok: true, itens: [], entregas: [], faturamentos: [],
                 observacoes: [], avisos: []};
  const chave = (x) => JSON.stringify(x);
  const vistos = {entregas: new Set(), faturamentos: new Set(), observacoes: new Set()};
  const vistasPartes = new Set();
  const propostas = [];
  let somaPartes = 0, comTotal = 0;
  partes.forEach((p, i) => {
    /* A PARTE inteira é a unidade de repetição. Escolheu o mesmo arquivo duas
       vezes, a segunda não conta. Antes a proteção era item a item, e isso
       estragava a ALG: os quatro arquivos dela pedem OS MESMOS dois produtos,
       um para cada filial, e a AF saía com 2 em vez de 8. */
    const impressao = JSON.stringify([
      (p.itens || []).map(it => [it.codigo, it.descricao, it.quantidade,
                                 it.preco_total_com]),
      p.valor_total || "", (p.numero_proposta || "").trim()]);
    if (vistasPartes.has(impressao)) return;
    vistasPartes.add(impressao);
    for (const k in p) {
      if (fora.has(k)) continue;
      const v = p[k];
      if (v === null || v === undefined || v === "") continue;
      if (junto[k] === undefined || junto[k] === "") junto[k] = v;   // 1ª que trouxer
    }
    /* ITENS SOMAM. A AF-E-347 nasceu de quatro propostas da SEICOM (uma por
       estado) e tem 8 itens = 2+2+2+2. A regra antiga, "fica a lista maior",
       daria 2. Item igual em partes diferentes entra de novo, porque é pedido
       de novo: a ALG repete os mesmos dois produtos para cada filial. */
    (p.itens || []).forEach(it => junto.itens.push(it));
    const t = parseBRL(p.valor_total);
    if (t) { somaPartes += t; comTotal++; }
    const np = (p.numero_proposta || "").trim();
    if (np && !propostas.includes(np)) propostas.push(np);
    for (const campo of ["entregas", "faturamentos", "observacoes"]) {
      (p[campo] || []).forEach(x => {
        const c = chave(x);
        if (vistos[campo].has(c)) return;
        vistos[campo].add(c);
        junto[campo].push(x);
      });
    }
    (p.avisos || []).forEach(a => {
      const marca = partes.length > 1 ? `[parte ${i + 1}] ${a}` : a;
      if (!junto.avisos.includes(marca)) junto.avisos.push(marca);
    });
  });
  // TODAS as propostas no campo, como na AF pronta:
  // "000.148-003, 149-003, 150-003 e 151-003"
  junto.numero_proposta = propostas.length > 1
    ? propostas.slice(0, -1).join(", ") + " e " + propostas[propostas.length - 1]
    : (propostas[0] || "");
  /* O TOTAL só vira soma quando a CONTA FECHA: a soma dos totais das partes
     tem de bater com a soma dos itens juntados. Não batendo, fica o maior e o
     app avisa — inventar um número de fechamento seria pior que avisar. */
  const somaItens = junto.itens.reduce((a, it) => a + (parseBRL(it.preco_total_com) || 0), 0);
  const maior = Math.max(...partes.map(p => parseBRL(p.valor_total) || 0), 0);
  if (comTotal > 1 && somaPartes > 0) {
    if (somaItens > 0 && Math.abs(somaItens - somaPartes) > Math.max(1, 0.01 * somaPartes)) {
      junto.valor_total = fmtBRL(maior);
      junto.avisos.push(`⚠ Os totais das ${comTotal} partes somam ${fmtBRL(somaPartes)}, `
        + `mas os itens somam ${fmtBRL(somaItens)} — confira antes de gerar.`);
    } else {
      junto.valor_total = fmtBRL(somaPartes);
      junto.avisos.push(`As ${comTotal} partes somam ${fmtBRL(somaPartes)}, `
        + `que é o total da AF/AS.`);
    }
  } else {
    junto.valor_total = fmtBRL(maior) || (partes.find(p => p.valor_total) || {}).valor_total || "";
  }
  junto.caminho_pdf = partes[0].caminho_pdf || "";   // a 1ª é a que vai anexada
  return junto;
}

// --------------------------------------------------------- ler proposta ---
// `soltos` vem do arrastar-e-soltar; sem ele, lê do seletor de arquivo. Os dois
// caminhos partilham TODO o resto — juntar partes, CIENA, catálogo, avisos —
// porque duplicar isso seria duplicar o lugar onde os defeitos aparecem.
async function lerProposta(soltos) {
  const arquivos = soltos && soltos.length ? [...soltos] : [...$("filePdf").files];
  const file = arquivos[0];
  if (!file) return;
  setStatus("Lendo proposta… (pode levar alguns segundos)", "info");
  try {
    const lidas = [];
    for (const f of arquivos) {
      if (arquivos.length > 1)
        setStatus(`Lendo parte ${lidas.length + 1} de ${arquivos.length}: ${f.name}…`, "info");
      const buf = await f.arrayBuffer();
      const r = await api("/api/extrair", { headers: comNome(f.name), body: buf });
      const um = await r.json();
      if (!um.ok) { setStatus("Falha ao ler " + f.name + ": " + (um.erro || "?"), "erro"); return; }
      if (um.eh_ciena) { aplicarCienaEStatus(um); return; }   // CIENA não se combina
      lidas.push(um);
    }
    const p = lidas.length > 1 ? juntarPartes(lidas) : lidas[0];
    _ciena = null; renderCienaBar();                  // proposta comum → sem barra CIENA
    const forn = aplicarProposta(p);
    const avs = (p.avisos || []).join(" • ");
    const rec = forn
      ? `✔ Fornecedor reconhecido: ${forn.apelido || forn.empresa} — dados oficiais do catálogo aplicados.`
      : `⚠ Fornecedor "${p.fornecedor || "?"}" não está no catálogo — confira ou cadastre na aba Cadastros.`;
    const partes = lidas.length > 1 ? `Proposta lida de ${lidas.length} partes. ` : "Proposta lida. ";
    setStatus(partes + rec + (avs ? "  ⚠ " + avs : ""), forn && !avs ? "ok" : "aviso");
  } catch (e) { setStatus("Erro ao ler proposta: " + e, "erro"); }
  $("filePdf").value = "";
}

function aplicarCienaEStatus(p) {
  aplicarCiena(p);
  setStatus(`✔ Proposta CIENA importada${p.projeto ? " (" + p.projeto + ")" : ""}. `
    + `AF (equipamento) = US$ ${p.af.valor_total} · AS (serviço) = US$ ${p.as.valor_total}. `
    + `Mostrando a AF — use 🔀 para a AS.`, "ok");
  $("filePdf").value = "";
}

function aplicarProposta(p) {
  const set = (id, v) => { if (v) $(id).value = v; };
  $("fornecedor").value = p.fornecedor || ""; $("cnpj").value = p.cnpj || ""; $("ie").value = p.insc_est || "";
  $("endereco").value = p.endereco || ""; $("cep").value = p.cep || ""; setDur("garantia", p.garantia, "Meses");
  $("numProp").value = p.numero_proposta || ""; $("dataProp").value = p.data || ""; $("valor").value = p.valor_total || "";
  $("pagto").value = p.condicao_pagamento || ""; setDur("prazo", p.prazo_entrega, "Dias"); $("objeto").value = p.objeto || "";
  set("moeda", p.moeda);
  $("dataEmis").value = new Date().toLocaleDateString("pt-BR");   // emissão = sempre hoje
  caminhoPdf = p.caminho_pdf || "";
  items = (p.itens && p.itens.length) ? p.itens.map(it => Object.assign(novoItem(), it)) : [novoItem()];
  // Objeto = resumo BREVE das descrições dos produtos (tem prioridade); só usa o
  // objeto bruto da proposta se não houver itens p/ resumir.
  $("objeto").value = resumoItens() || p.objeto || "";
  // O TOTAL DA PROPOSTA MANDA — não a soma das linhas.
  // Aqui isto chamava atualizarValorTotal(), que somava os itens e escrevia por
  // cima. Numa proposta com frete fora da tabela (SUBTOTAL 51.289,52 + FRETE
  // 14.938,50 = TOTAL 66.228,02) a AF sairia por 51.289,52 — R$ 14.938,50 a
  // menos, sem ninguém perceber. Só soma quando a proposta não trouxe total.
  conciliarValorTotal(p.valor_total);
  // a proposta pode dizer PARA QUAL filial da Eletronet ela foi feita
  if (p.faturamentos && p.faturamentos.length) {
    faturamentos = p.faturamentos.slice();
    renderFaturamentos();
  }
  // ...e para ONDE entregar, quando traz um quadro por localidade
  if (p.entregas && p.entregas.length) {
    entregas = p.entregas.slice();
    renderEntregas();
  }
  // a ESPECIFICAÇÃO TÉCNICA da proposta vira observação da AF
  porObservacoes(p.observacoes);
  const forn = casarFornecedorCatalogo(p);   // reconhece o fornecedor → usa dados oficiais
  renderItems(); atualizarIdPrev();
  ligarPorProdutoSeDiferir();               // itens com prazos/garantias distintos
  schedulePreview();
  if (!forn) avisarFornecedorNaoIdentificado(p);
  return forn;
}

// ---- Proposta CIENA (Excel/DDPTool): 1 proposta → AF (equipamento) + AS (serviço) ----
let _ciena = null;
function aplicarCiena(p) {
  // a planilha traz os destinos e, por eles, as filiais de faturamento
  _ciena = { entregas: p.entregas || [], faturamentos: p.faturamentos || [],
    af: p.af, as: p.as,
    comum: { fornecedor: p.fornecedor, cnpj: p.cnpj, insc_est: p.insc_est,
             endereco: p.endereco, cep: p.cep, moeda: p.moeda || "Dólar Americano",
             prazo: p.prazo_entrega || "", projeto: p.projeto || "", caminho_pdf: p.caminho_pdf || "" } };
  mostrarLadoCiena("af");                     // começa na AF (equipamento)
}
function mostrarLadoCiena(lado) {
  if (!_ciena) return;
  _ciena.atual = lado;
  const s = _ciena[lado], c = _ciena.comum;
  $("fornecedor").value = c.fornecedor || ""; $("cnpj").value = c.cnpj || ""; $("ie").value = c.insc_est || "";
  $("endereco").value = c.endereco || ""; $("cep").value = c.cep || "";
  if (c.moeda) $("moeda").value = c.moeda;    // Dólar Americano
  $("prefixo").value = (lado === "af") ? "AF-E" : "AS-E";   // troca AF ↔ AS
  // Os destinos valem para os DOIS lados: o serviço é executado onde o
  // equipamento é entregue. E as filiais saem da UF de cada destino.
  if (_ciena.entregas.length) { entregas = _ciena.entregas.slice(); renderEntregas(); }
  if (_ciena.faturamentos.length) { faturamentos = _ciena.faturamentos.slice(); renderFaturamentos(); }
  $("prazoUn").value = "Livre"; $("prazoNum").value = c.prazo || ""; syncPronta();   // "24~28 semanas"
  $("objeto").value = s.objeto || "";
  $("valor").value = s.valor_total || "";
  $("dataEmis").value = new Date().toLocaleDateString("pt-BR");
  caminhoPdf = c.caminho_pdf || "";
  items = (s.itens && s.itens.length) ? s.itens.map(it => Object.assign(novoItem(), it)) : [novoItem()];
  casarFornecedorCatalogo({ fornecedor: c.fornecedor, cnpj: c.cnpj });   // dados oficiais CIENA
  renderItems(); renderCienaBar(); atualizarIdPrev(); schedulePreview();
}
function renderCienaBar() {
  const bar = $("cienaBar"); if (!bar) return;
  if (!_ciena) { bar.hidden = true; return; }
  bar.hidden = false;
  const af = _ciena.atual === "af", lado = af ? _ciena.af : _ciena.as;
  const proj = _ciena.comum.projeto ? ` · ${escapeHtml(_ciena.comum.projeto)}` : "";
  $("cienaInfo").innerHTML = `📦 <b>Proposta CIENA</b>${proj} — mostrando <b>${af ? "AF (equipamento)" : "AS (serviço)"}</b> · US$ ${escapeHtml(lado.valor_total || "—")}`;
  $("btnCienaTrocar").textContent = af ? "🔀 Trocar para AS (serviço)" : "🔀 Trocar para AF (equipamento)";
}

// Reconhece de qual fornecedor é a proposta (CNPJ é o mais confiável; senão pelo
// nome) e aplica os dados OFICIAIS do catálogo (CNPJ/IE/endereço/CEP/garantia).
function casarFornecedorCatalogo(p) {
  if (!DATA) return null;
  const dig = s => (s || "").replace(/\D/g, "");
  const cnpjP = dig(p.cnpj);
  let idx = cnpjP ? DATA.fornecedores.findIndex(f => dig(f.cnpj) && dig(f.cnpj) === cnpjP) : -1;
  if (idx < 0) {   // sem CNPJ: casa por uma palavra (4+ letras) do nome extraído
    const nome = (p.fornecedor || "").toLowerCase();
    const prim = (nome.match(/[a-zà-ÿ]{4,}/i) || [""])[0];
    if (prim) idx = DATA.fornecedores.findIndex(f =>
      (f.apelido || "").toLowerCase().includes(prim) || (f.empresa || "").toLowerCase().includes(prim));
  }
  if (idx < 0) return null;
  $("catalogo").value = idx;
  onCatalogo();   // preenche os campos com os dados do catálogo
  return DATA.fornecedores[idx];
}

// ----------------------------------------------- CAMINHO INVERSO: ler AF ---
// Lê uma AF/AS já gerada (.xlsx) e traz TODAS as informações de volta ao
// formulário — p/ revisar, gerar relato (a prévia) e reexportar.
function selectValue(id, v) {
  if (!v) return;
  const sel = $(id);
  const opt = [...sel.options].find(o => o.value === v || o.text === v);
  if (opt) sel.value = opt.value;
}
async function importarAF() {
  const file = $("fileAF").files[0];
  if (!file) return;
  setStatus("Lendo a AF…", "info");
  try {
    const buf = await file.arrayBuffer();
    const r = await api("/api/importar_af", { headers: comNome(file.name), body: buf });
    const d = await r.json();
    if (!d.ok) { setStatus("Não consegui importar: " + (d.erro || "?"), "erro"); return; }
    aplicarAF(d);
    const ni = (d.itens || []).length, nf = (d.faturamentos || []).length, ne = (d.entregas || []).length;
    const avs = (d.avisos || []).join(" • ");
    const cpm = (d.tipo === "CPM" || d.tipo === "CPS");
    const idDoc = cpm ? (d.cpm_id || d.af_id) : d.af_id;
    const detalhe = cpm ? "dados preenchidos na aba CPM/CPS — confira e reexporte"
      : `${ni} item(ns) · ${nf} faturamento(s) · ${ne} entrega(s). Revise e reexporte se quiser`;
    setStatus(`✔ ${d.tipo || "AF"} ${idDoc || ""} importada — ${detalhe}.`
      + (avs ? "  ⚠ " + avs : ""), avs ? "aviso" : "ok");
  } catch (e) { setStatus("Erro ao importar AF: " + e, "erro"); }
  $("fileAF").value = "";
}
function aplicarAF(d) {
  if (d.tipo === "CPM" || d.tipo === "CPS") { aplicarCPMimport(d); return; }
  $("fornecedor").value = d.fornecedor || ""; $("cnpj").value = d.cnpj || ""; $("ie").value = d.insc_est || "";
  $("endereco").value = d.endereco || ""; $("cep").value = d.cep || "";
  $("numProp").value = d.numero_proposta || ""; $("pagto").value = d.condicao_pagamento || "";
  $("objeto").value = d.objeto || "";
  setDur("garantia", d.garantia, "Meses"); setDur("prazo", d.prazo_entrega, "Dias");
  selectValue("moeda", d.moeda);
  $("dataProp").value = "";   // a AF não guarda a data da proposta
  $("dataEmis").value = d.data_emissao || new Date().toLocaleDateString("pt-BR");
  // Identificador (a partir do nº da AF)
  selectValue("prefixo", d.prefixo); $("numero").value = d.numero || ""; $("ano").value = d.ano || "";
  selectValue("mod", d.modificacao); $("rev").value = d.revisao || "0";
  // Itens, faturamento e entrega
  items = (d.itens && d.itens.length) ? d.itens.map(it => Object.assign(novoItem(), it)) : [novoItem()];
  faturamentos = (d.faturamentos || []).slice();
  entregas = (d.entregas || []).slice();
  caminhoPdf = "";            // sem proposta anexa nesta via
  renderItems(); renderFaturamentos(); renderEntregas(); atualizarPreferencias();
  porObservacoes(d.observacoes);            // as que estavam no documento
  ligarPorProdutoSeDiferir();               // a AF importada pode trazer item a item
  $("valor").value = d.valor_total || somaItens() || "";   // valor da AF (autoritativo)
  schedulePreview();
}

// Importar CPM/CPS: reconstrói as bases da AF + preenche a aba CPM e vai p/ lá.
function aplicarCPMimport(d) {
  // bases da AF (a CPM deriva delas)
  $("fornecedor").value = d.fornecedor || ""; $("cnpj").value = d.cnpj || ""; $("ie").value = d.insc_est || "";
  $("valor").value = d.valor_total || ""; selectValue("moeda", d.moeda);
  $("objeto").value = d.objeto || ""; $("pagto").value = d.condicao_pagamento || "";
  $("prazoUn").value = "Livre"; $("prazoNum").value = d.prazo_entrega || ""; syncPronta();
  selectValue("prefixo", d.prefixo); $("numero").value = d.numero || ""; $("ano").value = d.ano || "";
  selectValue("mod", d.modificacao); $("rev").value = d.revisao || "0";
  $("numProp").value = d.numero_proposta || "";
  items = [novoItem()]; faturamentos = []; entregas = [];
  renderItems(); renderFaturamentos(); renderEntregas();
  casarFornecedorCatalogo({ fornecedor: d.fornecedor });
  // campos próprios da CPM
  const s = (id, v) => { if ($(id)) $(id).value = v || ""; };
  s("cpmFinalidade", d.finalidade); s("cpmJustificativa", d.justificativa); s("cpmConsequencias", d.consequencias);
  s("cpmData", d.data_cpm); s("cpmDataRel", d.data_relatorio);
  s("cpmFantasia", d.fornecedor_fantasia); s("cpmAtendimento", d.atendimento);
  s("cpmCotacao", d.cotacao); s("cpmCapex", d.capex);
  // a cortina e um <select>: so aceita o que existe na lista
  if ($("cpmTipoVerba")) $("cpmTipoVerba").value =
    (String(d.tipo_verba || "").toUpperCase() === "OPEX") ? "OPEX" : "CAPEX";
  s("cpmGerente", d.gerente); s("cpmGerenteGeral", d.gerente_geral); s("cpmDiretor", d.diretor);
  s("cpmCfo", d.cfo); s("cpmPresidencia", d.presidencia); s("cpmConselho", d.conselho);
  (d.consultados || []).forEach((c, i) => {
    if (i < 4) { s("cpmForn" + (i + 1), c[0] || ""); s("cpmPrazo" + (i + 1), c[1] || ""); s("cpmVal" + (i + 1), c[2] || ""); }
  });
  // seleciona a alçada pela etiqueta, se casar
  if (d.alcada && DATA && DATA.alcadas) {
    const idx = DATA.alcadas.findIndex(a => d.alcada.includes(a.label) || a.label.includes(d.alcada));
    if (idx >= 0) $("cpmAlcadaSel").value = idx;
  }
  cpmIniciado = true;          // não deixa o autoPreencher sobrescrever o importado
  switchTab("cpm");            // vai p/ a aba CPM (onEnterCPM só atualiza os links + prévia)
}

// ------------------------------------------------ CPM / CPS (origina a AF) --
// Cada campo do form CPM ↔ chave do dict do CPM. Tudo editável.
// Só os campos PRÓPRIOS da CPM. Os principais (fornecedor/valor/proposta/prazo/
// pagamento) NÃO entram aqui — vêm LINKADOS da AF (cpm_de_form deriva deles).
const _CPM_CAMPOS = {
  cpmData: "data_cpm", cpmDataRel: "data_relatorio", cpmFantasia: "fornecedor_fantasia",
  cpmAtendimento: "atendimento", cpmCotacao: "cotacao", cpmCapex: "capex",
  cpmFinalidade: "finalidade", cpmJustificativa: "justificativa", cpmConsequencias: "consequencias",
  cpmGerente: "gerente", cpmGerenteGeral: "gerente_geral", cpmDiretor: "diretor",
  cpmCfo: "cfo", cpmPresidencia: "presidencia", cpmConselho: "conselho",
  cpmCenario: "cenario", cpmProjeto: "projeto", cpmTipoVerba: "tipo_verba",
  // cliente/POP/banda/serviço/CCS/OS/PSC/produtos agora são POR CLIENTE (cards) — ver clientesInfo()
};
let cpmIniciado = false;
function setCpm(msg, cls) { const s = $("cpmInfo"); s.textContent = msg; s.className = "cad-status " + (cls || ""); }
function popularAlcadas() {
  const arr = (DATA && DATA.alcadas) || [];
  const grupos = {};
  arr.forEach((a, i) => { (grupos[a.tipo] = grupos[a.tipo] || []).push({ a, i }); });
  $("cpmAlcadaSel").innerHTML = Object.keys(grupos).map(tipo =>
    `<optgroup label="${escapeHtml(tipo)}">` +
    grupos[tipo].map(o => `<option value="${o.i}">${escapeHtml(o.a.label)}</option>`).join("") +
    `</optgroup>`).join("");
}
// ------------------------------------- assinaturas da AF/AS ---------------
// Gestores que assinam ESTA AF/AS, além das duas linhas de sempre (Eletronet e
// fornecedor). O nome vem sugerido da mesma agenda usada no CPM/CPS.
let assinantesAF = [];
function renderAssinantesAF() {
  $("assinantesList").innerHTML = assinantesAF.map((x, i) =>
    `<div class="pessoa">` +
    `<input class="p-papel" data-ai="${i}" data-ak="papel" value="${escapeHtml(x.papel)}" placeholder="Cargo / setor" />` +
    `<input class="p-nome" data-ai="${i}" data-ak="nome" list="dlPessoas" value="${escapeHtml(x.nome)}" placeholder="Nome de quem assina" />` +
    `<button class="chipx" data-dela="${i}" title="Tirar esta assinatura">✕</button></div>`).join("");
}
function bindAssinantesAF() {
  $("btnAddAssinante").onclick = () => { assinantesAF.push({ papel: "", nome: "" }); renderAssinantesAF();
                                         const c = $("assinantesList").lastElementChild;
                                         if (c) c.querySelector(".p-papel").focus(); };
  $("assinantesList").oninput = (e) => {
    const t = e.target;
    if (t.dataset.ai !== undefined) { assinantesAF[+t.dataset.ai][t.dataset.ak] = t.value; schedulePreview(); }
  };
  $("assinantesList").onclick = (e) => {
    const d = e.target.dataset.dela;
    if (d !== undefined) { assinantesAF.splice(+d, 1); renderAssinantesAF(); schedulePreview(); }
  };
}

// ------------------------------------------- assinantes adicionais --------
// Além dos cargos fixos da alçada, o usuário pode incluir quantas pessoas
// quiser (papel livre + nome). O nome vem sugerido da agenda.
let extras = [];
function renderExtras() {
  $("extrasList").innerHTML = extras.map((x, i) =>
    `<div class="pessoa">` +
    `<input class="p-papel" data-xi="${i}" data-xk="papel" value="${escapeHtml(x.papel)}" placeholder="Cargo / setor" />` +
    `<input class="p-nome" data-xi="${i}" data-xk="nome" list="dlPessoas" value="${escapeHtml(x.nome)}" placeholder="Nome de quem assina" />` +
    `<label class="ass"><input type="checkbox" data-papel="extra${i}"${x.assina === false ? "" : " checked"}><span>assina</span></label>` +
    `<button class="chipx" data-delx="${i}" title="Tirar este assinante">✕</button></div>`).join("");
}
function bindExtras() {
  $("btnAddExtra").onclick = () => { extras.push({ papel: "", nome: "", assina: true }); renderExtras();
                                     const c = $("extrasList").lastElementChild;
                                     if (c) c.querySelector(".p-papel").focus(); };
  $("extrasList").oninput = (e) => {
    const t = e.target;
    if (t.dataset.xi !== undefined) { extras[+t.dataset.xi][t.dataset.xk] = t.value; cpmPreview(); }
  };
  $("extrasList").onchange = (e) => {
    const ck = e.target;
    if (ck.type === "checkbox") {
      const i = +ck.closest(".pessoa").querySelector("[data-xi]").dataset.xi;
      extras[i].assina = ck.checked; cpmPreview();
    }
  };
  $("extrasList").onclick = (e) => {
    const d = e.target.dataset.delx;
    if (d !== undefined) { extras.splice(+d, 1); renderExtras(); cpmPreview(); }
  };
}

function bindCPM() {
  bindExtras();
  $("btnLimparCPM").onclick = () => limparCPM();
  $("btnCpmAuto").onclick = () => autoPreencherCPM(true);
  $("btnCpmPdf").onclick = () => gerarCPM("pdf");
  $("btnCpmExcel").onclick = () => gerarCPM("excel");
  $("cpmAlcadaSel").onchange = onAlcadaSel;   // cortina → preenche os responsáveis
  $("cpmTipoVerba").onchange = cpmPreview;   // troca CAPEX/OPEX → prévia
  $("cpmCenario").onchange = onCenario;       // troca de cenário → mostra CAPEX + regera textos
  $("btnCpmTextos").onclick = gerarTextos;
  $("btnAddCliente").onclick = () => { addClienteCard(null, true, true); cpmPreview(); };
  $("viewCPM").addEventListener("input", (e) => {
    const id = e.target.id;
    if (id === "cpmCotacao") atualizarConv();
    if (id in _CPM_CAMPOS || id.startsWith("cpmForn") || id.startsWith("cpmVal") || id.startsWith("cpmPrazo")
        || e.target.classList.contains("cli-f")) cpmPreview();
  });
  // marcar/desmarcar "assina" não dispara "input" em checkbox em todos os casos
  $("viewCPM").addEventListener("change", (e) => {
    if (e.target.type === "checkbox" && e.target.dataset.papel) cpmPreview();
  });
}
function onCenario() {
  const cen = $("cpmCenario").value;
  $("cpmCapexSec").hidden = (cen === "sem");
  $("btnAddCliente").hidden = (cen !== "varios");     // "+ cliente" só no cenário Vários clientes
  if (cen === "varios") ensureCards(2);               // Vários clientes → no mínimo 2 cards
  else if (cen === "com") ensureCards(1);             // Com cliente → 1 card
  gerarTextos();
}
// ---- vários clientes: 1 CARD por cliente (POP/banda/serviço/CCS/OS/PSC próprios) ----
function cliCards() { return [...document.querySelectorAll("#cpmClientes .cli-card")]; }
function renumeraCli() {
  cliCards().forEach((c, i) => { const n = c.querySelector(".cli-num"); if (n) n.textContent = "Cliente " + (i + 1); });
}
function clienteCardHTML(removivel) {
  return `<div class="cli-card">
    <div class="cli-card-head"><span class="cli-num"></span>${removivel ? '<button type="button" class="cli-del" title="remover cliente">✕ remover</button>' : ""}</div>
    <div class="grid2">
      <div class="f span2"><label>Cliente</label><input class="cli-f cli-nome" placeholder="Razão social do cliente"></div>
      <div class="f"><label>POP origem</label><input class="cli-f cli-popa" placeholder="POP Eletronet Imperatriz"></div>
      <div class="f"><label>POP destino</label><input class="cli-f cli-popb" placeholder="POP Eletronet Belém"></div>
      <div class="f"><label>Banda</label><input class="cli-f cli-banda" placeholder="50G"></div>
      <div class="f"><label>Serviço</label><input class="cli-f cli-servico" placeholder="TRANSPORTE"></div>
      <div class="f"><label>CCS</label><input class="cli-f cli-ccs" placeholder="6587"></div>
      <div class="f"><label>OS</label><input class="cli-f cli-os" placeholder="SPM-698-9745/26"></div>
      <div class="f"><label>PSC/PS</label><input class="cli-f cli-psc" placeholder="110/26"></div>
      <div class="f span2"><label>Produtos/serviços</label><input class="cli-f cli-produtos" placeholder="QSFP28 ZR 100G/120Km"></div>
    </div>
  </div>`;
}
function setCardData(card, d) {
  const s = (sel, v) => { const el = card.querySelector(sel); if (el) el.value = v || ""; };
  s(".cli-nome", d.cliente); s(".cli-popa", d.pop_a); s(".cli-popb", d.pop_b);
  s(".cli-banda", d.banda); s(".cli-servico", d.servico); s(".cli-ccs", d.ccs);
  s(".cli-os", d.os || d.os_num); s(".cli-psc", d.psc); s(".cli-produtos", d.produtos);
}
function getCardData(card) {
  const g = sel => { const el = card.querySelector(sel); return el ? el.value.trim() : ""; };
  return { cliente: g(".cli-nome"), pop_a: g(".cli-popa"), pop_b: g(".cli-popb"),
           banda: g(".cli-banda"), servico: g(".cli-servico"), ccs: g(".cli-ccs"),
           os: g(".cli-os"), psc: g(".cli-psc"), produtos: g(".cli-produtos") };
}
function clientesInfo() { return cliCards().map(getCardData).filter(c => Object.values(c).some(v => v)); }
function addClienteCard(data, removivel, foco) {
  const wrap = document.createElement("div");
  wrap.innerHTML = clienteCardHTML(removivel);
  const card = wrap.firstElementChild;
  if (data) setCardData(card, data);
  const del = card.querySelector(".cli-del");
  if (del) del.onclick = () => {
    card.remove(); renumeraCli();
    const cen = $("cpmCenario").value;            // mantém o mínimo do cenário
    if (cen === "varios") ensureCards(2); else if (cen === "com") ensureCards(1);
    cpmPreview();
  };
  $("cpmClientes").appendChild(card);
  renumeraCli();
  if (foco) { const nome = card.querySelector(".cli-nome"); if (nome) nome.focus(); }
  return card;
}
function ensureCards(min) {                    // 1º card fixo; extras removíveis
  if (!cliCards().length) addClienteCard(null, false, false);
  while (cliCards().length < min) addClienteCard(null, true, false);
}
function setClientCards(lista) {               // recria os cards a partir do backend
  $("cpmClientes").innerHTML = "";
  (lista && lista.length ? lista : [null]).forEach((d, i) => addClienteCard(d, i > 0, false));
}
// Regera finalidade/justificativa/consequências no PADRÃO (cenário + CAPEX + AF).
async function gerarTextos() {
  const c = cpmCampos();
  c.finalidade = ""; c.justificativa = ""; c.consequencias = "";   // vazio → backend gera o padrão
  try {
    const r = await api("/api/cpm_dados", { headers: { "Content-Type": "application/json" }, body: JSON.stringify(Object.assign(collectForm(), c)) });
    const d = await r.json();
    if (!d.ok) return;
    $("cpmFinalidade").value = d.finalidade || "";
    $("cpmJustificativa").value = d.justificativa || "";
    $("cpmConsequencias").value = d.consequencias || "";
    cpmPreview();
  } catch (e) { /* silencioso */ }
}
function onAlcadaSel() {
  const a = (DATA.alcadas || [])[+($("cpmAlcadaSel").value || -1)];
  if (!a) return;
  $("cpmGerente").value = a.gerente || ""; $("cpmGerenteGeral").value = a.gerente_geral || "";
  $("cpmDiretor").value = a.diretor || ""; $("cpmCfo").value = a.cfo || "";
  $("cpmPresidencia").value = a.presidencia || ""; $("cpmConselho").value = a.conselho || "";
  cpmPreview();
}
function cpmAlcadaLabel() {
  const a = (DATA.alcadas || [])[+($("cpmAlcadaSel").value || -1)];
  return a ? a.label : "";
}
function cpmCampos() {
  const o = {};
  for (const id in _CPM_CAMPOS) o[_CPM_CAMPOS[id]] = val(id);
  o.alcada = cpmAlcadaLabel();
  // Quem ASSINA: o responsável desmarcado segue registrado na alçada, mas não
  // ganha linha de assinatura (ex.: só o Diretor assina).
  // Cargos fixos: só os de fora da lista de extras (lá o índice é reatribuído).
  o.assinam = [...document.querySelectorAll(".ass input[type=checkbox]")]
    .filter(ck => ck.checked && !ck.closest("#extrasList")).map(ck => ck.dataset.papel);
  // Assinantes adicionais: linha sem nome é descartada, e o índice de quem
  // ASSINA é recontado sobre a lista já filtrada — senão uma linha vazia no meio
  // deslocava o "extraN" e o visto ia parar na pessoa errada.
  const exs = extras.filter(x => (x.nome || "").trim());
  o.extras = exs.map(x => ({ papel: (x.papel || "").trim(), nome: x.nome.trim() }));
  exs.forEach((x, i) => { if (x.assina !== false) o.assinam.push("extra" + i); });
  const info = clientesInfo();               // 1 conjunto de campos POR CLIENTE (cards)
  o.clientes_info = info;
  o.clientes = info.map(c => c.cliente).filter(Boolean);
  const c0 = info[0] || {};                   // compat escalar (cenário sem/com e ecos)
  o.cliente = c0.cliente || ""; o.pop_a = c0.pop_a || ""; o.pop_b = c0.pop_b || "";
  o.banda = c0.banda || ""; o.servico = c0.servico || ""; o.ccs = c0.ccs || "";
  o.os_num = c0.os || ""; o.psc = c0.psc || ""; o.produtos = c0.produtos || "";
  o.consultados = [];                        // concorrência: [Fornecedor, Prazo, Valor]
  for (let i = 1; i <= 4; i++) {
    const nome = val("cpmForn" + i).trim();
    if (nome) o.consultados.push([nome, val("cpmPrazo" + i), val("cpmVal" + i)]);
  }
  return o;
}
function moedaSimb(m) {
  m = (m || "").toLowerCase();
  if (m.includes("real")) return "R$";
  if (m.includes("dólar") || m.includes("dolar")) return "US$";
  if (m.includes("euro")) return "€";
  if (m.includes("yuan") || m.includes("renminbi")) return "CN¥";
  return "R$";
}
// Cotação = quanto vale 1 unidade da moeda em R$. Mostra a relação e o valor convertido.
function atualizarConv() {
  const simb = moedaSimb(val("moeda"));
  $("cpmMoedaSimb").textContent = simb;
  const isReal = simb === "R$";
  // Em REAL nao existe cotacao: o campo pedia uma taxa que nao se aplica, e
  // quem preenchesse por engano poria no documento uma conversao inventada.
  // Somem os dois — o campo e a linha de conversao — e a verba ocupa a largura
  // inteira, para nao ficar meia linha vazia ao lado.
  $("cpmCotacaoLinha").hidden = isReal;
  $("cpmVerbaLinha").classList.toggle("c12", isReal);
  $("cpmVerbaLinha").classList.toggle("c6", !isReal);
  $("cpmConvLinha").hidden = isReal;
  if (isReal) return;
  const rate = parseBRL(val("cpmCotacao")) || 0, valF = parseBRL(val("valor")) || 0;
  $("cpmConv").value = `1 ${simb} = R$ ${fmtBRL(rate)}   ·   ${simb} ${fmtBRL(valF)} = R$ ${fmtBRL(valF * rate)}`;
}
// Campos LINKADOS (read-only) refletindo a AF.
function cpmLinks() {
  $("cpmFornLink").value = val("fornecedor") || "—";
  $("cpmValorLink").value = val("valor") || "—";
  $("cpmMoedaLink").value = val("moeda") || "Real";
  $("cpmPropLink").value = val("numProp") || "—";
  $("cpmPrazoLink").value = joinDur("prazo") || "—";
  $("cpmPagtoLink").value = val("pagto") || "—";
  const loc = entregas.map(e => e.sigla ? `${e.nome} (${e.sigla})` : e.nome).filter(Boolean).join("; ");
  if (loc) $("cpmLocalLink").value = loc;   // vários locais de entrega (POPs) da AF
}
// Entrou na aba CPM: 1ª vez sincroniza da AF; depois mantém edições e atualiza.
function onEnterCPM() {
  cpmIdsReadonly(); cpmLinks(); atualizarConv();
  if (!cpmIniciado) autoPreencherCPM(false);
  // A prévia é pedida SEMPRE, não só no fim do auto-preenchimento. O
  // `autoPreencherCPM` termina chamando `cpmPreview()` DENTRO do próprio
  // `try`: se o `/api/cpm_dados` falhasse, ele caía no catch e a prévia nunca
  // chegava a ser pedida — a moldura ficava branca por causa de um erro em
  // OUTRA chamada. Chamar aqui não custa uma requisição extra: o `cpmPreview`
  // é adiado em 250ms, então as duas chamadas viram uma só.
  cpmPreview();
}
// "N/A" (ou vazio) = documento SEM modificação: o sufixo some do identificador
// E do nome do arquivo — AF-E-444/2026 e AF-E-444_2026_DATACOM.pdf. Espelha o
// SEM_MODIFICACAO de core/modelos.py.
const _SEM_MOD = ["", "-", "N/A", "NA", "N/D", "NENHUMA"];
function modSufixo(sep) {
  const m = (val("mod") || "").trim();
  return _SEM_MOD.includes(m.toUpperCase()) ? "" : sep + m;
}
function cpmIdsReadonly() {
  const rev = (val("rev") || "").trim(), revP = (rev && rev !== "0") ? `-REV${rev}` : "";
  const pref = val("prefixo"), tipoPref = pref.replace("AF", "CPM").replace("AS", "CPS");
  $("cpmId").value = `${tipoPref}-${val("numero") || "___"}/${val("ano")}${modSufixo("-")}${revP}`;
  $("cpmAf").value = `${pref}-${val("numero") || "___"}/${val("ano")}${modSufixo("-")}${revP}`;
}
async function autoPreencherCPM(forcar) {
  try {
    const r = await api("/api/cpm_dados", { headers: { "Content-Type": "application/json" }, body: JSON.stringify(collectForm()) });
    const d = await r.json();
    if (!d.ok) { setCpm("Falha: " + (d.erro || "?"), "erro"); return; }
    $("cpmId").value = d.cpm_id || ""; $("cpmAf").value = d.af_id || "";
    for (const id in _CPM_CAMPOS) {
      const k = _CPM_CAMPOS[id];
      if (forcar || !val(id)) $(id).value = d[k] || "";   // não sobrescreve edição (a menos que force)
    }
    const idx = (DATA.alcadas || []).findIndex(a => a.label === d.alcada);   // seleciona a faixa
    if (idx >= 0) $("cpmAlcadaSel").value = idx;
    const cen = $("cpmCenario").value;
    $("cpmCapexSec").hidden = (cen === "sem");
    $("btnAddCliente").hidden = (cen !== "varios");
    if ((forcar || !clientesInfo().length) && Array.isArray(d.clientes_info) && d.clientes_info.length)
      setClientCards(d.clientes_info);                  // restaura os cards por cliente
    if (cen === "varios") ensureCards(2); else if (cen === "com") ensureCards(1);
    $("cpmLocalLink").value = d.local_entrega || "";
    if (forcar || !val("cpmForn1")) {   // 1ª linha da concorrência = o recomendado (da AF)
      $("cpmForn1").value = d.fornecedor_completo || "";
      $("cpmPrazo1").value = joinDur("prazo") || "";
      $("cpmVal1").value = d.valor || "";
    }
    cpmIniciado = true; cpmLinks(); atualizarConv();
    setCpm(`✔ Linkado à AF: ${d.cpm_id} → ${d.af_id}. Edite o que for da CPM — a prévia atualiza ao lado.`, "ok");
    cpmPreview();
  } catch (e) { setCpm("Erro: " + e, "erro"); }
}
let _cpmTmr = null;
function cpmPreview() {
  clearTimeout(_cpmTmr);
  _cpmTmr = setTimeout(async () => {
    try {
      const payload = Object.assign(collectForm(), cpmCampos());
      const r = await api("/api/cpm_preview", { headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      $("cpmPreview").srcdoc = await r.text();
    } catch (e) {
      // NÃO engolir. Era este catch silencioso que transformava qualquer falha
      // numa moldura branca sem explicação: quem olha não tem como distinguir
      // "o documento está vazio" de "a prévia não chegou".
      console.warn("prévia do CPM/CPS falhou:", e);
      setCpm("A prévia do CPM/CPS não pôde ser montada (" + e + "). Os campos acima continuam valendo — tente Sincronizar.", "erro");
    }
  }, 250);
}
async function gerarCPM(formato) {
  if (!val("numero").trim()) { setCpm("Informe o número da AF/AS (na aba Gerar AF/AS) para o CPM/CPS-…", "erro"); return; }
  const rev = (val("rev") || "").trim(), revPart = (rev && rev !== "0") ? `-REV${rev}` : "";
  const tipoPref = val("prefixo").replace("AF", "CPM").replace("AS", "CPS");
  const nome = `RTC-${tipoPref}-${val("numero")}_${val("ano")}${modSufixo("_")}${revPart}`;
  setCpm(`Gerando ${formato.toUpperCase()}… (pode levar alguns segundos)`, "");
  const botoes = [$("btnCpmPdf"), $("btnCpmExcel"), $("btnCpmAuto")];
  botoes.forEach(b => b.disabled = true);
  try {
    const payload = Object.assign(collectForm(), cpmCampos(), { formato, cpm_estilo: val("cpmEstilo"), nome_arquivo: nome });
    const r = await api("/api/gerar_cpm", { headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    const res = await r.json();
    if (res.ok) {
      const avs = (res.avisos || []).length
        ? ` &nbsp; ⚠ ${res.avisos.map(escapeHtml).join(" · ")}` : "";
      const s = $("cpmInfo"); s.className = "cad-status " + (avs ? "aviso" : "ok");
      s.innerHTML = `✔ Salvo: <b>${escapeHtml(res.arquivo)}</b> &nbsp; <a href="#" id="cpmAbrir">📂 abrir pasta</a>` + avs;
      $("cpmAbrir").onclick = (e) => { e.preventDefault(); abrirPasta(res.pasta); };
      abrirPasta(res.pasta);
    } else { setCpm("Falha ao gerar: " + (res.erro || "?"), "erro"); }
  } catch (e) { setCpm("Erro: " + e, "erro"); }
  botoes.forEach(b => b.disabled = false);
}

// --------------------------------------------------------------- gerar ----
/* O TOTAL contradiz as próprias linhas do documento?

   Caso real: a proposta da PADTEC foi lida com R$ 4.378,86 (um número solto no
   texto) enquanto a única linha da AF somava R$ 63.311,60. O documento saiu com
   os dois números, um embaixo do outro — o tipo de erro que se vê de longe numa
   AF assinada.

   O aviso já existia, mas na IMPORTAÇÃO: até a hora de gerar ele já tinha sido
   substituído por outra mensagem na barra de status. A conferência tem de ser
   aqui, no instante em que o documento nasce.

   Total MAIOR que a soma é normal — frete, seguro e taxas ficam fora da tabela
   de itens, e essa é a regra do app. Total MENOR não tem essa explicação: ou é
   desconto (raro) ou é total lido errado. Só esse caso pergunta. */
function totalBateComOsItens() {
  const total = parseBRL(val("valor")), soma = parseBRL(somaItens());
  if (total == null || soma == null || soma === 0) return true;
  if (total >= soma - 0.01) return true;             // sobra = frete/seguro: previsto
  const dif = soma - total;
  setStatus(`⚠ O valor total (${fmtBRL(total)}) é MENOR que a soma dos itens ` +
    `(${fmtBRL(soma)}) — faltam ${fmtBRL(dif)}. Confira o total antes de gerar.`, "erro");
  return confirm(
    `O valor total não fecha com os itens.

` +
    `Valor total informado:  ${fmtBRL(total)}
` +
    `Soma dos itens:         ${fmtBRL(soma)}
` +
    `Diferença:              ${fmtBRL(dif)} a menos

` +
    `Um total MENOR que a soma costuma ser total lido errado da proposta — o ` +
    `documento sairia com os dois números se contradizendo.

` +
    `Gerar assim mesmo?`);
}

async function gerar(formato) {
  const erros = [];
  if (!val("numero").trim()) erros.push("número");
  if (!val("fornecedor").trim()) erros.push("fornecedor");
  if (!val("valor").trim()) erros.push("valor total");
  if (erros.length) { setStatus("Preencha: " + erros.join(", "), "erro"); return; }
  if (!totalBateComOsItens()) return;

  const forn = val("fornecedor").split(/[ /-]/)[0];
  const rev = (val("rev") || "").trim();
  const revPart = (rev && rev !== "0") ? `-REV${rev}` : "";
  const nome = `${val("prefixo")}-${val("numero")}_${val("ano")}${modSufixo("_")}${revPart}_${forn}`;
  setStatus(`Gerando ${formato.toUpperCase()}… (pode levar alguns segundos)`, "info");
  const botoes = [$("btnPdf"), $("btnExcel")];
  botoes.forEach(b => b.disabled = true);
  try {
    const payload = Object.assign(collectForm(), { formato, nome_arquivo: nome });
    const r = await api("/api/gerar", { headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    const res = await r.json();
    if (res.ok) {
      descartarRascunho();     // virou documento: o rascunho perdeu a razão de existir
      const pg = res.paginas ? ` · ${res.paginas} págs (proposta anexada)` : "";
      const avs = (res.avisos || []).length
        ? `<br>⚠ ${res.avisos.map(escapeHtml).join(" · ")}` : "";
      const s = $("status"); s.className = "status " + (avs ? "aviso" : "ok");
      s.innerHTML = `✔ <b>Concluído!</b> ${formato.toUpperCase()} salvo em:<br>` +
        `<b>${escapeHtml(res.saida)}</b>${pg}` +
        ` &nbsp; <a href="#" id="lnkAbrir">📂 Abrir pasta</a>` + avs;
      $("lnkAbrir").onclick = (e) => { e.preventDefault(); abrirPasta(res.pasta); };
      abrirPasta(res.pasta);   // abre a subpasta da saída automaticamente
    } else { setStatus("Falha ao gerar: " + (res.erro || "?"), "erro"); }
  } catch (e) { setStatus("Erro ao gerar: " + e, "erro"); }
  botoes.forEach(b => b.disabled = false);
}


/* ===========================================================================
   COMODIDADES — o que todo site tem e aqui faltava.

   Três coisas, na ordem em que doem quando faltam:

   1. DESFAZER o "Limpar". O botão apaga a AF inteira atrás de um confirm(), e
      confirm() protege de clique errado, não de arrependimento. Quem clicou
      "sim" e percebeu no segundo seguinte não tinha volta nenhuma.

   2. RASCUNHO. O app é uma janela: fecha por engano, acaba a bateria, o Windows
      reinicia — e uma AF de 16 itens digitada à mão vai junto. Agora a tela é
      guardada no navegador enquanto se digita e é oferecida de volta na próxima
      abertura. Fica só nesta máquina e neste app; não é o cadastro, é rascunho.

   3. ATALHOS. Ctrl+S e Ctrl+O têm significado fixo na cabeça de quem usa
      computador, e neste app abriam a caixa do navegador ("salvar página como"),
      que aqui não serve para nada. Passam a fazer o que se espera. O "?" mostra
      a lista — atalho que ninguém descobre não existe.
   =========================================================================== */

const _CAMPOS_AF = ["fornecedor", "cnpj", "ie", "endereco", "cep", "dataProp", "numProp",
  "valor", "pagto", "objeto", "numero", "garantiaNum", "prazoNum", "catalogo", "catBusca",
  "rev", "garantiaUn", "prazoUn", "moeda", "prefixo", "mod", "ano", "dataEmis", "pdfEstilo"];
const _MARCAS_AF = ["ckRubricas", "ckRubTodas", "ckImpostos"];

function fotoAF() {
  const campos = {};
  _CAMPOS_AF.forEach(id => { const e = $(id); if (e) campos[id] = e.value; });
  // marcadores guardam `checked`, nao `value` — sem isto, recuperar um rascunho
  // devolvia a AF inteira mas perdia a opcao de rubrica
  const marcas = {};
  _MARCAS_AF.forEach(id => { const e = $(id); if (e) marcas[id] = e.checked; });
  const copia = x => JSON.parse(JSON.stringify(x));
  return {
    campos, marcas, itens: copia(items), faturamentos: copia(faturamentos), entregas: copia(entregas),
    assinantes: copia(assinantesAF), obs: obsRows().map(i => i.value),
    extra: extraDaProposta, caminho: caminhoPdf,
    porItem: [perItemGarantia, perItemPrazo],
  };
}

function porFotoAF(f) {
  if (!f) return;
  Object.entries(f.campos || {}).forEach(([id, v]) => { const e = $(id); if (e) e.value = v; });
  Object.entries(f.marcas || {}).forEach(([id, v]) => { const e = $(id); if (e) e.checked = !!v; });
  // marcar no braço não dispara `onchange`: sem isto a pastilha voltaria
  // apagada (ou com o modo da AF anterior) num rascunho que pedia rubrica
  pintarRubModo();
  items.length = 0; (f.itens || []).forEach(x => items.push(x));
  if (!items.length) items.push(novoItem());
  faturamentos.length = 0; (f.faturamentos || []).forEach(x => faturamentos.push(x));
  entregas.length = 0; (f.entregas || []).forEach(x => entregas.push(x));
  assinantesAF.length = 0; (f.assinantes || []).forEach(x => assinantesAF.push(x));
  $("obsList").innerHTML = "";
  (f.obs || []).forEach(v => addObsRow(v, false));
  renderObsVazio();
  extraDaProposta = f.extra || 0;
  caminhoPdf = f.caminho || "";
  [perItemGarantia, perItemPrazo] = f.porItem || [false, false];
  refletirCatalogo();
  renderItems(); renderFaturamentos(); renderEntregas(); renderAssinantesAF();
  atualizarIdPrev();
  schedulePreview();
}

/* --- 1. desfazer o Limpar ------------------------------------------------ */
let _antesDeLimpar = null;

function desfazerLimpar() {
  if (!_antesDeLimpar) { setStatus("Não há nada para desfazer.", "aviso"); return; }
  porFotoAF(_antesDeLimpar);
  _antesDeLimpar = null;
  atualizarValorTotal();
  setStatus("✔ Limpeza desfeita — a AF voltou como estava.", "ok");
}

/* --- 2. rascunho -------------------------------------------------------- */
const RASCUNHO = "autoaf:rascunho";
let _tmrRascunho = 0;

function temConteudo(f) {
  const c = f.campos || {};
  const digitou = ["fornecedor", "cnpj", "objeto", "valor", "numProp", "numero"]
    .some(k => (c[k] || "").trim());
  const itensCheios = (f.itens || []).some(i => (i.descricao || "").trim() || (i.quantidade || "").trim());
  return digitou || itensCheios;
}

function guardarRascunho() {
  clearTimeout(_tmrRascunho);
  _tmrRascunho = setTimeout(() => {
    try {
      const f = fotoAF();
      // Tela VAZIA não apaga rascunho. Este era o furo: ao abrir o app, o
      // formulário está em branco e o autosave disparava 1,2s depois — apagando
      // justamente o rascunho que acabara de ser oferecido na tela. O descarte
      // agora é só por decisão de alguém: o botão "Descartar" ou o documento
      // gerado (aí a AF virou papel e o rascunho perdeu a razão de existir).
      if (!temConteudo(f)) return;
      localStorage.setItem(RASCUNHO, JSON.stringify({ quando: Date.now(), foto: f }));
    } catch (e) { /* cota cheia ou navegador sem storage: rascunho é bônus */ }
  }, 1200);
}

function descartarRascunho() {
  try { localStorage.removeItem(RASCUNHO); } catch (e) {}
}

const DIAS_RASCUNHO = 7;      // depois disso a AF ou saiu ou foi abandonada

function ofereceRascunho() {
  let d = null;
  try { d = JSON.parse(localStorage.getItem(RASCUNHO) || "null"); } catch (e) { return; }
  if (!d || !d.foto || !temConteudo(d.foto)) return;
  if (Date.now() - (d.quando || 0) > DIAS_RASCUNHO * 864e5) { descartarRascunho(); return; }
  // não oferecer por cima de uma tela já preenchida: quem abriu e começou a
  // digitar não quer o rascunho de ontem passando por cima
  if (temConteudo(fotoAF())) return;
  const quando = new Date(d.quando || Date.now());
  const barra = document.createElement("div");
  barra.className = "rascunho";
  barra.innerHTML = `<span>Há uma AF que ficou pela metade em <b>${
    quando.toLocaleDateString("pt-BR")} ${quando.toLocaleTimeString("pt-BR").slice(0, 5)}</b>.</span>`;
  const sim = document.createElement("button");
  sim.className = "btn primary sm"; sim.textContent = "Recuperar";
  sim.onclick = () => {
    porFotoAF(d.foto);
    atualizarValorTotal();
    barra.remove();
    setStatus("✔ Rascunho recuperado. Confira os valores antes de gerar.", "ok");
  };
  const nao = document.createElement("button");
  nao.className = "btn ghost sm"; nao.textContent = "Descartar";
  nao.onclick = () => { descartarRascunho(); barra.remove(); };
  barra.append(sim, nao);
  const alvo = document.querySelector("#viewGerar .form-col");
  if (alvo) alvo.prepend(barra);
}

/* --- 3. atalhos --------------------------------------------------------- */
const ATALHOS = [
  ["Ctrl + S", "Gerar o PDF"],
  ["Ctrl + O", "Ler uma proposta"],
  ["Ctrl + E", "Baixar em Excel"],
  ["Ctrl + 1 … 4", "Trocar de aba"],
  ["Ctrl + Z", "Desfazer o Limpar"],
  ["Enter / Shift+Enter", "Descer / subir na tabela de itens"],
  ["Esc", "Fechar a busca aberta"],
  ["?", "Esta lista"],
];

function painelAtalhos() {
  let p = $("atalhos");
  if (p) { p.hidden = !p.hidden; return; }
  p = document.createElement("div");
  p.id = "atalhos"; p.className = "atalhos";
  p.innerHTML = "<h3>Atalhos</h3>" + ATALHOS.map(
    ([k, o]) => `<div class="at-linha"><kbd>${k}</kbd><span>${o}</span></div>`).join("")
    + '<div class="at-pe">Esc ou ? para fechar</div>';
  p.onclick = () => p.remove();
  document.body.appendChild(p);
}

function digitando(e) {
  const t = e.target;
  return t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable);
}

function ligarAtalhos() {
  document.addEventListener("keydown", _atalho);
  // A PRÉVIA é um <iframe>. Clicar nela — coisa natural, ela ocupa metade da
  // tela — tira o foco do documento principal, e a partir daí NENHUM atalho
  // respondia: a tecla ia para dentro do quadro. Como a prévia vem do mesmo
  // servidor, dá para ouvir lá dentro também.
  ["preview", "cpmPreview"].forEach(id => {
    const f = $(id);
    if (!f) return;
    f.addEventListener("load", () => {
      try { f.contentDocument.addEventListener("keydown", _atalho); } catch (e) { /* outra origem */ }
    });
  });
}

function _atalho(e) {
  const p = $("atalhos");
  if (e.key === "Escape" && p) { p.remove(); return; }
  // "?" só fora de campo de texto — senão não dá para digitar uma interrogação
  if (e.key === "?" && !digitando(e)) { e.preventDefault(); painelAtalhos(); return; }
  if (!e.ctrlKey || e.altKey) return;
  const acao = {
    s: () => $("btnPdf") && $("btnPdf").click(),          // no navegador abriria "salvar página"
    o: () => $("btnLer") && $("btnLer").click(),          // e aqui, "abrir arquivo"
    e: () => $("btnExcel") && $("btnExcel").click(),
    1: () => switchTab("gerar"), 2: () => switchTab("cpm"),
    3: () => switchTab("cadastros"), 4: () => switchTab("excluir"),
  }[e.key.toLowerCase()];
  if (acao) { e.preventDefault(); acao(); return; }
  // Ctrl+Z fora de campo de texto desfaz o Limpar; dentro dele, o navegador
  // desfaz a digitação, que é o que se espera ali
  if (e.key.toLowerCase() === "z" && !digitando(e) && _antesDeLimpar) {
    e.preventDefault(); desfazerLimpar();
  }
}


init();
