/* Office display is presentation-only. It reads the compiled scorecard so the
 * scoring/rendering code does not need to know how offices are represented. */
(function () {
  const esc = value => String(value ?? '').replace(/[&<>'"]/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
  }[c]));

  const officesFor = profile => {
    const offices = Array.isArray(profile?.offices)
      ? profile.offices.filter(Boolean)
      : profile?.office
        ? [profile.office]
        : [];
    return [...new Set(offices.map(x => String(x).trim()).filter(Boolean))];
  };

  const playerOfficeCount = player =>
    (player?.profiles || []).reduce((sum, profile) => sum + officesFor(profile).length, 0);

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
  };

  const originalRenderPlayers = window.renderPlayers;
  if (typeof originalRenderPlayers === 'function') {
    window.renderPlayers = function () {
      originalRenderPlayers.apply(this, arguments);
      fetch('data/conservative_scorecard.json')
        .then(response => response.json())
        .then(data => decorate(data.players || []))
        .catch(() => {});
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
        node.innerHTML = `<strong>Offices held:</strong> ${esc(offices.length ? offices.join(', ') : 'No office')}`;
        if (!existing) account.appendChild(node);
      });

      const total = playerOfficeCount(player);
      const subtitle = dialog.querySelector('.detail-sub');
      if (subtitle && !subtitle.dataset.officeAdded) {
        subtitle.textContent += ` · ${total === 0 ? 'No office' : `${total} office${total === 1 ? '' : 's'} held`}`;
        subtitle.dataset.officeAdded = '1';
      }
    };
  }
})();