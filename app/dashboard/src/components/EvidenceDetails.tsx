import type { CspCondition, CspContext, Evidence } from "../api/types";

const contextLabels: Record<CspContext, string> = {
  "network-script": "Network script elements",
  "inline-script": "Inline script elements",
  "script-attribute": "Inline event handlers",
  eval: "JavaScript string evaluation",
};
const conditionLabels: Record<CspCondition, string> = {
  "missing-directive": "No applicable script directive",
  "wildcard-source": "Wildcard network sources",
  "http-scheme-source": "Any HTTP(S) origin",
  "https-scheme-source": "Any HTTPS origin",
  "global-host-source": "Global HTTP(S) host wildcard",
  "unsafe-inline": "Effective unsafe-inline permission",
  "unsafe-eval": "Effective unsafe-eval permission",
};

export function EvidenceDetails({ evidence }: { evidence: Evidence[] }) {
  return (
    <div className="evidence-list">
      {evidence.map(({ id, data }) => (
        <section className="evidence" key={id} aria-label="Finding evidence">
          <dl>
            <dt>Response URL</dt>
            <dd>{data.url}</dd>
            <dt>Header</dt>
            <dd><code>{data.header}</code></dd>
            {"rule_id" in data && (
              <>
                <dt>Rule</dt><dd>{data.rule_id}</dd>
                <dt>HTTP status</dt><dd>{data.status_code}</dd>
                <dt>Declared media type</dt><dd>{data.media_type ?? "Unknown"}</dd>
              </>
            )}
            {"condition" in data && (
              <>
                <dt>Observed condition</dt><dd>{data.condition}</dd>
                <dt>Expected requirement</dt><dd>{data.expected}</dd>
              </>
            )}
            {"observations" in data && (
              <>
                <dt>Enforced policies</dt><dd>{data.policy_count}</dd>
                <dt>Permitted execution contexts</dt>
                <dd>
                  <ol>
                    {data.observations.map((item) => (
                      <li key={item.context + ":" + item.policy_index}>
                        Policy {item.policy_index}: {contextLabels[item.context]}
                        {" ; "}<code>{item.directive ?? "No script directive"}</code>
                        {" ; "}{conditionLabels[item.condition]}
                      </li>
                    ))}
                  </ol>
                </dd>
              </>
            )}
            {data.header === "set-cookie" && (
              <>
                <dt>Cookie name</dt><dd>{data.cookie_name}</dd>
                <dt>Rule</dt><dd>{data.rule}</dd>
                <dt>Secure present</dt><dd>{data.secure ? "Yes" : "No"}</dd>
                {"httponly" in data && <><dt>HttpOnly present</dt><dd>{data.httponly ? "Yes" : "No"}</dd></>}
                {"samesite" in data && (
                  <><dt>SameSite</dt><dd>{data.samesite}</dd></>
                )}
                {"https" in data && (
                  <><dt>HTTPS response</dt><dd>{data.https ? "Yes" : "No"}</dd></>
                )}
                {"domain_present" in data && (
                  <>
                    <dt>Nonempty Domain present</dt><dd>{data.domain_present ? "Yes" : "No"}</dd>
                    <dt>Explicit Path=/</dt><dd>{data.root_path ? "Yes" : "No"}</dd>
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
