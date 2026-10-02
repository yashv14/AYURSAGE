# AYURSAGE repository guidance

- Treat the V17 model, its preprocessing, and `predict_single()` behavior as frozen.
- Do not retrain, refit, relabel, reconstruct, or substitute the model. Do not invent feature categories, defaults, probabilities, or clinical rules.
- Keep ML integration unavailable until the original artifact, callable, trusted checksum, dependency evidence, and authorized reference cases are supplied.
- Keep patient input, raw model output, deterministic enrichment, and doctor-authored decisions distinct.
- Use synthetic data in tests. Never commit credentials, patient data, model binaries, or generated clinical reports.
- Run the relevant backend tests and frontend checks before committing.
