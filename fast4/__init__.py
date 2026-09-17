from pathlib import Path


_SOURCE_PACKAGE = Path(__file__).parent / "src" / "fast4"
if str(_SOURCE_PACKAGE) not in __path__:
    __path__.append(str(_SOURCE_PACKAGE))
