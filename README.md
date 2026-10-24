# voos2026

Cancelamentos e atrasos de voos no Brasil, agregados por origem–destino (aeroporto, município servido, UF, região,
perfil eleitoral do destino) e cruzados com meteorologia (METAR). Caso de partida: a alegação de 24/10/2026 sobre
voos POA → Nordeste. O app não infere motivo: mostra taxas-base, contrafactuais e intervalos.

Stack: Observable Framework (site estático) + data loaders em Python (DuckDB/pyarrow). Fontes gratuitas:
ANAC VRA/SIROS, painel da Fraport (POA/FOR), IEM/REDEMET (METAR), Open-Meteo, INMET, TSE, IBGE, OurAirports.
