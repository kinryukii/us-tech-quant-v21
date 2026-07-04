# Moomoo Data Source

The primary market-data path uses Moomoo OpenD quote APIs only. It requires `moomoo-api` and OpenD at `MOOMOO_OPEND_HOST`/`MOOMOO_OPEND_PORT` (defaults 127.0.0.1:11111). No yfinance fallback, trade API, account unlock, or broker action is allowed. DRAM maps to `US.DRAM` and is always included as a priority symbol.
