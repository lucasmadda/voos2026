"""Testes das funções puras da dimensão de aeroportos (sem rede)."""
import pyarrow as pa

from voos.marts import dims
from voos.marts.dims import apply_overrides, build_dim_airport, uf_from_name
from voos.sources.anac_aerodromos import (
    parse_date_br,
    parse_decimal,
    parse_text,
    title_case_pt,
    updated_at_from_header,
)
from voos.sources import ourairports

ANAC_SAMPLE = (
    "Atualizado em: 2026-10-15\n"
    "Código OACI;CIAD;Nome;Município;UF;Município Servido;UF Servido;LATGEOPOINT;LONGEOPOINT;Latitude;Longitude;"
    "Altitude;Operação Diurna;Operação Noturna;Situação;Validade do Registro;Portaria de Registro;Link Portaria\n"
    "SBPA;RS0001;Salgado Filho;PORTO ALEGRE;Rio Grande do Sul;Porto Alegre;Rio Grande do Sul;-29.994722;-51.171111;"
    "29° 59' 41'' S;51° 10' 16'' W;9,0;VFR/IFR;VFR/IFR;Cadastrado;;Portaria X;http://x\n"
    "SBSG;RN0001;Aeroporto de Natal;SÃO GONÇALO DO AMARANTE;Rio Grande do Norte;Natal;Rio Grande do Norte;-5.7688889;"
    "-35.366389;;;83,0;VFR;VFR;Cadastrado;26/12/2027;;\n"
    "SDRS;RJ0007;Resende;;;Resende;Rio de Janeiro;-22.478611;-44.480278;;;1.234,5;VFR;;Interditado;;;\n"
)


def test_title_case_pt():
    assert title_case_pt("SÃO GONÇALO DO AMARANTE") == "São Gonçalo do Amarante"
    assert title_case_pt("PORTO ALEGRE") == "Porto Alegre"
    assert title_case_pt("RIO DE JANEIRO") == "Rio de Janeiro"
    assert title_case_pt("GUAJARÁ-MIRIM") == "Guajará-Mirim"
    assert title_case_pt("SANTA BÁRBARA D'OESTE") == "Santa Bárbara d'Oeste"
    assert title_case_pt("  FERNANDO   DE NORONHA ") == "Fernando de Noronha"
    assert title_case_pt("DE") == "De"  # primeira palavra sempre capitalizada
    assert title_case_pt("") is None
    assert title_case_pt(None) is None


def test_parse_decimal_comma():
    assert parse_decimal("894,0") == 894.0
    assert parse_decimal("1.234,5") == 1234.5
    assert parse_decimal("-29.994722") == -29.994722
    assert parse_decimal(" 9,0 ") == 9.0
    assert parse_decimal("") is None
    assert parse_decimal(None) is None
    assert parse_decimal("abc") is None


def test_parse_date_br():
    assert parse_date_br("26/12/2027") == "2027-12-26"
    assert parse_date_br("2026-10-15") == "2026-10-15"
    assert parse_date_br("") is None
    assert parse_date_br("n/a") is None
    assert updated_at_from_header("Atualizado em: 2026-10-15") == "2026-10-15"
    assert updated_at_from_header("Atualizado em: 15/10/2026") == "2026-10-15"


def test_uf_from_name():
    assert uf_from_name("Rio Grande do Sul") == ("RS", "S", "Sul")
    assert uf_from_name("Sao Paulo") == ("SP", "SE", "Sudeste")  # sem acento
    assert uf_from_name("BA") == ("BA", "NE", "Nordeste")  # sigla
    assert uf_from_name("Distrito Federal") == ("DF", "CO", "Centro-Oeste")
    assert uf_from_name("Narnia") == (None, None, None)
    assert uf_from_name(None) == (None, None, None)


def test_parse_anac_text():
    tbl = parse_text(ANAC_SAMPLE)
    assert tbl.num_rows == 3
    rows = {r["icao"]: r for r in tbl.to_pylist()}
    sbpa = rows["SBPA"]
    assert sbpa["ciad"] == "RS0001"
    assert sbpa["municipio"] == "Porto Alegre"
    assert sbpa["uf_nome"] == "Rio Grande do Sul"
    assert (sbpa["lat"], sbpa["lon"], sbpa["altitude_m"]) == (-29.994722, -51.171111, 9.0)
    assert sbpa["validade_registro"] is None
    assert sbpa["updated_at"] == "2026-10-15"
    sbsg = rows["SBSG"]
    assert sbsg["municipio"] == "São Gonçalo do Amarante"
    assert sbsg["municipio_servido"] == "Natal"
    assert sbsg["validade_registro"] == "2027-12-26"
    sdrs = rows["SDRS"]
    assert sdrs["municipio"] is None and sdrs["uf_nome"] is None
    assert sdrs["uf_servido_nome"] == "Rio de Janeiro"
    assert sdrs["altitude_m"] == 1234.5
    assert tbl.schema.field("lat").type == pa.float64()
    assert tbl.schema.field("updated_at").type == pa.string()


