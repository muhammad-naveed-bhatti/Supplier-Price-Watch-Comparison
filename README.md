# Supplier Price Watch & Comparison

A Streamlit procurement-intelligence app for comparing supplier prices, stock and lead times across multiple parts/SKUs.

## Features

- Multi-supplier comparison
- Currency normalization to USD
- Price-history tracking
- Supplier-level price-change percentages
- Cheapest-offer flag
- Stock and lead-time comparison
- Simple supplier score
- CSV export
- Optional Apify live price collection

## Public API

The app uses **Frankfurter** for exchange-rate conversion without requiring an API key.

## Optional Apify setup

```toml
APIFY_TOKEN = "your-token"
APIFY_ACTOR_ID = "username/actor-name"
```

Never commit API tokens.

## Run

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy

Deploy `app.py` from the repository root on Streamlit Community Cloud.

## Demo-data notice

`data/sample_prices.csv` contains fictional portfolio data. Always verify actual price, stock, supplier and procurement terms from official sources.
