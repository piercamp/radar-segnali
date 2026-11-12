# Radar segnali USA: motore dati

Ogni sera, dopo la chiusura di Wall Street, GitHub esegue la scansione di **tutte le azioni NYSE e Nasdaq** e salva in `output/` i candidati migliori, con un punteggio oggettivo. La mattina Claude legge il file e fa la parte di giudizio: notizie, tono dei testi, veti qualitativi.

> Segnali di studio, non consigli di investimento. Le decisioni restano tue.

## Come funziona

1. **Universo:** elenco ufficiale SEC dei titoli quotati su NYSE e Nasdaq (warrant, unit e rights esclusi).
2. **Filtro rapido**, su tutti i titoli:
   - prezzo ≥ 5 USD;
   - controvalore medio a 20 giorni ≥ 20 milioni USD;
   - almeno 220 sedute di storico;
   - prezzo aggiornato all'ultima seduta.
3. **Punteggio tecnico**, sui titoli liquidi: trend, forza relativa rispetto all'S&P 500, accumulo dei volumi.
4. **Analisi completa** dei 60 migliori: acquisti degli insider (SEC Form 4), fondamentali, short volume FINRA, data della trimestrale.
5. **Uscita:** i 30 titoli idonei migliori, più i 10 migliori esclusi (per veto o dati incompleti), utili per la sezione "Da monitorare".

## Punteggio (0–100, pesi in `config.yaml`)

| Componente | Peso | Cosa misura | Fonte |
|---|---|---|---|
| Trend | 25 | Prezzo sopra la media a 200 giorni, media a 50 sopra quella a 200, prezzo sopra la media a 50 | Prezzi |
| Momentum | 25 | Forza relativa a 6 e 3 mesi rispetto a SPY (posizione in classifica su tutto il mercato) | Prezzi |
| Accumulo | 15 | Volumi nei giorni di rialzo rispetto ai giorni di ribasso, volume recente, vicinanza al massimo a 52 settimane | Prezzi |
| Insider | 15 | Acquisti a mercato dei dirigenti negli ultimi 30 giorni: massimo con almeno 1 mln USD o con 2 o più insider | SEC EDGAR |
| Fondamentali | 15 | Ricavi e utili in crescita, margine operativo positivo, debito sostenibile, P/E prospettico tra 0 e 40 | Yahoo Finance |
| Short (sperimentale) | 5 | Vendite allo scoperto ≥ 50% del volume assorbite da un prezzo in salita | FINRA |

### Regole di sicurezza

- **Dato mancante = N/D**, mai stimato. La *completezza* indica la quota di peso coperta da dati veri. Sotto l'85% il titolo **non è idoneo**.
- **Veto:** trimestrale entro 3 giorni lavorativi.
- **Flag:** volatilità alta, quando l'escursione media giornaliera supera il 5%.
- **Seduta incompleta:** se meno dell'80% dei titoli ha prezzi validi, oppure manca SPY, nessun titolo è idoneo quel giorno.

## File in `output/`

| File | Contenuto |
|---|---|
| `candidati_latest.csv` | I candidati dell'ultima seduta: è il file letto da Claude |
| `rapporto_latest.json` | Stato della seduta: copertura, fonti non raggiungibili, performance dei segnali |
| `segnali_log.csv` | I 10 migliori di ogni seduta, con prezzo e punteggio |
| `segnali_performance.csv` | Rendimento di ogni segnale a 1, 5 e 20 sedute, anche rispetto a SPY |
| `storico/` | Una copia dei candidati per ogni seduta |

## Attivazione (circa 15 minuti, una volta sola)

1. Crea un account gratuito su <https://github.com>.
2. Crea un repository **privato** chiamato `radar-segnali`: pulsante *New repository*, visibilità *Private*.
3. Carica tutti i file di questa cartella: *Add file → Upload files*. Trascina il contenuto dello zip, compresa la cartella `.github`. In alternativa colleghi GitHub a Claude e li carica Claude.
4. Crea il secret richiesto dalla SEC: *Settings → Secrets and variables → Actions → New repository secret*.
   - Nome: `SEC_USER_AGENT`
   - Valore: `Nome Cognome indirizzo@email`

   La SEC chiede un contatto a chi scarica i suoi dati: resta privato nel repository.
5. Prima esecuzione: *Actions → radar-serale → Run workflow*. Dura circa 10–20 minuti.
6. Collega GitHub a Claude, così le attività pianificate possono leggere `output/`.

## Limiti noti

- I prezzi arrivano da Yahoo Finance tramite la libreria non ufficiale `yfinance`, che può bloccarsi. Il controllo di copertura impedisce allerte su dati incompleti.
- GitHub può avviare le esecuzioni programmate con qualche decina di minuti di ritardo.
- Il modello è un filtro, non una previsione. I pesi vanno rivisti solo con dati di `segnali_performance.csv`, dopo almeno 4–6 settimane.
