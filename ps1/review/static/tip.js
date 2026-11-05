/* The hover dictionary: a token of the Japanese (`span.tok[data-g]`, built by
   rubyHtml from the server's tokens) shows its JMdict entry in one floating
   box beside the pointer. Used by the review page. */
(function () {
  const tip = document.createElement('div');
  tip.id = 'tip'; tip.hidden = true;
  document.body.appendChild(tip);
  let cur = null;
  function place(ev) {
    const pad = 14, w = tip.offsetWidth, h = tip.offsetHeight;
    let x = ev.clientX + pad, y = ev.clientY + pad;
    if (x + w > innerWidth - 8) x = ev.clientX - w - pad;
    if (y + h > innerHeight - 8) y = ev.clientY - h - pad;
    tip.style.left = Math.max(4, x) + 'px'; tip.style.top = Math.max(4, y) + 'px';
  }
  document.addEventListener('mouseover', ev => {
    const t = ev.target.closest && ev.target.closest('.tok[data-g]');
    if (!t || t === cur) return;
    cur = t;
    tip.textContent = t.dataset.g;
    tip.hidden = false;
    place(ev);
  });
  document.addEventListener('mousemove', ev => { if (!tip.hidden) place(ev); });
  document.addEventListener('mouseout', ev => {
    const t = ev.target.closest && ev.target.closest('.tok[data-g]');
    if (t && t === cur && !(ev.relatedTarget && t.contains(ev.relatedTarget))) { cur = null; tip.hidden = true; }
  });
})();
