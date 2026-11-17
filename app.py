import io
import time
from datetime import date, datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

API = "https://api.finmindtrade.com/api/v4/data"
st.set_page_config(page_title="台股投信買超雷達 V2.0", page_icon="📡", layout="wide")
st.markdown("""
<style>
.block-container{padding-top:1.2rem;max-width:1600px}
[data-testid="stMetric"]{background:#101d32;border:1px solid #263a59;padding:13px 16px;border-radius:12px}
[data-testid="stDataFrame"]{border:1px solid #253a59;border-radius:10px}
div.stButton>button[kind="primary"]{background:#d9a441;color:#111827;border:0;font-weight:700}
.small{color:#8da2bd;font-size:12px}
</style>
""", unsafe_allow_html=True)

def finmind(dataset: str, start: Optional[str], end: Optional[str], token: str, data_id: Optional[str]=None):
    params = {"dataset": dataset}
    if start:
        params["start_date"] = start
    if end:
        params["end_date"] = end
    if data_id:
        params["data_id"] = data_id
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    resp = requests.get(API, params=params, headers=headers, timeout=90)
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("status") not in (200, "200", None):
        raise RuntimeError(payload.get("msg", str(payload)[:300]))
    rows = payload.get("data", [])
    if not isinstance(rows, list):
        raise RuntimeError("API 回傳格式不是資料清單")
    return pd.DataFrame(rows)

@st.cache_data(ttl=1800, show_spinner=False)
def load_market_data(start: str, end: str, token: str):
    inst = finmind("TaiwanStockInstitutionalInvestorsBuySell", start, end, token)
    return inst

@st.cache_data(ttl=1800, show_spinner=False)
def load_market_prices(start: str, end: str, token: str):
    return finmind("TaiwanStockPrice", start, end, token)

@st.cache_data(ttl=3600, show_spinner=False)
def load_market_revenue(start: str, end: str, token: str):
    return finmind("TaiwanStockMonthRevenue", start, end, token)

@st.cache_data(ttl=86400, show_spinner=False)
def load_stock_info(token: str):
    return finmind("TaiwanStockInfo", None, None, token)

def normalize_inst(df):
    required = {"date","stock_id","name","buy","sell"}
    if df.empty or not required.issubset(df.columns):
        raise ValueError(f"法人資料缺少必要欄位：{required - set(df.columns)}")
    x=df.copy()
    x["date"]=pd.to_datetime(x["date"],errors="coerce")
    x["stock_id"]=x["stock_id"].astype(str).str.strip()
    x["buy"]=pd.to_numeric(x["buy"],errors="coerce").fillna(0)
    x["sell"]=pd.to_numeric(x["sell"],errors="coerce").fillna(0)
    x=x[x["name"].eq("Investment_Trust")].copy()
    x["net_shares"]=x["buy"]-x["sell"]
    return x.dropna(subset=["date"])

def normalize_prices(df):
    if df.empty: return pd.DataFrame()
    x=df.copy()
    x["date"]=pd.to_datetime(x["date"],errors="coerce")
    x["stock_id"]=x["stock_id"].astype(str).str.strip()
    for c in ["open","max","min","close","Trading_Volume","trading_volume"]:
        if c in x: x[c]=pd.to_numeric(x[c],errors="coerce")
    if "Trading_Volume" not in x and "trading_volume" in x:
        x["Trading_Volume"]=x["trading_volume"]
    return x.dropna(subset=["date","stock_id","close"]).sort_values(["stock_id","date"])

def normalize_revenue(df):
    if df.empty:return pd.DataFrame()
    x=df.copy()
    x["stock_id"]=x["stock_id"].astype(str).str.strip()
    x["revenue"]=pd.to_numeric(x["revenue"],errors="coerce")
    x["revenue_year"]=pd.to_numeric(x["revenue_year"],errors="coerce")
    x["revenue_month"]=pd.to_numeric(x["revenue_month"],errors="coerce")
    x["date"]=pd.to_datetime(x["date"],errors="coerce")
    return x.dropna(subset=["stock_id","revenue","revenue_year","revenue_month"])

