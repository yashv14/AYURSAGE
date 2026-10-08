import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import {
  ErrorNotice,
  Field,
  JsonView,
  Loading,
  Notice,
  useResource,
} from "./components";

export default function DoctorReview({ item, update, dirty, setDirty }) {
  const resource = useResource("/consultations/" + item.id + "/review-context");
  const [draft, setDraft] = useState(null),
    [saved, setSaved] = useState(null),
    [version, setVersion] = useState(item.rowVersion);
  const [error, setError] = useState(null),
    [busy, setBusy] = useState(false),
    [message, setMessage] = useState("");
  const [reason, setReason] = useState(""),
    [confirmation, setConfirmation] = useState(false);
  const [historicalRevision, setHistoricalRevision] = useState(""),
    [historical, setHistorical] = useState(null);
  const approvalAttempt = useRef(null);
  const approvalDialog = useRef(null),
    approvalTrigger = useRef(null);
  useEffect(() => {
    if (confirmation) approvalDialog.current?.focus();
  }, [confirmation]);
  const [reviewDirty, setReviewDirty] = useState(false);
  useEffect(() => {
    if (!resource.value) return;
    const review = resource.value.latestReview;
    setSaved(review);
    setVersion(resource.value.consultation.rowVersion);
    setDraft({
      decisions: Object.keys(
        resource.value.source.prediction.originalOutputs,
      ).map((target) => {
        const old = review?.decisions.find(
          (value) => value.targetCode === target,
        );
        return {
          targetCode: target,
          action: old?.action || "",
          content: old?.content || "",
          reason: old?.reason || "",
        };
      }),
      careNotes: review?.careNotes || "",
      careNotesCompleted: review?.careNotesCompleted || false,
      prescription: review?.prescription || "",
    });
  }, [resource.value]);
  function change(field, value) {
    setDraft((old) => ({ ...old, [field]: value }));
    setReviewDirty(true);
    setDirty(true);
    setMessage("");
    setConfirmation(false);
  }
  function decision(index, field, value) {
    setDraft((old) => ({
      ...old,
      decisions: old.decisions.map((entry, i) =>
        i === index ? { ...entry, [field]: value } : entry,
      ),
    }));
    setReviewDirty(true);
    setDirty(true);
    setMessage("");
    setConfirmation(false);
  }
  async function save(event) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setMessage("");
    try {
      const body = {
        ...draft,
        prescription: draft.prescription.trim() || null,
        expectedRowVersion: version,
        expectedReviewRevision: saved?.revision || 0,
        inputRevision: resource.value.source.input.revision,
        predictionRunId: resource.value.source.prediction.id,
        decisions: draft.decisions
          .filter((d) => d.action)
          .map((d) =>
            d.action === "ACCEPT"
              ? { targetCode: d.targetCode, action: d.action }
              : d,
          ),
      };
      const data = await api("/consultations/" + item.id + "/review", {
        method: "POST",
        body,
      });
      setSaved(data.review);
      setVersion(data.consultation.rowVersion);
      update(data.consultation);
      setReviewDirty(false);
      setDirty(Boolean(reason));
      approvalAttempt.current = null;
      setMessage("Review revision " + data.review.revision + " saved.");
      setConfirmation(false);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  async function approve() {
    setBusy(true);
    setError(null);
    const body = {
      expectedRowVersion: version,
      reviewId: saved.id,
      reviewRevision: saved.revision,
    };
    const fingerprint = JSON.stringify(body);
    if (approvalAttempt.current?.fingerprint !== fingerprint)
      approvalAttempt.current = { fingerprint, key: crypto.randomUUID() };
    try {
      await api("/consultations/" + item.id + "/approve", {
        method: "POST",
        body,
        key: approvalAttempt.current.key,
      });
      setDirty(false);
      update((await api("/consultations/" + item.id)).consultation);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
      setConfirmation(false);
    }
  }
  async function requestInformation(event) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const data = await api(
        "/consultations/" + item.id + "/request-information",
        { method: "POST", body: { expectedRowVersion: version, reason } },
      );
      setDirty(false);
      update(data.consultation);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  async function history(event) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const data = await api(
        "/consultations/" +
          item.id +
          "/review?revision=" +
          encodeURIComponent(historicalRevision),
      );
      setHistorical(data.review);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  function reload() {
    if (
      !dirty ||
      window.confirm("Discard your unsaved review and load the latest record?")
    ) {
      setDirty(false);
      setReviewDirty(false);
      setReason("");
      setError(null);
      setMessage("");
      setConfirmation(false);
      resource.reload();
    }
  }
  if (resource.loading) return <Loading />;
  if (resource.error || !draft)
    return (
      <>
        <ErrorNotice error={resource.error} />
        <button onClick={reload}>Reload review context</button>
      </>
    );
  const source = resource.value.source;
  return (
    <>
      <section className="card">
        <h2>Original input &amp; provenance</h2>
        <p className="muted">
          Input revision {source.input.revision} · Prediction run{" "}
          {source.prediction.id}
        </p>
        <JsonView
          title="Patient input and collection provenance"
          value={source.input}
        />
        <JsonView
          title="Model and adapter provenance"
          value={source.modelProvenance}
        />
      </section>
      <section className="card">
        <div className="card-heading">
          <h2>Doctor review</h2>
          <button onClick={reload} disabled={busy}>
            Reload current record
          </button>
        </div>
        <Notice>
          <strong>Clinical approval policy unavailable</strong>
          <p>
            You may save supported review drafts. A completed draft is not an
            approval. The backend blocks live approval until the clinic policy
            is verified.
          </p>
        </Notice>
        <ErrorNotice error={error} />
        {message && (
          <p role="status" className="success">
            {message}
          </p>
        )}
        <p className="muted">
          Current saved review:{" "}
          {saved ? "revision " + saved.revision + " · " + saved.status : "none"}{" "}
          · Consultation version {version}
        </p>
        <form onSubmit={save}>
          <fieldset disabled={busy}>
            {draft.decisions.map((entry, index) => (
              <article className="decision" key={entry.targetCode}>
                <h3>{entry.targetCode}</h3>
                <div className="original">
                  <p className="eyebrow">Original model output · unapproved</p>
                  <p>
                    {
                      source.prediction.originalOutputs[entry.targetCode]
                        .category
                    }
                  </p>
                  <JsonView
                    title="Confidence as supplied by the original model"
                    value={
                      source.prediction.originalOutputs[entry.targetCode]
                        .confidence ?? "Not supplied"
                    }
                  />
                  <JsonView
                    title="Deterministic enrichment — unchanged"
                    value={source.enrichment.result[entry.targetCode]}
                  />
                </div>
                <Field label={"Decision for " + entry.targetCode}>
                  <select
                    value={entry.action}
                    onChange={(e) => decision(index, "action", e.target.value)}
                  >
                    <option value="">Not decided</option>
                    <option value="ACCEPT">
                      ACCEPT — retain original category and enrichment
                    </option>
                    <option value="EDIT">EDIT — doctor replacement</option>
                    <option value="OVERRIDE">
                      OVERRIDE — doctor replacement
                    </option>
                  </select>
                </Field>
                {["EDIT", "OVERRIDE"].includes(entry.action) && (
                  <div className="doctor-content">
                    <Field label={"Replacement for " + entry.targetCode}>
                      <textarea
                        rows={4}
                        maxLength={16000}
                        required
                        value={entry.content}
                        onChange={(e) =>
                          decision(index, "content", e.target.value)
                        }
                      />
                    </Field>
                    <Field label={"Reason for " + entry.targetCode}>
                      <textarea
                        rows={2}
                        maxLength={2000}
                        required
                        value={entry.reason}
                        onChange={(e) =>
                          decision(index, "reason", e.target.value)
                        }
                      />
                    </Field>
                  </div>
                )}
              </article>
            ))}
            <Field label="Doctor care notes">
              <textarea
                rows={5}
                maxLength={16000}
                value={draft.careNotes}
                required={draft.careNotesCompleted}
                onChange={(e) => change("careNotes", e.target.value)}
              />
            </Field>
            <label className="check">
              <input
                type="checkbox"
                checked={draft.careNotesCompleted}
                onChange={(e) => change("careNotesCompleted", e.target.checked)}
              />
              Care notes are complete
            </label>
            <Field label="Optional doctor prescription">
              <textarea
                rows={3}
                maxLength={16000}
                value={draft.prescription}
                onChange={(e) => change("prescription", e.target.value)}
              />
            </Field>
            <div className="actions">
              <button type="submit" className="primary">
                {busy ? "Saving…" : "Save review revision"}
              </button>
              <button
                type="button"
                disabled={dirty || saved?.status !== "COMPLETED"}
                ref={approvalTrigger}
                onClick={() => setConfirmation(true)}
              >
                Review approval
              </button>
            </div>
          </fieldset>
        </form>
        {confirmation && (
          <div
            role="dialog"
            ref={approvalDialog}
            tabIndex={-1}
            aria-modal="false"
            aria-labelledby="approve-title"
            className="confirmation"
          >
            <h3 id="approve-title">Confirm exact saved review</h3>
            <p>
              Review revision {saved.revision} · Review ID {saved.id}
            </p>
            <p>
              Consultation version {version}. This requests an immutable
              approval. Missing clinical policy will block it.
            </p>
            <button className="primary" onClick={approve} disabled={busy}>
              Confirm approval of revision {saved.revision}
            </button>
            <button
              onClick={() => {
                setConfirmation(false);
                approvalTrigger.current?.focus();
              }}
              disabled={busy}
            >
              Cancel approval
            </button>
          </div>
        )}
      </section>
      <section className="card">
        <h2>Request patient information</h2>
        <p>
          The patient can then create a new revision. Existing submitted input
          stays unchanged.
        </p>
        <form onSubmit={requestInformation}>
          <Field label="Information request reason">
            <textarea
              rows={3}
              required
              maxLength={2000}
              value={reason}
              onChange={(e) => {
                setReason(e.target.value);
                setDirty(true);
              }}
            />
          </Field>
          <button disabled={busy || reviewDirty} type="submit">
            Send information request
          </button>
          {reviewDirty && (
            <p className="muted">
              Save or discard review changes before requesting information.
            </p>
          )}
        </form>
      </section>
      <section className="card">
        <h2>Saved review history</h2>
        <form className="actions" onSubmit={history}>
          <Field
            label="Historical review revision"
            type="number"
            min="1"
            step="1"
            required
            value={historicalRevision}
            onChange={(e) => setHistoricalRevision(e.target.value)}
          />
          <button disabled={busy}>Inspect saved revision</button>
        </form>
        {historical && (
          <JsonView
            title={
              "Saved review revision " + historical.revision + " (read-only)"
            }
            value={historical}
          />
        )}
      </section>
    </>
  );
}
