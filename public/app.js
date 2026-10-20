const state = {
  data: null,
  players: [],
  bills: [],
  pending: [],
  filtered: [],
  problemsOnly: false,
  rules: null,
  baseData: null,
  adminUnlocked: false,
  adminOverrides: {}
};

const $ = id => document.getElementById(id);

const esc = v => String(v ?? '').replace(/[&<>'"]/g, c => ({
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  "'": '&#39;',
  '"': '&quot;'
}[c]));

const num = v =>
  v === null || v === undefined || v === '' || !Number.isFinite(Number(v))
    ? null
    : Number(v);

const fmt = v =>
  num(v) === null ? 'N/A' : Number(v).toFixed(Number(v) % 1 ? 2 : 0);

const label = v =>
  v ? v.charAt(0).toUpperCase() + v.slice(1) : 'Unknown';

const IDEOLOGY = {
  social: [
    'Mega Woke', 'Woke', 'Wokelite', 'Left-Leaning', 'Moderate',
    'Right-Leaning', 'Chudlite', 'Chud', 'Giga Chud'
  ],
  economic: [
    'Communist', 'Socialist', 'Progressive', 'Social Democrat',
    'Mixed-Market', 'Center-Right', 'Conservative',
    'Lite-Libertarian', 'True Libertarian'
  ],
  foreign: [
    'Warhawk', 'Neocon', 'Lite Neocon', 'Interventionist',
    'Moderate', 'Hemispherist', 'Contra', 'Patriot', 'Gigapatriot'
  ]
};

function ideology(cat, v) {
  const n = num(v);
  if (n === null) return 'N/A';
  if (!IDEOLOGY[cat]) return '';
  return IDEOLOGY[cat][Math.max(0, Math.min(8, Math.floor(n / 10) - 1))];
}

const partyLabel = v => ({
  gop: 'GOP',
  dem: 'Dem',
  grn: 'Green',
  cst: 'Constitutional'
})[String(v || '').toLowerCase()] || String(v || 'Other');

const initials = v =>
  String(v || '?')
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map(x => x[0])
    .join('')
    .toUpperCase();

function avatar(p) {
  return p.avatar
    ? `<img class="avatar" src="${esc(p.avatar)}" alt="">`
    : `<div class="avatar-fallback">${esc(initials(p.name))}</div>`;
}

function billTotal(b) {
  return (b.scorecard?.provisions || []).reduce(
    (sum, p) => sum + (p.scorable === false ? 0 : (p.direction || 0)),
    0
  );
}

function siteUrl(path = '') {
  return new URL(path, window.location.href).href;
}

function profileUrl(profileId) {
  return profileId
    ? `https://powerplayusa.net/wiki/politician/${encodeURIComponent(profileId)}`
    : null;
}

function shareUrl(player) {
  const id = player.user_id || player.player_id;
  return siteUrl(`share/${encodeURIComponent(id)}/`);
}

function billUrl(resolutionId) {
  const bill = state.data?.bills?.[String(resolutionId)];
  return bill?.url || siteUrl(`?bill=${encodeURIComponent(resolutionId)}`);
}

function voteTotals(bill) {
  const status = String(bill?.status || '').toLowerCase();

  let chamber = status.includes('house')
    ? bill?.votes?.house
    : status.includes('senate')
      ? bill?.votes?.senate
      : null;

  if (!chamber) {
    const house = bill?.votes?.house;
    const senate = bill?.votes?.senate;

    const houseCount =
      (house?.aye?.length || 0) +
      (house?.nay?.length || 0);

    const senateCount =
      (senate?.aye?.length || 0) +
      (senate?.nay?.length || 0);

    chamber = houseCount >= senateCount ? house : senate;
  }

  return {
    yeas: chamber?.aye?.length || 0,
    nays: chamber?.nay?.length || 0
  };
}

function alignmentClass(alignment) {
  return alignment === 'Conservative'
    ? 'positive'
    : alignment === 'Liberal'
      ? 'negative'
      : 'neutral';
}

async function loadData() {
  const [scorecardResponse, rulesResponse] = await Promise.all([
    fetch('data/conservative_scorecard.json'),
    fetch('data/scorecard_rules.json')
  ]);

  if (!scorecardResponse.ok || !rulesResponse.ok) {
    throw new Error('Unable to load scorecard data or scoring rules.');
  }

  const [scorecard, rules] = await Promise.all([
    scorecardResponse.json(),
    rulesResponse.json()
  ]);

  state.baseData = structuredClone(scorecard);
  state.rules = rules;

  const stored = localStorage.getItem('ppusa_admin_policy_v1');

  if (stored) {
    try {
      const parsed = JSON.parse(stored);

      if (parsed && parsed.provision_overrides) {
        state.adminOverrides = parsed.provision_overrides;
      }
    } catch (_) {
      localStorage.removeItem('ppusa_admin_policy_v1');
    }
  }

  applyAdminPolicy(true);
}

const ADMIN_SECRET_HASH =
  '4fed7d100abaeae41e5f614b747bf78f9047b5cc055e521eec3de0cadbe4cc0d';

const ADMIN_DIRECTION_OPTIONS = `
  <option value="1">+1 — Conservative</option>
  <option value="0">0 — Neutral</option>
  <option value="-1">−1 — Liberal</option>
`;

function directionLabel(v) {
  const n = Number(v);

  if (n === 1) return 'Conservative (+1)';
  if (n === -1) return 'Liberal (−1)';

  return 'Neutral (0)';
}

