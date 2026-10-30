# ADR-007: Packing proof vault (photo/video before shipping, linked by QR)

- Status: accepted (2026-10-30)
- Related: ADR-005 (evidence copilot), ADR-006 (agent action proposals)

## Context

"Not as described" (SNAD) disputes are not covered by PayPal Seller Protection, and a seller rarely has anything
to show about what was in the box. "Item not received" cases also improve when the seller can show the parcel
was packed and labelled. Indonesian buyers and sellers already rely on unboxing videos on marketplaces; direct
sellers paid through PayPal have no equivalent.

## Decision

Before shipping, the seller records the parcel in SAL: one or more photos or a short video of the item being
packed, plus the order number, PayPal transaction id and/or tracking number. SAL stores the files with their
SHA-256 and the server time, issues a random packing code, and renders a printable QR label for it. The seller
sticks the label on the parcel and keeps it visible in the photos, which binds the pictures to that parcel.

When a dispute arrives (sync or webhook), the worker matches it to a packing record by transaction id, tracking
number or order number, attaches the record to the case as evidence and proposes a card. Nothing is sent to
PayPal without the merchant's approval (ADR-003/ADR-006 unchanged).

## Rules

- A packing record is the seller's word (origin `SELLER_INPUT`, doc type `packing_proof`). It shows what was
  packed and when; it never proves delivery. Grounding accepts no delivery or payment fact from it.
- PayPal evidence accepts only JPG, GIF, PNG and PDF up to 10 MB per file: photos are attached as they are; a
  video is kept in SAL and only still frames (or a PDF sheet of them) go to PayPal.
- The QR encodes only the random code (no personal data, no amounts). Codes are unguessable (128-bit).
- Retention: 180 days after creation (PayPal's dispute window), then files and rows are deleted.
- Tenant isolation: RLS FORCE like every tenant table; files under `storage_dir/<merchant>/packing/<id>/`.
- SAL never promises an outcome: for SNAD the card says the proof strengthens the reply, PayPal decides.

## Consequences

- SAL moves from answering disputes to preparing evidence before a dispute exists.
- Couriers do not scan SAL's QR; the courier's own tracking remains the delivery proof.
- A dishonest seller can still photograph one item and ship another; the label in the photo makes it harder,
  not impossible. This limit is stated in the README.
- New dependency: a small QR encoder (pure Python, no network).
