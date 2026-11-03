import requests
import pandas as pd
import streamlit as st

st.set_page_config(page_title="FVPBlessed Paper Trading", layout="wide")
st.title("📈 FVPBlessed AI Trading Bot")
st.caption("PAPER TRADING • Virtual funds only • No real orders")
st.warning("Educational simulator. Signals can lose money. No profit is guaranteed. Kraken provides public price data only.")

with st.sidebar:
    st.header("Bot Controls")
    starting_cash = st.number_input("Starting virtual cash (USDT)", min_value=100.0, value=1000.0, step=100.0)
    trade_pct = st.slider("Position size (% of available cash)", 5, 50, 20)
    stop_loss_pct = st.slider("Stop loss (%)", 0.5, 10.0, 2.0, 0.5)
    take_profit_pct = st.slider("Take profit (%)", 1.0, 20.0, 4.0, 0.5)
    fee_pct = st.number_input("Simulated fee per side (%)", min_value=0.0, max_value=1.0, value=0.10, step=0.05)
    refresh = st.button("Refresh market data")
    st.caption("Reset clears this browser session's paper portfolio.")

@st.cache_data(ttl=60)
def fetch_kraken_candles():
    response = requests.get(
        "https://api.kraken.com/0/public/OHLC",
        params={"pair": "XBTUSDT", "interval": 5},
        timeout=20,
        headers={"User-Agent": "FVPBlessed-PaperTrading/2.0"},
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

def add_signals(df):
    df = df.copy()
    df["sma9"] = df.close.rolling(9).mean()
    df["sma21"] = df.close.rolling(21).mean()
    df["vol_avg20"] = df.volume.rolling(20).mean()
    df["recent_high"] = df.high.shift(1).rolling(20).max()
    df["recent_low"] = df.low.shift(1).rolling(20).min()
    df["bull_sweep"] = (df.low < df.recent_low) & (df.close > df.recent_low)
    df["bear_sweep"] = (df.high > df.recent_high) & (df.close < df.recent_high)
    df["volume_spike"] = df.volume >= 1.8 * df.vol_avg20
    df["buy_signal"] = df.bull_sweep & (df.sma9 > df.sma21) & df.volume_spike
    df["sell_signal"] = df.bear_sweep & (df.sma9 < df.sma21) & df.volume_spike
    # A more readable signal score; not a prediction probability.
    df["signal_score"] = (
        df.bull_sweep.astype(int) + (df.sma9 > df.sma21).astype(int) +
        df.volume_spike.astype(int)
    )
    return df

if refresh:
    fetch_kraken_candles.clear()
try:
    df = add_signals(fetch_kraken_candles())
except Exception as exc:
    st.error(f"Kraken market data could not be loaded: {exc}")
    st.info("Check your connection and refresh. No real orders are placed.")
    st.stop()
if len(df) < 25:
    st.error("Kraken returned too few candles.")
    st.stop()

latest = df.iloc[-1]
price = float(latest.close)
signal = "BUY" if bool(latest.buy_signal) else ("SELL" if bool(latest.sell_signal) else "WAIT")

# Portfolio is stored only in this Streamlit browser session.
if "paper_cash" not in st.session_state:
    st.session_state.paper_cash = float(starting_cash)
    st.session_state.paper_qty = 0.0
    st.session_state.paper_entry = 0.0
    st.session_state.paper_trades = []
    st.session_state.paper_last_candle = None
if st.sidebar.button("Reset paper account"):
    for key in ["paper_cash", "paper_qty", "paper_entry", "paper_trades", "paper_last_candle"]:
        st.session_state.pop(key, None)
    st.rerun()

cash = float(st.session_state.paper_cash)
qty = float(st.session_state.paper_qty)
entry = float(st.session_state.paper_entry)
trades = st.session_state.paper_trades
candle_id = str(latest.time)

# Execute simulator once per new candle. Buy only when signal says BUY; exit on SELL or SL/TP.
if st.session_state.paper_last_candle != candle_id:
    fee = fee_pct / 100.0
    if qty > 0:
        exit_reason = None
        exit_price = price
        if float(latest.low) <= entry * (1 - stop_loss_pct/100):
            exit_price = entry * (1 - stop_loss_pct/100); exit_reason = "Stop loss"
        elif float(latest.high) >= entry * (1 + take_profit_pct/100):
            exit_price = entry * (1 + take_profit_pct/100); exit_reason = "Take profit"
        elif bool(latest.sell_signal):
            exit_reason = "SELL signal"
        if exit_reason:
            proceeds = qty * exit_price
            exit_fee = proceeds * fee
            pnl = (exit_price-entry)*qty - (entry*qty*fee) - exit_fee
            cash += proceeds - exit_fee
            trades.append({"Opened (UTC)": st.session_state.get("paper_open_time", ""),
                           "Closed (UTC)": candle_id, "Side": "LONG",
                           "Entry": entry, "Exit": exit_price, "Quantity BTC": qty,
                           "Net P&L USDT": pnl, "Reason": exit_reason})
            qty = 0.0; entry = 0.0
            st.session_state.paper_open_time = ""
    if qty == 0 and bool(latest.buy_signal):
        spend = cash * trade_pct/100
        buy_fee = spend * fee
        buy_value = spend - buy_fee
        if buy_value > 0:
            qty = buy_value / price
            entry = price
            cash -= spend
            st.session_state.paper_open_time = candle_id
    st.session_state.paper_cash = cash
    st.session_state.paper_qty = qty
    st.session_state.paper_entry = entry
    st.session_state.paper_trades = trades
    st.session_state.paper_last_candle = candle_id

cash = float(st.session_state.paper_cash)
qty = float(st.session_state.paper_qty)
entry = float(st.session_state.paper_entry)
trades = st.session_state.paper_trades
position_value = qty * price
equity = cash + position_value
unrealized = (price-entry)*qty if qty else 0.0
closed = pd.DataFrame(trades)
wins = int((closed["Net P&L USDT"] > 0).sum()) if not closed.empty else 0
losses = int((closed["Net P&L USDT"] <= 0).sum()) if not closed.empty else 0
win_rate = wins / len(closed) * 100 if not closed.empty else 0.0
realized = float(closed["Net P&L USDT"].sum()) if not closed.empty else 0.0

m1,m2,m3,m4,m5 = st.columns(5)
m1.metric("BTC/USDT (Kraken)", f"${price:,.2f}")
m2.metric("Signal", signal)
m3.metric("Account equity", f"{equity:,.2f} USDT", f"{equity-starting_cash:+,.2f} vs start")
m4.metric("Realized P&L", f"{realized:+,.2f} USDT")
m5.metric("Win rate", f"{win_rate:.1f}%", f"{wins} wins / {losses} losses")
st.caption(f"Latest candle: {latest.time.strftime('%Y-%m-%d %H:%M UTC')} • Candle interval: 5 minutes • Signal score: {int(latest.signal_score)}/3 (not a probability)")

if qty:
    tp_price = entry * (1 + take_profit_pct/100)
    sl_price = entry * (1 - stop_loss_pct/100)
    st.success(f"Open virtual LONG: {qty:.6f} BTC • Position value ${position_value:,.2f} • Unrealized P&L {unrealized:+,.2f} USDT")
    st.subheader("🎯 Active trade levels")
    a, b, c = st.columns(3)
    a.metric("Entry price", f"${entry:,.2f}")
    b.metric("Take profit (TP)", f"${tp_price:,.2f}", f"+{take_profit_pct:.2f}%")
    c.metric("Stop loss (SL)", f"${sl_price:,.2f}", f"-{stop_loss_pct:.2f}%")
    st.caption("TP/SL are simulated exit triggers. The app checks candle high/low; if both are touched in one candle, stop loss is conservatively prioritized.")
else:
    st.info("No open virtual position. Entry, TP, and SL will appear here after a simulated BUY.")

chart = df.set_index("time")[["close","sma9","sma21"]].rename(columns={"close":"BTC price","sma9":"SMA 9","sma21":"SMA 21"})
st.line_chart(chart)
st.subheader("Paper account overview")
x,y,z = st.columns(3)
x.metric("Available virtual cash", f"{cash:,.2f} USDT")
y.metric("Open position value", f"{position_value:,.2f} USDT")
z.metric("Unrealized P&L", f"{unrealized:+,.2f} USDT")
st.caption(f"Position sizing: {trade_pct}% of cash • SL {stop_loss_pct}% • TP {take_profit_pct}% • Fee {fee_pct}% each side")

st.subheader("Closed paper trades")
if closed.empty:
    st.write("No completed simulated trades yet. Signals may be infrequent; this is normal.")
else:
    st.dataframe(closed.iloc[::-1], use_container_width=True, hide_index=True)
    st.download_button("Download trade history CSV", closed.to_csv(index=False).encode("utf-8"), "fvpblessed_paper_trades.csv", "text/csv")

st.subheader("Recent candles and signals")
st.dataframe(df[["time","open","high","low","close","volume","bull_sweep","bear_sweep","volume_spike","buy_signal","sell_signal"]].tail(15), use_container_width=True, hide_index=True)
st.caption("FVPBlessed • Paper trading only • No exchange order placement • Portfolio persists only for this Streamlit session/browser.")
