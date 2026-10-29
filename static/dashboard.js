// JavaScript / browser / Brawl Room dashboard
(() => {
  const cfg = window.dashboardConfig;
  const target = document.getElementById('target');
  target.value = localStorage.getItem('brawl-target') || 'all';
  if (!target.selectedOptions.length) target.value = 'all';
  target.addEventListener('change', () => localStorage.setItem('brawl-target', target.value));
  for (const form of document.querySelectorAll('.target-form')) {
    form.addEventListener('submit', () => { form.querySelector('[name=target]').value = target.value; });
  }
  const age = seconds => {
    if (!seconds) return 'sem ligação';
    const n = Math.max(0, Math.floor(Date.now() / 1000 - seconds));
    return n < 20 ? 'agora' : n < 60 ? `há ${n} s` : n < 3600 ? `há ${Math.floor(n / 60)} min` : `há ${Math.floor(n / 3600)} h`;
  };
  const refreshTimes = () => {
    document.querySelectorAll('[data-last-seen]').forEach(el => { el.textContent = age(Number(el.dataset.lastSeen)); });
    document.querySelectorAll('[data-time]').forEach(el => { el.textContent = age(Number(el.dataset.time)); });
  };
  const filter = () => {
    const only = document.getElementById('only-online').checked;
    document.querySelectorAll('.device').forEach(card => { card.hidden = only && card.dataset.online !== '1'; });
  };
  document.getElementById('only-online').addEventListener('change', filter);
  const activity = items => {
    const root = document.getElementById('activity');
    root.replaceChildren();
    for (const item of items) {
      const row = document.createElement('div'); row.className = 'event';
      const dot = document.createElement('i'); dot.className = item.status;
      const content = document.createElement('div');
      const title = document.createElement('strong');
      title.textContent = `${item.device_name} · ${cfg.names[item.action] || item.action}`;
      const detail = document.createElement('p'); detail.textContent = item.detail || item.status;
      content.append(title, detail);
      const time = document.createElement('time'); time.dataset.time = item.created;
      row.append(dot, content, time); root.append(row);
    }
    if (!items.length) root.textContent = 'Ainda não há ações.';
  };
  async function refresh() {
    try {
      const response = await fetch(cfg.online, {cache: 'no-store'});
      if (!response.ok) throw Error('status');
      const data = await response.json();
      document.getElementById('connection').classList.toggle('connected', data.online > 0);
      document.getElementById('connection-text').textContent = `${data.online} / ${data.total} ligados`;
      document.getElementById('online-count').textContent = data.online;
      document.getElementById('playing-count').textContent = data.devices.filter(d => d.active_mode).length;
      document.getElementById('queue-count').textContent = data.devices.reduce((sum, d) => sum + d.queued, 0);
      document.getElementById('ranked-count').textContent = data.devices.filter(d => d.ranked_status === 'available').length;
      for (const device of data.devices) {
        const card = document.querySelector(`[data-device="${device.id}"]`);
        if (!card) continue;
        card.dataset.online = device.online ? '1' : '0';
        const status = card.querySelector('[data-status]');
        status.textContent = device.online ? 'Ligado' : 'Desligado';
        status.className = 'status ' + (device.online ? 'on' : 'off');
        card.querySelector('[data-mode]').textContent = device.active_mode === 'farm_ranked' ? 'Ranked ativo' : device.active_mode ? 'Auto farm ativo' : 'Em espera';
        let progress = card.querySelector('[data-progress]');
        if (!progress) {
          progress = document.createElement('p'); progress.dataset.progress = '';
          progress.className = 'progress';
          card.querySelector('.badges').after(progress);
        }
        progress.textContent = device.progress || '';
        progress.hidden = !device.progress;
        card.querySelector('[data-queue]').textContent = `${device.queued} em fila`;
        const rank = card.querySelector('[data-ranked]');
        rank.textContent = device.ranked_status === 'available' ? 'Ranked disponível' : device.ranked_status === 'locked' ? 'Ranked bloqueado' : 'Ranked por verificar';
        rank.className = device.ranked_status;
        card.querySelector('[data-last-seen]').dataset.lastSeen = device.last_seen;
        const shot = card.querySelector('[data-shot]');
        if (shot && device.screenshot_at && Number(shot.dataset.at) !== device.screenshot_at) {
          shot.dataset.at = device.screenshot_at;
          shot.src = shot.src.split('?')[0] + '?t=' + Math.floor(device.screenshot_at);
        }
      }
      activity(data.activity || []);
      filter(); refreshTimes();
    } catch (_) {
      document.getElementById('connection').classList.remove('connected');
    }
  }
  document.getElementById('copy-command').addEventListener('click', async () => {
    const button = document.getElementById('copy-command');
    try {
      await navigator.clipboard.writeText(document.getElementById('agent-command').textContent);
      button.textContent = 'Copiado';
    } catch (_) { button.textContent = 'Seleciona o comando'; }
  });
  refreshTimes(); refresh(); setInterval(refresh, 5000); setInterval(refreshTimes, 1000);
})();
