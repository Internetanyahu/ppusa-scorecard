/* Office display is presentation-only. The compiled scorecard is authoritative. */
(function () {
  const esc = value => String(value ?? '').replace(/[&<>'"]/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
  }[c]));

  const style = document.createElement('style');
  style.textContent = '.office-display-pending .profile-strip{visibility:hidden}.office-display-ready .profile-strip{visibility:visible}';
  document.head.appendChild(style);
  document.documentElement.classList.add('office-display-pending');

  const officesFor = profile => {
    const offices = Array.isArray(profile?.offices)
      ? profile.offices.filter(Boolean)
      : profile?.office
        ? [profile.office]
        : [];
    return [...new Set(offices.map(x => String(x).trim()).filter(Boolean))];
  };

  const playerOfficeCount = player => {
    const explicit = Number(player?.office_count ?? player?.offices_held);
    if (Number.isFinite(explicit) && explicit >= 0) return explicit;
    return (player?.profiles || []).reduce((sum, profile) => sum + officesFor(profile).length, 0);
  };

  const decorate = players => {
    document.querySelectorAll('[data-player-index]').forEach(card => {
      const name = card.querySelector('h3')?.textContent?.trim();
      const player = players.find(p => p.name === name);
      if (!player) return;

      const count = playerOfficeCount(player);
      const label = count === 0 ? 'No office' : `${count} office${count === 1 ? '' : 's'} held`;
      const strong = card.querySelector('.profile-strip strong');
      if (strong) strong.textContent = label;

      card.querySelectorAll('.profile-chip').forEach((chip, index) => {
        const profile = player.profiles?.[index];
        if (!profile) return;
        const offices = officesFor(profile);
        const location = [profile.chamber, profile.state].filter(Boolean).join(' · ');
        chip.innerHTML = `<strong>${esc(profile.name || 'Unknown')}</strong> · ${esc(location)} · ${esc(offices.length ? offices.join(', ') : 'No office')}`;
      });
    });
    document.documentElement.classList.remove('office-display-pending');
    document.documentElement.classList.add('office-display-ready');
  };

  const originalRenderPlayers = window.renderPlayers;
  if (typeof originalRenderPlayers === 'function') {
    window.renderPlayers = function () {
      originalRenderPlayers.apply(this, arguments);
      fetch('data/conservative_scorecard.json', { cache: 'no-store' })
        .then(response => response.json())
        .then(data => decorate(data.players || []))
        .catch(error => {
          console.error('Office display data error:', error);
          document.documentElement.classList.remove('office-display-pending');
          document.documentElement.classList.add('office-display-ready');
        });
    };
  }

  const originalOpenPlayer = window.openPlayer;
  if (typeof originalOpenPlayer === 'function') {
    window.openPlayer = function (player) {
      originalOpenPlayer.apply(this, arguments);
      const dialog = document.querySelector('#scorecardDetail');
      if (!dialog) return;

      const accounts = dialog.querySelectorAll('.account');
      (player.profiles || []).forEach((profile, index) => {
        const account = accounts[index];
        if (!account) return;
        const offices = officesFor(profile);
        const existing = account.querySelector('.office-detail');
        const node = existing || document.createElement('span');
        node.className = 'office-detail';
        node.innerHTML = `<strong>Office:</strong> ${esc(offices.length ? offices.join(', ') : 'No office')}`;
        if (!existing) account.appendChild(node);
      });
    };
  }
})();
