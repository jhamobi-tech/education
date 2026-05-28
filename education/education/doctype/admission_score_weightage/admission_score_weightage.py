# Copyright (c) 2024, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class AdmissionScoreWeightage(Document):
	def validate(self):
		self.calculate_total_weightage()
		self.validate_single_default()

	def calculate_total_weightage(self):
		self.total_weightage = flt(self.external_exam_weightage) + flt(self.cet_weightage) + \
			flt(self.gd_weightage) + flt(self.pi_weightage) + flt(self.extempore_weightage)

	def validate_single_default(self):
		if self.is_default:
			filters = {"is_default": 1, "name": ("!=", self.name)}
			if self.program:
				filters["program"] = self.program
			if self.academic_year:
				filters["academic_year"] = self.academic_year
			existing = frappe.db.exists("Admission Score Weightage", filters)
			if existing:
				frappe.throw(
					_("Another default weightage config already exists: {0}").format(existing)
				)
