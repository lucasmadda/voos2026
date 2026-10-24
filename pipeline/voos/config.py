"""Constantes do projeto: caminhos, URLs das fontes, aeroportos de interesse, datas."""
from __future__ import annotations

from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA = REPO_ROOT / "data"
RAW = DATA / "raw"
ARCHIVE = DATA / "archive"
REF = DATA / "ref"
ONTOLOGY = REPO_ROOT / "ontology"

# --- Fontes -----------------------------------------------------------------
FRAPORT_SITES = {"POA": "portoalegre-airport.com.br", "FOR": "fortaleza-airport.com.br"}
FRAPORT_URL = (
    "https://api-site.fraport-brasil.com/api/flight"
    "?page=1&per_page=1000&home=0&all=1&language_slug=pt"
)
FRAPORT_ICAO = {"POA": "SBPA", "FOR": "SBFZ"}

INMET_ALERTS_URL = "https://apiprevmet3.inmet.gov.br/avisos/ativos"

SIROS_BASE = "https://siros.anac.gov.br/siros/registros"
SIROS_DIARIO_URL = f"{SIROS_BASE}/diario/diario.csv"
SIROS_DIARIO_SERIE = f"{SIROS_BASE}/diario/serie/{{year}}/diario_{{day}}.csv"  # day = YYYY-MM-DD
SIROS_DATE_URL = f"{SIROS_BASE}/date.txt"
VRA_DIR = f"{SIROS_BASE}/diversos/vra/{{year}}/"
VRA_URL = f"{SIROS_BASE}/diversos/vra/{{year}}/VRA_{{year}}_{{month:02d}}.csv"

IEM_ASOS_URL = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"
OPEN_METEO_HIST_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"
AVIATIONWEATHER_METAR_URL = "https://aviationweather.gov/api/data/metar"

TSE_PARTIDO_ZIP = (
    "https://cdn.tse.jus.br/estatistica/sead/odsele/votacao_partido_munzona/"
    "votacao_partido_munzona_{year}.zip"
)
TSE_MUN_CROSSWALK = "https://resultados.tse.jus.br/oficial/ele2026/6258/config/mun-e006258-cm.json"
TSE_LIVE_MUN = (
    "https://resultados.tse.jus.br/oficial/ele2026/{eleicao}/dados/{uf}/{uf}{cd_tse}-c0001-e00{eleicao}-u.json"
)

ANAC_AERODROMOS_CSV = (
    "https://sistemas.anac.gov.br/dadosabertos/Aerodromos/"
    "Aer%C3%B3dromos%20P%C3%BAblicos/Lista%20de%20aer%C3%B3dromos%20p%C3%BAblicos/AerodromosPublicos.csv"
)
OURAIRPORTS_CSV = "https://davidmegginson.github.io/ourairports-data/airports.csv"
IBGE_MALHAS_UF = (
    "https://servicodados.ibge.gov.br/api/v3/malhas/paises/BR"
    "?formato=application/json&qualidade=minima&intrarregiao=UF"
)
IBGE_MALHAS_REGIAO = (
    "https://servicodados.ibge.gov.br/api/v3/malhas/paises/BR"
    "?formato=application/json&qualidade=minima&intrarregiao=regiao"
)
IBGE_MUNICIPIOS = "https://servicodados.ibge.gov.br/api/v1/localidades/municipios?view=nivelado"
IBGE_ESTADOS = "https://servicodados.ibge.gov.br/api/v1/localidades/estados"

# --- Escopo ----------------------------------------------------------------
FOCUS_ORIGIN = "SBPA"
NE_AIRPORTS = [
    "SBSV", "SBRF", "SBFZ", "SBSG", "SBMO", "SBJP", "SBAR", "SBSL", "SBTE",
    "SBPS", "SBIL", "SBPL", "SBJU", "SBVC", "SBKG", "SBFN", "SBIZ",
]
HUB_AIRPORTS = [
    "SBGR", "SBSP", "SBKP", "SBBR", "SBGL", "SBRJ", "SBCF", "SBCT", "SBFL", "SBNF", "SBGO",
]
AIRPORTS = [FOCUS_ORIGIN] + NE_AIRPORTS + HUB_AIRPORTS
# Estações METAR (IEM): SBVC não existe no IEM (só REDEMET)
IEM_STATIONS = [a for a in AIRPORTS if a != "SBVC"]

# Fuso IANA por aeroporto; o padrão é America/Sao_Paulo (UTC−3, sem horário de verão em 2026)
AIRPORT_TZ_DEFAULT = "America/Sao_Paulo"
AIRPORT_TZ = {
    "SBFN": "America/Noronha",   # UTC−2
    "SBEG": "America/Manaus",    # UTC−4
    "SBPV": "America/Porto_Velho",
    "SBRB": "America/Rio_Branco",
    "SBBV": "America/Boa_Vista",
    "SBCG": "America/Campo_Grande",
    "SBCY": "America/Cuiaba",
}

ELECTION_DATES = {
    date(2022, 10, 2): "1º turno 2022",
    date(2022, 10, 30): "2º turno 2022",
    date(2026, 10, 4): "1º turno 2026",
    date(2026, 10, 25): "2º turno 2026",
}
BASELINE_START = date(2024, 10, 1)
# Fechamento do Salgado Filho pela enchente (excluir/flagar no baseline)
SBPA_CLOSURE = (date(2024, 5, 3), date(2024, 10, 20))
EXTRA_VRA_MONTHS = [(2022, 10)]
