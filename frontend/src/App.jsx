export default function App() {
  return (
    <main className="shell">
      <section className="card" aria-labelledby="page-title">
        <p className="eyebrow">Foundation status</p>
        <h1 id="page-title">AYUR-SAGE</h1>
        <p className="summary">
          A clinical decision-support application foundation with mandatory doctor review.
        </p>
        <div className="notice" role="status">
          <strong>Clinical prediction is unavailable.</strong>
          <span>
            The frozen V17 artifact and original inference contract have not been supplied.
          </span>
        </div>
        <p className="boundary">
          This application does not diagnose disease or create doctor prescriptions.
        </p>
      </section>
    </main>
  )
}