def get_market_map(info):
    if info.empty:return {}
    out={}
    for _,r in info.iterrows():
        sid=str(r.get("stock_id","")).strip()
        if sid:
            out[sid]={"name":r.get("stock_name",sid),"industry":r.get("industry_category",""),"market":r.get("type","")}
    return out

def compute_streak(group):
    vals=group.sort_values("date")["net_shares"].to_numpy()[::-1]
    n=0
    for v in vals:
        if v>0:n+=1
        else:break
    return n

def revenue_metrics(rev):
    if rev.empty:return pd.DataFrame(columns=["stock_id","營收年增率(%)","連續營收年增月數","最近營收月份"])
    rows=[]
    for sid,g in rev.groupby("stock_id"):
        g=g.sort_values(["revenue_year","revenue_month"]).drop_duplicates(["revenue_year","revenue_month"],keep="last")
        lookup={(int(r.revenue_year),int(r.revenue_month)):float(r.revenue) for r in g.itertuples()}
        latest=g.iloc[-1]
        y,m=int(latest.revenue_year),int(latest.revenue_month)
        prior=lookup.get((y-1,m))
        yoy=(float(latest.revenue)/prior-1)*100 if prior not in (None,0) else np.nan
        streak=0
        yy,mm=y,m
        while (yy-1,mm) in lookup and (yy,mm) in lookup:
            if lookup[(yy,mm)]>lookup[(yy-1,mm)]:
                streak+=1
            else:break
            mm-=1
            if mm==0:yy-=1;mm=12
        rows.append({"stock_id":sid,"營收年增率(%)":yoy,"連續營收年增月數":streak,"最近營收月份":f"{y}-{m:02d}"})
    return pd.DataFrame(rows)

def build_daily_panel(inst, prices, rev_metrics, info_map, min_days, min_net10, universe):
    inst=inst[inst["stock_id"].str.fullmatch(r"\d{4,6}",na=False)].copy()
    if universe=="上市＋上櫃":
        inst=inst[inst["stock_id"].map(lambda s: info_map.get(s,{}).get("market","") in ["twse","tpex","上市","上櫃","TWSE","TPEx",""])]
    elif universe=="上市":
        inst=inst[inst["stock_id"].map(lambda s: str(info_map.get(s,{}).get("market","")).lower() in ["twse","上市"])]
    elif universe=="上櫃":
        inst=inst[inst["stock_id"].map(lambda s: str(info_map.get(s,{}).get("market","")).lower() in ["tpex","上櫃"])]
    rows=[]
    for sid,g in inst.groupby("stock_id"):
        g=g.sort_values("date").drop_duplicates("date")
        if len(g)<min_days:continue
        streak=compute_streak(g)
        net10=float(g.tail(10)["net_shares"].sum()/1000)
        net20=float(g.tail(20)["net_shares"].sum()/1000)
        if streak<min_days or net10<min_net10:continue
        rows.append({"stock_id":sid,"連續買超日數":streak,"近5日買超(張)":g.tail(5)["net_shares"].sum()/1000,
                     "近10日買超(張)":net10,"近20日買超(張)":net20,"最新法人資料日":g["date"].max()})
    c=pd.DataFrame(rows)
    if c.empty:return c
    if not prices.empty:
        p=prices.sort_values(["stock_id","date"]).copy()
        p["MA20"]=p.groupby("stock_id")["close"].transform(lambda s:s.rolling(20,min_periods=20).mean())
        p["MA60"]=p.groupby("stock_id")["close"].transform(lambda s:s.rolling(60,min_periods=60).mean())
        p["近5日漲幅(%)"]=p.groupby("stock_id")["close"].pct_change(5)*100
        p["近20日漲幅(%)"]=p.groupby("stock_id")["close"].pct_change(20)*100
        p["成交量5日均量"]=p.groupby("stock_id")["Trading_Volume"].transform(lambda s:s.rolling(5,min_periods=5).mean()) if "Trading_Volume" in p else np.nan
        p["成交量20日均量"]=p.groupby("stock_id")["Trading_Volume"].transform(lambda s:s.rolling(20,min_periods=20).mean()) if "Trading_Volume" in p else np.nan
        p["量比"]=p["成交量5日均量"]/p["成交量20日均量"]
        latest=p.sort_values("date").groupby("stock_id").tail(1)
        cols=["stock_id","date","close","MA20","MA60","近5日漲幅(%)","近20日漲幅(%)","量比"]
        c=c.merge(latest[cols],on="stock_id",how="left")
        c=c.rename(columns={"date":"最新股價日期","close":"收盤價"})
    if not rev_metrics.empty:c=c.merge(rev_metrics,on="stock_id",how="left")
    else:
        c["營收年增率(%)"]=np.nan;c["連續營收年增月數"]=np.nan;c["最近營收月份"]=""
    c["股票名稱"]=c["stock_id"].map(lambda s:info_map.get(s,{}).get("name",s))
    c["產業"]=c["stock_id"].map(lambda s:info_map.get(s,{}).get("industry",""))
    c["市場"]=c["stock_id"].map(lambda s:info_map.get(s,{}).get("market",""))
    return c

