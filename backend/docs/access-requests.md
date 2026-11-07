# Patient access requests

Clinicians request access for their own account using a patient ID supplied by the responsible clinician. View only permits reading; view and edit also permits the clinical actions already allowed by the account. Neither changes the primary clinician or grants new account capabilities.

An account with grants:approve reviews the request with a reason. It cannot approve its own request. Pending and rejected requests grant no access. Requesters can cancel pending requests; reviewers can revoke approved grants. Grants have no automatic expiry. Each decision is version checked and audited, with encrypted reasons and history.

Patient access is checked on each request. Revocation removes only that grant, preserving independent assignments or other approved grants. OCR and summary workers also check write access before saving results. Previously downloaded copies cannot be removed by revocation.

## Try it

1. Open Alex Demo as the original clinician. Copy the patient ID from the address, after /patients/.
2. Sign in as Bob. Open Access requests, paste the ID, select View only, and explain why access is needed.
3. Before approval, Alex must not appear in Bob's patient list.
4. Sign in with the oversight account, open Access requests, enter a decision reason, and approve Bob's request.
5. As Bob, refresh Patients. Alex is visible, but creating notes or changing follow-ups must be denied.
6. As oversight, revoke the grant with a reason. Refresh as Bob: Alex is no longer accessible unless Bob has another independent grant or assignment.
7. Repeat with View and edit to test writing. Rejecting or cancelling a request must not give access.

Run `python -m pytest tests/test_grants.py -q` from backend with the virtual environment active. Apply migration 0014 with `alembic upgrade head` before starting the updated backend or workers.
