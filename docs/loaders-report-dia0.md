# weather

## summary
Implemented the METAR/IEM weather area end to end: `pipeline/voos/sources/iem.py` (URL builder, age-based cache on top of http.cached_download, cross-process file lock + 1.1 s throttle, 429/5xx/transport retries with backoff, CSV-shape validation, `month_windows`), `pipeline/voos/marts/weather.py` (DuckDB-SQL parser `parse_asos`/`parse_asos_many` with vis/ceiling/sky/wx/flags/severity, `metar_recent`, `metar_hourly`, `weather_daily`, plus pure `hourly_from_reports`/`daily_from_hourly`), the three Observable shims, and `tests/test_weather.py` (14 tests, all pass; full suite 45 pass). All four required verifications match: SBPA 2026-10-24 18:00Z vis 2000 / ceiling 900, SPECI 16:08Z 3000 m, 14:00Z and 19:00Z ceiling 700, no convective flags for SBPA, SBSV all severity 0; 28 distinct stations (none missing from IEM); full 2024-01-01→today hourly run = 705,632 reports → 665,981 station-hours in 2 min 42 s (32 downloads + 2 cached), and a rerun reused the cache with zero downloads; weather_daily SBPA 2026-10-24 hours_imc = 12. SBPA shows the real flood gap (72 hours in May 2024, nothing Jun–Sep, resumes Oct 2024). Two design decisions worth knowing: (1) IEM does not emit a report_type column even when asked, so report_type is derived (minute :00 → 3 routine, otherwise or 'SPECI' prefix → 4; confirmed all 28 stations report routine METARs only at :00); (2) vsby arrives as 2-decimal miles (±8 m), so vis_m is snapped to METAR reporting resolution (50 m below 800 m, 100 m above; ≥6.2 mi → 10000) to recover the reported value (3000 not 2993) — this is what makes the expected 2000/3000 values come out exactly. Convective detection tokenizes weather groups at 2-letter alignment (so TSRA, +TSRA, VCTS, RETS, SHGR match; SBGR station id, FEW040TCU, NOSIG do not), plus CB cloud layers and heavy rain (+RA/+SHRA); zero misses/false positives found in a sweep of 36,865 real reports. Did not run git/npm/launchctl. Note: git status now shows my weather.py/test_weather.py as 'M' (tracked), meaning someone committed an intermediate snapshot of my files mid-work; the on-disk versions are the final, tested ones.

## files
- /Users/lucasgomesmaddalena/voos2026/pipeline/voos/sources/iem.py
- /Users/lucasgomesmaddalena/voos2026/pipeline/voos/marts/weather.py
- /Users/lucasgomesmaddalena/voos2026/src/data/live/metar_recent.parquet.py
- /Users/lucasgomesmaddalena/voos2026/src/data/hist/metar_hourly.parquet.py
- /Users/lucasgomesmaddalena/voos2026/src/data/hist/weather_daily.parquet.py
- /Users/lucasgomesmaddalena/voos2026/tests/test_weather.py

## issues
- IEM does not return a report_type column (even with data=report_type), so report_type is DERIVED: 3 when the minute is :00 (or 4 if the raw text starts with SPECI / minute != 0). Verified against 8 days of data that all 28 stations issue routine METARs only at :00, but a SPECI issued exactly at :00 would be labelled 3.
- vis_m is snapped to METAR reporting resolution (50 m below 800 m, 100 m otherwise, >= 6.2 mi -> 10000) instead of plain round(vsby*1609.344); this recovers the reported metres (2000/3000 as expected) because IEM's 2-decimal miles carry +/-8 m error. Documented in the module docstring.
- convective also fires on recent-weather groups like RETS (thunderstorm in the past hour) and on +SHRA (heavy rain showers); TCU alone, the station identifier (e.g. SBGR) and RERA never fire. Verified 0 misses / 0 false positives over 36,865 real reports.
- weather_daily's first local day for each range is partial (e.g. 2023-12-31 appears with 27 rows because 2024-01-01T00-02Z is still Dec 31 local); similarly the current local day is partial (SBPA 2026-10-24 has 21 hours so far).
- http.cached_download has no validators to work with for IEM (no ETag/Last-Modified), so iem.fetch_asos decides locally: closed months are never re-fetched if the file exists; recent windows are re-fetched with force=True after max_age (no HEAD is ever sent, saving a request). Months that closed less than 1 day ago are still refreshed (CLOSED_GRACE) to pick up late reports.
- data/raw/iem/ keeps a .lock (fcntl) and .last_request marker to serialize/throttle IEM requests across concurrently running loaders. Rolling metar_recent windows create a new cache file per hour (asos_<start>_<end>...csv) and are not pruned; consider a cleanup if the folder grows.
- pipeline/voos/sources/__init__.py and pipeline/voos/marts/__init__.py already existed when I checked (created by another agent); I did not modify them.
- git status shows pipeline/voos/marts/weather.py and tests/test_weather.py as modified-tracked, i.e. an intermediate snapshot of my files was committed by someone else mid-task; the on-disk versions are the final tested ones (the committed snapshot predates the .arrow() -> to_arrow_table() fix and may not run on duckdb 1.5.6). I did not run git.

## shared_module_changes_needed
- voos.http.cached_download: when the server returns neither ETag nor Last-Modified (IEM), a cached file with max_age_hours=None is HEAD-checked and then re-downloaded on every call; suggest a `trust_local=True`/immutable option (or treat 'no validators + file exists' as fresh) and skipping the HEAD when the previous manifest entry has no validators. Worked around inside sources/iem.py.
- voos.http.cached_download: manifest.json is read-modify-written without locking; concurrent data loaders (Observable runs them in parallel) can clobber each other's entries. Suggest a file lock or atomic write (tmp + os.replace).
- voos.http.cached_download: the GET path has no retry/backoff for 429/503 (get_bytes does, but cached_download does not use it); sources/iem.py wraps it with its own retries. Consider routing cached_download's GET through get_bytes.

## schema
metar_recent.parquet (live, one row per METAR/SPECI, last 8 days, 28 stations): icao: string; valid_utc: string ('YYYY-MM-DDTHH:MM:SSZ'); report_type: int64 (3 routine, 4 SPECI); vis_m: double (null if not reported; 10000 = >= 9999 m); ceiling_ft: int64 (null if no BKN/OVC/VV layer); sky: string ('BKN009 BKN030 FEW040'); wx: string ('' if none); wind_dir: int64; wind_kt: double; gust_kt: double; temp_c: double; dewp_c: double; pressure_hpa: double; metar_raw: string; imc: bool; red: bool; below_cat1: bool; convective: bool; gusty: bool; severity: int64 (0-3); severity_label: string ('VMC','IMC','vermelho','abaixo CAT I'); source: string ('iem').
metar_hourly.parquet (hist, icao x hour UTC, 2024-01-01 -> today): icao: string; hour_utc: string ('YYYY-MM-DDTHH:00:00Z'); min_vis_m: double; min_ceiling_ft: int64; max_severity: int64; severity_label: string; any_convective: bool; any_red: bool; any_imc: bool; max_gust_kt: double; n_reports: int64; wx_all: string (distinct wx codes, sorted, space-joined).
weather_daily.parquet (hist, icao x local date via airport tz: America/Sao_Paulo default, America/Noronha for SBFN): icao: string; date_local: string ('YYYY-MM-DD'); hours_imc: int64; hours_red: int64; hours_convective: int64; min_vis_m: double; min_ceiling_ft: int64; max_gust_kt: double; max_severity: int64; n_hours: int64.

