"""CSV cell sanitisation: prevent spreadsheet formula injection.

Excel, LibreOffice and Google Sheets treat a cell starting with ``=``, ``+``,
``-`` or ``@`` as a formula even when the file was generated server-side, and
DDE payloads can lead to code execution on the opener's machine. Prefixing the
cell with a single quote forces text interpretation. Tab and CR are included
because Excel strips them before evaluating.
"""

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(value: object) -> object:
    """Stringify a cell, neutralising formula-leading text. Numbers pass
    through unchanged so spreadsheet columns stay numeric."""
    if value is None:
        return ""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    text = str(value)
    if text.startswith(_FORMULA_PREFIXES):
        return "'" + text
    return text
