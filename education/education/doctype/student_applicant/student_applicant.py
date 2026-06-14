# Copyright (c) 2015, Frappe Technologies and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_years, date_diff, flt, getdate, nowdate


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
		Dispatch to the dynamic Selection Criteria path when one is available,
		otherwise fall back to the legacy Admission Score Weightage path.
		"""
		criteria = self._get_selection_criteria()
		if criteria:
			self._compute_from_criteria(criteria)
		else:
			self._compute_from_weightage_config()

	# ── Dynamic path (Selection Criteria) ────────────────────────────────────

	def _get_selection_criteria(self):
		"""Return the active Selection Criteria doc for this applicant, or None."""
		from education.education.doctype.selection_criteria.selection_criteria import (
			SelectionCriteria,
		)

		if self.selection_criteria:
			return frappe.get_doc("Selection Criteria", self.selection_criteria)

		criteria = SelectionCriteria.get_active_criteria(
			program=self.program,
			academic_year=self.academic_year,
			admission_round=self.student_admission,
		)
		if criteria:
			self.selection_criteria = criteria.name
		return criteria

	def _compute_from_criteria(self, criteria):
		"""
		Score computation driven entirely by Selection Criteria config.
		Scores are read from the student_exam_scores child table (dynamic entry).
		entrance_exams on the criteria doc provides the max_score per exam.
		"""
		# Build score map from student_exam_scores table: exam_name → (obtained, max)
		score_map = {
			row.exam_name: (flt(row.obtained_score), flt(row.max_score))
			for row in (self.student_exam_scores or [])
		}

		self.score_components = []
		total_weighted, total_weightage, has_scores = 0.0, 0.0, False

		for w_row in criteria.weightage_configuration:
			if not w_row.is_active:
				continue

			obtained, max_score = score_map.get(w_row.exam_name, (0.0, 0.0))

			if obtained:
				has_scores = True

			normalized = _normalize(obtained, max_score) if max_score else 0.0
			weightage  = flt(w_row.weightage)
			weighted   = flt((normalized * weightage) / 100, 4)

			self.append("score_components", {
				"component":      w_row.exam_name,
				"score":          normalized,
				"maximum_score":  max_score,
				"weightage":      weightage,
				"weighted_score": weighted,
			})
			total_weighted  += weighted
			total_weightage += weightage

		if not has_scores:
			return

		self.consolidated_score = flt(
			(total_weighted / total_weightage) * 100, 2
		) if total_weightage else 0.0
		self.score_status = "Computed"

	# ── Legacy path (Admission Score Weightage) ───────────────────────────────

	def _compute_from_weightage_config(self):
		"""
		Original hardcoded scoring path kept for backward compatibility.
		Used when no Selection Criteria matches this applicant.
		"""
		cet_score       = flt(self.get("mit_cet_score"))
		gd_score        = flt(self.get("gd_score"))
		pi_score        = flt(self.get("pi_score"))
		extempore_score = flt(self.get("extempore_score"))

		if not any([cet_score, gd_score, pi_score, extempore_score]):
			return

		cet_norm       = _normalize(cet_score,       100)
		gd_norm        = _normalize(gd_score,         20)
		pi_norm        = _normalize(pi_score,         20)
		extempore_norm = _normalize(extempore_score,  20)

		config = self._get_weightage_config()
		if not config:
			return

		component_map = {
			"External Exam": (cet_norm,       flt(config.external_exam_weightage)),
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
