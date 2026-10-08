import { useRef, useState } from "react";
import { api } from "./api";
import { ErrorNotice, Field, Notice, SectionHeading } from "./components";

export default function Admin({ setDirty }) {
  const dirtyForms = useRef({ doctor: false, assignment: false });
  const [error, setError] = useState(null),
    [busy, setBusy] = useState(false),
    [message, setMessage] = useState("");
  const [doctor, setDoctor] = useState({
    email: "",
    password: "",
    verificationProvenance: "",
  });
  const [assignment, setAssignment] = useState({
    consultationId: "",
    expectedRowVersion: "",
    doctorId: "",
    reason: "",
  });
  function change(setter, field, value) {
    dirtyForms.current[setter === setDoctor ? "doctor" : "assignment"] = true;
    setter((old) => ({ ...old, [field]: value }));
    setDirty(true);
    setMessage("");
  }
  async function onboard(event) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const provenance = JSON.parse(doctor.verificationProvenance);
      const data = await api("/admin/doctors", {
        method: "POST",
        body: {
          email: doctor.email,
          password: doctor.password,
          verificationProvenance: provenance,
        },
      });
      setMessage("Verified doctor account created. Doctor ID: " + data.user.id);
      setDoctor({ email: "", password: "", verificationProvenance: "" });
      dirtyForms.current.doctor = false;
      setDirty(dirtyForms.current.assignment);
    } catch (e) {
      setError(
        e instanceof SyntaxError
          ? new Error("Verification provenance must be valid JSON.")
          : e,
      );
    } finally {
      setBusy(false);
    }
  }
  async function assign(event) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const data = await api(
        "/admin/consultations/" +
          encodeURIComponent(assignment.consultationId) +
          "/assignment",
        {
          method: "POST",
          body: {
            expectedRowVersion: Number(assignment.expectedRowVersion),
            doctorId: assignment.doctorId,
            reason: assignment.reason,
          },
        },
      );
      setMessage(
        "Assignment recorded. New record version: " +
          data.consultation.rowVersion,
      );
      setAssignment({
        ...assignment,
        expectedRowVersion: String(data.consultation.rowVersion),
        reason: "",
      });
      dirtyForms.current.assignment = false;
      setDirty(dirtyForms.current.doctor);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <SectionHeading
        eyebrow="Operational workspace"
        title="Clinic administration"
      />
      <Notice>
        <strong>Operational access only</strong>
        <p>
          Administrator authority does not grant clinical review, approval or
          access to patient reports. Only existing onboarding and assignment
          operations are available.
        </p>
      </Notice>
      <ErrorNotice error={error} />
      {message && (
        <p role="status" className="success">
          {message}
        </p>
      )}
      <div className="admin-grid">
        <section className="card">
          <h2>Onboard a verified doctor</h2>
          <p>
            Record independently reviewed qualification evidence before
            activating a doctor.
          </p>
          <form onSubmit={onboard}>
            <fieldset disabled={busy}>
              <Field
                label="Doctor email"
                type="email"
                autoComplete="off"
                required
                value={doctor.email}
                onChange={(e) => change(setDoctor, "email", e.target.value)}
              />
              <Field
                label="Initial doctor password"
                type="password"
                autoComplete="new-password"
                minLength={12}
                maxLength={256}
                required
                value={doctor.password}
                onChange={(e) => change(setDoctor, "password", e.target.value)}
              />
              <Field label="Verification provenance (JSON object)">
                <textarea
                  rows={6}
                  required
                  value={doctor.verificationProvenance}
                  onChange={(e) =>
                    change(setDoctor, "verificationProvenance", e.target.value)
                  }
                />
              </Field>
              <button className="primary">Create verified doctor</button>
            </fieldset>
          </form>
        </section>
        <section className="card">
          <h2>Assign an active doctor</h2>
          <p>
            Use the consultation identifier and current record version from your
            authorized operational workflow. No clinical directory is exposed.
          </p>
          <form onSubmit={assign}>
            <fieldset disabled={busy}>
              <Field
                label="Consultation ID"
                required
                value={assignment.consultationId}
                onChange={(e) =>
                  change(setAssignment, "consultationId", e.target.value)
                }
              />
              <Field
                label="Expected record version"
                type="number"
                min="1"
                step="1"
                required
                value={assignment.expectedRowVersion}
                onChange={(e) =>
                  change(setAssignment, "expectedRowVersion", e.target.value)
                }
              />
              <Field
                label="Active verified doctor ID"
                required
                value={assignment.doctorId}
                onChange={(e) =>
                  change(setAssignment, "doctorId", e.target.value)
                }
              />
              <Field label="Assignment reason">
                <textarea
                  required
                  rows={3}
                  value={assignment.reason}
                  onChange={(e) =>
                    change(setAssignment, "reason", e.target.value)
                  }
                />
              </Field>
              <button className="primary">Record assignment</button>
            </fieldset>
          </form>
        </section>
      </div>
    </>
  );
}