function normalizeAdminOverride(name, value, fallback) {
  const base = fallback || {};
  const direction = Number(value?.direction);

  return {
    direction: [-1, 0, 1].includes(direction)
      ? direction
      : Number(base.direction ?? 0),
    category: value?.category ?? base.category ?? null,
    rationale:
      value?.rationale ||
      base.rationale ||
      'Assigned by the site policy editor.',
    group: value?.group ?? base.group ?? null
  };
}

function provisionAssignment(name) {
  const overrides = state.adminOverrides || {};
  const configured = overrides[name];

  if (configured) {
    return normalizeAdminOverride(name, configured, configured);
  }

  const base =
    state.rules?.admin_policy?.provision_overrides?.[name];

  if (base) {
    return normalizeAdminOverride(name, base, base);
  }

  const bill = state.bills.find(b =>
    (b.scorecard?.provisions || []).some(p => p.name === name)
  );

  const provision =
    bill?.scorecard?.provisions?.find(p => p.name === name);

  return normalizeAdminOverride(
    name,
    provision || {},
    provision || {}
  );
}

function allProvisionNames() {
  const names = new Set();

  Object.values(state.baseData?.bills || {}).forEach(b => {
    (b.scorecard?.provisions || []).forEach(p => {
      if (p.name) names.add(p.name);
    });
  });

  return [...names].sort((a, b) => a.localeCompare(b));
}

function cloneBase() {
  return structuredClone(state.baseData);
}

function recalculatePlayer(player, bills) {
  const details = (player.bill_details || []).map(detail => {
    const bill = bills[String(detail.resolution_id)];

    const provision = bill?.scorecard?.provisions?.find(
      p => p.name === detail.provision
    );

    if (!provision) {
      return {
        ...detail,
        direction: 0,
        category: null,
        scorable: false,
        aligned: false
      };
    }

    const direction = Number(provision.direction);
    const vote = String(detail.vote || '').toLowerCase();

    return {
      ...detail,
      direction,
      category: provision.category ?? null,
      scorable:
        provision.scorable !== false &&
        [-1, 1].includes(direction),
      aligned:
        direction === 1
          ? vote === 'aye'
          : direction === -1
            ? vote === 'nay'
            : false,
      weight:
        bill.scorecard?.weight ??
        detail.weight ??
        1
    };
  });

  const scored = details.filter(
    x =>
      x.scorable !== false &&
      [-1, 1].includes(Number(x.direction))
  );

  const counts = {};

  ['social', 'economic', 'foreign'].forEach(cat => {
    counts[cat] =
      scored.filter(x => x.category === cat).length;
  });

  const categoryScores = {};

  ['social', 'economic', 'foreign'].forEach(cat => {
    const rows =
      scored.filter(x => x.category === cat);

    if (rows.length < 3) {
      categoryScores[cat] = null;
      return;
    }

    const denominator = rows.reduce(
      (sum, x) => sum + Number(x.weight ?? 1),
      0
    );

    const aligned = rows
      .filter(x => x.aligned)
      .reduce(
        (sum, x) => sum + Number(x.weight ?? 1),
        0
      );

    categoryScores[cat] =
      denominator
        ? 100 * aligned / denominator
        : null;
  });

  const eligible =
    Object.values(counts).some(n => n >= 3);

  const denominator = scored.reduce(
    (sum, x) => sum + Number(x.weight ?? 1),
    0
  );

  const aligned = scored
    .filter(x => x.aligned)
    .reduce(
      (sum, x) => sum + Number(x.weight ?? 1),
      0
    );

  const overall =
    eligible && denominator
      ? 100 * aligned / denominator
      : null;

  return {
    ...player,
    bill_details: details,
    scores: {
      ...categoryScores,
      overall,
      tier:
        overall === null
          ? 'N/A'
          : overall >= 90
            ? 'A+'
            : overall >= 80
              ? 'A'
              : overall >= 70
                ? 'B'
                : overall >= 60
                  ? 'C'
                  : overall >= 50
                    ? 'D'
                    : 'F'
    },
    sample_size: {
      ...counts,
      overall: scored.length
    },
    provisions_scored: scored.length,
    aligned_provisions:
      scored.filter(x => x.aligned).length,
    aligned_votes:
      scored.filter(x => x.aligned).length,
    eligible_for_grade: eligible
  };
}

function applyAdminPolicy(render = true) {
  const data = cloneBase();
  const overrides = state.adminOverrides || {};

  Object.values(data.bills || {}).forEach(bill => {
    const provisions =
      bill.scorecard?.provisions || [];

    provisions.forEach(provision => {
      const assignment =
        overrides[provision.name] ||
        state.rules?.admin_policy?.provision_overrides?.[
          provision.name
        ];

      if (!assignment) return;

      const direction =
        Number(assignment.direction);

      provision.direction = direction;
      provision.category =
        assignment.category ?? null;

      provision.scorable =
        direction !== 0;

      provision.source = 'admin';

      provision.rule_id =
        `ADMIN-${assignment.group || 'EXACT'}`;

      provision.rationale =
        assignment.rationale ||
        'Assigned by the site policy editor.';
    });

    const scored = provisions.filter(
      p =>
        p.scorable !== false &&
        [-1, 1].includes(Number(p.direction))
    );

    const total = scored.reduce(
      (sum, p) =>
        sum + Number(p.direction),
      0
    );

    bill.scorecard.total = total;
    bill.scorecard.scored_provisions =
      scored.length;

    bill.scorecard.alignment =
      total > 0
        ? 'Conservative'
        : total < 0
          ? 'Liberal'
          : 'Neutral / mixed';
  });

  data.players =
    (data.players || []).map(
      player =>
        recalculatePlayer(
          player,
          data.bills
        )
    );

  state.data = data;
  state.players = data.players || [];

  state.bills =
    Object.values(data.bills || {})
      .sort(
        (a, b) =>
          Number(a.resolution_id) -
          Number(b.resolution_id)
      );

  state.pending =
    data.pending_bills || [];

  if (render) {
    renderSummary();
    renderPending();
    applyFilters();
    renderAdminPanel();
  }
}

