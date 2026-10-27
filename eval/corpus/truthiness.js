/**
 * JS truthiness probe (eval corpus, trap #1): [] "0" {} are truthy in JS.
 */

/**
 * @param {any} x
 */
function toLabel(x) {
  if (x) return "yes";
  return "no";
}

module.exports = { toLabel };
