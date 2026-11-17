# 台股投信買超雷達 V2.0（網頁部署版）

## 本版功能
- FinMind 全市場歷史投信買賣超（上市、上櫃、興櫃資料；介面可篩上市／上櫃）
- 投信連續買超日數、近 5／10／20 日累計買超
- 全市場日價格、MA20／MA60、5／20 日漲幅、成交量比
- 全市場月營收年增率與連續年增月數
- 100 分制綜合評分
- 個股 K 線與均線
- 歷史訊號回測：訊號日收盤後判斷，下一交易日收盤進場，持有 5／10／20 日
- Excel 雷達報表、CSV 回測明細

## 重要：資料權限
本版使用 FinMind API 的全市場日期查詢：
- `TaiwanStockInstitutionalInvestorsBuySell`
- `TaiwanStockPrice`
- `TaiwanStockMonthRevenue`
- `TaiwanStockInfo`

FinMind 文件將「不指定 data_id、一次查詢特定日期所有股票」的法人與月營收查詢標示為 Backer／Sponsor 會員功能。請確認帳戶方案、Token 權限及 API 配額。免費方案通常不能保證全市場歷史掃描可用。API Token 在網頁側欄輸入，不要寫入 GitHub 程式碼。

FinMind 官方文件：
- https://finmind.github.io/tutor/TaiwanMarket/Chip/
- https://finmind.github.io/tutor/TaiwanMarket/Fundamental/
- https://finmindtrade.com/

## 部署到 Streamlit Community Cloud
1. 解壓縮 ZIP。
2. 將 `app.py`、`requirements.txt`、`README.md` 上傳至 GitHub repository 根目錄。
3. 登入 https://share.streamlit.io/ 並授權 GitHub。
4. Create app，選擇 repository、branch `main`、主程式 `app.py`。
5. Deploy 後取得 `*.streamlit.app` 網址。
6. 開啟網站，在左側輸入 FinMind Token 即可使用。

官方部署說明：https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app

## 本機測試（選用）
```bash
python -m pip install -r requirements.txt
streamlit run app.py
```

## 回測方法與限制
- 訊號日收盤後判斷連續買超與近 10 日淨買超。
- 下一個可交易日收盤價進場，持有 5、10、20 個後續交易日。
- 不含手續費、證交稅、滑價、停牌與流動性限制。
- 同一檔股票的連續訊號可能重疊，不可視為獨立交易。
- 使用當前股票清單可能產生存活者偏誤；嚴謹研究需納入下市股票歷史名單。
- 營收資料僅作當下評分，不放進歷史回測，避免沒有歷史公告時間時產生前視偏誤。

## 評分（最高 100 分）
- 投信連續買超日數：30
- 近 10 日投信買超張數：20
- 股價趨勢與均線：25
- 月營收年增率及連續年增月數：25

缺資料時，分數依已取得的項目重新標準化；需同時檢視欄位是否完整。

## 風險聲明
此工具僅供研究與資料整理，不構成投資建議。投信買超不保證上漲，歷史回測不代表未來績效。
