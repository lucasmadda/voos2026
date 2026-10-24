---
title: Metodologia e fontes
---

# Metodologia e fontes

<div class="note">Versão inicial (Dia 0). As seções de definições formais (modelo conceitual), estatística e licenças completas entram nos Dias 1–3.</div>

## O que é provisório e o que é oficial

- **Provisório:** status lido do painel público do operador do aeroporto (Fraport Brasil, POA e FOR), arquivado a cada 15 minutos. "Cancelado" ali é o cancelamento declarado no painel; não há horário real de decolagem nem motivo.
- **Oficial:** o VRA (Voo Regular Ativo) da ANAC, publicado cerca de três a quatro semanas após o fim do mês. É o registro do que foi previsto, realizado ou cancelado. Desde abril de 2020 **não traz justificativa** (Resolução ANAC 550/2020), portanto a atribuição a clima vem do METAR, não da ANAC.
- Um trecho retirado da malha (SIROS) antes do dia **não aparece como cancelado** em nenhuma fonte; por isso o snapshot diário do SIROS também é arquivado.

## Fontes

| Fonte | Uso | Acesso | Licença / termos |
|---|---|---|---|
| ANAC — VRA (SIROS) | histórico oficial de etapas | CSV mensal público | dados abertos (Decreto 8.777/2016) |
| ANAC — SIROS diário | malha planejada do dia (UTC) | CSV público | dados abertos |
| Fraport Brasil — painel de voos POA/FOR | status de hoje e amanhã | API pública do site, sem chave | termos não publicados; coleta a cada 15 min, com atribuição |
| DECEA via Iowa Environmental Mesonet | METAR/SPECI horários | CGI público | atribuição ao IEM |
| Open-Meteo | CAPE, chuva e visibilidade modeladas | API pública | CC BY 4.0, não comercial |
| INMET | avisos meteorológicos ativos | API pública | dados abertos |
| TSE — dados abertos | votação por município (2026, 2022) | CSV público | dados abertos |
| IBGE — malhas e localidades | UF, região, município | API pública | dados abertos |
| OurAirports | códigos IATA/ICAO, coordenadas | CSV público | domínio público |

## Horários

Tudo é armazenado em UTC. O "dia" da análise é o dia local do aeroporto (America/Sao_Paulo, UTC−3, sem horário de verão em 2026; Noronha é UTC−2). O VRA registra todos os aeroportos em horário de Brasília.
