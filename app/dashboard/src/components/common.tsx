import type { ReactNode } from "react";
import { ApiError } from "../api/client";
import type { Status } from "../api/types";

export function ErrorMessage({
  error,
  retry,
}: {
  error: Error | null;
  retry?: () => void;
}) {
  if (!error) return null;
  return (
    <div role="alert" className="error">
      {error.message}
      {retry && (
        <button type="button" className="subtle" onClick={retry}>
          Try again
        </button>
      )}
    </div>
  );
}
export function FieldError({
  error,
  name,
}: {
  error: Error | null;
  name: string;
}) {
  return error instanceof ApiError && error.fields[name] ? (
    <span className="field-error" role="alert">
      {error.fields[name]}
    </span>
  ) : null;
}
export function StatusBadge({ status }: { status: Status }) {
  return <span className={`badge ${status}`}>{status}</span>;
}
export function Empty({ children }: { children: ReactNode }) {
  return <p className="empty">{children}</p>;
}
export function date(value: string) {
  return new Date(value).toLocaleString();
}
export function More({
  hasMore,
  loading,
  load,
}: {
  hasMore?: boolean;
  loading: boolean;
  load: () => void;
}) {
  return hasMore ? (
    <button type="button" className="subtle" disabled={loading} onClick={load}>
      {loading ? "Loading…" : "Load more"}
    </button>
  ) : null;
}