def score_row(r):
    components=[]
    streak=min(float(r.get("連續買超日數",0))/5,1)*30
    net10=min(max(float(r.get("近10日買超(張)",0)),0)/3000,1)*20
    components += [(streak,30),(net10,20)]
    p5=r.get("近5日漲幅(%)");p20=r.get("近20日漲幅(%)")
    if pd.notna(p5) and pd.notna(p20):
        trend=(10 if p5>0 else 0)+(10 if -5<=p20<=20 else 5 if 20<p20<=30 else 0)
        if pd.notna(r.get("MA20")) and pd.notna(r.get("MA60")):
            trend += 5 if r["收盤價"]>r["MA20"]>r["MA60"] else 2.5 if r["收盤價"]>r["MA20"] else 0
        components.append((trend,25))
    if pd.notna(r.get("營收年增率(%)")):
        rev=15 if r["營收年增率(%)"]>=20 else 10 if r["營收年增率(%)"]>0 else 0
        rev += min(float(r.get("連續營收年增月數",0))/6,1)*10
        components.append((rev,25))
    return round(sum(v for v,w in components)/sum(w for v,w in components)*100,1) if components else np.nan

def backtest(inst, prices, min_days, min_net10, start, end):
    """Signal after close on day t; entry at close t+1; exits after 5/10/20 further sessions."""
    if inst.empty or prices.empty:return pd.DataFrame(),pd.DataFrame()
    x=inst.copy()
    x=x[(x["date"]>=pd.Timestamp(start))&(x["date"]<=pd.Timestamp(end))]
    signal_rows=[]
    for sid,g in x.groupby("stock_id"):
        g=g.sort_values("date").drop_duplicates("date").set_index("date")
        all_dates=g.index.sort_values()
        for i,d in enumerate(all_dates):
            hist=g.loc[:d].tail(20)
            if len(hist)<min_days:continue
            streak=0
            for v in hist["net_shares"].to_numpy()[::-1]:
                if v>0:streak+=1
                else:break
            net10=hist.tail(10)["net_shares"].sum()/1000
            if streak>=min_days and net10>=min_net10:
                signal_rows.append({"stock_id":sid,"訊號日":d,"連買日數":streak,"近10日買超(張)":net10})
    sig=pd.DataFrame(signal_rows)
    if sig.empty:return sig,pd.DataFrame()
    p=prices.sort_values(["stock_id","date"]).copy()
    out=[]
    for r in sig.itertuples():
        q=p[p["stock_id"]==r.stock_id].sort_values("date")
        future=q[q["date"]>r.訊號日].reset_index(drop=True)
        if len(future)<21:continue
        entry=float(future.loc[0,"close"])
        row={"stock_id":r.stock_id,"訊號日":r.訊號日,"進場日":future.loc[0,"date"],"進場價":entry,"連買日數":r.連買日數,"近10日買超(張)":r.近10日買超_張_}
        for h in [5,10,20]:
            exit_price=float(future.loc[h,"close"])
            row[f"{h}日出場日"]=future.loc[h,"date"]
            row[f"{h}日報酬(%)"]=(exit_price/entry-1)*100 if entry>0 else np.nan
        out.append(row)
    trades=pd.DataFrame(out)
    if trades.empty:return sig,trades
    return sig,trades

