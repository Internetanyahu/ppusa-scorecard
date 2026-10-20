const state = {
  data: null,
  players: [],
  bills: [],
  filtered: []
};

const $ = (id) => document.getElementById(id);
const esc = (value) => String(value ?? '').replace(/[&<>'"]/g, c => ({
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  "'": '&#39;',
  '"': '&quot;'
}[c]));

const fmt = (n) =>
  Number.isFinite(Number(n))
    ? Number(n).toFixed(Number(n) % 1 ? 2 : 0)
    : '—';

function categoryLabel(category) {
  return category
    ? category.charAt(0).toUpperCase() + category.slice(1)
    : 'Unknown';
}

function billTotal(bill) {
  const provisions = bill.scorecard?.provisions || [];

  return provisions.reduce(
    (sum, p) => sum + (p.direction || 0),
    0
  );
}

function loadData() {
  return Promise.all([
    fetch('data/conservative_scorecard.json').then(r => r.json()),
    fetch('data/scorecard_rules.json').then(r => r.json())
  ]).then(([scorecard, rules]) => {
    state.data = scorecard;
    state.players = scorecard.players || [];

    state.bills = Object.values(scorecard.bills || {})
      .sort(
        (a, b) =>
          Number(a.resolution_id) - Number(b.resolution_id)
      );

    renderSummary(rules);
    applyFilters();
  });
}

function renderSummary(rules) {
  const provisionCount = state.bills.reduce(
    (n, bill) =>
      n + (bill.scorecard?.provisions?.length || 0),
    0
  );

  $('playerCount').textContent = state.players.length;
  $('billCount').textContent = state.bills.length;
  $('provisionCount').textContent = provisionCount;

  $('generatedAt').textContent =
    `Data generated ${new Date(
      state.data.generated_at
    ).toLocaleString()}`;
}

function applyFilters() {
  const q = $('search').value.trim().toLowerCase();
  const tier = $('tier').value;
  const category = $('category').value;

  state.filtered = state.players
    .filter(player => {
      const haystack =
        `${player.name || ''} ${player.discord || ''}`
          .toLowerCase();

      const matchesQuery =
        !q || haystack.includes(q);

      const matchesTier =
        tier === 'all' ||
        player.scores?.tier === tier;

      const categoryScore =
        player.scores?.[category];

      const matchesCategory =
        category === 'all' ||
        Number.isFinite(Number(categoryScore));

      return (
        matchesQuery &&
        matchesTier &&
        matchesCategory
      );
    })
    .sort(
      (a, b) =>
        (b.scores?.overall ?? -1) -
        (a.scores?.overall ?? -1)
    );

  renderPlayers();
  renderBills();
}

function renderPlayers() {
  $('resultCount').textContent =
    `${state.filtered.length} scorecard${
      state.filtered.length === 1 ? '' : 's'
    }`;

  const root = $('scorecards');

  if (!state.filtered.length) {
    root.innerHTML =
      '<div class="empty">No scorecards match the current filters.</div>';
    return;
  }

  root.innerHTML = state.filtered
    .map((p, i) => {
      const s = p.scores || {};

      return `
        <button
          class="scorecard"
          data-player-index="${i}"
        >
          <div class="scorecard-top">
            <div>
              <h3>${esc(p.name)}</h3>
              <div class="handle">
                ${esc(p.discord || 'No handle listed')}
              </div>
            </div>

            <div class="tier tier-${esc(s.tier || '')}">
              ${esc(s.tier || '—')}
            </div>
          </div>

          <div class="score-main">
            <strong>${fmt(s.overall)}</strong>
            <span>/ 100</span>
          </div>

          <div class="mini-bars">
            ${['social', 'economic', 'foreign']
              .map(cat => {
                const value = Number(s[cat]);

                const width =
                  Number.isFinite(value)
                    ? Math.max(
                        0,
                        Math.min(100, value)
                      )
                    : 0;

                return `
                  <div class="mini-row">
                    <span>
                      ${categoryLabel(cat)}
                    </span>

                    <div class="bar">
                      <span
                        style="width:${width}%"
                      ></span>
                    </div>

                    <span class="mini-value">
                      ${
                        Number.isFinite(value)
                          ? fmt(value)
                          : 'N/A'
                      }
                    </span>
                  </div>
                `;
              })
              .join('')}
          </div>
        </button>
      `;
    })
    .join('');

  root
    .querySelectorAll('[data-player-index]')
    .forEach(btn => {
      btn.addEventListener('click', () => {
        openPlayer(
          state.filtered[
            Number(btn.dataset.playerIndex)
          ]
        );
      });
    });
}

