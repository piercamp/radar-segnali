"""Tracciamento dei segnali: registra i migliori di ogni seduta e misura cosa è successo dopo."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


def append_signals(log_path: Path, risultati: pd.DataFrame, data: str, n: int) -> pd.DataFrame:
    top = risultati[risultati["idoneo"]].head(n)
    nuovi = pd.DataFrame({"data_segnale": data, "ticker": top["ticker"],
                          "punteggio": top["punteggio"], "prezzo_segnale": top["chiusura"]})
    if log_path.exists():
        log = pd.read_csv(log_path)
        log = log[log["data_segnale"] != data]  # riesecuzione della stessa seduta: sovrascrive
        log = pd.concat([log, nuovi], ignore_index=True)
    else:
        log = nuovi
    log.to_csv(log_path, index=False)
    return log


def evaluate(log: pd.DataFrame, prices: dict[str, pd.DataFrame], orizzonti: list[int]) -> pd.DataFrame:
    """Rendimento a N sedute di ogni segnale, e differenza rispetto a SPY nello stesso periodo."""
    spy = prices.get("SPY")
    righe = []
    for _, s in log.iterrows():
        df = prices.get(s["ticker"])
        rec = s.to_dict()
        for n in orizzonti:
            rec[f"rend_{n}g"] = rec[f"vs_spy_{n}g"] = np.nan
            if df is None or spy is None:
                continue
            idx = df.index[df.index.strftime("%Y-%m-%d") >= s["data_segnale"]]
            if len(idx) <= n:
                continue
            i0 = df.index.get_loc(idx[0])
            p0, pn = df["Close"].iloc[i0], df["Close"].iloc[i0 + n]
            r = pn / p0 - 1
            sp = spy["Close"]
            j0 = sp.index.searchsorted(df.index[i0])
            rs = sp.iloc[min(j0 + n, len(sp) - 1)] / sp.iloc[j0] - 1
            rec[f"rend_{n}g"], rec[f"vs_spy_{n}g"] = r, r - rs
        righe.append(rec)
    return pd.DataFrame(righe)


def summary(ev: pd.DataFrame, orizzonti: list[int]) -> dict:
    out = {"segnali_totali": int(len(ev))}
    for n in orizzonti:
        col = ev.get(f"vs_spy_{n}g")
        if col is None or col.dropna().empty:
            out[f"{n}g"] = "dati insufficienti"
            continue
        c = col.dropna()
        out[f"{n}g"] = {"segnali_misurati": int(len(c)),
                        "quota_meglio_di_spy": round(float((c > 0).mean()), 2),
                        "extra_rendimento_medio": round(float(c.mean()), 4)}
    return out