def metrics(trades):
    rows=[]
    for h in [5,10,20]:
        c=f"{h}日報酬(%)"
        s=pd.to_numeric(trades[c],errors="coerce").dropna()
        rows.append({"持有期間":f"{h}日","樣本數":len(s),"平均報酬(%)":round(s.mean(),2) if len(s) else np.nan,
                     "中位數報酬(%)":round(s.median(),2) if len(s) else np.nan,
                     "勝率(%)":round((s>0).mean()*100,1) if len(s) else np.nan,
                     "正報酬筆數":int((s>0).sum()) if len(s) else 0})
    return pd.DataFrame(rows)

def make_chart(px, sid):
    g=px[px["stock_id"]==sid].sort_values("date").tail(150)
    if g.empty:return None
    fig=go.Figure()
    fig.add_trace(go.Candlestick(x=g["date"],open=g["open"],high=g["max"],low=g["min"],close=g["close"],name="K線"))
    fig.add_trace(go.Scatter(x=g["date"],y=g["close"].rolling(20).mean(),name="MA20",line={"width":1.4}))
    fig.add_trace(go.Scatter(x=g["date"],y=g["close"].rolling(60).mean(),name="MA60",line={"width":1.4}))
    fig.update_layout(height=520,xaxis_rangeslider_visible=False,template="plotly_dark",margin=dict(l=10,r=10,t=30,b=10),legend_orientation="h")
    return fig

st.title("📡 台股投信買超雷達 V2.0")
st.caption("全市場歷史籌碼｜技術趨勢｜月營收成長｜個股圖表｜訊號績效回測")
with st.sidebar:
    st.header("資料連線")
    token=st.text_input("FinMind API Token",type="password",help="全市場歷史資料需使用 FinMind 支援全市場日期查詢的會員權限；Token 僅在本次工作階段使用。")
    st.markdown("[取得 FinMind Token](https://finmindtrade.com/)")
    st.divider()
    st.header("選股條件")
    universe=st.selectbox("市場",["上市＋上櫃","上市","上櫃"])
    min_days=st.selectbox("投信連續買超至少", [3,4,5,10],index=0)
    min_net10=st.number_input("近10日累計買超至少（張）",min_value=0,value=0,step=100)
    st.divider()
    lookback_months=st.selectbox("籌碼／股價資料回溯", [6,12,24],index=1)
    include_revenue=st.checkbox("載入月營收基本面",value=True)
    st.caption("全市場歷史法人與價格資料量大，首次載入可能需要數分鐘；請留意 FinMind 帳戶的 API 配額與方案權限。")

if not token:
    st.warning("請在左側輸入 FinMind API Token，才能查詢全市場歷史法人、股價及營收資料。Token 不會寫入程式碼或報表。")
    st.markdown("### V2.0 模組")
    a,b,c,d=st.columns(4)
    a.metric("籌碼評分","50 分")
    b.metric("技術評分","25 分")
    c.metric("營收評分","25 分")
    d.metric("回測期間","5／10／20 日")
    st.stop()

