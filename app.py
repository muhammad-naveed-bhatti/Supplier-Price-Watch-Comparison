from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import requests
import streamlit as st

ROOT = Path(__file__).resolve().parent
SAMPLE = ROOT / "data" / "sample_prices.csv"

st.set_page_config(
    page_title="Supplier Price Watch & Comparison",
    page_icon="📈",
    layout="wide",
)

st.markdown(
    """
<style>
.block-container{padding-top:1.55rem;padding-bottom:2.5rem}
[data-testid="stMetric"]{border:1px solid #2a3447;border-radius:14px;padding:12px 14px;background:#151d2e}
.pill{border:1px solid #2a3447;border-radius:999px;padding:4px 9px;display:inline-block;margin:0 6px 6px 0;font-size:.78rem}
</style>
""",
    unsafe_allow_html=True,
)

@st.cache_data
def load_sample() -> pd.DataFrame:
    return pd.read_csv(SAMPLE)

@st.cache_data(ttl=3600)
def fx_to_usd(currencies: tuple[str, ...]) -> dict[str, float]:
    fallback = {
        "USD":1.0, "EUR":1.17, "GBP":1.33, "AED":0.2723,
        "QAR":0.2747, "SAR":0.2666, "PKR":0.0036,
    }
    out: dict[str, float] = {}
    for cur in currencies:
        cur = str(cur).upper().strip()
        if not cur:
            continue
        if cur == "USD":
            out[cur] = 1.0
            continue
        try:
            r = requests.get(
                "https://api.frankfurter.app/latest",
                params={"from":cur, "to":"USD"},
                timeout=8,
            )
            r.raise_for_status()
            out[cur] = float(r.json()["rates"]["USD"])
        except Exception:
            out[cur] = fallback.get(cur, 1.0)
    return out

