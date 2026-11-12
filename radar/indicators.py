"""Indicatori tecnici calcolati sui prezzi giornalieri (nessun dato stimato)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def _ret(close: pd.Series, n: int) -> float:
    return float(close.iloc[-1] / close.iloc[-1 - n] - 1) if len(close) > n else np.nan


def technicals(df: pd.DataFrame, spy: pd.DataFrame | None) -> dict:
    c, h, l, v = df["Close"], df["High"], df["Low"], df["Volume"]
    prev = c.shift(1)
    tr = pd.concat([h - l, (h - prev).abs(), (l - prev).abs()], axis=1).max(axis=1)
    chg = c.diff()
    up_vol = v.where(chg > 0, 0).tail(50).sum()
    dn_vol = v.where(chg < 0, 0).tail(50).sum()
    spy_c = spy["Close"] if spy is not None else None
    r63, r126 = _ret(c, 63), _ret(c, 126)
    return {
        "chiusura": float(c.iloc[-1]),
        "data_chiusura": str(c.index[-1].date()) if hasattr(c.index[-1], "date") else str(c.index[-1]),
        "sma50": float(c.tail(50).mean()),
        "sma200": float(c.tail(200).mean()),
        "rend_3m": r63,
        "rend_6m": r126,
        "fr_3m": r63 - _ret(spy_c, 63) if spy_c is not None else np.nan,   # forza relativa vs SPY
        "fr_6m": r126 - _ret(spy_c, 126) if spy_c is not None else np.nan,
        "controvalore_20g": float((c * v).tail(20).mean()),
        "volume_rel_5_50": float(v.tail(5).mean() / v.tail(50).mean()) if v.tail(50).mean() else np.nan,
        "accumulo_50g": float(up_vol / dn_vol) if dn_vol else np.nan,
        "dist_max_52s": float(c.iloc[-1] / h.tail(252).max() - 1),
        "atr_pct": float(tr.tail(14).mean() / c.iloc[-1]),
        "sedute": int(len(c)),
    }
