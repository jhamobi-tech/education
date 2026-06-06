# Copyright (c) 2024, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, now_datetime

MERIT_STATUSES = ("Selected", "Waiting", "In Progress", "Rejected")


class MeritListStatus(Document):
	def validate(self):
		self._assert_not_locked()
		self._validate_score_ranges()

	def before_save(self):
		# Auto-lock when published via the checkbox
		if self.is_published and not self.is_locked:
			self.is_locked = 1
			if not self.published_on:
				self.published_on = now_datetime()

	# ── Validation helpers ────────────────────────────────────────────────────

	def _assert_not_locked(self):
		if self.is_locked and not self.flags.allow_locked_write:
			frappe.throw(_("This Merit List is locked and cannot be modified."))

	def _validate_score_ranges(self):
		if not self.score_ranges:
			frappe.throw(_("At least one Score Range must be defined."))
		for row in self.score_ranges:
			min_s = row.min_score
			max_s = row.max_score
			if min_s is not None and max_s is not None and flt(max_s) < flt(min_s):
				frappe.throw(
					_("Score Range row #{0}: Max Score cannot be less than Min Score.").format(row.idx)
				)

	# ── Public API ────────────────────────────────────────────────────────────

	@frappe.whitelist()
	def generate_merit_list(self):
		"""
		Assign merit status to every applicant for this admission round + program.

		Resolution rules:
		  - score_status != "Computed"  →  "In Progress"
		  - score_status == "Computed"  →  first matching score range row (by idx order)
		  - no range matched            →  skip (applicant not updated)

		Every assignment is written to Student Applicant via set_value (no full save,
		avoiding recursive score recomputation) and logged in Merit List History.
		Returns a summary dict.
		"""
		if self.is_locked:
			frappe.throw(_("Cannot regenerate a locked/published Merit List."))

		applicants = self._get_applicants()
		counts = {s: 0 for s in MERIT_STATUSES}

		for app in applicants:
			if app.score_status != "Computed":
				status = "In Progress"
			else:
				status = self._resolve_status(flt(app.consolidated_score))
				if not status:
					continue

			# Direct DB update — avoids re-triggering compute_consolidated_score
			frappe.db.set_value(
				"Student Applicant",
				app.name,
				{"merit_status": status, "merit_list": self.name},
				update_modified=False,
			)

			frappe.get_doc({
				"doctype": "Merit List History",
				"student_applicant": app.name,
				"merit_list": self.name,
				"merit_list_number": self.merit_list_number or 1,
				"merit_status": status,
				"score_at_assignment": flt(app.consolidated_score),
				"assigned_on": now_datetime(),
				"assigned_by": frappe.session.user,
			}).insert(ignore_permissions=True)

			counts[status] += 1

		self._update_range_counts(counts)
		total = sum(counts.values())

		self.flags.allow_locked_write = True
		self.db_set("total_applicants_processed", total, update_modified=False)
		self.db_set(
			"generation_remarks",
			", ".join(f"{s}: {c}" for s, c in counts.items() if c),
			update_modified=False,
		)

		frappe.db.commit()
		return {"status": "success", "total": total, "counts": counts}

	@frappe.whitelist()
	def publish_merit_list(self):
		"""Publish and permanently lock this merit list."""
		if self.is_locked:
			frappe.throw(_("Merit List is already published and locked."))

		self.flags.allow_locked_write = True
		self.db_set("is_published", 1, update_modified=False)
		self.db_set("is_locked", 1, update_modified=False)
		self.db_set("published_on", now_datetime(), update_modified=False)
		frappe.db.commit()
		return {"status": "published", "published_on": str(self.published_on)}

	# ── Internal helpers ──────────────────────────────────────────────────────

	def _get_applicants(self):
		"""Return all applicants matching this round and program."""
		filters = {"program": self.program}
		if self.admission_round:
			filters["student_admission"] = self.admission_round
		return frappe.get_all(
			"Student Applicant",
			filters=filters,
			fields=["name", "consolidated_score", "score_status"],
		)

	def _resolve_status(self, score):
		"""
		Iterate score_ranges in row order (idx); return the first status whose
		range contains `score`.

		A row matches when:
		  score >= min_score  (if min_score is set; defaults to 0)
		  score <= max_score  (if max_score is set; no upper bound otherwise)
		"""
		for row in self.score_ranges:
			min_s = flt(row.min_score) if row.min_score is not None else 0.0
			max_s = flt(row.max_score) if row.max_score else None
			if score < min_s:
				continue
			if max_s is not None and score > max_s:
				continue
			return row.merit_status
		return None

	def _update_range_counts(self, counts):
		"""Write per-status applicant counts back into each score range row."""
		status_totals = {}
		for row in self.score_ranges:
			status_totals.setdefault(row.merit_status, 0)
			status_totals[row.merit_status] += counts.get(row.merit_status, 0)

		for row in self.score_ranges:
			frappe.db.set_value(
				"Merit Score Range",
				row.name,
				"applicant_count",
				status_totals.get(row.merit_status, 0),
				update_modified=False,
			)


# ── Module-level whitelisted wrappers (for client-side calls) ─────────────────

@frappe.whitelist()
def generate_merit_list(merit_list_name):
	return frappe.get_doc("Merit List Status", merit_list_name).generate_merit_list()


@frappe.whitelist()
def publish_merit_list(merit_list_name):
	return frappe.get_doc("Merit List Status", merit_list_name).publish_merit_list()


@frappe.whitelist()
def get_merit_report(merit_list_name):
	"""Return a ranked applicant list for the given merit list."""
	doc = frappe.get_doc("Merit List Status", merit_list_name)
	applicants = frappe.get_all(
		"Student Applicant",
		filters={"merit_list": merit_list_name},
		fields=[
			"name", "title", "program",
			"consolidated_score", "merit_status", "application_status",
			"student_email_id",
		],
		order_by="consolidated_score desc",
	)
	return {
		"merit_list": merit_list_name,
		"title": doc.title,
		"admission_round": doc.admission_round,
		"program": doc.program,
		"merit_list_number": doc.merit_list_number,
		"is_published": doc.is_published,
		"published_on": str(doc.published_on) if doc.published_on else None,
		"total": len(applicants),
		"applicants": applicants,
	}
