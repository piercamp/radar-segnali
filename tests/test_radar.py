"""Collaudo con dati simulati: verifica filtri, N/D, veti, tracciamento."""
import datetime as dt
import json

import numpy as np
import pandas as pd

from radar import run
from radar.data_sources import _parse_form4

OGGI = dt.date(2026, 11, 12)


class FakeProvider:
    """Mercato simulato: 300 titoli, alcuni in trend, alcuni illiquidi, alcuni con storico corto."""

    def __init__(self, fine: dt.date, seed: int = 7):
        self.fine = fine
        rng = np.random.default_rng(seed)
        self.idx = pd.bdate_range(end=pd.Timestamp(fine), periods=300)
        self.tickers = [f"T{i:03d}" for i in range(300)]
        self.px = {}
        for i, t in enumerate(self.tickers):
            drift = 0.0015 if i < 40 else (-0.001 if i < 80 else 0.0)
            r = rng.normal(drift, 0.018, len(self.idx))
            c = 50 * np.exp(np.cumsum(r))
            vol = (2e6 if i % 10 else 5e3) * rng.uniform(0.6, 1.4, len(self.idx))  # ogni 10° illiquido
            df = pd.DataFrame({"Open": c, "High": c * 1.01, "Low": c * 0.99, "Close": c, "Volume": vol},
                              index=self.idx)
            self.px[t] = df.tail(100) if t == "T005" else df  # storico corto
        s = 400 * np.exp(np.cumsum(rng.normal(0.0004, 0.01, len(self.idx))))
        self.px["NVDA"] = self.px["T001"].copy()
        self.px["SPY"] = pd.DataFrame({"Open": s, "High": s, "Low": s, "Close": s, "Volume": 1e8},
                                      index=self.idx)

    def universe(self, borse):
        return pd.DataFrame({"ticker": self.tickers, "name": [f"Società {t}" for t in self.tickers],
                             "cik": range(1, 301), "exchange": "NYSE"})

    def prices(self, tickers):
        return {t: self.px[t] for t in tickers if t in self.px}

    def insider_purchases(self, cik_by_ticker, giorni):
        out = {t: [] for t in cik_by_ticker}
        primi = list(cik_by_ticker)
        out[primi[0]] = [{"insider": "CEO A", "valore_usd": 800_000}, {"insider": "CFO B", "valore_usd": 300_000}]
        out[primi[3]] = None  # SEC non raggiungibile per questo titolo
        return out

    def short_volume(self, tickers):
        return {t: 0.55 for t in tickers}

    def fundamentals(self, tickers):
        base = {"revenueGrowth": 0.1, "earningsGrowth": 0.05, "operatingMargins": 0.2,
                "debtToEquity": 60, "forwardPE": 22, "sector": "Consumer Defensive",
                "prossima_trimestrale": self.fine + dt.timedelta(days=40)}
        out = {t: dict(base) for t in tickers}
        out[tickers[1]]["prossima_trimestrale"] = self.fine + dt.timedelta(days=2)  # veto
        out[tickers[2]] = {}  # fondamentali assenti
        return out


def test_end_to_end(tmp_path):
    p = FakeProvider(OGGI)
    rap = run.main(provider=p, out_dir=tmp_path, oggi=OGGI)
    c = pd.read_csv(tmp_path / "candidati_latest.csv")

    assert rap["seduta_completa"]
    assert c["idoneo"].sum() == 30 and len(c) <= 40
    assert "T005" not in set(c["ticker"])                                  # storico corto escluso
    assert not any(int(t[1:]) % 10 == 0 for t in c["ticker"])             # illiquidi esclusi
    assert c["punteggio"].between(0, 100).all()
    # i titoli simulati in trend dominano la classifica
    assert (c.head(10)["ticker"].str[1:].astype(int) < 40).mean() >= 0.7

    tutti = pd.read_csv(tmp_path / "storico" / f"candidati_{rap['seduta']}.csv")
    ordine = list(tutti["ticker"])
    veto = tutti[tutti["veto"].fillna("") != ""]
    assert len(veto) >= 1 and not veto["idoneo"].any()                    # veto trimestrale rispettato
    assert rap["fonti_ko"]["insider_N/D"] == 1

    m = pd.read_csv(tmp_path / "monitorati_latest.csv")
    assert set(m["ticker"]) >= {"NVDA"}
    log = pd.read_csv(tmp_path / "segnali_log.csv")
    assert len(log) == 10 and log["ticker"].isin(ordine).all()


def test_completezza_bassa_non_idonea(tmp_path):
    p = FakeProvider(OGGI)
    p.fundamentals = lambda tickers: {t: {} for t in tickers}             # nessun fondamentale
    p.insider_purchases = lambda m, g: {t: None for t in m}               # SEC giù
    run.main(provider=p, out_dir=tmp_path, oggi=OGGI)
    c = pd.read_csv(tmp_path / "candidati_latest.csv")
    assert (c["completezza"] < 0.85).all() and not c["idoneo"].any()      # N/D -> nessuna allerta


def test_copertura_insufficiente(tmp_path):
    p = FakeProvider(OGGI)
    full = p.prices
    p.prices = lambda tickers: {k: v for k, v in full(tickers).items() if not k.startswith("T") or int(k[1:]) < 100}
    rap = run.main(provider=p, out_dir=tmp_path, oggi=OGGI)
    assert not rap["seduta_completa"] and rap["candidati_idonei"] == 0


def test_tracciamento_performance(tmp_path):
    run.main(provider=FakeProvider(OGGI - dt.timedelta(days=42)), out_dir=tmp_path,
             oggi=OGGI - dt.timedelta(days=42))
    rap = run.main(provider=FakeProvider(OGGI), out_dir=tmp_path, oggi=OGGI)
    perf = rap["performance_segnali"]
    assert perf["segnali_totali"] == 20
    assert perf["20g"]["segnali_misurati"] == 10


def test_parse_form4():
    xml = """<ownershipDocument><reportingOwner><reportingOwnerId><rptOwnerName>Rossi Mario</rptOwnerName>
    </reportingOwnerId><reportingOwnerRelationship><officerTitle>CEO</officerTitle></reportingOwnerRelationship>
    </reportingOwner><nonDerivativeTable>
    <nonDerivativeTransaction><transactionCoding><transactionCode>P</transactionCode></transactionCoding>
    <transactionAmounts><transactionShares><value>1000</value></transactionShares>
    <transactionPricePerShare><value>150.5</value></transactionPricePerShare></transactionAmounts>
    </nonDerivativeTransaction>
    <nonDerivativeTransaction><transactionCoding><transactionCode>S</transactionCode></transactionCoding>
    <transactionAmounts><transactionShares><value>500</value></transactionShares>
    <transactionPricePerShare><value>151</value></transactionPricePerShare></transactionAmounts>
    </nonDerivativeTransaction></nonDerivativeTable></ownershipDocument>"""
    out = _parse_form4(xml, "2026-11-10")
    assert len(out) == 1 and out[0]["valore_usd"] == 150500 and out[0]["ruolo"] == "CEO"
