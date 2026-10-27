/**
 * Pure date helpers, UTC-only (eval corpus). String in/out keeps the
 * oracle wire simple; invalid input throws on both sides (trap #10).
 */

/**
 * @param {string} iso
 * @param {number} n
 */
function addDays(iso, n) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) throw new Error("addDays: bad date");
  if (!Number.isInteger(n)) throw new Error("addDays: integer days expected");
  return new Date(d.getTime() + n * 86400000).toISOString();
}

/**
 * 0 = Sunday .. 6 = Saturday, always UTC.
 * @param {string} iso
 */
function dayOfWeekUtc(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) throw new Error("dayOfWeekUtc: bad date");
  return d.getUTCDay();
}

module.exports = { addDays, dayOfWeekUtc };