function persistAdminPolicy() {
  const payload = {
    version: 1,
    provision_overrides:
      state.adminOverrides
  };

  localStorage.setItem(
    'ppusa_admin_policy_v1',
    JSON.stringify(payload)
  );
}

function setAdminAssignment(name, direction) {
  const base =
    state.rules.admin_policy.provision_overrides[name];

  if (!base) return;

  state.adminOverrides[name] =
    normalizeAdminOverride(
      name,
      {
        ...base,
        direction: Number(direction)
      },
      base
    );

  persistAdminPolicy();
  applyAdminPolicy();
}

function setAdminGroup(groupId, direction) {
  const group =
    (state.rules?.admin_policy?.groups || [])
      .find(x => x.id === groupId);

  if (!group) return;

  group.provisions.forEach(name => {
    setAdminAssignmentWithoutRender(
      name,
      Number(direction)
    );
  });

  persistAdminPolicy();
  applyAdminPolicy();
}

function setAdminAssignmentWithoutRender(
  name,
  direction
) {
  const base =
    state.rules.admin_policy
      .provision_overrides[name];

  if (!base) return;

  state.adminOverrides[name] =
    normalizeAdminOverride(
      name,
      {
        ...base,
        direction
      },
      base
    );
}

function resetAdminPolicy() {
  state.adminOverrides = {};

  localStorage.removeItem(
    'ppusa_admin_policy_v1'
  );

  applyAdminPolicy();
}

function downloadAdminRules() {
  const rules =
    structuredClone(state.rules);

  rules.admin_policy.provision_overrides = {
    ...(state.rules.admin_policy
      .provision_overrides || {}),
    ...(structuredClone(
      state.adminOverrides
    ) || {})
  };

  const blob = new Blob(
    [
      JSON.stringify(
        rules,
        null,
        2
      ) + '\n'
    ],
    {
      type: 'application/json'
    }
  );

  const url =
    URL.createObjectURL(blob);

  const link =
    document.createElement('a');

  link.href = url;
  link.download =
    'scorecard_rules.json';

  link.click();

  setTimeout(
    () =>
      URL.revokeObjectURL(url),
    1000
  );
}

async function sha256(value) {
  const bytes =
    new TextEncoder().encode(value);

  const hash =
    await crypto.subtle.digest(
      'SHA-256',
      bytes
    );

  return [...new Uint8Array(hash)]
    .map(x =>
      x.toString(16).padStart(2, '0')
    )
    .join('');
async function unlockAdmin() {
  if (state.adminUnlocked) {
    renderAdminPanel();
    $('adminDialog').showModal();
    return;
  }

  // Wait until the scorecard/rules data are loaded.
  if (!state.rules || !state.baseData) {
    window.alert('Please wait for the scorecard to finish loading, then try again.');
    return;
  }

  const secret = window.prompt(
    'Paste the PPUSA admin secret key below.\n\n' +
    'Press OK after pasting it.'
  );

  if (secret === null) return;

  const trimmed = secret.trim();

  if (!trimmed) {
    window.alert('Admin secret cannot be empty.');
    return;
  }

  try {
    const hash = await sha256(trimmed);

    if (hash !== ADMIN_SECRET_HASH) {
      window.alert(
        'Invalid admin secret.\n\n' +
        'Make sure you pasted the complete key with no extra characters.'
      );
      return;
    }

    state.adminUnlocked = true;

    renderAdminPanel();

    const dialog = $('adminDialog');

    if (dialog && typeof dialog.showModal === 'function') {
      dialog.showModal();
    }
  } catch (error) {
    console.error('Admin unlock error:', error);
    window.alert(
      'Could not verify the admin secret. ' +
      'Please reload the page and try again.'
    );
  }
}

  const choice = window.confirm(
    'Admin access requires the secret key.\n\n' +
    'OK = paste the key\n' +
    'Cancel = upload a .txt file containing the key'
  );

  if (choice) {
    const secret =
      window.prompt(
        'Paste the admin secret key:'
      );

    if (secret === null) {
      return;
    }

    const trimmed =
      secret.trim();

    if (!trimmed) {
      window.alert(
        'Admin secret cannot be empty.'
      );
      return;
    }

    try {
      if (
        (await sha256(trimmed)) !==
        ADMIN_SECRET_HASH
      ) {
        window.alert(
          'Invalid admin secret.'
        );
        return;
      }

      state.adminUnlocked = true;

      renderAdminPanel();

      $('adminDialog').showModal();
    } catch (_) {
      window.alert(
        'Could not verify the admin secret.'
      );
    }

    return;
  }

  const input =
    document.createElement('input');

  input.type = 'file';
  input.accept =
    '.txt,text/plain';
  input.style.display =
    'none';

  document.body.appendChild(input);

  const cleanup = () =>
    input.remove();

  input.addEventListener(
    'change',
    async () => {
      const file =
        input.files?.[0];

      if (!file) {
        cleanup();
        return;
      }

      try {
        const secret =
          (await file.text()).trim();

        if (
          (await sha256(secret)) !==
          ADMIN_SECRET_HASH
        ) {
          window.alert(
            'Invalid admin secret file.'
          );

          cleanup();
          return;
        }

        state.adminUnlocked = true;

        cleanup();

        renderAdminPanel();

        $('adminDialog').showModal();
      } catch (_) {
        window.alert(
          'Could not read the admin secret file.'
        );

        cleanup();
      }
    },
    { once: true }
  );

  input.click();
}