def _oa_table() -> pa.Table:
    cols = ["ident", "icao", "iata", "name", "lat", "lon", "country", "region", "municipality",
            "scheduled_service", "local_code", "type"]
    data = [
        ["SBPA", "SBPA", "POA", "Porto Alegre-Salgado Filho", -29.993984, -51.167482, "BR", "BR-RS", "Porto Alegre",
         True, "RS0001", "large_airport"],
        # SBSG sem icao_code no OurAirports: só casa pelo local_code = CIAD
        ["BR-XYZ", None, "NAT", "Natal Intl", -5.769822, -35.36661, "BR", "BR-RN", "Natal", True, "RN0001",
         "large_airport"],
        ["LPPT", "LPPT", "LIS", "Lisbon Humberto Delgado Airport", 38.7813, -9.13592, "PT", "PT-11", "Lisbon",
         True, None, "large_airport"],
        # duplicata de ICAO no exterior: fica a de maior porte
        ["LPPT-old", "LPPT", None, "Lisbon old", 38.0, -9.0, "PT", "PT-11", "Lisbon", True, None, "closed"],
        # sem serviço regular e fora do Brasil → excluído
        ["XXXX", "XXXX", "XXX", "Nowhere", 0.0, 0.0, "AR", "AR-B", "Nowhere", False, None, "small_airport"],
    ]
    return pa.table({c: [row[i] for row in data] for i, c in enumerate(cols)})


def test_build_dim_airport(monkeypatch):
    monkeypatch.setattr(dims, "load_overrides", lambda: {"SBPA": {"municipio_servido": "Porto Alegre (RS)"},
                                                         "SBSG": {"lat": "-5,77"}})
    tbl = build_dim_airport(parse_text(ANAC_SAMPLE), _oa_table())
    assert tbl.schema.names == dims.SCHEMA.names
    rows = {r["icao"]: r for r in tbl.to_pylist()}
    assert list(rows) == ["SBPA", "SBSG", "SDRS", "LPPT"]  # país, icao
    sbpa = rows["SBPA"]
    assert sbpa["iata"] == "POA" and sbpa["scheduled_service"] is True
    assert (sbpa["uf"], sbpa["regiao"], sbpa["regiao_nome"]) == ("RS", "S", "Sul")
    assert sbpa["tz"] == "America/Sao_Paulo" and sbpa["is_focus_origin"] is True
    assert sbpa["municipio_servido"] == "Porto Alegre (RS)"  # override aplicado
    assert sbpa["lat"] == -29.994722  # coordenada da ANAC, não do OurAirports
    sbsg = rows["SBSG"]
    assert sbsg["iata"] == "NAT"  # via fallback local_code = CIAD
    assert sbsg["is_ne"] is True and sbsg["is_hub"] is False
    assert sbsg["lat"] == -5.77  # override com vírgula decimal
    sdrs = rows["SDRS"]
    assert sdrs["municipio"] == "Resende" and sdrs["uf"] == "RJ"  # fallback para o município/UF servidos
    assert sdrs["iata"] is None and sdrs["scheduled_service"] is False
    lis = rows["LPPT"]
    assert lis["source"] == "ourairports" and lis["country"] == "PT" and lis["tz"] == "UTC"
    assert lis["iata"] == "LIS" and lis["municipio"] is None and lis["municipio_servido"] == "Lisbon"
    assert lis["uf"] is None and lis["regiao"] is None


def test_apply_overrides_coercion():
    rec = {"icao": "SBVC", "iata": None, "scheduled_service": False, "lat": 1.0}
    out = apply_overrides(rec, {"iata": "VDC", "scheduled_service": "true", "lat": "-14,9"})
    assert out == {"icao": "SBVC", "iata": "VDC", "scheduled_service": True, "lat": -14.9}
    assert rec["iata"] is None  # não altera o original


def test_ourairports_parse(tmp_path):
    csv_path = tmp_path / "airports.csv"
    csv_path.write_text(
        "id,ident,type,name,latitude_deg,longitude_deg,elevation_ft,continent,iso_country,iso_region,municipality,"
        "scheduled_service,icao_code,iata_code,gps_code,local_code,home_link,wikipedia_link,keywords\n"
        '1,SBPA,large_airport,"Porto Alegre, Salgado Filho",-29.99,-51.16,11,SA,BR,BR-RS,Porto Alegre,yes,SBPA,POA,SBPA,RS0001,,,\n'
        "2,SSRS,small_airport,Rosario,-30.0,-55.0,100,SA,BR,BR-RS,Rosário do Sul,no,,,SSRS,RS0047,,,\n"
        "3,03N,seaplane_base,Utirik,11.2,169.8,4,OC,MH,MH-UTI,Utirik,yes,,UTK,,03N,,,\n"
        "4,SAEZ,large_airport,Ezeiza,-34.8,-58.5,67,SA,AR,AR-B,Buenos Aires,yes,SAEZ,EZE,SAEZ,EZE,,,\n"
        "5,SNXX,small_airport,Fazenda,-10.0,-50.0,300,SA,BR,BR-MT,Nada,no,,,,,,,\n"
        "6,X1,heliport,Heli,-10.0,-50.0,300,SA,AR,AR-B,Nada,no,,,,,,,\n",
        encoding="utf-8",
    )
    tbl = ourairports.parse(csv_path)
    rows = {r["ident"]: r for r in tbl.to_pylist()}
    assert set(rows) == {"SBPA", "SSRS", "03N", "SAEZ", "SNXX"}  # X1: sem serviço e fora do BR
    assert rows["SBPA"]["name"] == "Porto Alegre, Salgado Filho" and rows["SBPA"]["scheduled_service"] is True
    assert rows["SSRS"]["icao"] == "SSRS"  # fallback para ident
    assert rows["SNXX"]["icao"] == "SNXX" and rows["SNXX"]["iata"] is None
    assert rows["03N"]["icao"] is None and rows["03N"]["iata"] == "UTK"
    assert rows["SAEZ"]["lat"] == -34.8 and rows["SAEZ"]["local_code"] == "EZE"
    assert tbl.schema.field("scheduled_service").type == pa.bool_()
