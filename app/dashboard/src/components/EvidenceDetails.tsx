import type { Evidence } from "../api/types";

export function EvidenceDetails({ evidence }: { evidence: Evidence[] }) {
  return (
    <div className="evidence-list">
      {evidence.map(({ id, data }) => (
        <section className="evidence" key={id} aria-label="Finding evidence">
          <dl>
            <dt>Response URL</dt>
            <dd>{data.url}</dd>
            <dt>Header</dt>
            <dd>
              <code>{data.header}</code>
            </dd>
            {"rule_id" in data && (
              <>
                <dt>Rule</dt>
                <dd>{data.rule_id}</dd>
                <dt>HTTP status</dt>
                <dd>{data.status_code}</dd>
                <dt>Declared media type</dt>
                <dd>{data.media_type ?? "Unknown"}</dd>
                <dt>Observed condition</dt>
                <dd>{data.condition}</dd>
                <dt>Expected requirement</dt>
                <dd>{data.expected}</dd>
              </>
            )}
            {data.header === "set-cookie" && (
              <>
                <dt>Cookie name</dt>
                <dd>{data.cookie_name}</dd>
                <dt>Rule</dt>
                <dd>{data.rule}</dd>
                <dt>Secure present</dt>
                <dd>{data.secure ? "Yes" : "No"}</dd>
                {"samesite" in data && (
                  <>
                    <dt>SameSite</dt>
                    <dd>{data.samesite}</dd>
                  </>
                )}
                {"https" in data && (
                  <>
                    <dt>HTTPS response</dt>
                    <dd>{data.https ? "Yes" : "No"}</dd>
                  </>
                )}
                {"domain_present" in data && (
                  <>
                    <dt>Nonempty Domain present</dt>
                    <dd>{data.domain_present ? "Yes" : "No"}</dd>
                    <dt>Explicit Path=/</dt>
                    <dd>{data.root_path ? "Yes" : "No"}</dd>
                  </>
                )}
              </>
            )}
          </dl>
        </section>
      ))}
    </div>
  );
}
