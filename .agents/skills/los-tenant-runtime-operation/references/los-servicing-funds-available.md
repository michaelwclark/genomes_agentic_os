# LOS Servicing Funds Available

Use this reference for LOS Django production investigations where Loan Details
shows a funds-available or principal-balance discrepancy.

## Code Anchors

- `los/servicing/models.py`: `LoanValidation` stores `initial_approved_amount`, `current_approval_amount`, `outstanding_balance`, `total_undisbursed_amount`, `total_amount_due`, `payment_account_id`, and `funds_available`.
- `los/servicing/api/serializers.py`: `LoanValidationSerializer` exposes `funds_available` directly.
- `los/static/lender-vue/vue-components/PeakWorkManagement/components/loan-servicing/LoanDetailsTab.vue`: Loan Details labels `Principal Balance` from `outstanding_balance` and `Funds Available` from `funds_available`.
- `los/servicing/models.py`: `PaymentHistory` stores local transaction rows with `amount`, `entry_date`, `process_date`, `trans_code`, `principal_amount`, `interest_amount`, and `details`.
- `los/servicing/api/views.py`: `PaymentHistoryViewSet` filters local rows to numeric `trans_code` 300 through 397. For Ventures-backed loans, it can call `VenturesClient.get_payment_transactions` when `servicing_provider == "ventures"` and `payment_account_id` exists.
- `los/services/vendors/ventures/client.py`: `get_payment_transactions` reads Ventures `PaymentsTransaction` rows by `accountId`.

## Investigation Checks

1. Resolve the tenant from public `Organization`/`Domain` rows.
2. Switch to the tenant schema with `schema_context(schema_name)`.
3. Locate the `LoanValidation` by loan number first, then application number and business name as backup signals.
4. Print stored detail fields and calculate:

```python
approved_basis = current_approval_amount or initial_approved_amount
expected_funds_available = approved_basis - outstanding_balance
delta = funds_available - expected_funds_available
implied_balance_from_funds_available = approved_basis - funds_available
```

5. Print local `PaymentHistory` rows around the reported payment date and sum principal amounts in that window.
6. If the tenant is Ventures-backed, enable live Ventures reads only when the user asks for them or when a read-only vendor call is acceptable for the incident.

## Lafayette Example

For loan `14805662293` / application `2025102901`, the screenshot shows:

- current approved amount: `200000.00`
- principal balance: `112704.10`
- funds available: `87111.53`
- principal payment on `2026-06-03`: `184.37`

The immediate arithmetic check is:

```python
200000.00 - 112704.10 == 87295.90
200000.00 - 87111.53 == 112888.47
112888.47 - 112704.10 == 184.37
```

That pattern indicates `funds_available` may be based on the previous balance before the `184.37` principal payment, while the displayed principal balance reflects the payment. The production script should confirm whether the stored `LoanValidation.funds_available` is stale, whether `PaymentHistory`/Ventures rows support the payment, and which upstream import last updated the stored fields before classifying the issue as code or data.
