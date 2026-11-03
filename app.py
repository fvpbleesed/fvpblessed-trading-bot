import requests
import pandas as pd
import streamlit as st
from datetime import datetime
from zoneinfo import ZoneInfo

st.set_page_config(page_title="FVPBlessed Global Smart Money", layout="wide")
st.title("🌐 FVPBlessed — Global Smart Money Monitor")
st.caption("PHASE 4 • 10× LEVERAGED FUTURES PAPER SIMULATOR • Kraken public market data • No real orders")
st.warning("Educational simulator only — NO real Futures orders. 10× leverage magnifies gains and losses; liquidation is approximated. Geopolitical, whale-flow and liquidation inputs below are MANUAL.")

PHT = ZoneInfo("Asia/Manila")
now_pht = datetime.now(PHT)
hour = now_pht.hour
# Session labels in PHT; approximations, not exchange opening guarantees.
if 8 <= hour < 16: session = "Asia session"
elif 16 <= hour < 22: session = "London overlap / Europe"
elif 22 <= hour or hour < 5: session = "US session"
else: session = "Quiet transition"
with st.sidebar:
    st.header("Paper Bot Controls")
    starting_cash = st.number_input("Starting virtual cash (USDT)", min_value=100.0, value=1000.0, step=100.0)
    trade_pct = st.slider("Margin allocated (% available cash)", 5, 50, 20)
    leverage = st.select_slider("Paper leverage", options=[2,3,5,10,15,20], value=10)
    maintenance_margin_pct = 0.5
    stop_loss_pct = st.slider("Stop loss (%)", 0.5, 10.0, 2.0, 0.5)
    take_profit_pct = st.slider("Take profit (%)", 1.0, 20.0, 4.0, 0.5)
    fee_pct = st.number_input("Simulated fee per side (%)", min_value=0.0, max_value=1.0, value=0.10, step=0.05)
    st.divider()
    st.subheader("Risk inputs (manual)")
    geopolitics = st.selectbox("Geopolitical risk", ["Low", "Moderate", "High", "Severe"], index=1)
    hormuz = st.selectbox("Hormuz traffic status", ["Unknown / not checked", "Normal", "Disrupted", "Severely disrupted (90%+ reported drop)"])
    whale = st.selectbox("Exchange BTC inflow status", ["Unknown / not checked", "Neutral", "Elevated inflow", "Strong inflow"])
    liq_bias = st.selectbox("Liquidation cluster bias", ["Unknown / not checked", "Above price", "Below price", "Both sides / unclear"])
    risk_block = st.checkbox("Block new BUYs when risk is High/Severe or inflows are strong", value=True)
    refresh = st.button("Refresh Kraken data")
    st.caption("Risk/news/whale fields are manual analyst inputs—not live verified feeds.")

@st.cache_data(ttl=60)
def fetch_kraken_candles():
    r=requests.get("https://api.kraken.com/0/public/OHLC",params={"pair":"XBTUSDT","interval":5},timeout=20,headers={"User-Agent":"FVPBlessed/3.0"})
    r.raise_for_status(); j=r.json()
    if j.get("error"): raise RuntimeError(", ".join(j["error"]))
    res=j["result"]; key=next(k for k in res if k!="last")
    df=pd.DataFrame(res[key][-120:],columns=["time","open","high","low","close","vwap","volume","count"])
    for c in ["open","high","low","close","volume"]: df[c]=pd.to_numeric(df[c],errors="coerce")
    df["time"]=pd.to_datetime(df.time,unit="s",utc=True)
    return df.dropna().reset_index(drop=True)

@st.cache_data(ttl=30)
def fetch_orderbook():
    r=requests.get("https://api.kraken.com/0/public/Depth",params={"pair":"XBTUSDT","count":100},timeout=20,headers={"User-Agent":"FVPBlessed/3.0"})
    r.raise_for_status(); j=r.json()
    if j.get("error"): raise RuntimeError(", ".join(j["error"]))
    book=j["result"]; key=next(iter(book))
    bids=book[key]["bids"]; asks=book[key]["asks"]
    bid_qty=sum(float(x[1]) for x in bids); ask_qty=sum(float(x[1]) for x in asks)
    return bid_qty,ask_qty, (bid_qty/(bid_qty+ask_qty) if bid_qty+ask_qty else .5)

def signals(df):
    d=df.copy()
    d["sma9"]=d.close.rolling(9).mean(); d["sma21"]=d.close.rolling(21).mean()
    d["vol_avg20"]=d.volume.rolling(20).mean()
    d["recent_high"]=d.high.shift(1).rolling(20).max(); d["recent_low"]=d.low.shift(1).rolling(20).min()
    d["bull_sweep"]=(d.low<d.recent_low)&(d.close>d.recent_low)
    d["bear_sweep"]=(d.high>d.recent_high)&(d.close<d.recent_high)
    d["volume_spike"]=d.volume>=1.8*d.vol_avg20
    d["buy_signal"]=d.bull_sweep&(d.sma9>d.sma21)&d.volume_spike
    d["sell_signal"]=d.bear_sweep&(d.sma9<d.sma21)&d.volume_spike
    d["score"]=d.bull_sweep.astype(int)+(d.sma9>d.sma21).astype(int)+d.volume_spike.astype(int)
    return d

