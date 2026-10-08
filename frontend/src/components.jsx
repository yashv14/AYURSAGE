import { cloneElement, useEffect, useId, useRef, useState } from "react";
import { api } from "./api";

export function ErrorNotice({ error }) {
  const ref = useRef(null);
  useEffect(() => {
    if (error) ref.current?.focus();
  }, [error]);
  if (!error) return null;
  const conflict = error.status === 409;
  return (
    <div ref={ref} tabIndex={-1} role="alert" className="alert error">
      <strong>
        {conflict
          ? "This record changed"
          : error.status === 503
            ? "Action unavailable"
            : "Unable to complete action"}
      </strong>
      <p>{error.message}</p>
      {conflict && (
        <p>
          Your unsaved work is retained. Reload the current record before
          applying changes again.
        </p>
      )}
      {error.requestId && <small>Support request: {error.requestId}</small>}
    </div>
  );
}
export function Notice({ children }) {
  return <div className="alert notice">{children}</div>;
}
export function Status({ value }) {
  return (
    <span className={"status " + (value === "APPROVED" ? "approved" : "")}>
      {value?.replaceAll("_", " ")}
    </span>
  );
}
export function Field({ label, children, hint, ...props }) {
  const id = useId(),
    description = hint ? id + "-hint" : undefined;
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {children ? (
        cloneElement(children, { id, "aria-describedby": description })
      ) : (
        <input id={id} aria-describedby={description} {...props} />
      )}
      {hint && <small id={description}>{hint}</small>}
    </div>
  );
}
export function JsonView({ title, value }) {
  return (
    <details className="json">
      <summary>{title}</summary>
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </details>
  );
}
export function useResource(path) {
  const [value, setValue] = useState(null),
    [error, setError] = useState(null),
    [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    setValue(null);
    api(path)
      .then((data) => {
        if (alive) setValue(data);
      })
      .catch((e) => {
        if (alive) setError(e);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [path, revision]);
  return {
    value,
    error,
    loading,
    reload: () => setRevision((n) => n + 1),
    setValue,
  };
}
export function Loading() {
  return (
    <p role="status" className="loading">
      Loading your workspace…
    </p>
  );
}
export function SectionHeading({ eyebrow, title, children }) {
  return (
    <div className="section-heading">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
      </div>
      {children}
    </div>
  );
}
