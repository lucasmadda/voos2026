// Converte uma tabela Arrow (FileAttachment.parquet) em array de objetos simples.
// int64 chega como BigInt no Arrow JS → Number; strings e doubles passam direto.
export function rows(table) {
  const out = [];
  for (const r of table) {
    const o = typeof r.toJSON === "function" ? r.toJSON() : {...r};
    for (const k in o) if (typeof o[k] === "bigint") o[k] = Number(o[k]);
    out.push(o);
  }
  return out;
}
