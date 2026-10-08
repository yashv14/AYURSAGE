import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import {
  ErrorNotice,
  Field,
  JsonView,
  Loading,
  Notice,
  SectionHeading,
  Status,
  useResource,
} from "./components";

const inputNames = [
  "Disease",
  "Symptom Severity",
  "Nadi Reading",
  "Constitution/Prakriti",
  "Stress Levels",
  "Sleep Patterns",
  "Age Group",
  "Physical Activity Levels",
  "BP Systolic",
  "BP Diastolic",
  "Pulse Rate",
  "Weight (kg)",
];
export function ConsultationList({ user, navigate }) {
  const resource = useResource("/consultations"),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(null);
  const [queue, setQueue] = useState(null);
  useEffect(() => {
    if (user.role === "DOCTOR")
      api("/doctor/review-queue?limit=25").then(setQueue).catch(setError);
  }, [user.role]);
  async function create() {
    setBusy(true);
    setError(null);
    try {
      const data = await api("/consultations", { method: "POST", body: {} });
      navigate("/consultations/" + data.consultation.id);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  async function more() {
    setBusy(true);
    try {
      const data = await api(
        "/doctor/review-queue?limit=25&cursor=" +
          encodeURIComponent(queue.nextCursor),
      );
      setQueue((old) => ({ ...data, items: [...old.items, ...data.items] }));
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <SectionHeading
        eyebrow={
          user.role === "PATIENT" ? "Your care workspace" : "Doctor workspace"
        }
        title={
          user.role === "PATIENT"
            ? "My consultations"
            : "Assigned consultations"
        }
      >
        {user.role === "PATIENT" && (
          <button className="primary" onClick={create} disabled={busy}>
            ＋ New consultation
          </button>
        )}
      </SectionHeading>
      <ErrorNotice error={error || resource.error} />
      {user.role === "DOCTOR" && queue && (
        <section className="card">
          <h2>
            Pending review queue{" "}
            <span className="count">{queue.items.length}</span>
          </h2>
          <ConsultationCards items={queue.items} navigate={navigate} />
          {queue.nextCursor && (
            <button disabled={busy} onClick={more}>
              Load more pending cases
            </button>
          )}
        </section>
      )}
      {resource.loading ? (
        <Loading />
      ) : (
        resource.value && (
          <section className="card">
            <h2>
              {user.role === "PATIENT"
                ? "Your consultation history"
                : "Assigned case history"}
            </h2>
            <p className="muted">
              Showing up to 50 recent consultations. Each consultation keeps its
              own input and review history.
            </p>
            <ConsultationCards
              items={resource.value.items}
              navigate={navigate}
            />
          </section>
        )
      )}
    </>
  );
}
function ConsultationCards({ items, navigate }) {
  return items.length ? (
    <div className="case-list">
      {items.map((item) => (
        <button
          className="case-row"
          key={item.id}
          onClick={() => navigate("/consultations/" + item.id)}
        >
          <span>
            <strong>Consultation {item.id.slice(0, 8)}</strong>
            <small>
              Input revision {item.currentInputRevision ?? "not saved"} · Record
              version {item.rowVersion}
            </small>
          </span>
          <Status value={item.state} />
          <svg aria-hidden="true" width="16" height="16" viewBox="0 0 16 16">
            <path
              d="M3 8h10M9 4l4 4-4 4"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
            />
          </svg>
        </button>
      ))}
    </div>
  ) : (
    <div className="empty">
      <span aria-hidden="true">✧</span>
      <h3>No consultations here yet</h3>
      <p>Cases you can access will appear here.</p>
    </div>
  );
}
export function PatientDraft({ item, update, dirty, setDirty, capabilities }) {
  const current = item.currentInput;
  const [schema, setSchema] = useState(current?.schemaVersion || ""),
    [input, setInput] = useState(
      JSON.stringify(current?.clinicalInput || {}, null, 2),
    );
  const [provenance, setProvenance] = useState(
    JSON.stringify(current?.provenance || {}, null, 2),
  );
  const [error, setError] = useState(null),
    [busy, setBusy] = useState(false),
    [message, setMessage] = useState("");
  const submission = useRef(null);
  const editable = ["DRAFT", "NEEDS_INFORMATION"].includes(item.state);
  const info = useResource(
    "/consultations/" +
      item.id +
      (item.state === "NEEDS_INFORMATION" ? "/information-request" : ""),
  );
  function changed(setter, value) {
    setter(value);
    setDirty(true);
    setMessage("");
  }
  async function save(event) {
    event.preventDefault();
    setError(null);
    setMessage("");
    setBusy(true);
    try {
      const clinicalInput = JSON.parse(input),
        source = JSON.parse(provenance);
      if (
        !clinicalInput ||
        Array.isArray(clinicalInput) ||
        typeof clinicalInput !== "object" ||
        !source ||
        Array.isArray(source) ||
        typeof source !== "object"
      )
        throw new Error("Draft data and provenance must each be JSON objects.");
      const data = await api("/consultations/" + item.id + "/inputs", {
        method: "PUT",
        body: {
          expectedRowVersion: item.rowVersion,
          schemaVersion: schema,
          clinicalInput,
          provenance: source,
        },
      });
      update({
        ...data.consultation,
        currentInput: {
          schemaVersion: schema,
          clinicalInput,
          provenance: source,
        },
      });
      setDirty(false);
      submission.current = null;
      setMessage(
        "Draft saved as input revision " + data.inputRevision.revision + ".",
      );
    } catch (e) {
      setError(
        e instanceof SyntaxError
          ? new Error("Enter valid JSON for draft data and provenance.")
          : e,
      );
    } finally {
      setBusy(false);
    }
  }
  async function submit() {
    setBusy(true);
    setError(null);
    const body = {
      expectedRowVersion: item.rowVersion,
      inputRevision: item.currentInputRevision,
    };
    const fingerprint = JSON.stringify(body);
    if (submission.current?.fingerprint !== fingerprint)
      submission.current = { fingerprint, key: crypto.randomUUID() };
    try {
      const data = await api("/consultations/" + item.id + "/submit", {
        method: "POST",
        body,
        key: submission.current.key,
      });
      update(data.consultation);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="card">
      <h2>{editable ? "Your input draft" : "Submitted input"}</h2>
      {item.state === "NEEDS_INFORMATION" && (
        <>
          <h3>Doctor information request</h3>
          {info.loading ? (
            <Loading />
          ) : (
            info.value?.informationRequest && (
              <Notice>
                <p>{info.value.informationRequest.reason}</p>
                <p>
                  Requested fields:{" "}
                  {info.value.informationRequest.requestedFields?.join(", ") ||
                    "See doctor instructions above."}
                </p>
              </Notice>
            )
          )}
          <ErrorNotice error={info.error} />
        </>
      )}
      <Notice>
        <strong>Clinical collection form unavailable</strong>
        <p>
          Collection categories, numeric bounds and verification rules are
          awaiting clinical approval. Existing draft data can be recorded below;
          saving a draft does not validate it for model use.
        </p>
      </Notice>
      <details>
        <summary>Evidenced model field names</summary>
        <ul>
          {inputNames.map((name) => (
            <li key={name}>{name}</li>
          ))}
        </ul>
        <p>
          No permitted-value options or numerical limits are inferred from these
          names.
        </p>
      </details>
      <ErrorNotice error={error} />
      {message && (
        <p role="status" className="success">
          {message}
        </p>
      )}
      {editable ? (
        <form onSubmit={save}>
          <fieldset disabled={busy}>
            <Field
              label="Draft schema version"
              value={schema}
              onChange={(e) => changed(setSchema, e.target.value)}
              required
              maxLength={64}
              hint="Use the version supplied by your clinic or project. No clinical schema is currently approved."
            />
            <Field label="Draft data (JSON object)">
              <textarea
                className="code"
                rows={9}
                value={input}
                onChange={(e) => changed(setInput, e.target.value)}
                required
              />
            </Field>
            <Field
              label="Input provenance (JSON object)"
              hint="Keep patient-reported context distinct from clinician verification. Do not claim verification that has not occurred."
            >
              <textarea
                className="code"
                rows={5}
                value={provenance}
                onChange={(e) => changed(setProvenance, e.target.value)}
                required
              />
            </Field>
            <div className="actions">
              <button className="primary" type="submit">
                {busy ? "Saving…" : "Save input draft"}
              </button>
              <button
                type="button"
                onClick={submit}
                disabled={
                  busy ||
                  dirty ||
                  !item.currentInputRevision ||
                  capabilities?.ml !== "ready"
                }
              >
                Submit saved revision
              </button>
            </div>
          </fieldset>
          <p className="muted">
            Submission is unavailable while model evidence and clinical input
            policies remain unresolved.
          </p>
        </form>
      ) : (
        <JsonView
          title="Saved input and provenance"
          value={current || "No saved input available."}
        />
      )}
    </section>
  );
}
export function ApprovedContent({ item }) {
  const resource = useResource("/consultations/" + item.id + "/approved"),
    [error, setError] = useState(null),
    [busy, setBusy] = useState(false);
  const [report, setReport] = useState(null);
  async function download() {
    setBusy(true);
    setError(null);
    try {
      const result = await api("/consultations/" + item.id + "/reports", {
        method: "POST",
        body: {
          approvalId: resource.value.approval.id,
          reportVersion: "approved-patient-v1",
        },
      });
      setReport(result.report);
      const data = await api("/reports/" + result.report.id + "/download", {
        blob: true,
      });
      if (data.type !== "application/pdf")
        throw new Error("The server did not return a PDF report.");
      const url = URL.createObjectURL(data),
        link = document.createElement("a");
      link.href = url;
      link.download = "ayursage-report-" + result.report.id + ".pdf";
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  if (resource.loading) return <Loading />;
  return (
    <section className="card">
      <h2>Approved care snapshot</h2>
      <ErrorNotice error={error || resource.error} />
      {resource.value && (
        <>
          <p className="muted">
            Approval version {resource.value.approval.version} ·{" "}
            {new Date(resource.value.approval.approvedAt).toLocaleString()}
          </p>
          <p className="identifier">
            Approval ID: {resource.value.approval.id}
          </p>
          <div className="recommendations">
            {Object.entries(
              resource.value.approval.approvedContent.recommendations,
            ).map(([target, value]) => (
              <article key={target}>
                <h3>{target}</h3>
                <PublicRecommendation value={value} />
              </article>
            ))}
          </div>
          <h3>Doctor care notes</h3>
          <p className="long-text">
            {resource.value.approval.approvedContent.careNotes}
          </p>
          {resource.value.approval.approvedContent.prescription && (
            <>
              <h3>Doctor prescription</h3>
              <p className="long-text">
                {resource.value.approval.approvedContent.prescription}
              </p>
            </>
          )}
          <button className="primary" onClick={download} disabled={busy}>
            {busy ? "Preparing private PDF…" : "Download approved PDF"}
          </button>
          {report && (
            <p className="muted">
              Report status: {report.status}. Report {report.id}
            </p>
          )}
        </>
      )}
    </section>
  );
}
function PublicRecommendation({ value }) {
  return Object.entries(value).map(([name, content]) => (
    <div key={name}>
      {name !== "text" && <h4>{name.replaceAll("_", " ")}</h4>}
      {Array.isArray(content) ? (
        <ul>
          {content.map((text, i) => (
            <li key={i}>{text}</li>
          ))}
        </ul>
      ) : (
        <p className="long-text">{String(content ?? "")}</p>
      )}
    </div>
  ));
}
