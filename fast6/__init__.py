"""FAST6 data engineering package; no modeling surface is exposed here."""

from pathlib import Path


# Keep the requested ``python -m fast6.scripts...`` command compatible with the
# repository's lightweight src layout without installing a package.
_src_package = Path(__file__).parent / "src" / "fast6"
if _src_package.is_dir():
    __path__.append(str(_src_package))