function renderAdminPanel() {
  const root =
    $('adminPanel');

  if (
    !root ||
    !state.rules?.admin_policy
  ) {
    return;
  }

  const policy =
    state.rules.admin_policy;

  const names =
    allProvisionNames();

  const groups =
    policy.groups || [];

  const groupRows =
    groups.map(group => {
      const assigned =
        group.provisions
          .map(
            name =>
              provisionAssignment(
                name
              ).direction
          );

      const mixed =
        new Set(assigned).size > 1;

      return `
        <div class="admin-group">
          <div>
            <strong>${esc(group.label)}</strong>
            <span>
              ${group.provisions.length}
              provision${group.provisions.length === 1 ? '' : 's'}
            </span>
            <small>
              ${
                mixed
                  ? 'Current assignments are mixed.'
                  : `Current: ${directionLabel(assigned[0])}`
              }
            </small>
          </div>

          <select data-admin-group="${esc(group.id)}">
            <option value="">Bulk assign…</option>
            ${ADMIN_DIRECTION_OPTIONS}
          </select>
        </div>
      `;
    }).join('');

  const options =
    names.map(name => {
      const a =
        provisionAssignment(name);

      return `
        <option value="${esc(name)}">
          ${esc(name)} — ${directionLabel(a.direction)}
        </option>
      `;
    }).join('');

  root.innerHTML = `
    <div class="detail-header">
      <p class="eyebrow">
        PRIVATE POLICY EDITOR
      </p>

      <h2>
        Conservative-policy assignments
      </h2>

      <p class="detail-sub">
        Group controls apply to every provision in
        the group. Advanced controls let you change
        one provision at a time. Changes are saved
        only in this browser until you export the
        rules file.
      </p>
    </div>

    <div class="admin-warning">
      This is a static GitHub Pages site. The secret
      hides the editor, but it is not server-side
      authentication. For real access control, the
      admin UI would need a server-side identity
      provider.
    </div>

    <div class="admin-actions">
      <button
        class="toggle"
        id="exportRules"
      >
        Export updated rules
      </button>

      <button
        class="toggle"
        id="resetRules"
      >
        Reset local assignments
      </button>
    </div>

    <p class="eyebrow">
      GROUP ASSIGNMENTS
    </p>

    <div class="admin-groups">
      ${groupRows}
    </div>

    <p class="eyebrow admin-advanced-label">
      ADVANCED
    </p>

    <div class="admin-advanced">
      <label for="adminProvision">
        Provision
      </label>

      <select id="adminProvision">
        <option value="">
          Select a provision…
        </option>

        ${options}
      </select>

      <label for="adminDirection">
        Assignment
      </label>

      <select
        id="adminDirection"
        disabled
      >
        <option value="">
          Select a provision first…
        </option>

        ${ADMIN_DIRECTION_OPTIONS}
      </select>
    </div>

    <div class="admin-coverage">
      ${names.length}
      named provisions currently have explicit
      assignments.
    </div>
  `;

  root
    .querySelectorAll(
      '[data-admin-group]'
    )
    .forEach(select => {
      select.addEventListener(
        'change',
        e => {
          if (
            e.target.value === ''
          ) {
            return;
          }

          setAdminGroup(
            e.target.dataset.adminGroup,
            e.target.value
          );

          e.target.value = '';
        }
      );
    });

  const provisionSelect =
    $('adminProvision');

  const directionSelect =
    $('adminDirection');

  provisionSelect.addEventListener(
    'change',
    () => {
      const name =
        provisionSelect.value;

      directionSelect.disabled =
        !name;

      if (!name) {
        return;
      }

      directionSelect.value =
        String(
          provisionAssignment(
            name
          ).direction
        );
    }
  );

  directionSelect.addEventListener(
    'change',
    () => {
      if (!provisionSelect.value) {
        return;
      }

      setAdminAssignment(
        provisionSelect.value,
        directionSelect.value
      );
    }
  );

  $('exportRules')
    .addEventListener(
      'click',
      downloadAdminRules
    );

  $('resetRules')
    .addEventListener(
      'click',
      () => {
        if (
          window.confirm(
            'Reset all browser-local policy assignments?'
          )
        ) {
          resetAdminPolicy();
        }
      }
    );
}

function renderSummary() {
  const n =
    state.bills.reduce(
      (sum, b) =>
        sum +
        (b.scorecard?.provisions || [])
          .filter(
            p => p.scorable !== false
          )
          .length,
      0
    );

  $('playerCount').textContent =
    state.players.length;

  $('billCount').textContent =
    state.bills.length;

  $('provisionCount').textContent =
    n;

  $('generatedAt').textContent =
    `Data generated ${
      new Date(
        state.data.generated_at
      ).toLocaleString()
    }`;
}

