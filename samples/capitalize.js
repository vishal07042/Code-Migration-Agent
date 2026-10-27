/**
 * Capitalize the first character.
 * @param {string} s the input string
 * @returns {string} the string with the first character upper-cased
 */
function capitalize(s) {
  if (!s) return s;
  return s.charAt(0).toUpperCase() + s.slice(1);
}
module.exports = { capitalize };