if refresh: fetch_kraken_candles.clear(); fetch_orderbook.clear()
try:
    df=signals(fetch_kraken_candles()); bid_btc,ask_btc,book_ratio=fetch_orderbook()
except Exception as e:
    st.error(f"Kraken data error: {e}"); st.info("Refresh or check connectivity."); st.stop()
if len(df)<25: st.error("Not enough candles returned."); st.stop()
latest=df.iloc[-1]; price=float(latest.close)
base_signal="BUY" if bool(latest.buy_signal) else ("SELL" if bool(latest.sell_signal) else "WAIT")
# Order-book imbalance is live but shallow/displayed liquidity can change or be spoofed.
book_label="Bid-heavy" if book_ratio>=.58 else ("Ask-heavy" if book_ratio<=.42 else "Balanced")
risk_high=geopolitics in ["High","Severe"] or hormuz=="Severely disrupted (90%+ reported drop)" or whale=="Strong inflow"
signal=base_signal
if base_signal=="BUY" and risk_block and risk_high: signal="WAIT — RISK BLOCK"
if base_signal=="BUY" and book_ratio<.42: signal="WAIT — ASK-HEAVY BOOK"

# Session state portfolio
if "cash" not in st.session_state:
    st.session_state.cash=float(starting_cash); st.session_state.qty=0.0; st.session_state.entry=0.0; st.session_state.margin=0.0; st.session_state.notional=0.0
    st.session_state.open_time=""; st.session_state.trades=[]; st.session_state.last_candle=None
if st.sidebar.button("Reset paper account"):
    for k in ["cash","qty","entry","margin","notional","open_time","trades","last_candle"]: st.session_state.pop(k,None)
    st.rerun()
cash=float(st.session_state.cash); qty=float(st.session_state.qty); entry=float(st.session_state.entry); margin=float(st.session_state.get("margin",0.0)); notional=float(st.session_state.get("notional",0.0)); trades=st.session_state.trades
candle_id=str(latest.time)
# execute only once per completed/new candle
if st.session_state.last_candle!=candle_id:
    fee=fee_pct/100
    if qty>0:
        reason=None; exit_price=price
        liq_price=entry*(1-(1/leverage)+(maintenance_margin_pct/100))
        if float(latest.low)<=liq_price: exit_price=liq_price; reason="Estimated liquidation"
        elif float(latest.low)<=entry*(1-stop_loss_pct/100): exit_price=entry*(1-stop_loss_pct/100); reason="Stop Loss"
        elif float(latest.high)>=entry*(1+take_profit_pct/100): exit_price=entry*(1+take_profit_pct/100); reason="Take Profit"
        elif bool(latest.sell_signal): reason="SMC SELL signal"
        if reason:
            exit_notional=qty*exit_price; exit_fee=exit_notional*fee
            gross_pnl=(exit_price-entry)*qty
            pnl=gross_pnl-entry*qty*fee-exit_fee
            cash+=margin+gross_pnl-exit_fee
            trades.append({"Opened UTC":st.session_state.open_time,"Closed UTC":candle_id,"Entry":entry,"Exit":exit_price,"Qty BTC":qty,"Leverage":leverage,"Margin USDT":margin,"Gross P&L USDT":gross_pnl,"Net P&L USDT":pnl,"Exit reason":reason})
            qty=0.; entry=0.; margin=0.; notional=0.; st.session_state.open_time=""
    if qty==0 and bool(latest.buy_signal) and signal=="BUY":
        margin=cash*trade_pct/100
        notional=margin*leverage
        buy_fee=notional*fee
        if margin+buy_fee<=cash and notional>0:
            qty=notional/price; entry=price; cash-=margin+buy_fee; st.session_state.open_time=candle_id
    st.session_state.cash=cash; st.session_state.qty=qty; st.session_state.entry=entry; st.session_state.margin=margin; st.session_state.notional=notional; st.session_state.trades=trades; st.session_state.last_candle=candle_id
cash=float(st.session_state.cash); qty=float(st.session_state.qty); entry=float(st.session_state.entry); margin=float(st.session_state.get("margin",0.0)); notional=float(st.session_state.get("notional",0.0)); trades=st.session_state.trades
pos=qty*price; unreal=(price-entry)*qty if qty else 0; equity=cash+margin+unreal
closed=pd.DataFrame(trades); wins=int((closed["Net P&L USDT"]>0).sum()) if len(closed) else 0; losses=int((closed["Net P&L USDT"]<=0).sum()) if len(closed) else 0
wr=wins/len(closed)*100 if len(closed) else 0; realized=float(closed["Net P&L USDT"].sum()) if len(closed) else 0

