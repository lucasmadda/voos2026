// Configuração do Observable Framework — voos2026
import {existsSync} from "node:fs";
import {resolve} from "node:path";

// Loaders Python rodam com o interpretador do .venv (DuckDB 1.5.6, pyarrow 26); fallback python3.
const python = existsSync(".venv/bin/python") ? resolve(".venv/bin/python") : "python3";

export default {
  title: "voos2026",
  root: "src",
  output: "dist",
  pages: [
    {name: "Hoje e amanhã", path: "/hoje"},
    {name: "Rotas (motor O-D)", path: "/rotas"},
    {name: "Clima × cancelamentos", path: "/clima"},
    {name: "Perfil eleitoral do destino", path: "/eleitoral"},
    {name: "Baselines e contrafactuais", path: "/baselines"},
    {name: "O voo G3 1979", path: "/voo-1979"},
    {name: "Metodologia e fontes", path: "/metodologia"}
  ],
  style: "style.css",
  toc: false,
  pager: false,
  search: false,
  typographer: false,
  interpreters: {".py": [python]},
  head: `<meta name="description" content="Cancelamentos e atrasos de voos no Brasil × meteorologia × perfil eleitoral do destino — dados ANAC, Fraport, DECEA/IEM, TSE, IBGE.">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>✈</text></svg>">`,
  footer: ({path}) => `voos2026 · dados: ANAC (VRA/SIROS), Fraport Brasil, IEM/DECEA (METAR), Open-Meteo (CC BY 4.0), INMET, TSE, IBGE, OurAirports · uso não comercial · <a href="/metodologia">metodologia e fontes</a>`
};
