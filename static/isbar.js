// Shows an ISBAR handover ("Identify: ...", "Situation: ..." lines) as a labelled list.
// Text that does not use the labels is shown as it is.
window.isbarView = function (text) {
  const labels = ["Identify", "Situation", "Background", "Assessment", "Recommendation"];
  const parts = [];
  let current = null;
  String(text || "").split(/\r?\n/).forEach(function (line) {
    const m = line.match(/^(Identify|Situation|Background|Assessment|Recommendation):\s*(.*)$/);
    if (m) {
      current = { label: m[1], text: m[2] };
      parts.push(current);
    } else if (current && line.trim()) {
      current.text += " " + line.trim();
    } else if (line.trim()) {
      current = { label: "", text: line.trim() };
      parts.push(current);
    }
  });
  const known = parts.length && parts.every(function (p) { return labels.indexOf(p.label) >= 0; });
  if (!known) {
    const p = document.createElement("p");
    p.style.whiteSpace = "pre-line";
    p.textContent = text;
    return p;
  }
  const dl = document.createElement("dl");
  dl.className = "isbar";
  parts.forEach(function (p) {
    const dt = document.createElement("dt");
    dt.textContent = p.label;
    const dd = document.createElement("dd");
    dd.textContent = p.text;
    dl.append(dt, dd);
  });
  return dl;
};