def prepare(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    required = [
        "sku","description","supplier","country","unit_price","currency",
        "stock_qty","lead_time_days","observed_date","source_url"
    ]
    for col in required:
        if col not in out.columns:
            out[col] = ""

    out["unit_price"] = pd.to_numeric(out["unit_price"], errors="coerce")
    out["stock_qty"] = pd.to_numeric(out["stock_qty"], errors="coerce").fillna(0)
    out["lead_time_days"] = pd.to_numeric(out["lead_time_days"], errors="coerce")
    out["currency"] = out["currency"].fillna("").astype(str).str.upper()
    out["observed_date"] = pd.to_datetime(out["observed_date"], errors="coerce")

    currencies = tuple(sorted(c for c in out["currency"].dropna().unique() if c))
    rates = fx_to_usd(currencies)
    out["price_usd"] = out.apply(
        lambda r: round(float(r["unit_price"]) * rates.get(r["currency"], 1.0), 2)
        if pd.notna(r["unit_price"]) else None,
        axis=1,
    )

    out = out.sort_values(["sku","supplier","observed_date"])
    out["previous_price_usd"] = out.groupby(["sku","supplier"])["price_usd"].shift(1)
    out["price_change_usd"] = (out["price_usd"] - out["previous_price_usd"]).round(2)
    out["price_change_pct"] = (
        (out["price_change_usd"] / out["previous_price_usd"]) * 100
    ).round(2)

    latest = out.groupby(["sku","supplier"], as_index=False).tail(1).copy()
    min_by_sku = latest.groupby("sku")["price_usd"].transform("min")
    latest["is_cheapest"] = latest["price_usd"].eq(min_by_sku)
    latest["supplier_score"] = (
        latest["is_cheapest"].astype(int) * 45
        + (latest["stock_qty"].clip(0,20) / 20 * 25)
        + ((30 - latest["lead_time_days"].clip(0,30)) / 30 * 30)
    ).clip(0,100).round(1)

    return out, latest

def secret(key: str) -> str:
    try:
        return str(st.secrets.get(key,""))
    except Exception:
        return ""

def run_apify(actor_id: str, token: str, run_input: dict[str,Any], max_items: int) -> pd.DataFrame:
    actor = actor_id.replace("/","~")
    r = requests.post(
        f"https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items",
        headers={"Authorization":f"Bearer {token}","Content-Type":"application/json"},
        params={"clean":"true","format":"json","maxItems":max_items,"timeout":120},
        json=run_input,
        timeout=135,
    )
    r.raise_for_status()
    payload = r.json()
    items = payload if isinstance(payload,list) else payload.get("items",[])
    return pd.json_normalize(items)

st.title("📈 Supplier Price Watch & Comparison")
st.caption("Track supplier prices, normalize currencies, compare availability and flag price movements.")
st.markdown(
    '<span class="pill">Frankfurter FX</span><span class="pill">Apify-ready</span>'
    '<span class="pill">Price history</span><span class="pill">Supplier scoring</span>'
    '<span class="pill">CSV export</span>',
    unsafe_allow_html=True,
)

with st.sidebar:
    st.header("Filters")
    base = load_sample()
    sku_options = sorted(base["sku"].unique())
    selected_skus = st.multiselect("SKU / Part number", sku_options, default=sku_options[:3])
    suppliers = st.multiselect("Supplier", sorted(base["supplier"].unique()))
    countries = st.multiselect("Country", sorted(base["country"].unique()))
    in_stock_only = st.toggle("In-stock only", value=True)
    max_lead = st.slider("Maximum lead time (days)", 1, 60, 30)
    st.divider()
    st.header("Watch settings")
    alert_pct = st.slider("Flag price increase above (%)", 1, 50, 8)
    cheapest_only = st.toggle("Show cheapest offers only", value=False)

history, latest = prepare(base)

mask = pd.Series(True, index=latest.index)
if selected_skus:
    mask &= latest["sku"].isin(selected_skus)
if suppliers:
    mask &= latest["supplier"].isin(suppliers)
if countries:
    mask &= latest["country"].isin(countries)
if in_stock_only:
    mask &= latest["stock_qty"] > 0
mask &= latest["lead_time_days"].fillna(999) <= max_lead
if cheapest_only:
    mask &= latest["is_cheapest"]

view = latest.loc[mask].sort_values(
    ["sku","supplier_score","price_usd"],
    ascending=[True,False,True],
).reset_index(drop=True)

m1,m2,m3,m4 = st.columns(4)
m1.metric("Offers", len(view))
m2.metric("Suppliers", view["supplier"].nunique() if len(view) else 0)
m3.metric("Parts", view["sku"].nunique() if len(view) else 0)
rises = int((view["price_change_pct"].fillna(0) >= alert_pct).sum()) if len(view) else 0
m4.metric(f"Price rises ≥ {alert_pct}%", rises)

tab1,tab2,tab3,tab4 = st.tabs([
    "Comparison","Price history","Apify collector","About"
])

with tab1:
    st.subheader("Latest supplier offers")
    if view.empty:
        st.info("No offers match the current filters.")
    else:
        cols = [
            "sku","description","supplier","country","unit_price","currency","price_usd",
            "price_change_pct","stock_qty","lead_time_days","is_cheapest",
            "supplier_score","observed_date","source_url"
        ]
        st.dataframe(
            view[cols],
            use_container_width=True,
            hide_index=True,
            column_config={
                "price_usd":st.column_config.NumberColumn("USD normalized",format="$%.2f"),
                "price_change_pct":st.column_config.NumberColumn("Δ price %",format="%.2f%%"),
                "is_cheapest":st.column_config.CheckboxColumn("Cheapest"),
                "supplier_score":st.column_config.ProgressColumn("Score",min_value=0,max_value=100,format="%.1f"),
                "source_url":st.column_config.LinkColumn("Source"),
            },
        )

        flagged = view[view["price_change_pct"].fillna(0) >= alert_pct]
        if len(flagged):
            st.warning(
                f"{len(flagged)} offer(s) crossed the configured price-rise threshold of {alert_pct}%."
            )
        best = view.sort_values(["is_cheapest","supplier_score"],ascending=[False,False]).iloc[0]
        st.success(
            f"Highlighted offer: {best['sku']} · {best['supplier']} · "
            f"${best['price_usd']:,.2f} · {int(best['stock_qty'])} in stock · "
            f"{int(best['lead_time_days'])}-day lead."
        )

        st.download_button(
            "Download supplier comparison (CSV)",
            view[cols].to_csv(index=False).encode("utf-8-sig"),
            file_name=f"supplier_price_comparison_{date.today().isoformat()}.csv",
            mime="text/csv",
        )

with tab2:
    st.subheader("Price movement")
    if selected_skus:
        chart_sku = st.selectbox("SKU", selected_skus)
    else:
        chart_sku = st.selectbox("SKU", sorted(history["sku"].unique()))
    hist = history[history["sku"] == chart_sku].copy()
    if hist.empty:
        st.info("No history available.")
    else:
        pivot = hist.pivot_table(
            index="observed_date",
            columns="supplier",
            values="price_usd",
            aggfunc="last",
        ).sort_index()
        st.line_chart(pivot)
        st.dataframe(
            hist[[
                "observed_date","supplier","country","unit_price","currency",
                "price_usd","price_change_pct","stock_qty","lead_time_days"
            ]].sort_values("observed_date",ascending=False),
            use_container_width=True,
            hide_index=True,
        )

with tab3:
    st.subheader("Optional live price collection with Apify")
    st.write(
        "Connect an Apify Actor to supplier catalogue/product pages. "
        "Keep supplier-specific scraping logic outside the core comparison engine."
    )
    actor_id = st.text_input("Actor ID", value=secret("APIFY_ACTOR_ID"), placeholder="username/actor-name")
    token = st.text_input("Apify token", value=secret("APIFY_TOKEN"), type="password")
    urls = st.text_area(
        "Supplier/product URLs, one per line",
        placeholder="https://supplier.example.com/product/part-number",
        height=120,
    )
    max_items = st.number_input("Maximum returned items",1,300,50)
    actor_input = {
        "startUrls":[{"url":u.strip()} for u in urls.splitlines() if u.strip()],
        "maxCrawlPages":int(max_items),
    }
    with st.expander("Actor input preview"):
        st.code(json.dumps(actor_input,indent=2),language="json")

    if st.button("Run price collector", type="primary"):
        if not actor_id or not token:
            st.error("Actor ID and token are required.")
        elif not actor_input["startUrls"]:
            st.error("Add at least one supplier/product URL.")
        else:
            try:
                with st.spinner("Running Actor…"):
                    live = run_apify(actor_id,token,actor_input,int(max_items))
                st.success(f"Collected {len(live)} item(s).")
                st.dataframe(live,use_container_width=True,hide_index=True)
                if not live.empty:
                    st.download_button(
                        "Download raw Apify results",
                        live.to_csv(index=False).encode("utf-8-sig"),
                        file_name=f"apify_price_results_{date.today().isoformat()}.csv",
                        mime="text/csv",
                    )
            except Exception as exc:
                st.error(f"Apify run failed: {exc}")

with tab4:
    st.markdown(
        """
### What this app demonstrates

- Multi-supplier SKU/part comparison.
- Public **Frankfurter** exchange-rate normalization to USD.
- Latest-offer extraction from historical observations.
- Price change calculation by supplier and part.
- Cheapest-offer identification.
- Simple supplier scoring using price, stock and lead time.
- Optional **Apify** live price collection.
- CSV export for sourcing analysis.

The bundled supplier records are fictional sample data. Verify every live price, stock level, supplier identity and procurement condition before purchase.
        """
    )

st.divider()
st.caption("Portfolio demo by Muhammad Naveed · Procurement · Supply Chain · Materials")
