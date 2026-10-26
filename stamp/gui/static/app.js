const token = document.querySelector('meta[name="stamp-token"]').content;
const grid = document.getElementById("grid");
const countEl = document.getElementById("count");
const statusEl = document.getElementById("status");
const homeEl = document.getElementById("home");
const query = document.getElementById("q");

const addDialog = document.getElementById("add-dialog");
const stampDialog = document.getElementById("stamp-dialog");
const sheetDialog = document.getElementById("sheet-dialog");

let album = { stamps: [], home: "" };
let current = null;

function say(text) {
  statusEl.textContent = text;
  statusEl.hidden = !text;
}

function media(path) {
  const join = path.includes("?") ? "&" : "?";
  return path + join + "t=" + encodeURIComponent(token);
}

async function api(path, body) {
  const res = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers: {
      "X-Stamp-Token": token,
      ...(body === undefined ? {} : { "Content-Type": "application/json" }),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.ok === false) throw new Error(data.error || "Something went wrong");
  return data;
}

function visibleStamps() {
  const q = query.value.trim().toLowerCase();
  if (!q) return album.stamps;
  return album.stamps.filter((s) =>
    [s.label, s.host, s.url, s.short, s.sha256, s.description || ""].join("\n").toLowerCase().includes(q)
  );
}

function render() {
  const stamps = visibleStamps();
  const total = album.stamps.length;
  const noun = total === 1 ? "stamp" : "stamps";
  countEl.textContent = query.value.trim()
    ? `${stamps.length} of ${total} ${noun}`
    : total ? `${total} ${noun}` : "No stamps yet";
  homeEl.textContent = "";
  homeEl.title = album.home ? "Album directory: " + album.home : "";
  grid.replaceChildren();
  if (!stamps.length) {
    const empty = document.createElement("div");
    empty.className = "empty";
    const h = document.createElement("h2");
    h.textContent = total ? "Nothing matches" : "An empty album";
    const p = document.createElement("p");
    p.textContent = total
      ? "Try another word, or clear the filter."
      : "Add the address of a page that mattered. It comes back as a stamp.";
    empty.append(h, p);
    grid.append(empty);
    return;
  }
  stamps.forEach((s, i) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "card";
    btn.dataset.hash = s.sha256;
    const img = document.createElement("img");
    img.src = media(s.svg);
    img.alt = "";
    img.width = 300;
    img.height = 380;
    if (i === 0 && !query.value.trim()) img.setAttribute("fetchpriority", "high");
    else img.loading = "lazy";
    const cap = document.createElement("span");
    cap.className = "cap";
    const name = document.createElement("span");
    name.className = "name";
    name.textContent = s.caption || s.label;
    const meta = document.createElement("span");
    meta.className = "meta";
    meta.textContent = `${s.date} · ${s.short}`;
    cap.append(name, meta);
    btn.append(img, cap);
    btn.addEventListener("click", () => openStamp(s.sha256));
    grid.append(btn);
  });
}

async function load() {
  album = await api("/api/album");
  render();
}

function show(dialog) {
  if (!dialog.open) dialog.showModal();
}

function openAdd() {
  document.getElementById("add-error").hidden = true;
  show(addDialog);
  document.getElementById("url").focus();
}

function fact(dl, term, value) {
  const dt = document.createElement("dt");
  dt.textContent = term;
  const dd = document.createElement("dd");
  if (term === "SHA-256" || term === "Short hash") {
    const code = document.createElement("code");
    code.textContent = value;
    dd.append(code);
  } else {
    dd.textContent = value;
  }
  dl.append(dt, dd);
}

function openStamp(hash) {
  const s = album.stamps.find((item) => item.sha256 === hash || item.short === hash);
  if (!s) return;
  current = s;
  document.getElementById("stamp-title").textContent = s.caption || s.label;
  document.getElementById("stamp-about").textContent = s.description || s.host || s.url;
  const img = document.getElementById("stamp-img");
  img.src = media(s.svg);
  img.alt = s.label;
  const dl = document.getElementById("stamp-facts");
  dl.replaceChildren();
  fact(dl, "Site", s.host || s.url);
  fact(dl, "Address", s.url);
  fact(dl, "Filed", s.fetched_at);
  fact(dl, "Type", s.content_type || "—");
  fact(dl, "Size", s.size_label);
  if (s.number) fact(dl, "Number", String(s.number));
  if (s.status) fact(dl, "Status", String(s.status));
  fact(dl, "Short hash", s.short);
  fact(dl, "SHA-256", s.sha256);
  const result = document.getElementById("verify-result");
  result.hidden = true;
  result.textContent = "";
  show(stampDialog);
}

async function verifyCurrent() {
  if (!current) {
    say("Open a stamp first.");
    return;
  }
  const result = document.getElementById("verify-result");
  result.hidden = false;
  result.textContent = "Checking the filed bytes…";
  result.className = "verify";
  try {
    const data = await api("/api/verify", { hash: current.sha256 });
    result.textContent = data.message;
    result.classList.add(data.match ? "good" : "bad");
    say(data.message);
  } catch (err) {
    result.textContent = err.message;
    result.classList.add("bad");
  }
}