## verification
$ .venv/bin/pytest tests/test_weather.py -q
..............                                                           [100%]
14 passed in 0.28s
$ .venv/bin/pytest tests -q
45 passed in 0.63s

(a) $ .venv/bin/python src/data/live/metar_recent.parquet.py > .../metar_recent.parquet   (3.26 s)
[23:40:10] IEM 28 estações 2026-10-16T23:00Z → 2026-10-25T00:00Z
[23:40:13] metar_recent: 5450 reportes, 28 estações
select valid_utc, report_type, vis_m, ceiling_ft, sky, wx, convective, severity, severity_label from metar_recent where icao='SBPA' and valid_utc between '2026-10-24T12:00:00Z' and '2026-10-24T20:00:00Z'
│ 2026-10-24T12:00:00Z │ 3 │ 10000.0 │ 900 │ … │ VCSH    │ false │ 1 │ IMC │
│ 2026-10-24T13:00:00Z │ 3 │  6000.0 │ 900 │ … │ -RA     │ false │ 1 │ IMC │
│ 2026-10-24T14:00:00Z │ 3 │  7000.0 │ 700 │ … │ -RA     │ false │ 1 │ IMC │
│ 2026-10-24T15:00:00Z │ 3 │ 10000.0 │ 900 │ … │         │ false │ 1 │ IMC │
│ 2026-10-24T16:00:00Z │ 3 │  9000.0 │ 900 │ … │ -RA     │ false │ 1 │ IMC │
│ 2026-10-24T16:08:00Z │ 4 │  3000.0 │ 900 │ … │ RA BR   │ false │ 1 │ IMC │
│ 2026-10-24T17:00:00Z │ 3 │  3000.0 │ 900 │ … │ RA BR   │ false │ 1 │ IMC │
│ 2026-10-24T18:00:00Z │ 3 │  2000.0 │ 900 │ … │ RA BR   │ false │ 1 │ IMC │
│ 2026-10-24T19:00:00Z │ 3 │  3000.0 │ 700 │ … │ RA BR   │ false │ 1 │ IMC │
│ 2026-10-24T20:00:00Z │ 3 │  4000.0 │ 900 │ … │ -RA BR  │ false │ 1 │ IMC │
SBPA convective today: [(0,)]
SBSV severity dist today: [(0, 24)]

(b) select count(distinct icao) n_icao, count(*) n, min(valid_utc), max(valid_utc) from metar_recent
│ 28 │ 5450 │ 2026-10-16T23:00:00Z │ 2026-10-24T23:00:00Z │
per station (icao, n, convective, max severity): SBAR 193 0 2, SBBR 194 19 2, SBCF 203 13 3, SBCT 207 14 3, SBFL 197 0 2, SBFN 222 0 1, SBFZ 193 0 0, SBGL 202 0 1, SBGO 204 33 2, SBGR 205 0 2, SBIL 130 6 2, SBIZ 137 1 2, SBJP 193 0 0, SBJU 193 0 0, SBKG 193 0 2, SBKP 208 11 2, SBMO 194 0 1, SBNF 161 0 2, SBPA 196 0 1, SBPL 197 11 2, SBPS 195 15 2, SBRF 194 0 1, SBRJ 203 1 2, SBSG 193 0 2, SBSL 195 0 2, SBSP 261 4 3, SBSV 193 0 2, SBTE 194 0 2  → all 28 IEM_STATIONS present, none missing.
minute distribution: every station's routine reports are at :00 (SBSP 187 at :00 + many SPECIs); report_type dist Sep–Oct 2026: 3 → 35125, 4 → 1740.
convective sanity (Sep–Oct 2026, 36865 reports): not-convective rows whose METAR body contains TS/CB/GR/GS/SQ/FC = 0; convective rows without any TS/CB/GR/GS/SQ/FC/+ in raw = 0.
sample convective: ('SBGO','2026-10-23T02:08:00Z','+TSRA','SBGO 230208Z 14027G38KT 3000 +TSRA BKN006 SCT050CB OVC070 ...'), ('SBKP','2026-10-17T03:00:00Z','-RA','... BKN007 OVC100 20/19 Q1013 RETS'), ('SBPS','2026-10-19T22:00:00Z','VCTS','... VCTS FEW025 FEW030CB BKN100 ...')
sample severity 3: ('SBCT','2026-10-24T00:00:00Z',300.0,100,'FG','SBCT 240000Z 13004KT 0300 R33/0900 R15/1100 FG VV001 16/16 Q1017')

(c) dev run metar_hourly(2026-09-01, 2026-10-24): 2 requests, 10.0 s total
[23:40:50] IEM mês 2026-09 (1/2) ... [23:40:56] IEM mês 2026-10 (2/2) [mês corrente]
[23:41:00] metar_hourly: 36865 reportes → 35137 horas-estação
│ 2026-09 │ 19497 │ 28 │ 2026-09-01T00:00:00Z │ 2026-09-30T23:00:00Z │
│ 2026-10 │ 15640 │ 28 │ 2026-10-01T00:00:00Z │ 2026-10-24T23:00:00Z │
SBPA hourly 2026-10-24 16:00Z: min_vis_m 3000, min_ceiling_ft 900, n_reports 2, wx_all '-RA BR RA'

FULL run: $ time .venv/bin/python src/data/hist/metar_hourly.parquet.py > metar_hourly_full.parquet
[23:44:19] metar_hourly: 705632 reportes → 665981 horas-estação (2024-01-01 → 2026-10-24)
.venv/bin/python src/data/hist/metar_hourly.parquet.py >  9.76s user 1.03s system 6% cpu 2:41.71 total
exit=0   downloads: 32 (34 months; 2 already cached from dev run)   parquet: 1,902,053 bytes
rows per year:
│ 2024 │ 234616 │ 28 │ 247827 │
│ 2025 │ 237799 │ 28 │ 252487 │
│ 2026 │ 193566 │ 28 │ 205318 │
total: [(665981, '2024-01-01T00:00:00Z', '2026-10-24T23:00:00Z')]
SBPA hours per month 2024: [('2024-01',744),('2024-02',696),('2024-03',744),('2024-04',720),('2024-05',72),('2024-10',406),('2024-11',546),('2024-12',669)]  (flood closure gap Jun–Sep 2024 confirmed)
severity distribution: [(0,'VMC',588985),(1,'IMC',47730),(2,'vermelho',27616),(3,'abaixo CAT I',1650)]
rerun of the full shim right after: no 'baixando' lines (cache reused), same 705632 → 665981.

