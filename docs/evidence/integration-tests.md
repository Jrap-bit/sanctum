# Integrated scenarios IT-01 to IT-10

Application revision `6231761`. Run on 2026-11-09 01:36 IST against the Docker Compose stack with synthetic data.

| Scenario | Outcome | Observation |
|---|---|---|
| IT-01 | pass | PDF extracted, confirmed; summary state completed, 1 evidence link(s) to the imported session. |
| IT-02 | pass | Statuses [404, 404, 404, 404]; no protected content returned; denial audited: True. |
| IT-03 | pass | After amendment the summary is stale; exporting the older preview returned 409. |
| IT-04 | pass | Withdraw 200, state withdrawn, reprocessing refused 409, re-import to the correct patient 201. |
| IT-05 | pass | With workers killed: note read 200, note create 201, original download 200. After restart: summary job completed with 1 summary, extraction completed, pages 200. |
| IT-06 | pass | Admin note read 403; self-approval 403; read afterwards 403; denial audited: True. |
| IT-07 | pass | Corrupt backup refused 422, active data intact 200. Valid restore 200; post-backup patient 404; restored original SHA-256 matches: True. |
| IT-08 | pass | Deleted after the backup (200); restoring that older backup did not reintroduce the patient: True. Same-host registry only; fresh-host restore not tested. |
| IT-09 | pass | Other patient's note content present: False; evidence outside the selected source: 0. The model has no tools and receives only the selected note. |
| IT-10 | pass | First save 200, stale save 409, stored text unchanged by the stale write: True. |
