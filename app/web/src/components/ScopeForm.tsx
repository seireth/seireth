import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { post } from "../api/client";
import type { Target } from "../api/types";
import { ErrorMessage, FieldError } from "./common";

export function defaultExpiry(now = Date.now()) {
  const value = new Date(now + 15 * 60_000);
  return new Date(value.getTime() - value.getTimezoneOffset() * 60_000)
    .toISOString()
    .slice(0, 16);
}
export function expiryTimestamp(value: string) {
  return new Date(value).toISOString();
}

export default function ScopeForm({
  target,
  onCreated,
}: {
  target: Target;
  onCreated?: (id: string) => void;
}) {
  const [url, setUrl] = useState(target.url);
  const [expiry, setExpiry] = useState(defaultExpiry);
  const client = useQueryClient();
  const create = useMutation({
    mutationFn: () =>
      post<{ id: string }>("/authorization-scopes", {
        project_id: target.project_id,
        target_id: target.id,
        allowed_url: url,
        expires_at: expiryTimestamp(expiry),
      }),
    onSuccess: ({ id }) => {
      void client.invalidateQueries({
        queryKey: [`/projects/${target.project_id}/authorization-scopes`],
      });
      void client.invalidateQueries({
        queryKey: [
          `/projects/${target.project_id}/authorization-scopes?target_id=${encodeURIComponent(target.id)}`,
        ],
      });
      onCreated?.(id);
    },
  });
  const invalidExpiry =
    !expiry ||
    !Number.isFinite(new Date(expiry).getTime()) ||
    new Date(expiry).getTime() <= Date.now();
  return (
    <form
      className="form-grid"
      onSubmit={(e) => {
        e.preventDefault();
        if (!create.isPending && !invalidExpiry) create.mutate();
      }}
    >
      <label>
        Authorized URL
        <input
          required
          type="url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
        />
        <FieldError error={create.error} name="allowed_url" />
      </label>
      <label>
        Expires at (local time)
        <input
          required
          type="datetime-local"
          value={expiry}
          onChange={(e) => setExpiry(e.target.value)}
        />
        <FieldError error={create.error} name="expires_at" />
        {invalidExpiry && (
          <span className="field-error">Choose a future expiry time.</span>
        )}
      </label>
      <p className="hint">
        Authorize only a URL within {target.url}. Creating a scope does not
        start an assessment.
      </p>
      <ErrorMessage error={create.error} />
      <button type="submit" disabled={create.isPending || invalidExpiry}>
        {create.isPending ? "Authorizing…" : "Create authorization scope"}
      </button>
    </form>
  );
}
