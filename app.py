import requests
import pandas as pd
import streamlit as st

st.set_page_config(page_title="FVPBlessed AI Trading Bot", layout="wide")
st.title("📈 FVPBlessed AI Trading Bot")
st.caption("PAPER TRADING • Virtual funds only • No real orders")
st.subheader("Smart Money Concepts (SMC) — candle-based proxy")
st.write("Liquidity sweeps + volume spike + SMA trend filter. This is not actual whale-wallet tracking.")
st.warning("Educational simulator only. Signals can lose money; this dashboard does not guarantee profits.")

with st.sidebar:
    st.header("Bot Controls")
    virtual_cash = st.number_input("Starting virtual cash (USDT)", min_value=100.0, value=1000.0, step=100.0)
    trade_pct = st.slider("Trade size (% of cash)", 5, 50, 20)
    stop_loss = st.slider("Stop loss (%)", 0.5, 10.0, 2.0, 0.5)
    take_profit = st.slider("Take profit (%)", 1.0, 20.0, 4.0, 0.5)
    refresh = st.button("Refresh market data")

@st.cache_data(ttl=60)
def fetch_kraken_candles():
    # Kraken public OHLC endpoint; 5-minute candles; no API key needed.
    response = requests.get(
        "https://api.kraken.com/0/public/OHLC",
        params={"pair": "XBTUSDT", "interval": 5},
        timeout=20,
        headers={"User-Agent": "FVPBlessed-PaperTrading/1.0"},
    )
    response.raise_for_status()
    data = response.json()
    if data.get("error"):
        raise RuntimeError(", ".join(data["error"]))
    result = data["result"]
    pair_key = next(key for key in result if key != "last")
    rows = result[pair_key][-120:]
    df = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close", "vwap", "volume", "count"])
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    return df.dropna().reset_index(drop=True)

if refresh:
    fetch_kraken_candles.clear()

try:
    df = fetch_kraken_candles()
except Exception as exc:
    st.error(f"Kraken market data could not be loaded: {exc}")
    st.info("Refresh the page or try again later. This app does not place real trades.")
    st.stop()

if len(df) < 25:
    st.error("Kraken returned too few candles to calculate the indicators.")
    st.stop()

df["sma9"] = df["close"].rolling(9).mean()
df["sma21"] = df["close"].rolling(21).mean()
df["vol_avg20"] = df["volume"].rolling(20).mean()
df["recent_high"] = df["high"].shift(1).rolling(20).max()
df["recent_low"] = df["low"].shift(1).rolling(20).min()
df["bull_sweep"] = (df["low"] < df["recent_low"]) & (df["close"] > df["recent_low"])
df["bear_sweep"] = (df["high"] > df["recent_high"]) & (df["close"] < df["recent_high"])
df["volume_spike"] = df["volume"] >= 1.8 * df["vol_avg20"]
df["buy_signal"] = df["bull_sweep"] & (df["sma9"] > df["sma21"]) & df["volume_spike"]
df["sell_signal"] = df["bear_sweep"] & (df["sma9"] < df["sma21"]) & df["volume_spike"]

latest = df.iloc[-1]
price = float(latest["close"])
signal = "BUY" if bool(latest["buy_signal"]) else ("SELL" if bool(latest["sell_signal"]) else "WAIT")

a, b, c, d = st.columns(4)
a.metric("BTC/USDT (Kraken)", f"${price:,.2f}")
b.metric("SMC signal", signal)
c.metric("Candle interval", "5 minutes")
d.metric("Market data", "Kraken public API")
st.caption(f"Latest candle: {latest['time'].strftime('%Y-%m-%d %H:%M UTC')}")

plot = df.set_index("time")[["close", "sma9", "sma21"]].rename(
    columns={"close": "BTC price", "sma9": "SMA 9", "sma21": "SMA 21"}
)
st.line_chart(plot)

st.subheader("Recent candles and SMC signals")
st.dataframe(
    df[["time", "open", "high", "low", "close", "volume", "buy_signal", "sell_signal"]].tail(15),
    use_container_width=True,
)

st.subheader("Paper-trading settings")
st.write(
    f"Virtual starting cash: **${virtual_cash:,.2f} USDT** • "
    f"Trade sizing setting: **{trade_pct}%** • Stop loss: **{stop_loss}%** • "
    f"Take profit: **{take_profit}%**"
)
st.info("This build displays Kraken candles and SMC-style signals. It is not yet a persistent automated trade simulator.")
st.caption("FVPBlessed • Paper trading only • No real orders")
