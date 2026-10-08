import { useState } from "react";
import { api, signIn } from "./api";
import { ErrorNotice, Field } from "./components";

export default function Auth({ onUser, sessionError }) {
  const [register, setRegister] = useState(false),
    [email, setEmail] = useState(""),
    [password, setPassword] = useState("");
  const [terms, setTerms] = useState(import.meta.env.VITE_TERMS_VERSION || ""),
    [accepted, setAccepted] = useState(false);
  const [error, setError] = useState(null),
    [busy, setBusy] = useState(false);
  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (register)
        await api("/auth/register", {
          method: "POST",
          anonymous: true,
          body: { email, password, acceptedTermsVersion: terms },
        });
      onUser(await signIn(email, password));
    } catch (e) {
      setError(e);
    } finally {
      setPassword("");
      setBusy(false);
    }
  }
  return (
    <main className="auth-layout">
      <section className="auth-intro">
        <div className="brand">
          <span aria-hidden="true">❧</span> AYURSAGE
        </div>
        <p className="eyebrow">A considered approach to care</p>
        <h1>
          Your care.
          <br />A clearer view.
        </h1>
        <p>
          A private workspace to share your inputs, connect with your assigned
          doctor, and keep approved care recommendations together.
        </p>
        <div className="intro-note">
          Clinical recommendations require doctor review. Prediction and live
          approval remain unavailable until the required evidence and policies
          are verified.
        </div>
        <span className="botanical" aria-hidden="true">
          ❧
        </span>
      </section>
      <section className="auth-panel">
        <div className="auth-form">
          <p className="eyebrow">Welcome to your workspace</p>
          <h2>{register ? "Create patient account" : "Sign in"}</h2>
          <p className="muted">
            {register
              ? "Doctor accounts are onboarded by an authorized administrator."
              : "Use the account provided by your clinic, or create a patient account."}
          </p>
          <ErrorNotice error={error || sessionError} />
          <form onSubmit={submit}>
            <fieldset disabled={busy}>
              <Field
                label="Email address"
                type="email"
                autoComplete="username"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
              <Field
                label="Password"
                type="password"
                autoComplete={register ? "new-password" : "current-password"}
                minLength={register ? 12 : undefined}
                maxLength={256}
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
              {register && (
                <>
                  <Field
                    label="Clinic-provided terms version"
                    required
                    maxLength={64}
                    value={terms}
                    onChange={(e) => setTerms(e.target.value)}
                    hint="Obtain the actual terms and version from your clinic. This application does not supply an approved terms policy."
                  />
                  <label className="check">
                    <input
                      type="checkbox"
                      required
                      checked={accepted}
                      onChange={(e) => setAccepted(e.target.checked)}
                    />
                    I have read and accept the clinic terms identified above.
                  </label>
                </>
              )}
              <button className="primary wide">
                {busy
                  ? "Please wait…"
                  : register
                    ? "Create patient account"
                    : "Sign in"}
              </button>
            </fieldset>
          </form>
          <button
            className="text-button"
            disabled={busy}
            onClick={() => {
              setRegister(!register);
              setError(null);
            }}
          >
            {register
              ? "Already have an account? Sign in"
              : "New patient? Create an account"}
          </button>
          <p className="privacy-note">
            Your account role determines your access. Clinical data stays within
            your authorized workspace.
          </p>
        </div>
      </section>
    </main>
  );
}
