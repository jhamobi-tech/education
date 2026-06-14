# Copyright (c) 2024, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, nowdate


class SelectionCriteria(Document):
	def validate(self):
		self._validate_dates()
		self._calculate_total_weightage()
		self._validate_total_weightage()

	def _validate_dates(self):
		if self.start_date and self.end_date:
			if getdate(self.start_date) > getdate(self.end_date):
				frappe.throw(_("Start Date cannot be after End Date."))

	def _calculate_total_weightage(self):
		self.total_weightage = flt(
			sum(flt(row.weightage) for row in self.weightage_configuration if row.is_active)
		)

	def _validate_total_weightage(self):
		if self.weightage_configuration and abs(self.total_weightage - 100.0) > 0.01:
			frappe.throw(
				_("Total active weightage must equal 100%. Current total: {0}%").format(
					self.total_weightage
				)
			)

	@staticmethod
	def get_active_criteria(program, academic_year=None, admission_round=None):
		"""
		Return the best-matching active SelectionCriteria for the given scope.
		Resolution order (most-specific first):
		  1. program + academic_year + admission_round (date-bounded)
		  2. program + academic_year (date-bounded)
		  3. program only (date-bounded)
		  4. Same three without date filter (fallback)
		"""
		today = nowdate()
		base = {"program": program, "is_active": 1}

		scope_variants = [
			{"academic_year": academic_year, "admission_round": admission_round},
			{"academic_year": academic_year},
			{},
		]

		for extra in scope_variants:
			scoped = {**base, **{k: v for k, v in extra.items() if v}}
			# Try date-bounded first
			name = frappe.db.get_value(
				"Selection Criteria",
				{**scoped, "start_date": ["<=", today], "end_date": [">=", today]},
				"name",
			)
			if not name:
				name = frappe.db.get_value("Selection Criteria", scoped, "name")
			if name:
				return frappe.get_doc("Selection Criteria", name)

		return None


@frappe.whitelist()
def get_exam_names_for_criteria(criteria_name):
	"""Return exam names defined in a Selection Criteria document (used by client scripts)."""
	if not criteria_name:
		return []
	doc = frappe.get_doc("Selection Criteria", criteria_name)
	return [row.exam_name for row in doc.entrance_exams]
