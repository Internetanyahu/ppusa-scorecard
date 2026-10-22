(() => {
  function replaceRuntimeScoring() {
    if (typeof window.applyAdminPolicy !== 'function' || !window.state?.baseData) return false;

    window.recalculatePlayer = function recalculatePlayer(player, bills) {
      const details = (player.bill_details || []).map(detail => {
        const bill = bills[String(detail.resolution_id)];
        const provision = bill?.scorecard?.provisions?.find(p => p.name === detail.provision);

        if (!provision) {
          return { ...detail, direction: 0, category: null, scorable: false, aligned: false };
        }

        const direction = Number(provision.direction);
        const vote = String(detail.vote || '').toLowerCase();
        return {
          ...detail,
          direction,
          category: provision.category ?? null,
          scorable: provision.scorable !== false && [-1, 1].includes(direction),
          aligned: direction === 1 ? vote === 'aye' : direction === -1 ? vote === 'nay' : false,
          weight: bill.scorecard?.weight ?? detail.weight ?? 1,
        };
      });

      const scored = details.filter(x => x.scorable !== false && [-1, 1].includes(Number(x.direction)));
      const distinctBills = new Set(scored.map(x => String(x.resolution_id)));
      const eligible = distinctBills.size >= 3;
      const counts = {};
      const categoryScores = {};

      ['social', 'economic', 'foreign'].forEach(category => {
        const rows = scored.filter(x => x.category === category);
        counts[category] = rows.length;
        const denominator = rows.reduce((sum, x) => sum + Number(x.weight ?? 1), 0);
        const aligned = rows.filter(x => x.aligned).reduce((sum, x) => sum + Number(x.weight ?? 1), 0);
        categoryScores[category] = eligible && denominator ? 100 * aligned / denominator : null;
      });

      const denominator = scored.reduce((sum, x) => sum + Number(x.weight ?? 1), 0);
      const aligned = scored.filter(x => x.aligned).reduce((sum, x) => sum + Number(x.weight ?? 1), 0);
      const overall = eligible && denominator ? 100 * aligned / denominator : null;

      return {
        ...player,
        bill_details: details,
        scores: {
          ...categoryScores,
          overall,
          tier: overall === null ? 'N/A' : overall >= 90 ? 'S' : overall >= 80 ? 'A' : overall >= 70 ? 'B' : overall >= 60 ? 'C' : overall >= 50 ? 'D' : 'F',
        },
        sample_size: { ...counts, overall: scored.length },
        provisions_scored: scored.length,
        aligned_provisions: scored.filter(x => x.aligned).length,
        aligned_votes: scored.filter(x => x.aligned).length,
        finalized_bills_voted: distinctBills.size,
        eligible_for_grade: eligible,
      };
    };

    window.applyAdminPolicy();
    return true;
  }

  const started = Date.now();
  const timer = setInterval(() => {
    if (replaceRuntimeScoring() || Date.now() - started > 10000) clearInterval(timer);
  }, 100);
})();
