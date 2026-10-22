# Jev calibration plan

Use the human labels in `spikes/news_jev/labeling_sheet.csv` before enabling the sensor. Preserve the as-of timestamp, input digest, question/template version, typed answers, and human labels; never add raw headlines or secrets to calibration output.

For event probability, report Brier score and reliability bins only after at least `TRADER_JEV__CALIBRATION_MIN_N` labels (default 100, an assumption). For tone, report agreement/error against labels in `[-1, 1]`. Segment synthetic separately from forward-collected BLS records. `trader jev calibrate` currently reports label readiness only; it does not invoke Jev.

This is a sensor-contract calibration plan, not a test that Jev or news predicts BTC returns.
