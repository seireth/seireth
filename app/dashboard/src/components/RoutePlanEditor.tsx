import type { Plugin, Profiles } from "../api/types";

export interface RouteDraft {
  key: string; url: string; media: string; statuses: string; profile: string;
  session: string; expectedCookies: string;
  plugins?: string[];
  finalUrl?: string;
  requiredChecks?: string[];
}
export const newRoute = (url = "", key = "response"): RouteDraft => ({
  key, url, media: "text/html", statuses: "200", profile: "", session: "", expectedCookies: "",
});

const commaSeparated = (value: string) => value.split(",").map(item => item.trim()).filter(Boolean);

export function selectRoutePlugins(route: RouteDraft, plugins: string[], inherited = false): RouteDraft {
  return {
    ...route,
    plugins: inherited ? undefined : plugins,
    requiredChecks: route.requiredChecks?.filter(rule => plugins.includes(rule.split(":")[0])),
  };
}

export function routeRequest(route: RouteDraft, selectedPlugins: string[]) {
  return {
    key: route.key, url: route.url, plugins: route.plugins ?? selectedPlugins,
    request_profile: route.profile || null,
    ...(route.requiredChecks !== undefined ? { required_checks: route.requiredChecks } : {}),
    expected: {
      statuses: route.statuses.split(",").map(value => Number(value.trim())),
      final_url: route.finalUrl || null,
      media_types: commaSeparated(route.media),
    },
    analysis: {
      session_cookies: commaSeparated(route.session),
      expected_cookies: commaSeparated(route.expectedCookies),
    },
  };
}

export function RoutePlanEditor({ routes, onChange, profiles, plugins, selectedPlugins }: {
  routes: RouteDraft[]; onChange: (routes: RouteDraft[]) => void; profiles?: Profiles;
  plugins?: Plugin[]; selectedPlugins: string[];
}) {
  const update = (index: number, changes: Partial<RouteDraft>) =>
    onChange(routes.map((route, position) => position === index ? { ...route, ...changes } : route));
  const addRoute = () => {
    let number = routes.length + 1;
    while (routes.some(route => route.key === "route-" + number)) number++;
    onChange([...routes, newRoute("", "route-" + number)]);
  };
  return <section className="panel"><h2>Route plan</h2>
    <p>Declare the responses you expect. An unexpected login redirect blocks the release.</p>
    {routes.map((route, index) => <fieldset key={index}>
      <legend>Route {index + 1}</legend>
      <label>Route key<input value={route.key} onChange={e => update(index, { key: e.target.value })} /></label>
      <label>Response URL<input type="url" required value={route.url} onChange={e => update(index, { url: e.target.value })} /></label>
      <label>Expected status codes<input value={route.statuses} onChange={e => update(index, { statuses: e.target.value })} /></label>
      <label>Expected final URL after redirects (optional)<input type="url" value={route.finalUrl ?? ""}
        onChange={e => update(index, { finalUrl: e.target.value })} /></label>
      <label>Expected media types<input value={route.media} placeholder="text/html or application/json; leave blank for redirects"
        onChange={e => update(index, { media: e.target.value })} /></label>
      <label>Request profile<select value={route.profile} onChange={e => update(index, { profile: e.target.value })}>
        <option value="">Anonymous request</option>{Object.keys(profiles?.requests ?? {}).map(name => <option key={name}>{name}</option>)}
      </select></label>
      <label>Session cookie names<input value={route.session} onChange={e => update(index, { session: e.target.value })} /></label>
      <label>Cookies expected in this response<input value={route.expectedCookies} onChange={e => update(index, { expectedCookies: e.target.value })} /></label>
      <details><summary>Route checks</summary>
        {(plugins ?? []).map(plugin => <label key={plugin.id}>
          <input type="checkbox" checked={(route.plugins ?? selectedPlugins).includes(plugin.id)} onChange={e => {
            const current = route.plugins ?? selectedPlugins;
            const chosen = e.target.checked ? [...current, plugin.id] : current.filter(id => id !== plugin.id);
            update(index, selectRoutePlugins(route, chosen));
          }} />{plugin.name}
        </label>)}
        <label><input type="checkbox" checked={route.requiredChecks !== undefined} onChange={e =>
          update(index, { requiredChecks: e.target.checked ? [] : undefined })
        } />Customize required checks</label>
        {route.requiredChecks !== undefined && <>
          <p>An empty selection requires only the response expectation.</p>
          {(route.plugins ?? selectedPlugins).flatMap(plugin => Object.entries(plugins?.find(item => item.id === plugin)?.rules ?? {}).map(([rule, applicability]) => {
            const id = plugin + ":" + rule;
            return <label key={id}><input type="checkbox" checked={route.requiredChecks?.includes(id)} onChange={e =>
              update(index, {
                requiredChecks: e.target.checked ? [...(route.requiredChecks ?? []), id] : route.requiredChecks?.filter(value => value !== id),
              })
            } />{id} ({applicability})</label>;
          }))}
        </>}
      </details>
      {routes.length > 1 && <button type="button" className="subtle" onClick={() => onChange(routes.filter((_, position) => position !== index))}>Remove route</button>}
    </fieldset>)}
    <button type="button" className="subtle" disabled={routes.length >= 20}
      onClick={addRoute}>Add route</button>
  </section>;
}