function applyFilters() {
  const q =
    $('search').value
      .trim()
      .toLowerCase();

  const party =
    $('party').value;

  const chamber =
    $('chamber').value;

  const sort =
    $('sort').value;

  const dir =
    $('direction').value ===
    'asc'
      ? 1
      : -1;

  state.filtered =
    state.players
      .filter(p => {
        const profiles =
          p.profiles || [];

        const hay = [
          p.name,
          p.discord,
          ...profiles.map(
            x => x.name
          ),
          ...profiles.map(
            x => x.state
          )
        ]
          .join(' ')
          .toLowerCase();

        const parties =
          profiles.map(
            x => x.party
          );

        const chambers =
          profiles.map(
            x => x.chamber
          );

        return (
          (!q ||
            hay.includes(q)) &&
          (
            party === 'all' ||
            parties.includes(party)
          ) &&
          (
            chamber === 'all' ||
            chambers.includes(chamber)
          )
        );
      })
      .sort((a, b) => {
        let av;
        let bv;

        if (sort === 'score') {
          av =
            num(
              a.scores?.overall
            );

          bv =
            num(
              b.scores?.overall
            );
        } else if (
          [
            'social',
            'economic',
            'foreign'
          ].includes(sort)
        ) {
          av =
            num(
              a.scores?.[sort]
            );

          bv =
            num(
              b.scores?.[sort]
            );
        } else if (
          sort === 'state'
        ) {
          av =
            (
              a.state || ''
            ).toLowerCase();

          bv =
            (
              b.state || ''
            ).toLowerCase();
        } else if (
          sort === 'profile'
        ) {
          av =
            (
              a.discord || ''
            ).toLowerCase();

          bv =
            (
              b.discord || ''
            ).toLowerCase();
        } else {
          av =
            (
              a.name || ''
            ).toLowerCase();

          bv =
            (
              b.name || ''
            ).toLowerCase();
        }

        if (av === bv) {
          return 0;
        }

        if (
          av === null ||
          av === undefined ||
          av === ''
        ) {
          return 1;
        }

        if (
          bv === null ||
          bv === undefined ||
          bv === ''
        ) {
          return -1;
        }

        return (
          (av > bv ? 1 : -1) *
          dir
        );
      });

  renderPlayers();
  renderBills();
}

function renderPlayers() {
  $('resultCount').textContent =
    `${state.filtered.length} scorecard${
      state.filtered.length === 1
        ? ''
        : 's'
    }`;

  const root =
    $('scorecards');

  if (!state.filtered.length) {
    root.innerHTML =
      '<div class="empty">No scorecards match the current filters.</div>';
    return;
  }

  root.innerHTML =
    state.filtered
      .map((p, i) => {
        const s =
          p.scores || {};

        const profiles =
          p.profiles || [];

        const playerId =
          p.user_id ||
          p.player_id;

        const mainProfileId =
          p.profile_id ||
          profiles[0]?.profile_id ||
          profiles[0]?.id;

        const playerLink =
          profileUrl(
            mainProfileId
          );

        return `
          <article
            class="scorecard"
            tabindex="0"
            role="button"
            data-player-index="${i}"
          >
            <div class="card-main">
              <div class="identity">
                ${avatar({
                  name: p.name,
                  avatar: p.avatar
                })}

                <div>
                  <h3>
                    ${
                      playerLink
                        ? `
                          <a
                            class="main-profile-link"
                            href="${esc(playerLink)}"
                            target="_blank"
                            rel="noopener"
                          >
                            ${esc(p.name)}
                          </a>
                        `
                        : esc(p.name)
                    }
                  </h3>

                  <div class="handle">
                    ${esc(
                      p.discord ||
                      'No Discord handle'
                    )}
                  </div>

                  <div class="chips">
                    <span class="party-chip">
                      ${esc(
                        partyLabel(p.party)
                      )}
                    </span>

                    ${(p.chambers || [])
                      .map(c =>
                        `<span class="chamber-chip">${esc(c)}</span>`
                      )
                      .join('')}
                  </div>
                </div>
              </div>

              <div class="score-row">
                <div class="score-main">
                  <strong>
                    ${fmt(s.overall)}
                  </strong>

                  <span>
                    / 100
                  </span>
                </div>

                <div
                  class="tier tier-${esc(
                    s.tier || 'N/A'
                  )}"
                >
                  ${esc(
                    s.tier || 'N/A'
                  )}
                </div>
              </div>

              <div class="mini-bars">
                ${[
                  'social',
                  'economic',
                  'foreign'
                ].map(cat => {
                  const v =
                    num(s[cat]);

                  const w =
                    v === null
                      ? 0
                      : Math.max(
                          0,
                          Math.min(
                            100,
                            v
                          )
                        );

                  return `
                    <div class="mini-row">
                      <span>
                        ${label(cat)}
                      </span>

                      <div class="bar">
                        <span
                          style="width:${w}%"
                        ></span>
                      </div>

                      <span class="mini-value">
                        ${fmt(v)}
                      </span>

                      ${
                        ideology(
                          cat,
                          v
                        )
                          ? `
                            <span class="mini-tag">
                              ${esc(
                                ideology(
                                  cat,
                                  v
                                )
                              )}
                            </span>
                          `
                          : ''
                      }
                    </div>
                  `;
                }).join('')}
              </div>
            </div>

            <div class="profile-strip">
              <strong>
                ${profiles.length}
                office${
                  profiles.length === 1
                    ? ''
                    : 's'
                }
                on this user
              </strong>

              <div class="profile-list">
                ${profiles
                  .map(x => {
                    const url =
                      profileUrl(
                        x.profile_id ||
                        x.id
                      );

                    const text =
                      `${x.name} · ${x.chamber} · ${x.state}`;

                    return url
                      ? `
                        <a
                          class="profile-chip profile-link"
                          href="${esc(url)}"
                          target="_blank"
                          rel="noopener"
                        >
                          ${esc(text)}
                        </a>
                      `
                      : `
                        <span class="profile-chip">
                          ${esc(text)}
                        </span>
                      `;
                  })
                  .join('')}
              </div>
            </div>
          </article>
        `;
      })
      .join('');

  root
    .querySelectorAll(
      '[data-player-index]'
    )
    .forEach(card => {
      card.addEventListener(
        'click',
        e => {
          if (
            e.target.closest('a')
          ) {
            return;
          }

          openPlayer(
            state.filtered[
              Number(
                card.dataset
                  .playerIndex
              )
            ]
          );
        }
      );

      card.addEventListener(
        'keydown',
        e => {
          if (
            e.key === 'Enter' ||
            e.key === ' '
          ) {
            e.preventDefault();

            openPlayer(
              state.filtered[
                Number(
                  card.dataset
                    .playerIndex
                )
              ]
            );
          }
        }
      );
    });
}

