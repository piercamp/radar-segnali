"""Esecuzione serale: universo -> filtro rapido -> analisi completa -> file per Claude + tracciamento."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pandas as pd
import yaml

from . import scoring, track
from .indicators import technicals

ROOT = Path(__file__).resolve().parent.parent


def main(provider=None, out_dir: Path | None = None, oggi: dt.date | None = None) -> dict:
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
    out_dir = out_dir or ROOT / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    oggi = oggi or dt.date.today()
    if provider is None:
        from .data_sources import LiveProvider
        provider = LiveProvider()

    u = cfg["universo"]
    uni = provider.universe(u["borse"])
    monitorati = cfg.get("monitorati", [])
    extra = [t for t in monitorati + ["SPY"] if t not in set(uni["ticker"])]
    prezzi = provider.prices(uni["ticker"].tolist() + extra)
    spy = prezzi.get("SPY")

    righe = []
    for t in uni["ticker"]:
        df = prezzi.get(t)
        if df is None or len(df) < u["sedute_minime_storico"]:
            continue
        righe.append({"ticker": t, **technicals(df, spy)})
    tech = pd.DataFrame(righe)
    copertura = len(tech) / max(len(uni), 1)
    data_seduta = tech["data_chiusura"].max() if len(tech) else str(oggi)

    liquidi = tech[(tech["chiusura"] >= u["prezzo_minimo_usd"])
                   & (tech["controvalore_20g"] >= u["controvalore_medio_20g_min_usd"])]
    liquidi = liquidi[liquidi["data_chiusura"] == data_seduta]  # scarta titoli con prezzi non aggiornati
    s1 = scoring.stage1(liquidi, cfg["pesi"])
    cand = s1.head(cfg["fase2"]["candidati_da_analizzare"]).merge(uni[["ticker", "name", "cik"]], on="ticker")

    insider = provider.insider_purchases(dict(zip(cand["ticker"], cand["cik"])), cfg["insider"]["giorni"])
    short = provider.short_volume(cand["ticker"].tolist())
    fund = provider.fundamentals(cand["ticker"].tolist())
    s2 = scoring.stage2(cand, insider, short, fund, cfg, oggi)

    seduta_ok = copertura >= cfg["idoneita"]["copertura_minima_mercato"] and spy is not None
    if not seduta_ok:
        s2["idoneo"] = False

    # idonei migliori + i 10 migliori esclusi (veto o dati incompleti), utili per "Da monitorare"
    uscita = pd.concat([s2[s2["idoneo"]].head(cfg["fase2"]["candidati_in_uscita"]),
                        s2[~s2["idoneo"]].sort_values("punteggio", ascending=False).head(10)])
    colonne = ["ticker", "name", "settore", "punteggio", "completezza", "idoneo", "veto", "note",
               "chiusura", "data_chiusura", "sma50", "sma200", "fr_3m", "fr_6m", "volume_rel_5_50",
               "accumulo_50g", "dist_max_52s", "atr_pct", "insider", "fondamentali", "short",
               "prossima_trimestrale", "p_trend", "p_momentum", "p_accumulo", "p_insider",
               "p_fondamentali", "p_short"]
    uscita = uscita[colonne]
    uscita.round(4).to_csv(out_dir / "candidati_latest.csv", index=False)
    (out_dir / "storico").mkdir(exist_ok=True)
    uscita.round(4).to_csv(out_dir / "storico" / f"candidati_{data_seduta}.csv", index=False)

    # prezzi giornalieri della watchlist (ultimi 30 giorni), con verifica della data
    righe_m = []
    for t in monitorati:
        df = prezzi.get(t)
        if df is None or df.empty:
            righe_m.append({"ticker": t, "data": "N/D"})
            continue
        for d, r in df.tail(30).iterrows():
            righe_m.append({"ticker": t, "data": str(d.date()), "apertura": r["Open"], "massimo": r["High"],
                            "minimo": r["Low"], "chiusura": r["Close"], "volume": r["Volume"]})
    pd.DataFrame(righe_m).round(4).to_csv(out_dir / "monitorati_latest.csv", index=False)

    tr = cfg["tracciamento"]
    log = track.append_signals(out_dir / "segnali_log.csv", s2 if seduta_ok else s2.iloc[0:0],
                               data_seduta, tr["segnali_registrati_per_seduta"])
    ev = track.evaluate(log, prezzi, tr["orizzonti_giorni"])
    ev.round(4).to_csv(out_dir / "segnali_performance.csv", index=False)

    rapporto = {
        "generato_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
        "seduta": data_seduta,
        "seduta_completa": bool(seduta_ok),
        "titoli_universo": int(len(uni)),
        "titoli_con_prezzi_validi": int(len(tech)),
        "copertura_prezzi": round(copertura, 3),
        "titoli_liquidi": int(len(liquidi)),
        "candidati_analizzati": int(len(cand)),
        "candidati_idonei": int(s2["idoneo"].sum()),
        "monitorati_senza_prezzi": [t for t in monitorati if prezzi.get(t) is None],
        "fonti_ko": {"insider_N/D": int(sum(v is None for v in insider.values())),
                     "short_N/D": int(sum(v is None for v in short.values()))},
        "performance_segnali": track.summary(ev, tr["orizzonti_giorni"]),
    }
    (out_dir / "rapporto_latest.json").write_text(json.dumps(rapporto, indent=2, ensure_ascii=False))
    return rapporto


if __name__ == "__main__":
    print(json.dumps(main(), indent=2, ensure_ascii=False))