st.subheader("Philippine market clock")
a,b,c=st.columns(3); a.metric("Philippine time",now_pht.strftime("%I:%M %p")); b.metric("Session estimate",session); c.metric("Day",now_pht.strftime("%A, %d %b"))
st.caption("Session windows are approximate; crypto is open 24/7. Session activity does not guarantee an edge.")
st.subheader("Portfolio & signal")
st.caption(f"Paper Futures: {leverage}× leverage • margin allocation {trade_pct}% of available cash • approximate isolated margin")
m=st.columns(5); m[0].metric("BTC/USDT Kraken",f"${price:,.2f}"); m[1].metric("FVP Signal",signal); m[2].metric("Equity",f"{equity:,.2f} USDT",f"{equity-starting_cash:+,.2f}"); m[3].metric("Realized P&L",f"{realized:+,.2f} USDT"); m[4].metric("Win rate",f"{wr:.1f}%",f"{wins}W / {losses}L")
st.caption(f"Latest candle {latest.time.strftime('%Y-%m-%d %H:%M UTC')} • SMC score {int(latest.score)}/3 (not probability)")
if qty:
    tp=entry*(1+take_profit_pct/100); sl=entry*(1-stop_loss_pct/100); liq=entry*(1-(1/leverage)+(maintenance_margin_pct/100))
    st.success("OPEN VIRTUAL LONG")
    q=st.columns(6); q[0].metric("Entry",f"${entry:,.2f}"); q[1].metric("Take Profit",f"${tp:,.2f}"); q[2].metric("Stop Loss",f"${sl:,.2f}"); q[3].metric("Unrealized P&L",f"{unreal:+,.2f} USDT"); q[4].metric("Position notional",f"{pos:,.2f} USDT"); q[5].metric("Approx. liquidation",f"${liq:,.2f}"); st.caption(f"Isolated margin reserved: {margin:,.2f} USDT • Liquidation estimate uses a simplified {maintenance_margin_pct:.1f}% maintenance margin; actual exchange rules differ.")
else: st.info("No open virtual position. Entry / TP / SL / liquidation estimate appear after a simulated BUY.")
st.subheader("Live Kraken order-book snapshot")
x,y,z=st.columns(3); x.metric("Bid BTC depth (top 100)",f"{bid_btc:.2f} BTC"); y.metric("Ask BTC depth (top 100)",f"{ask_btc:.2f} BTC"); z.metric("Bid share",f"{book_ratio*100:.1f}%",book_label)
st.caption("Order book is live public Kraken depth. It is not whale tracking and can be spoofed/cancelled.")
st.subheader("Global risk monitor")
r=st.columns(4); r[0].metric("Geopolitical risk",geopolitics); r[1].metric("Hormuz",hormuz.split(" (")[0]); r[2].metric("BTC exchange inflow",whale); r[3].metric("Liquidation bias",liq_bias)
if risk_high: st.error("Risk flag active based on your MANUAL inputs. New BUY signals may be blocked.")
else: st.info("No severe risk flag from current manual inputs. This is not an automated news verification.")
st.markdown("**Data-source status:** Kraken price/order book = live public API • Truth Social/geopolitical headlines = manual check • Hormuz AIS = manual check • Whale exchange flows = manual check • Liquidation heatmap = manual check.")
st.markdown("Quick research links: [Trump Truth Social](https://truthsocial.com/@realDonaldTrump) · [CoinGlass liquidation heatmap](https://www.coinglass.com/LiquidityHeatmap) · [Whale Alert](https://whale-alert.io/) · [MarineTraffic](https://www.marinetraffic.com/)")
chart=df.set_index("time")[["close","sma9","sma21"]].rename(columns={"close":"BTC","sma9":"SMA 9","sma21":"SMA 21"})
st.line_chart(chart)
st.subheader("Paper account")
u,v,w=st.columns(3); u.metric("Available cash",f"{cash:,.2f} USDT"); v.metric("Position value",f"{pos:,.2f} USDT"); w.metric("Unrealized P&L",f"{unreal:+,.2f} USDT")
st.subheader("Closed paper trades")
if closed.empty: st.write("No completed simulated trades yet.")
else:
    st.dataframe(closed.iloc[::-1],use_container_width=True,hide_index=True)
    st.download_button("Download CSV",closed.to_csv(index=False).encode(),"FVPBlessed_trades.csv","text/csv")
st.subheader("Recent candles / SMC signals")
st.dataframe(df[["time","open","high","low","close","volume","bull_sweep","bear_sweep","volume_spike","buy_signal","sell_signal","score"]].tail(15),use_container_width=True,hide_index=True)
st.caption("FVPBlessed Phase 4 • 10× Futures paper simulator only • Session-based portfolio; resetting or browser session changes may clear state. No real exchange orders.")