function renderBills() {
  const root =
    $('bills');

  root.innerHTML =
    state.bills
      .map((b, i) => {
        const ps =
          (
            b.scorecard?.provisions ||
            []
          )
            .filter(
              p => p.scorable !== false
            );

        const t =
          b.scorecard?.total ??
          billTotal(b);

        const weight =
          num(
            b.scorecard?.weight
          );

        return `
          <button
            class="bill-card"
            data-bill-index="${i}"
          >
            <div class="bill-meta">
              <span>
                ${esc(b.number)}
              </span>

              <span>
                ${ps.length}
                scored provision${
                  ps.length === 1
                    ? ''
                    : 's'
                }
              </span>
            </div>

            <h3>
              ${esc(b.title)}
            </h3>

            <div class="bill-meta">
              <span>
                ${esc(b.status)}
              </span>

              <span
                class="bill-score ${
                  t >= 0
                    ? 'positive'
                    : 'negative'
                }"
              >
                ${t > 0 ? '+' : ''}${t}
              </span>
            </div>

            <div class="bill-meta">
              <span>
                ${esc(
                  b.scorecard
                    ?.finalized_game_date ||
                  'Date unknown'
                )}
              </span>

              <span>
                Weight ${
                  weight === null
                    ? '—'
                    : weight.toFixed(2)
                }
              </span>
            </div>
          </button>
        `;
      })
      .join('');

  root
    .querySelectorAll(
      '[data-bill-index]'
    )
    .forEach(b => {
      b.addEventListener(
        'click',
        () =>
          openBill(
            state.bills[
              Number(
                b.dataset
                  .billIndex
              )
            ]
          )
      );
    });
}

function renderPending() {
  const floors =
    state.pending.filter(
      b =>
        b.status !==
        'In Committee'
    );

  const committees =
    state.pending.filter(
      b =>
        b.status ===
        'In Committee'
    );

  const card =
    (b, i) => {
      const t =
        b.scorecard?.total ??
        billTotal(b);

      const ps =
        (
          b.scorecard?.provisions ||
          []
        ).filter(
          p =>
            p.scorable !== false
        );

      return `
        <button
          class="bill-card pending-bill"
          data-pending-index="${i}"
        >
          <div class="bill-meta">
            <span>
              ${esc(
                b.number ||
                'Bill'
              )}
            </span>

            <span>
              ${ps.length}
              scored provision${
                ps.length === 1
                  ? ''
                  : 's'
              }
            </span>
          </div>

          <h3>
            ${esc(
              b.title ||
              'Untitled bill'
            )}
          </h3>

          <div class="bill-meta">
            <span>
              ${esc(b.status)}
            </span>

            <span
              class="bill-score ${
                t >= 0
                  ? 'positive'
                  : 'negative'
              }"
            >
              ${t > 0 ? '+' : ''}${t}
              ·
              ${esc(
                b.scorecard
                  ?.alignment ||
                'Neutral / mixed'
              )}
            </span>
          </div>
        </button>
      `;
    };

  const floorRoot =
    $('floorBills');

  const committeeRoot =
    $('committeeBills');

  if (floorRoot) {
    floorRoot.innerHTML =
      floors.length
        ? floors
            .map(card)
            .join('')
        : `
          <div class="empty">
            No bills currently on the floor
            or awaiting a leadership call.
          </div>
        `;

    floorRoot
      .querySelectorAll(
        '[data-pending-index]'
      )
      .forEach(btn => {
        btn.addEventListener(
          'click',
          () =>
            openBill(
              floors[
                Number(
                  btn.dataset
                    .pendingIndex
                )
              ]
            )
        );
      });
  }

  if (committeeRoot) {
    committeeRoot.innerHTML =
      committees.length
        ? committees
            .map(card)
            .join('')
        : `
          <div class="empty">
            No bills currently in committee.
          </div>
        `;

    committeeRoot
      .querySelectorAll(
        '[data-pending-index]'
      )
      .forEach(btn => {
        btn.addEventListener(
          'click',
          () =>
            openBill(
              committees[
                Number(
                  btn.dataset
                    .pendingIndex
                )
              ]
            )
        );
      });
  }
}

