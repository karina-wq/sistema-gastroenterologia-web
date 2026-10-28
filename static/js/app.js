// Comportamiento de la interfaz: menú móvil, filtros de tablas, confirmaciones, avisos y gráficos.
(function () {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

  // Menú lateral en pantallas pequeñas
  const lateral = $('.barra-lateral'), boton = $('#abrir-menu');
  if (boton && lateral) {
    boton.addEventListener('click', () => lateral.classList.toggle('abierta'));
    document.addEventListener('click', e => {
      if (lateral.classList.contains('abierta') && !lateral.contains(e.target) && e.target !== boton && !boton.contains(e.target)) lateral.classList.remove('abierta');
    });
  }

  // Filtro instantáneo de tablas: <input data-filtro="#idTabla">
  $$('[data-filtro]').forEach(inp => {
    const filas = () => $$(inp.dataset.filtro + ' tbody tr');
    inp.addEventListener('input', () => {
      const q = inp.value.toLowerCase().trim();
      let visibles = 0;
      filas().forEach(tr => { const ok = !q || tr.textContent.toLowerCase().includes(q); tr.style.display = ok ? '' : 'none'; if (ok) visibles++; });
      const cont = $(inp.dataset.contador || '#__none');
      if (cont) cont.textContent = visibles;
    });
  });

  // Confirmación antes de acciones delicadas: <form data-confirmar="¿Seguro?">
  $$('form[data-confirmar]').forEach(f => f.addEventListener('submit', e => { if (!confirm(f.dataset.confirmar)) e.preventDefault(); }));

  // Evita dobles envíos
  $$('form').forEach(f => f.addEventListener('submit', e => {
    if (e.defaultPrevented) return;
    const b = e.submitter || $('button[type=submit]', f);
    if (b && !b.dataset.libre) setTimeout(() => { b.disabled = true; b.dataset.texto = b.innerHTML; b.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Procesando…'; }, 0);
  }));
  window.addEventListener('pageshow', () => $$('button[type=submit][disabled]').forEach(b => { b.disabled = false; if (b.dataset.texto) b.innerHTML = b.dataset.texto; }));

  // Avisos que se ocultan solos (los de error se quedan)
  $$('.alerts-flotantes .alert:not(.alert-danger)').forEach(a => setTimeout(() => { if (window.bootstrap) bootstrap.Alert.getOrCreateInstance(a).close(); }, 6500));

  // Abrir la pestaña indicada en la URL (#procedimientos) y recordarla al cambiar
  const hash = location.hash.replace('#', '');
  if (hash && window.bootstrap) { const t = $(`[data-bs-target="#tab-${hash}"]`); if (t) bootstrap.Tab.getOrCreateInstance(t).show(); }
  $$('[data-bs-toggle="tab"]').forEach(t => t.addEventListener('shown.bs.tab', () => { if (t.dataset.hash) history.replaceState(null, '', '#' + t.dataset.hash); }));

  // Botones que rellenan un modal con datos de la fila: <button data-modal="#m" data-campos='{"id":3}'>
  $$('[data-modal]').forEach(b => b.addEventListener('click', () => {
    const m = $(b.dataset.modal); if (!m) return;
    const datos = JSON.parse(b.dataset.campos || '{}');
    Object.entries(datos).forEach(([k, v]) => { const el = $('[data-campo="' + k + '"]', m); if (!el) return;
      if (el.tagName === 'FORM') el.action = v; else if ('value' in el) el.value = v; else el.textContent = v; });
    bootstrap.Modal.getOrCreateInstance(m).show();
  }));

  // Gráficos (Chart.js): <canvas data-grafico="barras|lineas" data-origen="#idJson">
  const COLORES = { asistio: '#1e9e6a', programada: '#1237c4', inasistio: '#d7263d', reprogramada: '#e39b0b', cancelada: '#7c879c' };
  const ETIQ = { asistio: 'Asistió', programada: 'Programada', inasistio: 'Inasistió', reprogramada: 'Reprogramada', cancelada: 'Cancelada' };
  const PALETA = ['#1237c4', '#d7263d', '#1e9e6a', '#e39b0b'];
  function dibujar(canvas) {
    if (!window.Chart) return;
    const d = JSON.parse($(canvas.dataset.origen).textContent);
    Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
    if (canvas.dataset.grafico === 'barras') {
      new Chart(canvas, { type: 'bar', data: { labels: d.dias, datasets: d.series.map(s => ({ label: ETIQ[s.estado] || s.estado, data: s.valores, backgroundColor: COLORES[s.estado], borderRadius: 4 })) },
        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom' } },
          scales: { x: { stacked: true, grid: { display: false } }, y: { stacked: true, beginAtZero: true, ticks: { precision: 0 } } } } });
    } else if (canvas.dataset.grafico === 'lineas') {
      new Chart(canvas, { type: 'line', data: { labels: d.meses, datasets: d.series.map((s, i) => ({ label: s.nombre, data: s.valores, borderColor: PALETA[i % 4], backgroundColor: PALETA[i % 4] + '22', tension: .3, spanGaps: true, pointRadius: 4, fill: false })) },
        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom' }, tooltip: { callbacks: { label: c => c.dataset.label + ': ' + c.parsed.y + ' %' } } },
          scales: { y: { beginAtZero: true, max: 100, ticks: { callback: v => v + ' %' } }, x: { grid: { display: false } } } } });
    } else if (canvas.dataset.grafico === 'dona') {
      new Chart(canvas, { type: 'doughnut', data: { labels: d.etiquetas.map(e => ETIQ[e] || e), datasets: [{ data: d.valores, backgroundColor: d.etiquetas.map(e => COLORES[e] || '#999'), borderWidth: 2 }] },
        options: { responsive: true, maintainAspectRatio: false, cutout: '62%', plugins: { legend: { position: 'bottom' } } } });
    }
  }
  const pendientes = $$('canvas[data-grafico]');
  pendientes.forEach(c => { if (c.offsetParent !== null) dibujar(c); else c.dataset.espera = '1'; });
  // Gráficos dentro de pestañas ocultas: se dibujan al mostrarse
  $$('[data-bs-toggle="tab"], [data-bs-toggle="pill"]').forEach(t => t.addEventListener('shown.bs.tab', () => {
    $$('canvas[data-espera="1"]').forEach(c => { if (c.offsetParent !== null) { c.dataset.espera = '0'; dibujar(c); } });
  }));
})();
