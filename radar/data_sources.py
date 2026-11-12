"""Fonti dati pubbliche e gratuite.

LiveProvider gira su GitHub Actions (accesso libero a internet).
Ogni metodo restituisce dati oppure None/vuoto: un dato mancante non viene mai inventato.
"""
from __future__ import annotations

import datetime as dt
import io
import os
import re
import time
import xml.etree.ElementTree as ET

import pandas as pd
import requests

SEC_UA = os.environ.get("SEC_USER_AGENT", "radar-segnali research")
SEC_HEADERS = {"User-Agent": SEC_UA, "Accept-Encoding": "gzip, deflate"}
TICKER_OK = re.compile(r"^[A-Z]{1,4}(-[A-Z])?$|^[A-Z]{5}$")


def _ticker_valido(t: str) -> bool:
    if not TICKER_OK.match(t):
        return False
    # escludi warrant, unit e rights a 5 lettere
    return not (len(t) == 5 and t[-1] in "WUR")


class LiveProvider:
    def __init__(self, sleep_sec: float = 0.12):
        self.sleep = sleep_sec
        self.s = requests.Session()

    # ---------- universo ----------
    def universe(self, borse: list[str]) -> pd.DataFrame:
        r = self.s.get("https://www.sec.gov/files/company_tickers_exchange.json",
                       headers=SEC_HEADERS, timeout=30)
        r.raise_for_status()
        j = r.json()
        df = pd.DataFrame(j["data"], columns=j["fields"])
        df = df[df["exchange"].isin(borse)].copy()
        df["ticker"] = df["ticker"].str.upper().str.replace(".", "-", regex=False)
        df = df[df["ticker"].map(_ticker_valido)]
        return df.drop_duplicates("ticker")[["ticker", "name", "cik", "exchange"]].reset_index(drop=True)

    # ---------- prezzi ----------
    def prices(self, tickers: list[str], chunk: int = 200) -> dict[str, pd.DataFrame]:
        import yfinance as yf
        out: dict[str, pd.DataFrame] = {}
        for i in range(0, len(tickers), chunk):
            part = tickers[i:i + chunk]
            try:
                data = yf.download(part, period="14mo", interval="1d", auto_adjust=True,
                                   group_by="ticker", threads=True, progress=False)
            except Exception:
                continue
            for t in part:
                try:
                    df = data[t] if len(part) > 1 else data
                    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
                    if len(df):
                        out[t] = df
                except Exception:
                    pass
            time.sleep(1)
        return out

    # ---------- insider (SEC Form 4) ----------
    def insider_purchases(self, cik_by_ticker: dict[str, int], giorni: int) -> dict[str, list[dict] | None]:
        """Per ticker: lista di acquisti a mercato (codice P) negli ultimi N giorni; None se la SEC non risponde."""
        limite = dt.date.today() - dt.timedelta(days=giorni)
        res: dict[str, list[dict] | None] = {}
        for t, cik in cik_by_ticker.items():
            try:
                url = f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json"
                rec = self.s.get(url, headers=SEC_HEADERS, timeout=30).json()["filings"]["recent"]
                time.sleep(self.sleep)
                acquisti = []
                for form, acc, fdate, doc in zip(rec["form"], rec["accessionNumber"],
                                                 rec["filingDate"], rec["primaryDocument"]):
                    if form != "4":
                        continue
                    if dt.date.fromisoformat(fdate) < limite:
                        break  # elenco ordinato dal più recente
                    xml_url = (f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
                               f"{acc.replace('-', '')}/{doc.split('/')[-1]}")
                    x = self.s.get(xml_url, headers=SEC_HEADERS, timeout=30)
                    time.sleep(self.sleep)
                    acquisti += _parse_form4(x.text, fdate)
                res[t] = acquisti
            except Exception:
                res[t] = None
        return res

    # ---------- short volume (FINRA) ----------
    def short_volume(self, tickers: list[str], sedute: int = 5) -> dict[str, float | None]:
        frames, d = [], dt.date.today()
        tentativi = 0
        while len(frames) < sedute and tentativi < 12:
            d -= dt.timedelta(days=1)
            tentativi += 1
            if d.weekday() >= 5:
                continue
            url = f"https://cdn.finra.org/equity/regsho/daily/CNMSshvol{d:%Y%m%d}.txt"
            try:
                r = self.s.get(url, timeout=30)
                if r.status_code == 200 and "|" in r.text:
                    frames.append(pd.read_csv(io.StringIO(r.text), sep="|"))
            except Exception:
                pass
        if not frames:
            return {t: None for t in tickers}
        df = pd.concat(frames)
        df = df[df["Symbol"].isin(tickers)]
        agg = df.groupby("Symbol")[["ShortVolume", "TotalVolume"]].sum()
        ratio = (agg["ShortVolume"] / agg["TotalVolume"]).to_dict()
        return {t: ratio.get(t) for t in tickers}

    # ---------- fondamentali e calendario ----------
    def fundamentals(self, tickers: list[str]) -> dict[str, dict]:
        import yfinance as yf
        out = {}
        for t in tickers:
            info, prossima = {}, None
            try:
                info = yf.Ticker(t).info or {}
            except Exception:
                pass
            try:
                cal = yf.Ticker(t).calendar or {}
                date = cal.get("Earnings Date") if isinstance(cal, dict) else None
                if date:
                    prossima = min(pd.Timestamp(x).date() for x in date)
            except Exception:
                pass
            out[t] = {
                "revenueGrowth": info.get("revenueGrowth"),
                "earningsGrowth": info.get("earningsGrowth"),
                "operatingMargins": info.get("operatingMargins"),
                "debtToEquity": info.get("debtToEquity"),
                "forwardPE": info.get("forwardPE"),
                "sector": info.get("sector"),
                "prossima_trimestrale": prossima,
            }
            time.sleep(0.3)
        return out


def _parse_form4(xml_text: str, fdate: str) -> list[dict]:
    """Estrae gli acquisti a mercato aperto (transactionCode = P) da un Form 4."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    nome = root.findtext(".//reportingOwner/reportingOwnerId/rptOwnerName", default="N/D")
    ruolo = root.findtext(".//reportingOwnerRelationship/officerTitle", default="") or (
        "Director" if root.findtext(".//reportingOwnerRelationship/isDirector") in ("1", "true") else "")
    out = []
    for tr in root.findall(".//nonDerivativeTable/nonDerivativeTransaction"):
        if tr.findtext("./transactionCoding/transactionCode") != "P":
            continue
        try:
            q = float(tr.findtext("./transactionAmounts/transactionShares/value"))
            p = float(tr.findtext("./transactionAmounts/transactionPricePerShare/value"))
        except (TypeError, ValueError):
            continue
        out.append({"insider": nome, "ruolo": ruolo, "azioni": q, "prezzo": p,
                    "valore_usd": q * p, "data_deposito": fdate})
    return out