function openPlayer(p) {
  state.problemsOnly =
    false;

  const s =
    p.scores || {};

  const d =
    p.bill_details || [];

  const aligned =
    d.filter(
      x => x.aligned
    ).length;

  const profiles =
    p.profiles || [];

  $('scorecardDetail').innerHTML = `
    <div class="detail-title-row">
      <div>
        <div class="detail-header">
          <p class="eyebrow">
            LEGISLATOR SCORECARD
          </p>

          <h2>
            ${esc(p.name)}
          </h2>

          <p class="detail-sub">
            ${esc(
              p.discord ||
              'No Discord handle'
            )}
            ·
            ${esc(
              partyLabel(p.party)
            )}
            ·
            ${esc(p.state || '')}
            ·
            ${d.length}
            provisions scored
          </p>
        </div>
      </div>

      <button
        class="share-scorecard"
        id="copyScorecardLink"
        type="button"
      >
        Copy Discord link
      </button>
    </div>

    <div class="account-grid">
      ${profiles
        .map(x => {
          const url =
            profileUrl(
              x.profile_id ||
              x.id
            );

          return `
            <div class="account">
              ${
                x.avatar
                  ? `
                    <img
                      class="avatar"
                      src="${esc(x.avatar)}"
                      alt=""
                    >
                  `
                  : ''
              }

              ${
                url
                  ? `
                    <a
                      class="profile-link"
                      href="${esc(url)}"
                      target="_blank"
                      rel="noopener"
                    >
                      <strong>
                        ${esc(x.name)}
                      </strong>
                    </a>
                  `
                  : `
                    <strong>
                      ${esc(x.name)}
                    </strong>
                  `
              }

              <span>
                ${esc(x.chamber)}
                ·
                ${esc(x.state)}
                ·
                ${esc(
                  partyLabel(x.party)
                )}
              </span>
            </div>
          `;
        })
        .join('')}
    </div>

    <div class="detail-score">
      <div class="detail-stat">
        <span>
          Overall
        </span>

        <strong>
          ${fmt(s.overall)}
          ·
          ${esc(
            s.tier || 'N/A'
          )}
        </strong>
      </div>

      <div class="detail-stat">
        <span>
          Social
        </span>

        <strong>
          ${fmt(s.social)}
        </strong>

        ${
          ideology(
            'social',
            s.social
          )
            ? `
              <div class="stat-tag">
                ${esc(
                  ideology(
                    'social',
                    s.social
                  )
                )}
              </div>
            `
            : ''
        }
      </div>

      <div class="detail-stat">
        <span>
          Economic
        </span>

        <strong>
          ${fmt(s.economic)}
        </strong>

        ${
          ideology(
            'economic',
            s.economic
          )
            ? `
              <div class="stat-tag">
                ${esc(
                  ideology(
                    'economic',
                    s.economic
                  )
                )}
              </div>
            `
            : ''
        }
      </div>

      <div class="detail-stat">
        <span>
          Foreign
        </span>

        <strong>
          ${fmt(s.foreign)}
        </strong>

        ${
          ideology(
            'foreign',
            s.foreign
          )
            ? `
              <div class="stat-tag">
                ${esc(
                  ideology(
                    'foreign',
                    s.foreign
                  )
                )}
              </div>
            `
            : ''
        }
      </div>
    </div>

    <div class="vote-row">
      <span>
        <strong>
          ${aligned}
        </strong>
        of
        <strong>
          ${d.length}
        </strong>
        scored provisions aligned
        with the conservative position.
      </span>
    </div>

    <div class="detail-controls">
      <p class="eyebrow">
        VOTING RECORD
      </p>

      <button
        class="toggle"
        id="problemsToggle"
      >
        Show problems only
      </button>
    </div>

    <div
      id="playerVotes"
      class="provision-list"
    ></div>
  `;

  renderPlayerVotes(p);

  $('problemsToggle')
    .addEventListener(
      'click',
      () => {
        state.problemsOnly =
          !state.problemsOnly;

        $('problemsToggle')
          .classList.toggle(
            'active',
            state.problemsOnly
          );

        $('problemsToggle')
          .textContent =
            state.problemsOnly
              ? 'Show all votes'
              : 'Show problems only';

        renderPlayerVotes(p);
      }
    );

  $('scorecardDialog')
    .showModal();

  $('copyScorecardLink')
    .addEventListener(
      'click',
      async () => {
        const url =
          shareUrl(p);

        try {
          await navigator
            .clipboard
            .writeText(url);

          $('copyScorecardLink')
            .textContent =
            'Copied';

          setTimeout(
            () => {
              $('copyScorecardLink')
                .textContent =
                'Copy Discord link';
            },
            1600
          );
        } catch (_) {
          window.prompt(
            'Copy this scorecard link:',
            url
          );
        }
      }
    );
}

function renderPlayerVotes(p) {
  const root =
    $('playerVotes');

  const d =
    (p.bill_details || [])
      .filter(
        x =>
          !state.problemsOnly ||
          !x.aligned
      );

  if (!d.length) {
    root.innerHTML =
      '<div class="empty">No problems found in the current view.</div>';
    return;
  }

  root.innerHTML =
    d.map(x => {
      const weight =
        num(x.weight);

      const bill =
        state.data?.bills?.[
          String(
            x.resolution_id
          )
        ];

      const url =
        billUrl(
          x.resolution_id
        );

      return `
        <div class="provision">
          <div>
            <div class="provision-name">
              <a
                class="bill-provision-link"
                href="${esc(url)}"
                target="_blank"
                rel="noopener"
              >
                ${esc(
                  x.provision ||
                  'Provision'
                )}
              </a>
            </div>

            <div class="provision-note">
              ${esc(
                x.number || ''
              )}
              ·
              ${esc(
                x.bill_title ||
                ''
              )}
              ·
              ${esc(
                label(x.category)
              )}
              ·
              ${esc(
                x.vote || ''
              )}
              ·
              ${esc(
                x.profile_name ||
                x.profile_id ||
                ''
              )}
              ·
              ${esc(
                x.chamber ||
                'Other'
              )}
              ·
              weight
              ${
                weight === null
                  ? '—'
                  : weight.toFixed(2)
              }
            </div>

            <span class="position-pill">
              Conservative position:
              ${
                x.direction > 0
                  ? '+1'
                  : '−1'
              }
            </span>
          </div>

          <span
            class="result-pill ${
              x.aligned
                ? 'aligned'
                : 'not-aligned'
            }"
          >
            ${
              x.aligned
                ? '+1'
                : '−1'
            }

            ${
              x.aligned
                ? 'Aligned'
                : 'Not aligned'
            }
          </span>
        </div>
      `;
    }).join('');
}