function renderBills() {
  const root = $('bills');

  root.innerHTML = state.bills
    .map((bill, i) => {
      const total = billTotal(bill);
      const count =
        bill.scorecard?.provisions?.length || 0;

      return `
        <button
          class="bill-card"
          data-bill-index="${i}"
        >
          <div class="bill-meta">
            <span>${esc(bill.number)}</span>
            <span>
              ${count}
              provision${count === 1 ? '' : 's'}
            </span>
          </div>

          <h3>${esc(bill.title)}</h3>

          <div class="bill-meta">
            <span>${esc(bill.status)}</span>

            <span
              class="bill-score ${
                total >= 0
                  ? 'positive'
                  : 'negative'
              }"
            >
              ${total > 0 ? '+' : ''}${total}
            </span>
          </div>
        </button>
      `;
    })
    .join('');

  root
    .querySelectorAll('[data-bill-index]')
    .forEach(btn => {
      btn.addEventListener('click', () => {
        openBill(
          state.bills[
            Number(btn.dataset.billIndex)
          ]
        );
      });
    });
}

function openPlayer(player) {
  const s = player.scores || {};
  const details = player.bill_details || [];

  const aligned =
    details.filter(d => d.aligned);

  $('scorecardDetail').innerHTML = `
    <div class="detail-header">
      <p class="eyebrow">
        LEGISLATOR SCORECARD
      </p>

      <h2>${esc(player.name)}</h2>

      <p class="detail-sub">
        ${esc(
          player.discord ||
          'No Discord handle listed'
        )}
        ·
        ${player.provisions_scored || 0}
        provisions scored
      </p>
    </div>

    <div class="detail-score">
      <div class="detail-stat">
        <span>Overall</span>
        <strong>
          ${fmt(s.overall)}
          ·
          ${esc(s.tier || '—')}
        </strong>
      </div>

      <div class="detail-stat">
        <span>Social</span>
        <strong>
          ${
            Number.isFinite(Number(s.social))
              ? fmt(s.social)
              : 'N/A'
          }
        </strong>
      </div>

      <div class="detail-stat">
        <span>Economic</span>
        <strong>
          ${
            Number.isFinite(Number(s.economic))
              ? fmt(s.economic)
              : 'N/A'
          }
        </strong>
      </div>

      <div class="detail-stat">
        <span>Foreign</span>
        <strong>
          ${
            Number.isFinite(Number(s.foreign))
              ? fmt(s.foreign)
              : 'N/A'
          }
        </strong>
      </div>
    </div>

    <p class="muted">
      ${aligned.length}
      of
      ${details.length}
      scored provisions aligned with the
      conservative position.
    </p>

    <div class="vote-row">
      <span>Aligned provisions</span>
      <strong>${aligned.length}</strong>
    </div>

    <div class="vote-row">
      <span>Scored provisions</span>
      <strong>${details.length}</strong>
    </div>

    <div style="margin-top:24px">
      <p class="eyebrow">
        VOTING RECORD
      </p>

      <div class="provision-list">
        ${
          details.length
            ? details
                .map(d => `
                  <div class="provision">
                    <div>
                      <div class="provision-name">
                        ${esc(
                          d.provision ||
                          'Provision'
                        )}
                      </div>

                      <div class="provision-note">
                        ${categoryLabel(d.category)}
                        ·
                        ${
                          d.vote
                            ? esc(d.vote)
                            : 'No vote recorded'
                        }
                      </div>
                    </div>

                    <div
                      class="
                        direction
                        ${
                          d.direction > 0
                            ? 'positive'
                            : 'negative'
                        }
                      "
                    >
                      ${
                        d.direction > 0
                          ? '+1'
                          : '−1'
                      }

                      ${
                        d.aligned
                          ? 'Aligned'
                          : 'Not aligned'
                      }
                    </div>
                  </div>
                `)
                .join('')
            : '<div class="empty">No scored provisions.</div>'
        }
      </div>
    </div>
  `;

  $('scorecardDialog').showModal();
}

