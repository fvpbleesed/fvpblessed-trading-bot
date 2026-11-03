"""
FVPBlessed AI Trading Bot — Dashboard (Paper Trading)
====================================================
Local Streamlit dashboard for a virtual BTC/USDT trading simulator.
No real orders are placed; no exchange credentials are needed.

Install:
  pip install -r requirements.txt

Run:
  streamlit run app.py
"""

import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="FVPBlessed AI Trading Bot", page_icon="📈", layout="wide")

# ---------------- Settings ----------------
SYMBOL = "BTCUSDT"
INTERVAL = "5m"
START_CASH = 1000.0
FAST = 9
SLOW = 21
TRADE_FRACTION = 0.20
SWING_LOOKBACK = 20
VOLUME_SPIKE_MULTIPLE = 1.8
STOP_LOSS = 0.02
TAKE_PROFIT = 0.04
FEE = 0.001
API = "https://api.binance.com/api/v3/klines"

st.title("📈 FVPBlessed AI Trading Bot")
st.caption("PAPER TRADING • Virtual funds only • No real orders")
st.subheader("Smart Money Concepts (SMC) — candle-based proxy")
st.write("Liquidity sweeps + volume spike + SMA trend filter. This does **not** identify actual whale wallets.")
st.warning("Educational simulator only. Trading signals can lose money; this dashboard does not guarantee profits.")