function openBill(b) {
  const ps =
    b.scorecard?.provisions ||
    [];

  const weight =
    num(
      b.scorecard?.weight
    );

  const totals =
    voteTotals(b);

  const billAlignment =
    b.scorecard?.alignment ||
    'Neutral / mixed';

  $('billDetail').innerHTML = `
    <div class="detail-header">
      <p class="eyebrow">
        ${
          b.finalized === false
            ? 'PENDING BILL'
            : 'BILL DETAILS'
        }
      </p>

      <h2>
        ${esc(b.number)}
        —
        ${esc(b.title)}
      </h2>

      <p class="detail-sub">
        ${esc(b.status)}
        ·
        Introduced
        ${esc(
          b.introduced ||
          '—'
        )}
        ·
        Passed
        ${esc(
          b.passed ||
          '—'
        )}
      </p>
    </div>

    <div class="detail-score">
      <div
        class="detail-stat alignment-stat ${
          alignmentClass(
            billAlignment
          )
        }"
      >
        <span>
          Alignment
        </span>

        <strong>
          ${esc(
            billAlignment
          )}

          <span class="vote-totals">
            Yea
            ${totals.yeas}
            ·
            Nay
            ${totals.nays}
          </span>
        </strong>
      </div>

      <div class="detail-stat">
        <span>
          Weight / age
        </span>

        <strong>
          ${
            weight === null
              ? 'Pending'
              : weight.toFixed(2)
          }

          ${
            b.scorecard
              ?.age_months ===
            undefined
              ? ''
              : ` · ${b.scorecard.age_months} months old`
          }
        </strong>
      </div>

      <div class="detail-stat">
        <span>
          Scored provisions
        </span>

        <strong>
          ${
            ps.filter(
              p =>
                p.scorable !== false
            ).length
          }
        </strong>
      </div>

      <div class="detail-stat">
        <span>
          Rightward
        </span>

        <strong>
          ${
            ps.filter(
              p =>
                p.direction > 0
            ).length
          }
        </strong>
      </div>

      <div class="detail-stat">
        <span>
          Leftward
        </span>

        <strong>
          ${
            ps.filter(
              p =>
                p.direction < 0
            ).length
          }
        </strong>
      </div>

      <div class="detail-stat">
        <span>
          Custom/neutral
        </span>

        <strong>
          ${
            ps.filter(
              p =>
                p.scorable === false
            ).length
          }
        </strong>
      </div>
    </div>

    <p class="eyebrow">
      PROVISIONS
    </p>

    <div class="provision-list">
      ${ps.map(x => `
        <div class="provision">
          <div>
            <div class="provision-name">
              ${esc(
                x.name
              )}
            </div>

            <div class="provision-note">
              ${esc(
                label(x.category) ||
                'Neutral'
              )}
              ·
              ${esc(
                x.rationale ||
                'No rationale listed.'
              )}

              ${
                x.current_law
                  ? `
                    <div class="provision-note">
                      Current-law reference:
                      ${esc(
                        JSON.stringify(
                          x.current_law
                        )
                      )}
                    </div>
                  `
                  : ''
              }
            </div>
          </div>

          <span
            class="result-pill ${
              x.scorable === false
                ? 'neutral'
                : x.direction > 0
                  ? 'aligned'
                  : 'not-aligned'
            }"
          >
            ${
              x.scorable === false
                ? 'Neutral'
                : x.direction > 0
                  ? '+1'
                  : '−1'
            }
          </span>
        </div>
      `).join('')}
    </div>

    ${
      b.scorecard?.method
        ? `
          <p class="provision-note">
            ${esc(
              b.scorecard.method
            )}
          </p>
        `
        : ''
    }
  `;

  $('billDialog')
    .showModal();
}

document.addEventListener(
  'DOMContentLoaded',
  () => {
    [
      'search',
      'party',
      'chamber',
      'sort',
      'direction'
    ].forEach(id => {
      const element = $(id);

      if (element) {
        element.addEventListener(
          'input',
          applyFilters
        );
      }
    });

    document
      .querySelectorAll(
        '[data-close]'
      )
      .forEach(b => {
        b.addEventListener(
          'click',
          () =>
            b.closest(
              'dialog'
            ).close()
        );
      });

    document
      .querySelectorAll(
        'dialog'
      )
      .forEach(d => {
        d.addEventListener(
          'click',
          e => {
            if (
              e.target === d
            ) {
              d.close();
            }
          }
        );
      });

    document.addEventListener(
      'keydown',
      e => {
        if (
          e.ctrlKey &&
          e.shiftKey &&
          e.key.toLowerCase() === 'a'
        ) {
          e.preventDefault();
          unlockAdmin();
        }
      }
    );

    if (
      window.location.hash ===
      '#admin'
    ) {
      setTimeout(
        unlockAdmin,
        250
      );
    }

    loadData()
      .then(() => {
        const params =
          new URLSearchParams(
            window.location.search
          );

        const playerId =
          params.get('player') ||
          params.get('profile');

        const billId =
          params.get('bill');

        if (playerId) {
          const player =
            state.players.find(
              p =>
                String(
                  p.user_id ||
                  p.player_id
                ) ===
                String(playerId)
            );

          if (player) {
            openPlayer(player);
          }
        }

        if (billId) {
          const bill =
            state.data?.bills?.[
              String(billId)
            ];

          if (bill) {
            openBill(bill);
          }
        }
      })
      .catch(e => {
        console.error(e);

        const root =
          $('scorecards');

        if (root) {
          root.innerHTML =
            '<div class="empty">Unable to load scorecard data. Check that public/data is present.</div>';
        }
      });
  }
);