async function openSheet() {
  document.getElementById("sheet-note").textContent = "Composing the sheet…";
  document.getElementById("sheet-img").removeAttribute("src");
  show(sheetDialog);
  try {
    const filtering = query.value.trim().length > 0;
    const hashes = filtering ? visibleStamps().map((s) => s.sha256) : [];
    if (filtering && hashes.length === 0) {
      document.getElementById("sheet-note").textContent = "Nothing matches the filter.";
      return;
    }
    const data = await api("/api/sheet", { hashes });
    const noun = data.count === 1 ? "stamp" : "stamps";
    document.getElementById("sheet-note").textContent =
      `${data.count} ${noun} on ${data.paper.toUpperCase()}, landscape. Cut along the perforations.`;
    const img = document.getElementById("sheet-img");
    img.src = media(data.url) + "&v=" + Date.now();
    say(`Sheet of ${data.count} ready.`);
  } catch (err) {
    document.getElementById("sheet-note").textContent = err.message;
    say(err.message);
  }
}

document.getElementById("add-btn").addEventListener("click", openAdd);
document.getElementById("add-cancel").addEventListener("click", () => addDialog.close());
document.getElementById("sheet-btn").addEventListener("click", openSheet);
document.getElementById("stamp-close").addEventListener("click", () => stampDialog.close());
document.getElementById("sheet-close").addEventListener("click", () => sheetDialog.close());
document.getElementById("verify-btn").addEventListener("click", verifyCurrent);
document.getElementById("open-btn").addEventListener("click", async () => {
  if (!current) return;
  try { await api("/api/open", { url: current.url }); }
  catch (err) { say(err.message); }
});
document.getElementById("reveal-btn").addEventListener("click", async () => {
  if (!current) return;
  try {
    const data = await api("/api/reveal", { what: "stamp", hash: current.sha256 });
    say(data.opened ? "Shown in the Finder." : data.path);
  } catch (err) { say(err.message); }
});
document.getElementById("sheet-reveal").addEventListener("click", async () => {
  try {
    const data = await api("/api/reveal", { what: "sheet" });
    say(data.opened ? "Shown in the Finder." : data.path);
  } catch (err) { say(err.message); }
});
document.getElementById("sheet-print").addEventListener("click", () => {
  const frame = document.getElementById("print-frame");
  frame.onload = () => {
    frame.contentWindow.focus();
    frame.contentWindow.print();
  };
  frame.src = "/print?t=" + encodeURIComponent(token);
});
document.getElementById("redraw-btn").addEventListener("click", async () => {
  try {
    const data = await api("/api/redraw", {});
    await load();
    say(`Redrew ${data.count} ${data.count === 1 ? "stamp" : "stamps"}.`);
  } catch (err) { say(err.message); }
});

query.addEventListener("input", render);

document.getElementById("add-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const error = document.getElementById("add-error");
  const submit = document.getElementById("add-submit");
  error.hidden = true;
  submit.disabled = true;
  submit.textContent = "Filing…";
  say("Fetching the page.");
  const body = {
    url: document.getElementById("url").value,
    title: document.getElementById("title").value,
    description: document.getElementById("description").value,
    no_preview: document.getElementById("no-preview").checked,
  };
  try {
    const data = await api("/api/add", body);
    await load();
    addDialog.close();
    document.getElementById("add-form").reset();
    say(data.message);
    if (data.stamp) openStamp(data.stamp.sha256);
  } catch (err) {
    error.textContent = err.message;
    error.hidden = false;
    say(err.message);
  } finally {
    submit.disabled = false;
    submit.textContent = "File this page";
  }
});

document.addEventListener("keydown", (event) => {
  const typing = /^(INPUT|TEXTAREA)$/.test(event.target.tagName);
  if (event.key === "/" && !typing) {
    event.preventDefault();
    query.focus();
  }
});

// Drop a link anywhere on the album to file it.
for (const type of ["dragover", "dragenter"]) {
  window.addEventListener(type, (event) => {
    if (![...event.dataTransfer.types].includes("text/uri-list") &&
        ![...event.dataTransfer.types].includes("text/plain")) return;
    event.preventDefault();
    document.body.classList.add("drop");
  });
}
window.addEventListener("dragleave", (event) => {
  if (event.target === document.documentElement) document.body.classList.remove("drop");
});
window.addEventListener("drop", (event) => {
  document.body.classList.remove("drop");
  const text = event.dataTransfer.getData("text/uri-list") || event.dataTransfer.getData("text/plain");
  const url = text.split("\n").map((s) => s.trim()).find((s) => /^https?:\/\//i.test(s));
  if (!url) return;
  event.preventDefault();
  document.getElementById("url").value = url;
  openAdd();
});

// Safari has no dialog closedby, so a click on the backdrop closes these.
if (!("closedBy" in HTMLDialogElement.prototype)) {
  for (const dialog of document.querySelectorAll('dialog[closedby="any"]')) {
    let pressedOutside = false;
    const outside = (e) => {
      const r = dialog.getBoundingClientRect();
      return e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom;
    };
    dialog.addEventListener("pointerdown", (e) => { pressedOutside = outside(e); });
    dialog.addEventListener("pointerup", (e) => {
      if (pressedOutside && outside(e)) dialog.close();
    });
  }
}

window.stampNative = {
  addURL: openAdd,
  printSheet: openSheet,
  verifySelected: verifyCurrent,
  revealAlbum: async () => {
    const data = await api("/api/reveal", { what: "album" });
    say(data.opened ? "Shown in the Finder." : data.path);
  },
};

load().catch((err) => {
  countEl.textContent = "Could not open the album";
  say(err.message);
});
