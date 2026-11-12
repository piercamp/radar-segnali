"""Punteggio oggettivo 0-100 con pesi dichiarati in config.yaml.

Regola chiave: un componente senza dati vale N/D (non zero, non stimato) e riduce la
'completezza'. Sotto la completezza minima il titolo non è idoneo ad allerta.
"""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd


def _pct_rank(s: pd.Series) -> pd.Series:
    return s.rank(pct=True, na_option="keep")


def stage1(tech: pd.DataFrame, w: dict) -> pd.DataFrame:
    """Trend, momentum e accumulo su tutto l'universo liquido."""
    t = tech.copy()
    t["p_trend"] = w["trend"] * (
        (t["chiusura"] > t["sma200"]) * 0.40
        + (t["sma50"] > t["sma200"]) * 0.32
        + (t["chiusura"] > t["sma50"]) * 0.28)
    t["p_momentum"] = w["momentum"] * (
        _pct_rank(t["fr_6m"]).fillna(0) * 0.6 + _pct_rank(t["fr_3m"]).fillna(0) * 0.4)
    t["p_accumulo"] = w["accumulo"] * (
        _pct_rank(t["accumulo_50g"]).fillna(0) * 0.55
        + _pct_rank(t["volume_rel_5_50"].clip(upper=3)).fillna(0) * 0.25
        + (t["dist_max_52s"] >= -0.10) * 0.20)
    t["punteggio_tecnico"] = t[["p_trend", "p_momentum", "p_accumulo"]].sum(axis=1)
    return t.sort_values("punteggio_tecnico", ascending=False)


def insider_points(acq: list[dict] | None, w: float, soglia: float, forte: float):
    if acq is None:
        return np.nan, "N/D"
    if not acq:
        return 0.0, "nessun acquisto"
    tot = sum(a["valore_usd"] for a in acq)
    persone = len({a["insider"] for a in acq})
    testo = f"{persone} insider, {tot/1e6:.2f} mln USD"
    if tot >= forte or (persone >= 2 and tot >= soglia):
        return float(w), testo
    if tot >= soglia:
        return w * 0.55, testo
    return w * 0.2, testo


def fundamental_points(f: dict, w: float):
    """5 controlli, ciascuno vale 1/5 del peso; quelli senza dato sono N/D."""
    checks = {
        "ricavi_in_crescita": (f.get("revenueGrowth"), lambda x: x > 0),
        "utili_in_crescita": (f.get("earningsGrowth"), lambda x: x > 0),
        "margine_operativo_positivo": (f.get("operatingMargins"), lambda x: x > 0),
        "debito_sostenibile": (f.get("debtToEquity"), lambda x: x < 150),
        "pe_prospettico_ragionevole": (f.get("forwardPE"), lambda x: 0 < x < 40),
    }
    disp = {k: fn(v) for k, (v, fn) in checks.items() if v is not None and not pd.isna(v)}
    if not disp:
        return np.nan, 0.0, "N/D"
    punti = w * sum(disp.values()) / len(checks)
    quota = len(disp) / len(checks)
    ok = [k for k, v in disp.items() if v]
    return punti, quota, ", ".join(ok) if ok else "nessun controllo superato"


def short_points(ratio: float | None, sopra_sma50: bool, w: float):
    """Sperimentale: vendite allo scoperto elevate assorbite da un prezzo in salita."""
    if ratio is None or pd.isna(ratio):
        return np.nan, "N/D"
    if ratio >= 0.50 and sopra_sma50:
        return float(w), f"short {ratio:.0%} assorbito dal prezzo"
    return 0.0, f"short {ratio:.0%}"


def business_days_until(d: dt.date | None, oggi: dt.date) -> int | None:
    if d is None:
        return None
    return int(np.busday_count(oggi, d)) if d >= oggi else -1


def stage2(cand: pd.DataFrame, insider: dict, short: dict, fund: dict, cfg: dict, oggi: dt.date) -> pd.DataFrame:
    w = cfg["pesi"]
    rows = []
    for _, r in cand.iterrows():
        t = r["ticker"]
        p_ins, ins_txt = insider_points(insider.get(t), w["insider"],
                                        cfg["insider"]["soglia_importo_usd"], cfg["insider"]["importo_forte_usd"])
        f = fund.get(t, {})
        p_fun, quota_fun, fun_txt = fundamental_points(f, w["fondamentali"])
        p_sh, sh_txt = short_points(short.get(t), r["chiusura"] > r["sma50"], w["short"])

        disponibili = w["trend"] + w["momentum"] + w["accumulo"]
        disponibili += w["insider"] if not np.isnan(p_ins) else 0
        disponibili += w["fondamentali"] * quota_fun
        disponibili += w["short"] if not np.isnan(p_sh) else 0
        completezza = disponibili / sum(w.values())

        punteggio = r["punteggio_tecnico"] + np.nansum([p_ins, p_fun, p_sh])

        giorni_tri = business_days_until(f.get("prossima_trimestrale"), oggi)
        veti = []
        if giorni_tri is not None and 0 <= giorni_tri <= cfg["veto"]["giorni_lavorativi_a_trimestrale"]:
            veti.append(f"trimestrale tra {giorni_tri} gg lavorativi")
        if giorni_tri is None:
            veti.append("data trimestrale N/D (da verificare)")

        flag = []
        if r["atr_pct"] >= cfg["volatilita"]["atr_alta_pct"]:
            flag.append(f"volatilità alta (ATR {r['atr_pct']:.1%})")

        rows.append({**r.to_dict(),
                     "p_insider": p_ins, "insider": ins_txt,
                     "p_fondamentali": p_fun, "fondamentali": fun_txt,
                     "p_short": p_sh, "short": sh_txt,
                     "settore": f.get("sector") or "N/D",
                     "prossima_trimestrale": str(f.get("prossima_trimestrale") or "N/D"),
                     "punteggio": round(float(punteggio), 1),
                     "completezza": round(completezza, 2),
                     "veto": "; ".join(v for v in veti if "N/D" not in v),
                     "note": "; ".join(flag + [v for v in veti if "N/D" in v])})
    out = pd.DataFrame(rows)
    out["idoneo"] = (out["completezza"] >= cfg["idoneita"]["completezza_minima"]) & (out["veto"] == "")
    return out.sort_values(["idoneo", "punteggio"], ascending=[False, False])
