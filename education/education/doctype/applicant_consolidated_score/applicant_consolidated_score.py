# Copyright (c) 2024, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

# Known maximum scores for external exams — used to auto-fill max_score
EXAM_MAX_SCORES = {
	"CAT": 100,
	"XAT": 100,
	"MAT": 100,
	"NMAT": 600,
	"SNAP": 150,
	"CMAT": 400,
	"GMAT": 800,
	"GRE": 340,
}


def normalize(actual, maximum):
	"""Return actual/maximum × 100, rounded to 2 decimal places."""
	if flt(maximum):
		return flt((flt(actual) / flt(maximum)) * 100, 2)
	return 0.0


class ApplicantConsolidatedScore(Document):
	def validate(self):
		self.validate_scores()
		self.set_exam_max_scores()
		self.compute_external_exam_normalized_scores()
		self.set_best_external_exam_score()
		self.compute_consolidated_score()

	def validate_scores(self):
		for row in self.external_exam_scores:
			if flt(row.actual_score) < 0:
				frappe.throw(_("Actual score for {0} cannot be negative").format(row.exam_name))
			if flt(row.maximum_score) <= 0:
				frappe.throw(_("Maximum score for {0} must be greater than 0").format(row.exam_name))
			if flt(row.actual_score) > flt(row.maximum_score):
				frappe.throw(
					_("{0}: Actual score {1} cannot exceed maximum score {2}").format(
						row.exam_name, row.actual_score, row.maximum_score
					)
				)

		for field, label, max_field in [
			("cet_score", "CET", "cet_max_score"),
			("gd_score", "GD", "gd_max_score"),
			("pi_score", "PI", "pi_max_score"),
			("extempore_score", "Extempore", "extempore_max_score"),
		]:
			score = flt(self.get(field))
			max_score = flt(self.get(max_field))
			if score < 0:
				frappe.throw(_("{0} score cannot be negative").format(label))
			if max_score > 0 and score > max_score:
				frappe.throw(
					_("{0}: Actual score {1} cannot exceed maximum score {2}").format(
						label, score, max_score
					)
				)

	def set_exam_max_scores(self):
		"""Pre-fill maximum_score from the known exam scale if not already set."""
		for row in self.external_exam_scores:
			if not flt(row.maximum_score) and row.exam_name in EXAM_MAX_SCORES:
				row.maximum_score = EXAM_MAX_SCORES[row.exam_name]

	def compute_external_exam_normalized_scores(self):
		"""Normalize each external exam score to a 0–100 scale."""
		for row in self.external_exam_scores:
			row.normalized_score = normalize(row.actual_score, row.maximum_score)

	def set_best_external_exam_score(self):
		"""Select the highest normalized score across all external exams."""
		best_score, best_name = 0.0, ""
		for row in self.external_exam_scores:
			if flt(row.normalized_score) > best_score:
				best_score = flt(row.normalized_score)
				best_name = row.exam_name
		self.best_external_exam_score = best_score
		self.best_external_exam_name = best_name

	def get_weightage_config(self):
		"""Resolve weightage config: explicit → program+year → program → global default."""
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

		frappe.throw(
			_("No active Admission Score Weightage configuration found. "
			  "Please create one and mark it as default.")
		)

	def compute_consolidated_score(self):
		"""
		Normalize all component scores to /100, then apply:
		  Consolidated Score = Σ(normalized_score × weightage) / total_weightage
		"""
		config = self.get_weightage_config()

		# Normalize internal assessments: actual / max × 100
		cet_normalized       = normalize(self.cet_score,       self.cet_max_score or 100)
		gd_normalized        = normalize(self.gd_score,        self.gd_max_score or 20)
		pi_normalized        = normalize(self.pi_score,        self.pi_max_score or 20)
		extempore_normalized = normalize(self.extempore_score, self.extempore_max_score or 20)

		component_map = {
			"External Exam": (flt(self.best_external_exam_score), flt(config.external_exam_weightage)),
			"CET":           (cet_normalized,                     flt(config.cet_weightage)),
			"GD":            (gd_normalized,                      flt(config.gd_weightage)),
			"PI":            (pi_normalized,                      flt(config.pi_weightage)),
			"Extempore":     (extempore_normalized,               flt(config.extempore_weightage)),
		}

		self.score_components = []
		total_weighted = 0.0
		total_weightage = 0.0

		for component, (norm_score, weightage) in component_map.items():
			weighted_score = flt((norm_score * weightage) / 100, 4) if weightage else 0
			self.append("score_components", {
				"component":     component,
				"score":         norm_score,
				"maximum_score": 100,
				"weightage":     weightage,
				"weighted_score": weighted_score,
			})
			total_weighted  += weighted_score
			total_weightage += weightage

		self.consolidated_score = flt(
			(total_weighted / total_weightage) * 100, 2
		) if total_weightage else 0.0

		self.status = "Computed"
