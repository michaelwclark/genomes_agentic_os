/** The same one-hour availability boundary used by local queue consumers. */
export const DISPATCH_STARVATION_AGE_SECONDS = 3600;

/**
 * Return the complete PostgreSQL ordering rule for a known internal consumer.
 * Every policy value remains a bound parameter. Neither SQL identifiers nor
 * fragments are accepted from callers, task payloads, or configuration.
 */
export function taskDispatchOrderSql(consumer: "claim" | "publish"): string {
  if (consumer !== "claim" && consumer !== "publish") {
    throw new Error("unsupported queue ordering consumer");
  }
  const ageParameter = consumer === "claim" ? "$8" : "$2";
  const cutoff = `now() - (${ageParameter}::integer * interval '1 second')`;
  const freshPriority = consumer === "claim"
    ? `t.priority + LEAST(
        $7::integer,
        GREATEST(0, floor(
          extract(epoch FROM (now() - t.created_at)) /
          GREATEST($5::integer,1)
        )::integer * $6::integer)
      ) DESC,
      (
        SELECT count(*) + 1 FROM fabric_tasks running
        WHERE running.status='running' AND running.namespace=t.namespace
      )::numeric /
        COALESCE(NULLIF(($4::jsonb ->> t.namespace)::numeric,0),1) ASC,`
    : "t.priority DESC,";
  return `CASE WHEN t.available_at <= ${cutoff} THEN 0 ELSE 1 END ASC,
    CASE WHEN t.available_at <= ${cutoff} THEN t.available_at END ASC,
    ${freshPriority}
    t.available_at,t.created_at,t.id`;
}
