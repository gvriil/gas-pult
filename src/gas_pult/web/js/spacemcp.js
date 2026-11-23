// «Подключения» в пространстве (GAS-38 (в), space_mcp.py): свои интеграции пространства — список, «Подключить» из
// каталога владельца (что просит ключ — ключ вводит человек), «Отключить». Ключ уходит на сервер один раз и в панель
// не возвращается: в списке — название и сервис. Владелец открывает список пространства только для чтения.

let bg = null, data = null, space = "";

const body = (html) => { const b = bg?.querySelector(".s-body"); if (b) b.innerHTML = html; };
const canEdit = () => !space && meta?.role !== "viewer";

function row(s) {
  return `<div class="mrow">${mono(s.name, s.name)}<div class="ctext"><b>${esc(s.name)}</b><small>${esc(s.target || s.type)}</small>
    ${canEdit() && s.removable ? `<div class="scn-opts">${sChip(false, `data-smcp-rm="${esc(s.name)}"`, "Отключить", ic("trash"))}</div>` : ""}</div></div>`;
}

function listHtml() {
  const s = data?.servers || [], p = data?.presets || [];
  const have = new Set(s.map((x) => x.name));
  return `<div id="smcpOut"></div><p class="note">${space ? "Подключения этого пространства — только названия. Ключи хранятся у пространства и сюда не приходят."
      : "Свои подключения этого пространства: ключи хранятся только у него, владельцу и другим пространствам они не видны."}</p>
    ${s.length ? s.map(row).join("") : '<div class="empty">Пока ничего не подключено.</div>'}
    ${canEdit() && p.length ? `<div class="s-lbl">Подключить</div><div class="scn-opts">${p.map((x, i) =>
      sChip(have.has(x.id), `data-smcp-p="${i}"`, x.title, ic(have.has(x.id) ? "check" : "plus"))).join("")}</div>` : ""}`;
}

function formHtml(p) {
  const fields = p.fields.map((f) => `<div class="field"><label for="sm_${f.key}">${esc(f.label)}${f.optional ? ' <span class="opt">— необязательно</span>' : ""}</label>
      <div class="inp">${f.options ? `<select id="sm_${f.key}">${f.options.map((o) => `<option value="${esc(o.v)}">${esc(o.t)}</option>`).join("")}</select>`
        : `<input id="sm_${f.key}" type="${f.secret ? "password" : "text"}" autocomplete="off" autocapitalize="off" spellcheck="false" placeholder="${esc(f.placeholder || "")}">`}</div>
      ${f.hint ? `<div class="hint">${esc(f.hint)}</div>` : ""}</div>`).join("");
  return `<div class="hero">${mono(p.title, p.id)}<h2 class="serif">${esc(p.title)}</h2><p>${esc(clean(p.about))}</p></div>
    ${p.id === "http" ? `<div class="field"><label for="sm__name">Короткое название (латиницей)</label><input id="sm__name" placeholder="например: crm" autocapitalize="off" spellcheck="false"></div>` : ""}
    ${!p.fields.length ? `<div class="result ok">${ic("check")}<span>Ключ не нужен.</span></div>` : ""}
    ${p.key_url && !p.key_url.includes("{") ? `<div class="scn-opts">${sChip(false, `data-smcp-url="${esc(p.key_url)}"`, "Где взять ключ", ic("ext"))}</div>` : ""}
    ${fields}
    <button class="btn wide" type="button" data-smcp-add="${esc(p.id)}">${ic("check")}Подключить</button>
    <div id="smcpOut"></div>
    <div class="scn-opts">${sChip(false, 'data-smcp-back="1"', "Назад к списку", ic("back"))}</div>
    <p class="note">Ключ хранится только в вашем пространстве и в панели больше не показывается.</p>`;
}

async function load() {
  try { data = await api("/api/space/mcp" + (space ? "?space=" + encodeURIComponent(space) : "")); body(listHtml()); }
  catch (e) { body(`<div class="result bad">${ic("warn")}<span>${esc(e.message)}</span></div>`); }
}

async function click(b) {
  const out = () => $("smcpOut");
  if (b.dataset.smcpP) return body(formHtml(data.presets[+b.dataset.smcpP]));
  if (b.dataset.smcpBack) return body(listHtml());
  if (b.dataset.smcpUrl) return openUrl(b.dataset.smcpUrl);
  if (b.dataset.smcpRm) {
    const name = b.dataset.smcpRm;
    return confirmDanger(`Отключить «${name}»?`, async () => {
      try { data = { ...data, servers: (await api("/api/space/mcp/remove", { name })).servers }; body(listHtml()); toast("«" + name + "» отключено"); }
      catch (e) { toast(e.message, 4500); }
    });
  }
  if (b.dataset.smcpAdd) {
    const p = data.presets.find((x) => x.id === b.dataset.smcpAdd);
    if (!(await consentOk({ what: "mcp:" + p.id, id: p.id, title: p.title, about: p.about, kind: "сервер MCP вашего пространства" }))) return;
    const values = Object.fromEntries(p.fields.map((f) => [f.key, $("sm_" + f.key).value]));
    const name = p.id === "http" ? $("sm__name").value.trim() : p.id;
    b.disabled = true; out().innerHTML = `<div class="result wait">${ic("wait")}<span>Подключаю…</span></div>`;
    try {
      const r = await api("/api/space/mcp/add", { preset: p.id, name, values });
      bg.querySelectorAll("input").forEach((x) => { x.value = ""; });          // ключ не держим в странице
      data = { ...data, servers: r.servers }; body(listHtml());
      out().innerHTML = `<div class="result ok">${ic("check")}<span>${esc(p.title)}: ${esc(clean(r.result))}</span></div>`;
      bg.querySelector(".s-body").scrollTop = 0; out().scrollIntoView({ block: "nearest" });
      haptic("notificationOccurred", "success");
    } catch (e) { b.disabled = false; out().innerHTML = `<div class="result bad">${ic("warn")}<span>${esc(e.message)}</span></div>`; haptic("notificationOccurred", "error"); }
  }
}

// slug — владелец смотрит пространство из группы «Пространства» (только названия); без него — своё пространство.
export function open(slug = "") {
  space = slug; data = null;
  bg = sSheet(hv("int.space"), slug ? "Подключения пространства" : "Подключения", '<div class="empty">Загружаю…</div>', click);
  load();
}
