# Copyright (c) 2015, Frappe Technologies and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_years, date_diff, flt, getdate, nowdate

EXAM_MAX_SCORES = {
	"CAT": 100, "XAT": 100, "MAT": 100,
	"NMAT": 600, "SNAP": 150, "CMAT": 400, "GMAT": 800, "GRE": 340,
}


def _normalize(actual, maximum):
	return flt((flt(actual) / flt(maximum)) * 100, 2) if flt(maximum) else 0.0


class StudentApplicant(Document):
	def autoname(self):
		from frappe.model.naming import set_name_by_naming_series

		if self.student_admission:
			naming_series = None
			if self.program:
				# set the naming series from the student admission if provided.
				student_admission = get_student_admission_data(self.student_admission, self.program)
				if student_admission:
					naming_series = student_admission.get("applicant_naming_series")
				else:
					naming_series = None
			else:
				frappe.throw(_("Select the program first"))

			if naming_series:
				self.naming_series = naming_series

		set_name_by_naming_series(self)

	def validate(self):
		self.set_title()
		self.validate_dates()
		self.validate_term()

		if self.student_admission and self.program and self.date_of_birth:
			self.validation_from_student_admission()

		self.compute_consolidated_score()

	def set_title(self):
		self.title = " ".join(
			filter(None, [self.first_name, self.middle_name, self.last_name])
		)

	def validate_dates(self):
		if self.date_of_birth and getdate(self.date_of_birth) >= getdate():
			frappe.throw(_("Date of Birth cannot be greater than today."))

	def validate_term(self):
		if self.academic_year and self.academic_term:
			actual_academic_year = frappe.db.get_value(
				"Academic Term", self.academic_term, "academic_year"
			)
			if actual_academic_year != self.academic_year:
				frappe.throw(
					_("Academic Term {0} does not belong to Academic Year {1}").format(
						self.academic_term, self.academic_year
					)
				)

	def validation_from_student_admission(self):

		student_admission = get_student_admission_data(self.student_admission, self.program)

		if (
			student_admission
			and student_admission.min_age
			and date_diff(
				nowdate(), add_years(getdate(self.date_of_birth), student_admission.min_age)
			)
			< 0
		):
			frappe.throw(
				_("Not eligible for the admission in this program as per Date Of Birth")
			)

		if (
			student_admission
			and student_admission.max_age
			and date_diff(
				nowdate(), add_years(getdate(self.date_of_birth), student_admission.max_age)
			)
			> 0
		):
			frappe.throw(
				_("Not eligible for the admission in this program as per Date Of Birth")
			)

	def compute_consolidated_score(self):
		"""
		Reads flat score fields from Application Details tab,
		normalizes them, and computes the weighted consolidated score.
		Flat fields: cat_score, xat_score, mat_score, nmat_score,
		             mit_cet_score (or cet_score), gd_score, pi_score, extempore_score
		"""
		# Read score fields from Application Details tab
		cet_score       = flt(self.get("mit_cet_score"))
		gd_score        = flt(self.get("gd_score"))
		pi_score        = flt(self.get("pi_score"))
		extempore_score = flt(self.get("extempore_score"))

		has_scores = any([cet_score, gd_score, pi_score, extempore_score])
		if not has_scores:
			return

		# MIT CET is the external exam (normalized to /100)
		best_name  = "MIT CET"
		best_score = _normalize(cet_score, 100)

		# ── Internal: normalize to /100 ───────────────────────────────────────
		cet_norm       = best_score
		gd_norm        = _normalize(gd_score,        20)
		pi_norm        = _normalize(pi_score,        20)
		extempore_norm = _normalize(extempore_score, 20)

		# ── Resolve weightage config ──────────────────────────────────────────
		config = self._get_weightage_config()
		if not config:
			return

		component_map = {
			"External Exam": (best_score,    flt(config.external_exam_weightage)),
			"CET":           (cet_norm,       flt(config.cet_weightage)),
			"GD":            (gd_norm,        flt(config.gd_weightage)),
			"PI":            (pi_norm,        flt(config.pi_weightage)),
			"Extempore":     (extempore_norm, flt(config.extempore_weightage)),
		}

		self.score_components = []
		total_weighted, total_weightage = 0.0, 0.0

		for component, (score, weightage) in component_map.items():
			weighted = flt((score * weightage) / 100, 4) if weightage else 0
			self.append("score_components", {
				"component":      component,
				"score":          score,
				"maximum_score":  100,
				"weightage":      weightage,
				"weighted_score": weighted,
			})
			total_weighted  += weighted
			total_weightage += weightage

		self.consolidated_score = flt(
			(total_weighted / total_weightage) * 100, 2
		) if total_weightage else 0.0
		self.score_status = "Computed"

	def _get_weightage_config(self):
		if self.weightage_config:
			return frappe.get_doc("Admission Score Weightage", self.weightage_config)

		for filters in [
			{"program": self.program, "academic_year": self.academic_year, "is_default": 1, "is_active": 1},
			{"program": self.program, "is_default": 1, "is_active": 1},
			{"is_default": 1, "is_active": 1},
		]:
			name = frappe.db.get_value("Admission Score Weightage", filters, "name")
			if name:
				self.weightage_config = name
				return frappe.get_doc("Admission Score Weightage", name)
		return None

	def on_payment_authorized(self, *args, **kwargs):
		self.db_set("paid", 1)


def get_student_admission_data(student_admission, program):

	admission_programs = frappe.get_all(
		"Student Admission Program",
		{"parenttype": "Student Admission", "parent": student_admission, "program": program},
		["applicant_naming_series", "min_age", "max_age"],
	)

	if admission_programs:
		return admission_programs[0]
	return None
