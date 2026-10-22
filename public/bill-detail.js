function billEffectDirection(direction) {
  const n = Number(direction);
  if (n === 1) return { label: 'Conservative', sign: '+1', className: 'positive' };
  if (n === -1) return { label: 'Liberal', sign: '−1', className: 'negative' };
  return { label: 'Neutral', sign: '0', className: 'neutral' };
}

function openBill(billOrId) {
  const bill = typeof billOrId === 'object'
    ? billOrId
    : state.data?.bills?.[String(billOrId)];
  const dialog = $('billDialog');
  const detail = $('billDetail');

  if (!bill || !detail) return;

  const provisions = bill.scorecard?.provisions || [];
  const scorable = provisions.filter(p => p.scorable !== false && [-1, 1].includes(Number(p.direction)));
  const total = scorable.reduce((sum, p) => sum + Number(p.direction), 0);
  const alignment = bill.scorecard?.alignment || (total > 0 ? 'Conservative' : total < 0 ? 'Liberal' : 'Neutral / mixed');
  const votes = voteTotals(bill);
  const weight = num(bill.scorecard?.weight);
  const status = bill.status || 'Status unavailable';
  const effectText = total > 0
    ? `This bill would move the scorecard ${Math.abs(total)} point${Math.abs(total) === 1 ? '' : 's'} Conservative.`
    : total < 0
      ? `This bill would move the scorecard ${Math.abs(total)} point${Math.abs(total) === 1 ? '' : 's'} Liberal.`
      : 'This bill would have a neutral effect on the scorecard.';

  detail.innerHTML = `
    <div class="detail-header">
      <p class="eyebrow">BILL DETAIL</p>
      <h2>${esc(bill.title || `Resolution ${bill.resolution_id}`)}</h2>
      <p class="detail-sub bill-status-line">${esc(status)}</p>
    </div>

    <div class="bill-impact">
      <div class="bill-impact-main">
        <span class="eyebrow">SCORECARD EFFECT</span>
        <strong class="${alignmentClass(alignment)}">${esc(total > 0 ? '+' : '')}${total}</strong>
        <p>${esc(effectText)}</p>
      </div>
      <div class="bill-impact-stats">
        <div><span>Alignment</span><strong>${esc(alignment)}</strong></div>
        <div><span>Scored provisions</span><strong>${scorable.length}</strong></div>
        <div><span>Votes</span><strong>${votes.yeas}–${votes.nays}</strong></div>
        ${weight !== null ? `<div><span>Weight</span><strong>${fmt(weight)}×</strong></div>` : ''}
      </div>
    </div>

    <div class="detail-section">
      <h3>How each provision affects the scorecard</h3>
      <div class="provision-list">
        ${provisions.length ? provisions.map(p => {
          const effect = billEffectDirection(p.direction);
          const scorableLabel = p.scorable === false ? 'Not scored' : effect.label;
          return `
            <div class="provision">
              <div>
                <div class="provision-name">${esc(p.name || 'Unnamed provision')}</div>
                <div class="provision-meta">${esc(scorableLabel)}${p.category ? ` · ${esc(p.category)}` : ''}</div>
                ${p.rationale ? `<div class="provision-rationale">${esc(p.rationale)}</div>` : ''}
              </div>
              <strong class="provision-direction ${effect.className}">${p.scorable === false ? '—' : effect.sign}</strong>
            </div>
          `;
        }).join('') : '<div class="empty">No provisions were recorded for this bill.</div>'}
      </div>
    </div>

    <div class="bill-source-row">
      ${bill.url ? `<a href="${esc(bill.url)}" target="_blank" rel="noopener">View source bill</a>` : ''}
    </div>
  `;

  if (typeof dialog.showModal === 'function') dialog.showModal();
  else dialog.setAttribute('open', '');
}