(d) $ time .venv/bin/python src/data/hist/weather_daily.parquet.py > weather_daily_full.parquet
[23:44:23] metar_hourly: 705632 reportes → 665981 horas-estação (2024-01-01 → 2026-10-24)
[23:44:23] weather_daily: 28654 dias-estação   (no downloads; cache reused)
per year (date_local): [('2023',27,27),('2024',10091,28),('2025',10220,28),('2026',8316,28)]
select * from weather_daily where icao='SBPA' and date_local='2026-10-24'
│ SBPA │ 2026-10-24 │ hours_imc 12 │ hours_red 0 │ hours_convective 0 │ min_vis_m 2000.0 │ min_ceiling_ft 700 │ max_gust_kt NULL │ max_severity 1 │ n_hours 21 │
SBPA around the 2024 flood: ('2024-05-01',11,4,13,2000.0,400,None,2,24), ('2024-05-02',20,0,9,2500.0,600,None,2,24), ('2024-05-03',21,0,0,2000.0,600,None,1,21) then nothing until Oct 2024.

# dims

## summary
Implemented the airport dimension end to end. (1) pipeline/voos/sources/anac_aerodromos.py: downloads the ANAC public-aerodromes CSV via http.cached_download(ANAC_AERODROMOS_CSV, RAW/'anac'/'AerodromosPublicos.csv', max_age_hours=168), decodes cp1252/latin-1, reads 'Atualizado em: YYYY-MM-DD' from line 1 into updated_at, parses the ';' CSV into a typed pyarrow.Table (icao, ciad, name, municipio [Portuguese Title Case], uf_nome, municipio_servido, uf_servido_nome, lat, lon, altitude_m [decimal comma], situacao, validade_registro ['YYYY-MM-DD'], updated_at). Exposes pure helpers title_case_pt, parse_decimal, parse_date_br, parse_text. (2) pipeline/voos/sources/ourairports.py: downloads via the exact shared call http.cached_download(OURAIRPORTS_CSV, RAW/'ourairports'/'airports.csv', max_age_hours=168), loads with DuckDB read_csv(all_varchar=true), derives icao = icao_code with fallback to a 4-letter ident, keeps rows with scheduled_service OR (BR and icao not null) → 7088 rows. (3) pipeline/voos/marts/dims.py: dim_airport() = ANAC public aerodromes (source 'anac', enriched with OurAirports iata/scheduled_service/type by ICAO, fallback local_code=CIAD, both sides deduped by type rank) UNION non-BR scheduled OurAirports airports (source 'ourairports'); UF/região from data/ref/ufs.csv (accent-insensitive), tz from AIRPORT_TZ for BR / 'UTC' abroad, flags is_focus_origin/is_ne/is_hub, data/ref/airports_override.csv applied with type coercion (field alias municipio_fisico→municipio), dedup on icao preferring anac, sorted by country, icao. Also exposes uf_from_name(name)->(uf, regiao, regiao_nome) (accepts full name or sigla), uf_row(), iata_to_icao()->dict (4150 entries, anac rows win), build_dim_airport(anac_tbl, oa_tbl) (pure, used by tests), load_overrides(), apply_overrides(). Result: 4439 rows (496 BR, 3943 abroad), ICAO unique, 0 null IATA among focus/NE/hub airports, all 17 NE and 11 hub airports present, every BR row has uf/regiao. (4) Shim src/data/dims/dim_airport.parquet.py (5-line template; runs in 0.4 s, 223 KB parquet). (5) tests/test_dims.py: 8 tests (title case incl. hyphen and d'Oeste, decimal comma, dates, uf_from_name, ANAC text parsing, OurAirports parsing from a temp CSV, full build with monkeypatched overrides, override coercion) — all pass; whole suite 14/14. Also created the empty packages' pipeline/voos/sources/__init__.py and pipeline/voos/marts/__init__.py (docstring only, guarded so as not to clobber other agents' files).

## files
- /Users/lucasgomesmaddalena/voos2026/pipeline/voos/sources/anac_aerodromos.py
- /Users/lucasgomesmaddalena/voos2026/pipeline/voos/sources/ourairports.py
- /Users/lucasgomesmaddalena/voos2026/pipeline/voos/marts/dims.py
- /Users/lucasgomesmaddalena/voos2026/src/data/dims/dim_airport.parquet.py
- /Users/lucasgomesmaddalena/voos2026/tests/test_dims.py
- /Users/lucasgomesmaddalena/voos2026/pipeline/voos/sources/__init__.py
- /Users/lucasgomesmaddalena/voos2026/pipeline/voos/marts/__init__.py

## issues
- data/ref/airports_override.csv uses field name 'municipio_fisico' for SBMO/SBCT (the task said 'municipio'); handled with OVERRIDE_FIELD_ALIASES {municipio_fisico→municipio, fuso/timezone→tz, nome→name} in marts/dims.py — no change to the ref file. Unknown fields are logged and skipped.
- 255 non-BR OurAirports rows with scheduled_service=yes have no resolvable ICAO (US seaplane bases/airstrips with idents like '03N', '19P'); since icao is the dimension key they are dropped. 52 non-BR scheduled rows got their ICAO from the 4-letter ident fallback. 289 of 4439 rows have null iata (none in the project scope).
- Per spec, non-BR rows have tz='UTC' (to be refined later), municipio=NULL and municipio_servido=OurAirports municipality; uf/regiao NULL. Lima resolves to icao SPJC (OurAirports icao_code; its ident is the legacy SPIM).
- ANAC data quirks handled: SDRS (Resende) has empty 'Município'/'UF' → fell back to 'Município Servido'/'UF Servido'; SBPW and SSBG have empty 'Município Servido' → fell back to the physical municipio. 30 aerodromes with Situação='Interditado' are kept (situacao is in the source table but not a dim_airport column, per the exact column list).
- Only 3 OurAirports BR rows with scheduled_service=yes are absent from the ANAC public list (SDYG airstrip, SDBW and SSCY heliports) — excluded per spec; all 29 project airports are present in both sources.
- pipeline/voos/sources/__init__.py and pipeline/voos/marts/__init__.py did not exist (empty dirs); created docstring-only files with a guard ([ -f ] ||) so other agents' copies are not overwritten. sources/iem.py (weather agent) appeared in the dir while I worked; untouched.
- dim_airport() and iata_to_icao() are lru_cached per process; build_dim_airport(anac_tbl, oa_tbl) is the pure, uncached builder used by tests.

## shared_module_changes_needed


## schema
src/data/dims/dim_airport.parquet — icao: string, iata: string|null, name: string, country: string ('BR' or ISO-3166 alpha-2), municipio: string|null, municipio_servido: string|null, uf: string|null, uf_nome: string|null, regiao: string|null ('N','NE','SE','S','CO'), regiao_nome: string|null, lat: double, lon: double, tz: string, ciad: string|null, scheduled_service: bool, is_focus_origin: bool, is_ne: bool, is_hub: bool, source: string ('anac'|'ourairports'). Source tables (not emitted as files): anac_aerodromos.load() — icao, ciad, name, municipio, uf_nome, municipio_servido, uf_servido_nome: string; lat, lon, altitude_m: double; situacao: string; validade_registro: string 'YYYY-MM-DD'|null; updated_at: string 'YYYY-MM-DD'. ourairports.load() — ident, icao, iata, name: string; lat, lon: double; country, region, municipality: string; scheduled_service: bool; local_code, type: string.

## verification
$ .venv/bin/pytest tests/test_dims.py -q
........                                                                 [100%]
8 passed in 1.90s

$ .venv/bin/pytest tests -q
..............                                                           [100%]
14 passed in 0.62s

$ time .venv/bin/python src/data/dims/dim_airport.parquet.py > $S/dim_airport.parquet   (stderr:)
[23:36:18] anac aeródromos públicos: 496 linhas (atualizado em 2026-10-15)
[23:36:18] ourairports: 7088 linhas (serviço regular ou BR com ICAO)
[23:36:18] dim_airport: 4439 aeroportos (496 BR, 3943 exterior)
0.35s user 0.06s system 105% cpu 0.389 total
-rw-r--r--@ 1 lucasgomesmaddalena  wheel  222957 Oct 24 20:36 .../scratchpad/dims/dim_airport.parquet

-- select icao, iata, municipio, municipio_servido, uf, regiao, lat, lon, tz, is_ne, is_hub, source from dim_airport where icao in (...) order by icao
┌─────────┬─────────┬─────────────────────────┬──────────────────────┬─────────┬─────────┬────────────┬────────────┬───────────────────┬─────────┬─────────┬─────────┐
│  icao   │  iata   │        municipio        │  municipio_servido   │   uf    │ regiao  │    lat     │    lon     │        tz         │  is_ne  │ is_hub  │ source  │
├─────────┼─────────┼─────────────────────────┼──────────────────────┼─────────┼─────────┼────────────┼────────────┼───────────────────┼─────────┼─────────┼─────────┤
│ SBCT    │ CWB     │ São José dos Pinhais    │ Curitiba             │ PR      │ S       │ -25.531667 │ -49.176111 │ America/Sao_Paulo │ false   │ true    │ anac    │
│ SBFN    │ FEN     │ Fernando de Noronha     │ Fernando de Noronha  │ PE      │ NE      │ -3.8547222 │ -32.428333 │ America/Noronha   │ true    │ false   │ anac    │
│ SBFZ    │ FOR     │ Fortaleza               │ Fortaleza            │ CE      │ NE      │ -3.7758333 │ -38.532222 │ America/Sao_Paulo │ true    │ false   │ anac    │
│ SBGR    │ GRU     │ Guarulhos               │ Guarulhos            │ SP      │ SE      │ -23.435556 │ -46.473056 │ America/Sao_Paulo │ false   │ true    │ anac    │
│ SBJP    │ JPA     │ Bayeux                  │ João Pessoa          │ PB      │ NE      │ -7.1483333 │ -34.950278 │ America/Sao_Paulo │ true    │ false   │ anac    │
│ SBKP    │ VCP     │ Campinas                │ Campinas             │ SP      │ SE      │ -23.006944 │ -47.134444 │ America/Sao_Paulo │ false   │ true    │ anac    │
│ SBMO    │ MCZ     │ Rio Largo               │ Maceió               │ AL      │ NE      │ -9.5108333 │ -35.791667 │ America/Sao_Paulo │ true    │ false   │ anac    │
│ SBPA    │ POA     │ Porto Alegre            │ Porto Alegre         │ RS      │ S       │ -29.994722 │ -51.171111 │ America/Sao_Paulo │ false   │ false   │ anac    │
│ SBRF    │ REC     │ Recife                  │ Recife               │ PE      │ NE      │ -8.1263889 │ -34.922778 │ America/Sao_Paulo │ true    │ false   │ anac    │
│ SBSG    │ NAT     │ São Gonçalo do Amarante │ Natal                │ RN      │ NE      │ -5.7688889 │ -35.366389 │ America/Sao_Paulo │ true    │ false   │ anac    │
│ SBSV    │ SSA     │ Salvador                │ Salvador             │ BA      │ NE      │ -12.908611 │   -38.3225 │ America/Sao_Paulo │ true    │ false   │ anac    │
│ SBVC    │ VDC     │ Vitória da Conquista    │ Vitória da Conquista │ BA      │ NE      │ -14.907778 │ -40.914722 │ America/Sao_Paulo │ true    │ false   │ anac    │
└─────────┴─────────┴─────────────────────────┴──────────────────────┴─────────┴─────────┴────────────┴────────────┴───────────────────┴─────────┴─────────┴─────────┘
  12 rows

-- select country='BR' as br, count(*) n ... group by 1
│ true    │   496 │
│ false   │  3943 │

-- select count(*) as null_iata_in_scope from d where iata is null and (is_ne or is_hub or is_focus_origin)
│                  0 │

NE present: 17 / 17 missing: []
HUB present: 11 / 11 missing: []

-- select count(*) n, count(distinct icao) n_icao, count(distinct iata) n_iata, sum(iata is null) null_iata
│  4439 │   4439 │   4150 │       289 │
-- select count(*) br_null_uf from d where country='BR' and uf is null
│          0 │
-- regiao counts (BR): CO 72 | N 69 | NE 92 | S 104 | SE 159

-- international destinations: select icao, iata, name, country, municipio_servido, tz, source where iata in ('LIS','LIM','EZE','SCL','PTY','MIA','MVD','ASU','MAD','CDG')
│ SGAS │ ASU │ Silvio Pettirossi Internatio… │ PY │ Asunción                       │ UTC │ ourairports │
│ LFPG │ CDG │ Charles de Gaulle Internatio… │ FR │ Paris (Roissy-en-France, Val-… │ UTC │ ourairports │
│ SAEZ │ EZE │ Ezeiza International Airport… │ AR │ Buenos Aires (Ezeiza)          │ UTC │ ourairports │
│ SPJC │ LIM │ Jorge Chávez International A… │ PE │ Lima                           │ UTC │ ourairports │
│ LPPT │ LIS │ Lisbon Humberto Delgado Airp… │ PT │ Lisbon                         │ UTC │ ourairports │
│ LEMD │ MAD │ Adolfo Suárez Madrid–Barajas… │ ES │ Madrid                         │ UTC │ ourairports │
│ KMIA │ MIA │ Miami International Airport   │ US │ Miami                          │ UTC │ ourairports │
│ SUMU │ MVD │ Carrasco General Cesáreo L. … │ UY │ Ciudad de la Costa             │ UTC │ ourairports │
│ MPTO │ PTY │ Tocumen International Airport │ PA │ Tocumen                        │ UTC │ ourairports │
│ SCEL │ SCL │ Comodoro Arturo Merino Benít… │ CL │ Santiago                       │ UTC │ ourairports │

-- tz / edge rows
│ SBCY │ CGB  │ true  │ false │ false │ false │ America/Cuiaba    │
│ SBEG │ MAO  │ true  │ false │ false │ false │ America/Manaus    │
│ SBFN │ FEN  │ true  │ true  │ false │ false │ America/Noronha   │
│ SBPW │ NULL │ false │ false │ false │ false │ America/Sao_Paulo │
│ SBVC │ VDC  │ true  │ true  │ false │ false │ America/Sao_Paulo │
│ SDRS │ REZ  │ false │ false │ false │ false │ America/Sao_Paulo │
│ SSBG │ BGV  │ false │ false │ false │ false │ America/Sao_Paulo │

-- describe: icao VARCHAR, iata VARCHAR, name VARCHAR, country VARCHAR, municipio VARCHAR, municipio_servido VARCHAR, uf VARCHAR, uf_nome VARCHAR, regiao VARCHAR, regiao_nome VARCHAR, lat DOUBLE, lon DOUBLE, tz VARCHAR, ciad VARCHAR, scheduled_service BOOLEAN, is_focus_origin BOOLEAN, is_ne BOOLEAN, is_hub BOOLEAN, source VARCHAR (19 columns, no timestamp types)

$ python -c "from voos.marts.dims import iata_to_icao ..."
iata_to_icao size 4150 {'POA': 'SBPA', 'FOR': 'SBFZ', 'GRU': 'SBGR', 'VDC': 'SBVC', 'NAT': 'SBSG', 'LIS': 'LPPT', 'LIM': 'SPJC', 'MIA': 'KMIA', 'CGH': 'SBSP', 'SDU': 'SBRJ'}
scheduled BR: 129
dup iata: []

data/raw/manifest.json: airports.csv (12751569 bytes, Last-Modified Sat, 24 Oct 2026 01:53:56 GMT); AerodromosPublicos.csv (102022 bytes, Last-Modified Thu, 15 Oct 2026 06:01:33 GMT)

# live

## summary
Implemented the "live" marts over the data/archive snapshots and their five Observable loaders.

pipeline/voos/marts/live.py:
- list_snapshots / load_snapshot / iter_snapshots (chronological by filename; partial or corrupt .gz written by the 15-min launchd capture is skipped with a stderr log; fetched_at normalized from '+00:00' to 'Z'); iter_flights handles both the dict-by-date and flat-list payload shapes; snapshots are streamed one at a time so memory does not grow with the archive.
- normalize_flight(site, direction, f, fetched_at, date_key=None) with exactly the 33 specified keys (direction accepts 'dep'/'arr' or 'departures'/'arrivals'; date_key is an optional fallback when original_scheduled_time is missing). IATA→ICAO via http.cached_download(OURAIRPORTS_CSV, RAW/'ourairports'/'airports.csv', max_age_hours=168), preferring scheduled_service='yes' on duplicates, falling back to a 4-letter `ident` when icao_code is empty, plus data/ref/airports_override.csv rows with field='iata'. other_uf is only set when the 2-letter prefix is a real UF from data/ref/ufs.csv.
- fraport_latest(): latest snapshot per site (both directions) + first_seen_at, n_snapshots, prev_status_raw, status_changed_at accumulated with a cheap pass over all earlier snapshots; sorted by site, direction, sched_utc. 793 rows now (POA 483, FOR 310).
- fraport_events(): per-site chronological walk emitting first_seen / status / estimated / disappeared (disappeared only when sched_utc is still >= 2 h ahead of that snapshot's fetched_at). Estimated from/to values are the resolved local ISO datetimes. With 3 snapshots per site it already captured 6 status changes and 1 estimated change.
- siros_today(): newest diario_YYYY-MM-DD.csv.gz (BOM + 'Importante' line handled), 2,920 legs, 718 focus legs; flight_key, UTC dep/arr with next-day rollover (395 legs), operates_today from the ISO-weekday column, data_registro parsed as Brasília.
- inmet_alerts(): newest snapshot, {'hoje','futuro'} flattened (with `grupo`), poligono/icone/municipios dropped, geocodes as list[str], ufs mapped from `estados` via ufs.csv (accent-insensitive), 9 alerts.
- asof(): built_at, per-site Fraport fetched_at/snapshot_file/n_snapshots/n_dep/n_arr/dates, inmet, siros_diario.
Shims in src/data/live/ (5-line, stdout only) and tests/test_live.py (17 tests: the four mandated normalize_flight cases, split_place, both iter_flights shapes, synthetic-stream tests for events and latest incl. disappeared-vs-rolled-off, SIROS leg incl. rollover/prefix/weekday, INMET alert, corrupt-snapshot skip, empty archive). Shared modules untouched; weather/dims files not touched or imported. Temporary outputs live in /private/tmp/claude-501/-Users-lucasgomesmaddalena-voos2026/96fd79d3-23e6-4a0e-ba14-07a45a88a656/scratchpad/live/.

## files
- /Users/lucasgomesmaddalena/voos2026/pipeline/voos/marts/live.py
- /Users/lucasgomesmaddalena/voos2026/src/data/live/fraport_latest.parquet.py
- /Users/lucasgomesmaddalena/voos2026/src/data/live/fraport_events.parquet.py
- /Users/lucasgomesmaddalena/voos2026/src/data/live/siros_today.parquet.py
- /Users/lucasgomesmaddalena/voos2026/src/data/live/inmet_alerts.json.py
- /Users/lucasgomesmaddalena/voos2026/src/data/live/asof.json.py
- /Users/lucasgomesmaddalena/voos2026/tests/test_live.py

## issues
- SIROS weekday columns (Seg..Dom) hold '0' when the flight does NOT operate that day (task text said 'empty'); operates_today treats both '' and '0' as not operating. 2026-10-24 is a Saturday: 2,758 of 2,920 legs operate today.
- Fraport place name 'BH - Confins' has a 2-letter prefix that is not a UF; split_place validates the prefix against data/ref/ufs.csv, so other_uf is None (other_city 'Confins', other_icao SBCF still resolves). All other prefixed names are real UFs. Also note 'DF - Brasilia' and 'DF - Brasília' both occur (kept raw).
- flight_key is NULL for 29 of 793 Fraport rows, all because the carrier is not in data/ref/carriers.csv: TP (TAP), CM (Copa), IB (Iberia), AR (Aerolineas Argentinas), AF (Air France), LP ('107917 - Lan Peru'), and '0S' (Sideral: carriers.csv has SID with an empty iata). other_icao resolved for 100% of rows (37 distinct IATA codes). If keys for those are wanted, add rows to data/ref/carriers.csv (e.g. 0S,SID; TP,TAP; CM,CMP; IB,IBE; AR,ARG; AF,AFR; LP,LPE) — I did not edit that reference file.
- INMET 'inicio'/'fim' ('2026-10-24 00:01') carry no timezone; inicio_utc/fim_utc assume Brasília (tz.brasilia_naive_to_utc). INMET's CAP feed uses -03:00 as far as I know, but this is unverified. Real INMET fields beyond the ones in the task text: id_aviso, id_sequencia, id_condicao_severa, id_icone, id_usuario, codigo (urn:oid…), referencia (null), data_inicio/data_fim (date-only 'T00:00:00.000Z'), hora_inicio/hora_fim, microrregioes, mesorregioes, regioes, alterado, encerrado, created_at, updated_at, icone (base64 PNG — dropped), instrucoes (list — kept). 'estados'/'geocodes' are comma-joined strings (split; geocode count == municipality count on every alert). The payload is {'hoje': [...], 'futuro': [...]}, exposed as `grupo` on each alert.
- fraport_events: the first snapshot of each site yields one first_seen row per flight (793 total), with to_value = initial status_raw and status_canon_to None (per spec: only for field='status'). No 'disappeared' events yet (nothing has vanished with sched_utc >= 2 h ahead); the logic is covered by a synthetic-stream unit test.
- delay_min is computed for every non-cancelled row with an estimated_time, including Decolagem/Pousado rows where the panel's estimated_time appears to be the actual time (e.g. AD4151 2026-10-23 07:00 est 09:00 → 120); the Cancelado rows have delay_min NULL as specified. The 'Alternado' G31244 row has delay_min 0 (est == sched).
- Extra columns beyond the spec, kept for convenience: siros_today.carrier_name (raw 'Empresa'); inmet alerts carry id_aviso, grupo, codigo, regioes, instrucoes, alterado, encerrado, inicio_utc, fim_utc; asof.inmet/asof.siros_diario carry snapshot_file. fetched_at strings are normalized from the envelope's '+00:00' form to 'Z'.
- inmet_alerts.json is ~150 KB because geocodes lists total ~13k codes across the 9 alerts (as requested: list of 7-digit strings).
- A corrupt/partial snapshot (e.g. mid-write by the launchd job) is skipped with a stderr log and does not abort the loaders; asof().n_snapshots counts files on disk, while fetched_at/snapshot_file refer to the latest readable one.

## shared_module_changes_needed
- None required. Optional (data/ref, not a module): add IATA codes to data/ref/carriers.csv for Sideral (0S → SID) and the foreign carriers seen at POA/FOR (TP→TAP, CM→CMP, IB→IBE, AR→ARG, AF→AFR, LP→LPE) so those Fraport rows get a flight_key; today keys.carrier_icao_from_iata returns None for them and flight_key is NULL (29/793 rows).

## schema
fraport_latest.parquet (37 cols): site: string, airport_icao: string, direction: string ('dep'|'arr'), flight_code_raw: string, carrier_iata: string, flight_number: string, carrier_icao: string, carrier_group: string, airline_name: string, other_iata: string, other_name_raw: string, other_city: string, other_uf: string, other_icao: string, sched_local: string, sched_utc: string, sched_date_local: string, sched_hour_local: int64, est_local: string, est_utc: string, delay_min: int64, status_raw: string, status_canon: string, event_class: string, status_kind: string, confidence: double, is_disruption: bool, gate: string, fraport_id: int64, event_key: string, flight_key: string, source: string, fetched_at: string, first_seen_at: string, n_snapshots: int64, prev_status_raw: string, status_changed_at: string
fraport_events.parquet (14 cols): site: string, direction: string, flight_code_raw: string, carrier_group: string, carrier_icao: string, other_iata: string, other_uf: string, sched_local: string, sched_date_local: string, changed_at: string, field: string ('first_seen'|'status'|'estimated'|'disappeared'), from_value: string, to_value: string, status_canon_to: string
siros_today.parquet (26 cols): snapshot_date: string, carrier_icao: string, carrier_name: string, carrier_group: string, flight_number: string, number_prefix: string, equipment: string, seats: int64, n_siros: string, data_registro_utc: string, inicio_operacao: string, fim_operacao: string, natureza: string, tipo_servico: string, objeto: string, leg_number: int64, origin_icao: string, origin_name: string, dest_icao: string, dest_name: string, sched_dep_utc: string, sched_arr_utc: string, operates_today: bool, codeshare: string, flight_key: string, is_focus_leg: bool
inmet_alerts.json: {fetched_at: str, source: 'inmet', snapshot_file: str, n_alerts: int, alerts: [{id: int, id_aviso: int, grupo: 'hoje'|'futuro', codigo: str, descricao: str, severidade: str, cor: str, inicio: str, fim: str, inicio_utc: str, fim_utc: str, estados: str, ufs: list[str], regioes: str, n_municipios: int, geocodes: list[str], riscos: list[str], instrucoes: list[str], alterado: bool, encerrado: bool}]}
asof.json: {built_at: str, fraport: {POA|FOR: {fetched_at: str, snapshot_file: str, n_snapshots: int, n_dep: int, n_arr: int, dates: {YYYY-MM-DD: {dep: int, arr: int}}} | null}, inmet: {fetched_at: str, snapshot_file: str, n_alerts: int} | null, siros_diario: {snapshot_date: str, snapshot_file: str, n_legs: int} | null}

## verification
$ .venv/bin/pytest tests/test_live.py -q
.................                                                        [100%]
17 passed in 0.64s

$ for f in fraport_latest fraport_events siros_today; do .venv/bin/python src/data/live/$f.parquet.py > $S/$f.parquet; done; (inmet_alerts, asof → .json)
[23:39:09] live: fraport_latest POA: 483 voos
[23:39:09] live: fraport_latest FOR: 310 voos
[23:39:09] live: fraport_events POA: 487 eventos
[23:39:09] live: fraport_events FOR: 313 eventos
[23:39:09] live: siros_today 2026-10-24: 2920 trechos, 718 de interesse
(archive at run time: fraport POA/FOR 3 snapshots each — 231934Z/233506Z/233807Z and 231938Z/233507Z/233810Z; inmet 2; siros diario_2026-10-24)

### fraport_latest: known rows
┌─────────┬───────────┬─────────────────┬─────────────────────┬─────────────────────┬───────────┬────────────┬──────────────┬──────────────────────────────┬────────────┐
│  site   │ direction │ flight_code_raw │     sched_local     │      est_local      │ delay_min │ status_raw │ status_canon │          flight_key          │ other_icao │
├─────────┼───────────┼─────────────────┼─────────────────────┼─────────────────────┼───────────┼────────────┼──────────────┼──────────────────────────────┼────────────┤
│ POA     │ arr       │ AD2680          │ 2026-10-23T00:15:00 │ 2026-10-23T00:20:00 │         5 │ Pousado    │ landed       │ AZU-2680-SBKP-20261023T0315Z │ SBKP       │
│ POA     │ arr       │ AD2680          │ 2026-10-24T00:15:00 │ 2026-10-24T00:30:00 │        15 │ Pousado    │ landed       │ AZU-2680-SBKP-20261024T0315Z │ SBKP       │
│ POA     │ arr       │ G31244          │ 2026-10-24T16:45:00 │ 2026-10-24T16:45:00 │         0 │ Alternado  │ diverted     │ GLO-1244-SBSP-20261024T1945Z │ SBSP       │
│ POA     │ arr       │ AD2680          │ 2026-10-25T00:15:00 │ 2026-10-25T01:15:00 │        60 │ Atrasado   │ delayed      │ AZU-2680-SBKP-20261025T0315Z │ SBKP       │
│ POA     │ dep       │ AD4151          │ 2026-10-23T07:00:00 │ 2026-10-23T09:00:00 │       120 │ Decolagem  │ departed     │ AZU-4151-SBPA-20261023T1000Z │ SBRF       │
│ POA     │ dep       │ AD4151          │ 2026-10-24T07:00:00 │ 2026-10-24T07:00:00 │         0 │ Decolagem  │ departed     │ AZU-4151-SBPA-20261024T1000Z │ SBRF       │
│ POA     │ dep       │ G31979          │ 2026-10-24T10:30:00 │ 2026-10-24T10:30:00 │      NULL │ Cancelado  │ cancelled    │ GLO-1979-SBPA-20261024T1330Z │ SBSV       │
│ POA     │ dep       │ AD4151          │ 2026-10-25T07:00:00 │ 2026-10-25T07:00:00 │         0 │ Previsto   │ scheduled    │ AZU-4151-SBPA-20261025T1000Z │ SBRF       │
└─────────┴───────────┴─────────────────┴─────────────────────┴─────────────────────┴───────────┴────────────┴──────────────┴──────────────────────────────┴────────────┘

### fraport_latest: counts by site, direction, sched_date_local
FOR arr 2026-10-22 4 | FOR arr 2026-10-23 56 | FOR arr 2026-10-24 55 | FOR arr 2026-10-25 40
FOR dep 2026-10-22 4 | FOR dep 2026-10-23 55 | FOR dep 2026-10-24 50 | FOR dep 2026-10-25 46
POA arr 2026-10-22 14 | POA arr 2026-10-23 88 | POA arr 2026-10-24 79 | POA arr 2026-10-25 59
POA dep 2026-10-22 11 | POA dep 2026-10-23 87 | POA dep 2026-10-24 76 | POA dep 2026-10-25 69
(16 rows; total 793)

### fraport_latest: null other_icao
┌───────────────────┬─────────────┐
│ n_null_other_icao │ failed_iata │
├───────────────────┼─────────────┤
│                 0 │ NULL        │
└───────────────────┴─────────────┘

### fraport_latest: null flight_key (all due to carriers outside carriers.csv; other_icao never null)
TP TAP Portugal 10 | CM Copa Airlines 6 | IB Iberia 4 | AR Aerolineas Argentinas 3 | AF Air France 3 | LP "107917 - Lan Peru" 2 | 0S Sideral 1   (29 of 793)

### fraport_latest: status distribution
Pousado/landed 278 · Decolagem/departed 277 · Previsto/scheduled 217 · Confirmado/confirmed 13 · Cancelado/cancelled 2 (is_disruption=true, delay_min NULL) · Embarque próximo/boarding 2 · Embarque/boarding 1 · Embarque encerrado/boarding 1 · Atrasado/delayed 1 (delay 60) · Alternado/diverted 1

### fraport_latest: rows whose status changed across snapshots
┌─────────┬─────────────────┬─────────────────────┬────────────────────┬──────────────────┬──────────────────────┬──────────────────────┬─────────────┐
│  site   │ flight_code_raw │     sched_local     │  prev_status_raw   │    status_raw    │  status_changed_at   │    first_seen_at     │ n_snapshots │
├─────────┼─────────────────┼─────────────────────┼────────────────────┼──────────────────┼──────────────────────┼──────────────────────┼─────────────┤
│ POA     │ LA3165          │ 2026-10-24T20:25:00 │ Embarque encerrado │ Decolagem        │ 2026-10-24T23:35:06Z │ 2026-10-24T23:19:34Z │           3 │
│ POA     │ AD2855          │ 2026-10-24T21:05:00 │ Embarque próximo   │ Embarque         │ 2026-10-24T23:35:06Z │ 2026-10-24T23:19:34Z │           3 │
│ POA     │ LA3132          │ 2026-10-24T21:40:00 │ Confirmado         │ Embarque próximo │ 2026-10-24T23:35:06Z │ 2026-10-24T23:19:34Z │           3 │
│ FOR     │ LA3507          │ 2026-10-24T20:10:00 │ Embarque encerrado │ Decolagem        │ 2026-10-24T23:35:07Z │ 2026-10-24T23:19:38Z │           3 │
│ FOR     │ G31773          │ 2026-10-25T04:40:00 │ Previsto           │ Confirmado       │ 2026-10-24T23:35:07Z │ 2026-10-24T23:19:38Z │           3 │
│ FOR     │ G31995          │ 2026-10-25T04:45:00 │ Previsto           │ Confirmado       │ 2026-10-24T23:35:07Z │ 2026-10-24T23:19:38Z │           3 │
└─────────┴─────────────────┴─────────────────────┴────────────────────┴──────────────────┴──────────────────────┴──────────────────────┴─────────────┘

### vocab.unmapped() after building fraport_latest + fraport_events in one process
rows: 793 800
vocab.unmapped(): []

### fraport_events: counts by field
┌────────────┬───────┐
│   field    │   n   │
├────────────┼───────┤
│ estimated  │     1 │
│ first_seen │   793 │
│ status     │     6 │
└────────────┴───────┘

### fraport_events: non-first_seen events
┌─────────┬───────────┬─────────────────┬─────────────────────┬──────────────────────┬───────────┬─────────────────────┬─────────────────────┬─────────────────┐
│  site   │ direction │ flight_code_raw │     sched_local     │      changed_at      │   field   │     from_value      │      to_value       │ status_canon_to │
├─────────┼───────────┼─────────────────┼─────────────────────┼──────────────────────┼───────────┼─────────────────────┼─────────────────────┼─────────────────┤
│ POA     │ arr       │ AD2675          │ 2026-10-24T20:00:00 │ 2026-10-24T23:35:06Z │ estimated │ 2026-10-24T20:35:00 │ 2026-10-24T20:40:00 │ NULL            │
│ POA     │ dep       │ LA3165          │ 2026-10-24T20:25:00 │ 2026-10-24T23:35:06Z │ status    │ Embarque encerrado  │ Decolagem           │ departed        │
│ POA     │ dep       │ AD2855          │ 2026-10-24T21:05:00 │ 2026-10-24T23:35:06Z │ status    │ Embarque próximo    │ Embarque            │ boarding        │
│ POA     │ dep       │ LA3132          │ 2026-10-24T21:40:00 │ 2026-10-24T23:35:06Z │ status    │ Confirmado          │ Embarque próximo    │ boarding        │
│ FOR     │ dep       │ LA3507          │ 2026-10-24T20:10:00 │ 2026-10-24T23:35:07Z │ status    │ Embarque encerrado  │ Decolagem           │ departed        │
│ FOR     │ dep       │ G31773          │ 2026-10-25T04:40:00 │ 2026-10-24T23:35:07Z │ status    │ Previsto            │ Confirmado          │ confirmed       │
│ FOR     │ dep       │ G31995          │ 2026-10-25T04:45:00 │ 2026-10-24T23:35:07Z │ status    │ Previsto            │ Confirmado          │ confirmed       │
└─────────┴───────────┴─────────────────┴─────────────────────┴──────────────────────┴───────────┴─────────────────────┴─────────────────────┴─────────────────┘

### siros_today: origin_icao='SBPA' and dest_icao in NE_AIRPORTS
┌──────────────┬───────────────┬───────────┬───────┬─────────────┬───────────┬──────────────────────┬──────────────────────┬────────────────┬──────────────┬──────────────────────────────┐
│ carrier_icao │ flight_number │ equipment │ seats │ origin_icao │ dest_icao │    sched_dep_utc     │    sched_arr_utc     │ operates_today │ is_focus_leg │          flight_key          │
├──────────────┼───────────────┼───────────┼───────┼─────────────┼───────────┼──────────────────────┼──────────────────────┼────────────────┼──────────────┼──────────────────────────────┤
│ AZU          │ 4151          │ A20N      │   174 │ SBPA        │ SBRF      │ 2026-10-24T10:00:00Z │ 2026-10-24T14:05:00Z │ true           │ true         │ AZU-4151-SBPA-20261024T1000Z │
│ GLO          │ 1979          │ B738      │   186 │ SBPA        │ SBSV      │ 2026-10-24T13:30:00Z │ 2026-10-24T16:45:00Z │ true           │ true         │ GLO-1979-SBPA-20261024T1330Z │
└──────────────┴───────────────┴───────────┴───────┴─────────────┴───────────┴──────────────────────┴──────────────────────┴────────────────┴──────────────┴──────────────────────────────┘

### siros_today: summary
n 2920 | n_today 2758 | n_focus 718 | n_null_key 0 | n_arr_before_dep 0 | n_arr_next_day 395 | n_prefix 9 | min_dep 2026-10-24T00:00:00Z | max_arr 2026-10-25T14:15:00Z

### asof.json (pretty)
{
  "built_at": "2026-10-24T23:39:10Z",
  "fraport": {
    "POA": {"fetched_at": "2026-10-24T23:38:07Z", "snapshot_file": "data/archive/fraport/POA/2026-10-24/20261024T233807Z.json.gz", "n_snapshots": 3, "n_dep": 243, "n_arr": 240,
            "dates": {"2026-10-22": {"dep": 11, "arr": 14}, "2026-10-23": {"dep": 87, "arr": 88}, "2026-10-24": {"dep": 76, "arr": 79}, "2026-10-25": {"dep": 69, "arr": 59}}},
    "FOR": {"fetched_at": "2026-10-24T23:38:10Z", "snapshot_file": "data/archive/fraport/FOR/2026-10-24/20261024T233810Z.json.gz", "n_snapshots": 3, "n_dep": 155, "n_arr": 155,
            "dates": {"2026-10-22": {"dep": 4, "arr": 4}, "2026-10-23": {"dep": 55, "arr": 56}, "2026-10-24": {"dep": 50, "arr": 55}, "2026-10-25": {"dep": 46, "arr": 40}}}
  },
  "inmet": {"fetched_at": "2026-10-24T23:35:08Z", "snapshot_file": "data/archive/inmet/2026-10-24/20261024T233508Z.json.gz", "n_alerts": 9},
  "siros_diario": {"snapshot_date": "2026-10-24", "snapshot_file": "data/archive/siros/diario/diario_2026-10-24.csv.gz", "n_legs": 2920}
}

### inmet_alerts.json (first alert, geocodes truncated)
{'fetched_at': '2026-10-24T23:35:08Z', 'source': 'inmet', 'snapshot_file': 'data/archive/inmet/2026-10-24/20261024T233508Z.json.gz', 'n_alerts': 9}
{"id": 56153, "id_aviso": 28544, "grupo": "hoje", "codigo": "urn:oid:2.49.0.0.76.0.2026.28544.1", "descricao": "Tempestade", "severidade": "Perigo Potencial", "cor": "#FFFE00", "inicio": "2026-10-24 00:01", "fim": "2026-10-24 23:59", "inicio_utc": "2026-10-24T03:01:00Z", "fim_utc": "2026-10-25T02:59:00Z", "estados": "Minas Gerais,Paraná,Santa Catarina,Rio Grande do Sul,São Paulo,Espírito Santo,Mato Grosso do Sul,Rio de Janeiro,Goiás", "ufs": ["MG","PR","SC","RS","SP","ES","MS","RJ","GO"], "regioes": "Sudeste,Sul,Centro-Oeste", "n_municipios": 2627, "geocodes": "[2627 items: ['3100104','3100203']…]", "riscos": ["Chuva entre 20 e 30 mm/h ou até 50 mm/dia, ventos intensos (40-60 km/h…"], "instrucoes": "[3 items]", "alterado": false, "encerrado": false}
(9 alerts: hoje 2 — Tempestade Perigo Potencial / Perigo; futuro 7 — Tempestade and Baixa Umidade for 2026-10-25..27; all 'estados' names resolved to UFs, no unknown-state warnings)

### DuckDB DESCRIBE (no timestamp types anywhere)
fraport_latest: 37 cols, VARCHAR except sched_hour_local/delay_min/fraport_id/n_snapshots BIGINT, confidence DOUBLE, is_disruption BOOLEAN
fraport_events: 14 cols, all VARCHAR
siros_today: 26 cols, VARCHAR except seats/leg_number BIGINT, operates_today/is_focus_leg BOOLEAN