function openBill(bill) {
  const provisions =
    bill.scorecard?.provisions || [];

  const total = billTotal(bill);

  $('billDetail').innerHTML = `
    <div class="detail-header">
      <p class="eyebrow">
        FINALIZED BILL
      </p>

      <h2>
        ${esc(bill.number)}
        —
        ${esc(bill.title)}
      </h2>

      <p class="detail-sub">
        ${esc(bill.status)}
        ·
        Introduced
        ${esc(bill.introduced || '—')}
        ·
        Passed
        ${esc(bill.passed || '—')}
      </p>
    </div>

    <div class="detail-score">
      <div class="detail-stat">
        <span>Provision count</span>
        <strong>${provisions.length}</strong>
      </div>

      <div class="detail-stat">
        <span>Rightward</span>
        <strong>
          ${
            provisions.filter(
              p => p.direction > 0
            ).length
          }
        </strong>
      </div>

      <div class="detail-stat">
        <span>Leftward</span>
        <strong>
          ${
            provisions.filter(
              p => p.direction < 0
            ).length
          }
        </strong>
      </div>

      <div class="detail-stat">
        <span>Net direction</span>
        <strong>
          ${total > 0 ? '+' : ''}${total}
        </strong>
      </div>
    </div>

    <p class="eyebrow">
      PROVISIONS
    </p>

    <div class="provision-list">
      ${
        provisions
          .map(p => `
            <div class="provision">
              <div>
                <div class="provision-name">
                  ${esc(p.name)}
                </div>

                <div class="provision-note">
                  ${categoryLabel(p.category)}
                  ·
                  ${esc(
                    p.rationale ||
                    'No rationale listed.'
                  )}
                  · Rule:
                  ${esc(
                    p.rule_id ||
                    'fallback'
                  )}
                </div>

                ${
                  p.current_law
                    ? `
                      <div class="provision-note">
                        Current-law reference:
                        ${esc(
                          JSON.stringify(
                            p.current_law
                          )
                        )}
                      </div>
                    `
                    : ''
                }
              </div>

              <div
                class="
                  direction
                  ${
                    p.direction > 0
                      ? 'positive'
                      : 'negative'
                  }
                "
              >
                ${
                  p.direction > 0
                    ? '+1'
                    : '−1'
                }
              </div>
            </div>
          `)
          .join('')
      }
    </div>
  `;

  $('billDialog').showModal();
}

document.addEventListener(
  'DOMContentLoaded',
  () => {
    ['search', 'tier', 'category'].forEach(
      id => {
        $(id).addEventListener(
          'input',
          applyFilters
        );
      }
    );

    document
      .querySelectorAll('[data-close]')
      .forEach(btn => {
        btn.addEventListener(
          'click',
          () =>
            btn
              .closest('dialog')
              .close()
        );
      });

    document
      .querySelectorAll('dialog')
      .forEach(dialog => {
        dialog.addEventListener(
          'click',
          e => {
            if (e.target === dialog) {
              dialog.close();
            }
          }
        );
      });

    loadData().catch(error => {
      console.error(error);

      $('scorecards').innerHTML =
        '<div class="empty">Unable to load scorecard data. Check that public/data is present.</div>';
    });
  }
);
