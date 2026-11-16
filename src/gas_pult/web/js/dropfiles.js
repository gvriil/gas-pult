// Перетаскивание и вставка файлов (владелец 17.11, Мак): картинка, брошенная в поле ввода или на ленту, и скриншот из
// буфера (Cmd/Ctrl+V) загружаются так же, как через скрепку, — upload() ядра: /api/upload, сжатие фото (#242),
// миниатюра в ленте (#253). Раньше браузер вставлял в поле текстом локальный путь (/var/folders/…/IMAGE ….jpg) — на
// сервере он бесполезен. Пришёл только путь или file:// без самого файла — подсказка, текст в поле не вставляем.

const FILE_PATH = /^(file:\/\/|\/(var|private|Users|tmp|home)\/|[A-Za-z]:\\)/m;
let depth = 0;

function filesOf(dt) {
  if (!dt) return [];
  const out = [...(dt.files || [])];
  if (!out.length) for (const it of dt.items || []) if (it.kind === "file") { const f = it.getAsFile(); if (f) out.push(f); }
  return out;
}
const hasFiles = (dt) => !!dt && [...(dt.types || [])].some((t) => t === "Files" || t === "application/x-moz-file");
const onlyPath = (dt) => { const t = dt?.getData?.("text/uri-list") || dt?.getData?.("text/plain") || ""; return FILE_PATH.test(t.trim()); };
const stamp = () => new Date().toISOString().slice(0, 19).replace(/[T:]/g, "-");

function named(f) {                                      // скриншот из буфера — «image.png»: даём имя с датой
  if (f.name && !/^image\.(png|jpe?g|gif|webp)$/i.test(f.name)) return f;
  const ext = (f.type.split("/")[1] || "png").replace("jpeg", "jpg");
  return new File([f], `снимок-${stamp()}.${ext}`, { type: f.type, lastModified: Date.now() });
}

function take(list) {
  if (!list.length) return false;
  for (const f of list) upload(named(f), !f.type.startsWith("image/"));   // фото — сжать, документ — как есть
  toast(list.length === 1 ? `Загружаю «${list[0].name || "снимок"}»` : `Загружаю файлов: ${list.length}`);
  return true;
}

function zone(on) { document.body.classList.toggle("drop-on", on); }

addEventListener("dragenter", (e) => { if (hasFiles(e.dataTransfer)) { depth++; zone(true); e.preventDefault(); } }, true);
addEventListener("dragover", (e) => {
  if (hasFiles(e.dataTransfer) || onlyPath(e.dataTransfer)) { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; }
}, true);
addEventListener("dragleave", () => { if (depth && --depth === 0) zone(false); }, true);
addEventListener("drop", (e) => {
  const dt = e.dataTransfer; depth = 0; zone(false);
  if (!hasFiles(dt) && !onlyPath(dt)) return;            // обычный текст — пусть вставится как всегда
  e.preventDefault(); e.stopPropagation();
  if (!take(filesOf(dt))) toast("Браузер передал только путь к файлу, не сам файл. Перетащите файл ещё раз (из Finder) или нажмите скрепку", 6000);
}, true);

$("input").addEventListener("paste", (e) => {
  const list = filesOf(e.clipboardData);
  if (list.length) { e.preventDefault(); take(list); return; }
  const t = e.clipboardData?.getData("text/plain") || "";
  if (FILE_PATH.test(t.trim()) && /\.(jpe?g|png|heic|gif|webp|pdf)$/i.test(t.trim())) {
    toast("Вставлен путь к файлу на компьютере — сервер его не видит. Скопируйте саму картинку или нажмите скрепку", 6000);
  }
});

const css = document.createElement("style");
css.textContent = `body.drop-on #content, body.drop-on #input { outline: 2px dashed var(--accent-primary); outline-offset: -4px;
  background-color: var(--accent-soft); transition: background-color .15s; }`;
document.head.append(css);

Object.assign(window, { dropFilesOf: filesOf });
