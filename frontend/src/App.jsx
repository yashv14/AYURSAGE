import { useEffect, useRef, useState } from "react";
import { onExpired, restoreSession, signOut } from "./api";
import Auth from "./Auth";
import Admin from "./Admin";
import DoctorReview from "./Doctor";
import { ApprovedContent, ConsultationList, PatientDraft } from "./Patient";
import {
  ErrorNotice,
  Loading,
  SectionHeading,
  Status,
  useResource,
} from "./components";

export default function App() {
  const [user, setUser] = useState(null),
    [restoring, setRestoring] = useState(true),
    [sessionError, setSessionError] = useState(null);
  const [route, setRoute] = useState(location.hash.slice(1) || "/"),
    [dirty, setDirty] = useState(false),
    [capabilities, setCapabilities] = useState(null);
  const dirtyRef = useRef(false),
    routeRef = useRef(route),
    main = useRef(null);
  function markDirty(value) {
    dirtyRef.current = value;
    setDirty(value);
  }
  function navigate(path) {
    if (
      dirtyRef.current &&
      !window.confirm("Discard unsaved changes and leave this page?")
    )
      return;
    markDirty(false);
    location.hash = path;
  }
  function acceptUser(value) {
    markDirty(false);
    setSessionError(null);
    setUser(value);
    location.hash = value.role === "ADMIN" ? "/admin" : "/";
  }
  useEffect(() => {
    let alive = true;
    onExpired(() => {
      if (alive) {
        markDirty(false);
        setUser(null);
        setSessionError(
          new Error("Your session has expired. Please sign in again."),
        );
      }
    });
    restoreSession()
      .then((value) => {
        if (alive) setUser(value);
      })
      .catch(() => {
        if (alive)
          setSessionError(
            new Error("Please sign in to restore your workspace."),
          );
      })
      .finally(() => {
        if (alive) setRestoring(false);
      });
    fetch("/api/v1/health/ready", { cache: "no-store" })
      .then((r) => r.json())
      .then((value) => {
        if (alive) setCapabilities(value.data);
      })
      .catch(() => {});
    return () => {
      alive = false;
      onExpired(() => {});
    };
  }, []);
  useEffect(() => {
    function hash() {
      const next = location.hash.slice(1) || "/";
      if (
        dirtyRef.current &&
        !window.confirm("Discard unsaved changes and leave this page?")
      ) {
        history.replaceState(null, "", "#" + routeRef.current);
        return;
      }
      markDirty(false);
      routeRef.current = next;
      setRoute(next);
    }
    function unload(event) {
      if (dirtyRef.current) {
        event.preventDefault();
        event.returnValue = "";
      }
    }
    window.addEventListener("hashchange", hash);
    window.addEventListener("beforeunload", unload);
    return () => {
      window.removeEventListener("hashchange", hash);
      window.removeEventListener("beforeunload", unload);
    };
  }, []);
  useEffect(() => {
    main.current?.focus();
  }, [route, user]);
  async function logout() {
    if (
      dirtyRef.current &&
      !window.confirm("Discard unsaved changes and sign out?")
    )
      return;
    try {
      await signOut();
      setSessionError(null);
    } catch (e) {
      setSessionError(e);
    } finally {
      markDirty(false);
      setUser(null);
      location.hash = "/";
    }
  }
  if (restoring)
    return (
      <main className="content">
        <Loading />
      </main>
    );
  if (!user)
    return (
      <>
        <Auth onUser={acceptUser} sessionError={sessionError} />
        {sessionError && (
          <button className="retry-logout" onClick={logout}>
            Retry server sign-out
          </button>
        )}
      </>
    );
  const match = route.match(/^\/consultations\/([^/]+)$/);
  const permitted =
    user.role === "ADMIN"
      ? route === "/admin" || route === "/"
      : route === "/" || Boolean(match);
  return (
    <div className="workspace">
      <a
        className="skip"
        href="#main"
        onClick={(e) => {
          e.preventDefault();
          main.current?.focus();
        }}
      >
        Skip to main content
      </a>
      <aside className="sidebar">
        <div className="brand">
          <span aria-hidden="true">❧</span> AYURSAGE
        </div>
        <nav aria-label="Workspace navigation">
          <button
            className="nav-item"
            onClick={() => navigate(user.role === "ADMIN" ? "/admin" : "/")}
          >
            {user.role === "ADMIN"
              ? "Administration"
              : user.role === "DOCTOR"
                ? "Assigned consultations"
                : "My consultations"}
          </button>
        </nav>
        <div className="account">
          <strong>{user.role.toLowerCase()} workspace</strong>
          <small>{user.email}</small>
        </div>
      </aside>
      <div className="workspace-body">
        <header className="topbar">
          <span>Care, with a human review.</span>
          <div>
            {dirty && (
              <span className="unsaved" role="status">
                Unsaved changes
              </span>
            )}
            <button onClick={logout}>Sign out</button>
          </div>
        </header>
        <main id="main" tabIndex={-1} ref={main} className="content">
          <div className="capability-strip">
            Clinical prediction{" "}
            {capabilities?.ml === "ready" ? "available" : "unavailable"} · Live
            clinical approval requires verified policy
          </div>
          <div key={user.id + ":" + route}>
            {!permitted ? (
              <ErrorNotice
                error={
                  new Error("This route is unavailable for your account role.")
                }
              />
            ) : user.role === "ADMIN" ? (
              <Admin setDirty={markDirty} />
            ) : match ? (
              <ConsultationDetail
                id={match[1]}
                user={user}
                dirty={dirty}
                setDirty={markDirty}
                navigate={navigate}
                capabilities={capabilities}
              />
            ) : (
              <ConsultationList user={user} navigate={navigate} />
            )}
          </div>
        </main>
      </div>
    </div>
  );
}
function ConsultationDetail({
  id,
  user,
  dirty,
  setDirty,
  navigate,
  capabilities,
}) {
  const resource = useResource("/consultations/" + encodeURIComponent(id));
  function update(item) {
    resource.setValue({ consultation: item });
  }
  function reload() {
    if (!dirty || window.confirm("Discard unsaved changes and reload?")) {
      setDirty(false);
      resource.reload();
    }
  }
  if (resource.loading) return <Loading />;
  if (resource.error)
    return (
      <>
        <ErrorNotice error={resource.error} />
        <button onClick={reload}>Retry loading consultation</button>
        <button onClick={() => navigate("/")}>Back to consultations</button>
      </>
    );
  const item = resource.value.consultation;
  return (
    <>
      <button className="text-button" onClick={() => navigate("/")}>
        ← Back to consultations
      </button>
      <SectionHeading
        eyebrow="Consultation record"
        title={"Consultation " + item.id.slice(0, 8)}
      >
        <Status value={item.state} />
      </SectionHeading>
      <div className="record-bar">
        <span className="identifier">
          ID: {item.id} · Record version {item.rowVersion}
        </span>
        <button onClick={reload}>Reload consultation</button>
      </div>
      {item.state === "APPROVED" ? (
        <ApprovedContent item={item} />
      ) : user.role === "PATIENT" ? (
        <PatientDraft
          item={item}
          update={update}
          dirty={dirty}
          setDirty={setDirty}
          capabilities={capabilities}
        />
      ) : item.state === "PENDING_DOCTOR_REVIEW" ? (
        <DoctorReview
          item={item}
          update={update}
          dirty={dirty}
          setDirty={setDirty}
        />
      ) : (
        <section className="card">
          <h2>Review unavailable</h2>
          <p>
            This consultation is {item.state.replaceAll("_", " ").toLowerCase()}
            . Clinical review requires a successfully processed, assigned
            consultation.
          </p>
        </section>
      )}
    </>
  );
}