tabs=st.tabs(["📊 全市場雷達","🔎 個股分析","🧪 歷史回測","📚 資料與評分說明"])
with tabs[0]:
    if st.button("🔄 載入資料並掃描全市場",type="primary",use_container_width=True):
        end=date.today()
        start=end-timedelta(days=int(lookback_months*31))
        with st.spinner("載入全市場投信買賣超資料…"):
            try:
                raw_inst=load_market_data(start.isoformat(),end.isoformat(),token)
                inst=normalize_inst(raw_inst)
                if inst.empty:raise RuntimeError("查無投信資料，請確認 Token 權限及日期區間。")
                with st.spinner("載入全市場日價格資料…"):
                    raw_px=load_market_prices(start.isoformat(),end.isoformat(),token)
                    prices=normalize_prices(raw_px)
                rev_metrics=pd.DataFrame()
                if include_revenue:
                    with st.spinner("載入全市場月營收資料…"):
                        raw_rev=load_market_revenue((end-timedelta(days=500)).isoformat(),end.isoformat(),token)
                        rev_metrics=revenue_metrics(normalize_revenue(raw_rev))
                with st.spinner("載入股票基本資料並計算評分…"):
                    info=get_market_map(load_stock_info(token))
                    result=build_daily_panel(inst,prices,rev_metrics,info,min_days,min_net10,universe)
                    if result.empty:raise RuntimeError("目前沒有符合條件的個股。可調低門檻或延長回溯期間。")
                    result["綜合評分"]=result.apply(score_row,axis=1)
                    result=result.sort_values(["綜合評分","近10日買超(張)"],ascending=False)
                st.session_state.update({"inst":inst,"prices":prices,"rev":rev_metrics,"info":info,"result":result,"loaded_at":datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
            except Exception as e:
                st.error(f"資料載入失敗：{e}")
                st.info("若出現權限或額度錯誤，請檢查 FinMind 方案；全市場日期查詢在官方文件中標示為 Backer／Sponsor 會員功能。")
    if "result" in st.session_state:
        r=st.session_state["result"]
        k1,k2,k3,k4=st.columns(4)
        k1.metric("符合條件",f"{len(r)} 檔")
        k2.metric("最高評分",f"{r['綜合評分'].max():.1f}")
        k3.metric("最長連續買超",f"{int(r['連續買超日數'].max())} 日")
        k4.metric("資料載入時間",st.session_state["loaded_at"])
        cols=["stock_id","股票名稱","市場","產業","連續買超日數","近5日買超(張)","近10日買超(張)","近20日買超(張)","近5日漲幅(%)","近20日漲幅(%)","營收年增率(%)","連續營收年增月數","綜合評分"]
        view=r[[c for c in cols if c in r]].rename(columns={"stock_id":"代號"})
        st.dataframe(view,use_container_width=True,hide_index=True)
        buf=io.BytesIO()
        with pd.ExcelWriter(buf,engine="openpyxl") as w:
            view.to_excel(w,index=False,sheet_name="投信雷達")
            st.session_state["inst"].to_excel(w,index=False,sheet_name="法人原始資料")
        st.download_button("⬇️ 下載完整 Excel 報表",buf.getvalue(),file_name=f"台股投信雷達V2_{date.today()}.xlsx",mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        st.caption("資料可能在交易日收盤後持續補計；建議至少於交易日後 1–2 個營業日再次核對。")

with tabs[1]:
    if "result" not in st.session_state:
        st.info("請先至「全市場雷達」載入資料。")
    else:
        r=st.session_state["result"];px=st.session_state["prices"]
        choices={f"{x.stock_id} {x.股票名稱}":x.stock_id for x in r.itertuples()}
        label=st.selectbox("選擇個股",list(choices))
        sid=choices[label]
        row=r[r["stock_id"]==sid].iloc[0]
        a,b,c,d=st.columns(4)
        a.metric("連續買超",f"{row['連續買超日數']} 日")
        b.metric("近10日投信買超",f"{row['近10日買超(張)']:,.0f} 張")
        c.metric("近20日漲幅",f"{row.get('近20日漲幅(%)',np.nan):.2f}%" if pd.notna(row.get("近20日漲幅(%)")) else "N/A")
        d.metric("綜合評分",f"{row['綜合評分']:.1f}")
        fig=make_chart(px,sid)
        if fig:st.plotly_chart(fig,use_container_width=True)
        details=["產業","收盤價","近5日漲幅(%)","近20日漲幅(%)","MA20","MA60","量比","營收年增率(%)","連續營收年增月數","最近營收月份"]
        st.dataframe(pd.DataFrame({"指標":details,"數值":[row.get(x,np.nan) for x in details]}),hide_index=True,use_container_width=True)

with tabs[2]:
    st.markdown("### 投信連續買超訊號歷史績效")
    st.warning("回測採訊號日收盤後判定、下一個可交易日收盤進場，再持有 5／10／20 個交易日。未計手續費、證交稅、滑價及停牌／流動性限制；同一股票訊號可能重疊。")
    if "inst" not in st.session_state:
        st.info("請先至「全市場雷達」載入歷史資料。")
    else:
        bt_start=st.date_input("回測訊號起日",value=date.today()-timedelta(days=180))
        bt_end=st.date_input("回測訊號迄日",value=date.today()-timedelta(days=25))
        if st.button("▶ 執行歷史回測",type="primary"):
            with st.spinner("正在計算歷史訊號及未來報酬…"):
                sig,trades=backtest(st.session_state["inst"],st.session_state["prices"],min_days,min_net10,bt_start,bt_end)
                st.session_state["trades"]=trades
            if trades.empty:st.warning("此區間沒有足夠的有效訊號或未來價格資料。")
            else:
                st.dataframe(metrics(trades),use_container_width=True,hide_index=True)
                st.markdown("#### 每筆訊號明細")
                st.dataframe(trades,use_container_width=True,hide_index=True)
                st.download_button("下載回測明細 CSV",trades.to_csv(index=False,encoding="utf-8-sig"),file_name="投信策略回測明細.csv",mime="text/csv")

with tabs[3]:
    st.markdown("""
### 資料來源
- **投信籌碼**：FinMind `TaiwanStockInstitutionalInvestorsBuySell`，取 `name=Investment_Trust`，淨買超＝buy－sell。
- **股價與成交量**：FinMind `TaiwanStockPrice`。
- **月營收**：FinMind `TaiwanStockMonthRevenue`，依最新月份對比去年同月。
- **股票清單與市場別**：FinMind `TaiwanStockInfo`。

### 100 分評分模型
| 面向 | 權重 | 規則 |
|---|---:|---|
| 投信連買天數 | 30 | 5 日達滿分 |
| 近 10 日投信累計買超 | 20 | 3,000 張達滿分 |
| 股價趨勢 | 25 | 5 日正報酬、20 日不過熱、均線排列 |
| 營收成長 | 25 | 年增率及連續年增月數 |

缺少資料的項目會從分母排除並重新標準化，避免把缺資料直接當成零分。分數是排序工具，不是報酬機率。

### 回測注意事項
- 以訊號日收盤後資料判斷，下一個交易日收盤價作進場價，避免同日收盤價前視偏誤。
- 未計交易成本、稅費、滑價與成交量限制。
- 若使用當前股票清單回看歷史，可能存在存活者偏誤；應搭配含下市股票的完整歷史名單驗證。
- 月營收資料若用於歷史回測，必須依實際公告日決定當時可用資料；目前營收僅用於當下選股評分，不納入歷史籌碼回測。

### 資料更新與權限
FinMind 文件指出，法人資料通常週一至週五更新，資料可能在初次發布後微幅補計；需要較穩定數字時，建議交易日後 1–2 個營業日再取用。全市場單日歷史資料查詢在文件中標示為 Backer／Sponsor 會員功能，請依你的方案與 API 配額使用。
""")
    st.markdown("[FinMind 籌碼資料文件](https://finmind.github.io/tutor/TaiwanMarket/Chip/) · [FinMind 基本面資料文件](https://finmind.github.io/tutor/TaiwanMarket/Fundamental/) · [FinMind 服務與方案](https://finmindtrade.com/)")

st.divider()
st.caption("風險揭露：本工具僅供公開資料整理、研究與策略回測，不構成投資建議。投信買超不保證股價上漲；回測結果不代表未來績效。")