@st.cache_data(ttl=45)
def get_candles():
    r = requests.get(API, params={"symbol": SYMBOL, "interval": INTERVAL, "limit": 120}, timeout=15)
    r.raise_for_status()
    raw = r.json()
    df = pd.DataFrame(raw, columns=[
        "open_time","open","high","low","close","volume","close_time",
        "quote_volume","trades","taker_buy_base","taker_buy_quote","ignore"
    ])
    for c in ["open","high","low","close","volume"]:
        df[c] = pd.to_numeric(df[c])
    df["time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    return df.iloc[:-1].copy()  # exclude candle still forming


def smart_money_signal(df):
    """Candle-based SMC proxy; not actual on-chain whale tracking."""
    if len(df) < max(SLOW, SWING_LOOKBACK) + 3:
        return "WAIT", "Not enough history", {}
    recent = df.iloc[-(SWING_LOOKBACK+1):-1]
    candle = df.iloc[-1]
    swing_high = float(recent["high"].max())
    swing_low = float(recent["low"].min())
    avg_vol = float(df["volume"].iloc[-21:-1].mean())
    vol = float(candle["volume"])
    fast = df["close"].rolling(FAST).mean()
    slow = df["close"].rolling(SLOW).mean()
    bullish = fast.iloc[-1] > slow.iloc[-1]
    bearish = fast.iloc[-1] < slow.iloc[-1]
    sweep_low = float(candle["low"]) < swing_low and float(candle["close"]) > swing_low
    sweep_high = float(candle["high"]) > swing_high and float(candle["close"]) < swing_high
    spike = avg_vol > 0 and vol >= VOLUME_SPIKE_MULTIPLE * avg_vol
    meta = {"swing_low": swing_low, "swing_high": swing_high,
            "volume_ratio": vol/avg_vol if avg_vol else 0}
    if sweep_low and bullish and spike:
        return "BUY", "Bullish liquidity sweep + volume + trend", meta
    if sweep_high and bearish and spike:
        return "SELL", "Bearish liquidity sweep + volume + trend", meta
    return "WAIT", "No confirmed SMC setup", meta

def init_state():
    defaults = {
        "cash": START_CASH, "btc": 0.0, "entry": None,
        "trades": [], "equity_history": [], "running": False,
        "last_signal": "Waiting for data", "last_processed": None,
    }
    for k,v in defaults.items():
        if k not in st.session_state: st.session_state[k] = v

init_state()

def reset():
    for k in ["cash","btc","entry","trades","equity_history","running","last_signal","last_processed"]:
        st.session_state.pop(k, None)
    init_state()

def process_market(df):
    # process only the newest closed candle once
    latest = df.iloc[-1]
    candle_time = latest["time"].isoformat()
    if st.session_state.last_processed == candle_time:
        return
    price = float(latest["close"])
    signal, signal_reason, meta = smart_money_signal(df)
    action, reason = "HOLD", signal_reason
    if st.session_state.btc == 0 and signal == "BUY":
        spend = st.session_state.cash * TRADE_FRACTION
        qty = (spend * (1-FEE)) / price
        st.session_state.cash -= spend
        st.session_state.btc += qty
        st.session_state.entry = price
        action, reason = "BUY", signal_reason
    elif st.session_state.btc > 0:
        pnl_pct = (price-st.session_state.entry)/st.session_state.entry
        exit_reason = None
        if pnl_pct <= -STOP_LOSS:
            exit_reason = "Stop-loss"
        elif pnl_pct >= TAKE_PROFIT:
            exit_reason = "Take-profit"
        elif signal == "SELL":
            exit_reason = signal_reason
        if exit_reason:
            proceeds = st.session_state.btc * price * (1-FEE)
            st.session_state.cash += proceeds
            st.session_state.btc = 0.0
            st.session_state.entry = None
            action, reason = "SELL", exit_reason
    equity = st.session_state.cash + st.session_state.btc * price
    st.session_state.trades.append({
        "time": candle_time, "action": action, "price": price,
        "cash": st.session_state.cash, "btc": st.session_state.btc,
        "equity": equity, "reason": reason
    })
    st.session_state.equity_history.append({"time": candle_time, "equity": equity})
    st.session_state.last_signal = f"{action} — {reason}"
    st.session_state.last_processed = candle_time

# ---------------- Sidebar controls ----------------
st.sidebar.header("Bot Controls")
st.sidebar.write(f"Pair: **{SYMBOL}**")
st.sidebar.write(f"Candle: **{INTERVAL}**")
st.sidebar.write(f"Starting virtual cash: **{START_CASH:.2f} USDT**")
st.sidebar.write(f"Trade size: **{TRADE_FRACTION:.0%} of cash**")
st.sidebar.write(f"Stop loss: **{STOP_LOSS:.0%}** • Take profit: **{TAKE_PROFIT:.0%}**")
if st.sidebar.button("Reset paper account", type="secondary"):
    reset()
    st.rerun()
st.sidebar.caption("Reset clears this browser session's simulated trade history.")

# ---------------- Main ----------------
try:
    df = get_candles()
    process_market(df)
    price = float(df.iloc[-1]["close"])
    equity = st.session_state.cash + st.session_state.btc * price
    pnl = equity - START_CASH
    ret = pnl / START_CASH * 100

    c1,c2,c3,c4 = st.columns(4)
    c1.metric("BTC/USDT", f"${price:,.2f}")
    c2.metric("Virtual equity", f"{equity:,.2f} USDT", f"{pnl:+,.2f} USDT")
    c3.metric("Return", f"{ret:+.2f}%")
    c4.metric("BTC held", f"{st.session_state.btc:.6f}")

    st.subheader("Market chart")
    chart = df.set_index("time")[["close"]].rename(columns={"close":"BTC price"})
    st.line_chart(chart)

    st.subheader("Bot status")
    st.info(f"Latest strategy status: **{st.session_state.last_signal}**")
    st.caption(f"Last closed candle: {df.iloc[-1]['time']} • SMC proxy • SMA {FAST}/{SLOW}")
    smc, smc_reason, meta = smart_money_signal(df)
    st.write(f"SMC signal: **{smc}** — {smc_reason}")
    if meta.get("volume_ratio"): st.write(f"Volume vs. average: **{meta['volume_ratio']:.2f}×**")
    if meta.get("swing_low") is not None: st.write(f"Recent liquidity range: ${meta['swing_low']:,.2f} – ${meta['swing_high']:,.2f}")

    left,right = st.columns(2)
    with left:
        st.subheader("Virtual equity history")
        if st.session_state.equity_history:
            hist = pd.DataFrame(st.session_state.equity_history).set_index("time")[["equity"]]
            st.line_chart(hist)
        else:
            st.write("No processed candles yet. The bot waits for a crossover.")
    with right:
        st.subheader("Position")
        if st.session_state.btc:
            st.write(f"Entry price: **${st.session_state.entry:,.2f}**")
            st.write(f"Unrealized P/L: **{(price-st.session_state.entry)/st.session_state.entry*100:+.2f}%**")
        else:
            st.write("No open BTC position.")

    st.subheader("Trade / decision log")
    trades = pd.DataFrame(st.session_state.trades)
    if not trades.empty:
        st.dataframe(trades.sort_values("time", ascending=False), use_container_width=True)
        st.download_button("Download CSV log", trades.to_csv(index=False), "fvpblessed_paper_trades.csv", "text/csv")
    else:
        st.write("The log will appear after the first processed candle.")
except Exception as e:
    st.error(f"Market data could not be loaded: {e}")
    st.info("Check your internet connection and try refreshing.")

st.caption("FVPBlessed • Phase 2 dashboard • Paper trading only")
# Auto-refresh to poll market data. Streamlit reruns the script every 60 seconds.
time.sleep(0.1)
st.markdown('<meta http-equiv="refresh" content="60">', unsafe_allow_html=True)
