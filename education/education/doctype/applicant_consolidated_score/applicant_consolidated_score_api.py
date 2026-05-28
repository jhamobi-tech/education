# Copyright (c) 2024, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt


@frappe.whitelist()
def compute_score(docname):
	"""Trigger score recomputation on a saved record and return the result."""
	doc = frappe.get_doc("Applicant Consolidated Score", docname)
	doc.save()
	return {
		"consolidated_score": doc.consolidated_score,
		"best_external_exam_score": doc.best_external_exam_score,
		"best_external_exam_name": doc.best_external_exam_name,
		"status": doc.status,
		"score_components": [
			{
				"component": row.component,
				"score": row.score,
				"weightage": row.weightage,
				"weighted_score": row.weighted_score,
			}
			for row in doc.score_components
		],
	}


@frappe.whitelist()
def bulk_recalculate(program=None, academic_year=None, weightage_config=None):
	"""Recalculate consolidated scores for all matching records.

	Returns a summary dict with counts of success and failures.
	"""
	filters = {}
	if program:
		filters["program"] = program
	if academic_year:
		filters["academic_year"] = academic_year

	records = frappe.get_all("Applicant Consolidated Score", filters=filters, pluck="name")

	success, failed = 0, []
	for name in records:
		try:
			doc = frappe.get_doc("Applicant Consolidated Score", name)
			if weightage_config:
				doc.weightage_config = weightage_config
			doc.save()
			success += 1
		except Exception as e:
			failed.append({"name": name, "error": str(e)})

	frappe.db.commit()
	return {"success": success, "failed": failed, "total": len(records)}


@frappe.whitelist()
def get_score_preview(
	student_applicant,
	external_exam_scores=None,
	cet_score=0,
	gd_score=0,
	pi_score=0,
	extempore_score=0,
	weightage_config=None,
):
	"""Compute a score preview without saving — used for live UI feedback."""
	import json
	from frappe.utils import flt as _flt

	EXAM_MAX_SCORES = {
		"CAT": 100, "XAT": 100, "MAT": 100,
		"NMAT": 600, "SNAP": 150, "CMAT": 400, "GMAT": 800, "GRE": 340,
	}

	if isinstance(external_exam_scores, str):
		external_exam_scores = json.loads(external_exam_scores)
	external_exam_scores = external_exam_scores or []

	# Normalize external exam scores
	best_score, best_name = 0.0, ""
	for row in external_exam_scores:
		max_s = _flt(row.get("maximum_score")) or EXAM_MAX_SCORES.get(row.get("exam_name"), 100)
		normalized = _flt((_flt(row.get("actual_score")) / max_s) * 100, 2) if max_s else 0
		row["normalized_score"] = normalized
		if normalized > best_score:
			best_score, best_name = normalized, row.get("exam_name")

	# Resolve weightage config
	config = None
	if weightage_config:
		config = frappe.get_doc("Admission Score Weightage", weightage_config)
	else:
		applicant = frappe.get_doc("Student Applicant", student_applicant)
		for f in [
			{"program": applicant.program, "academic_year": applicant.academic_year, "is_default": 1, "is_active": 1},
			{"program": applicant.program, "is_default": 1, "is_active": 1},
			{"is_default": 1, "is_active": 1},
		]:
			name = frappe.db.get_value("Admission Score Weightage", f, "name")
			if name:
				config = frappe.get_doc("Admission Score Weightage", name)
				break

	if not config:
		frappe.throw(_("No active Admission Score Weightage configuration found."))

	component_map = {
		"External Exam": (_flt(best_score),      _flt(config.external_exam_weightage)),
		"CET":           (_flt(cet_score),        _flt(config.cet_weightage)),
		"GD":            (_flt(gd_score),         _flt(config.gd_weightage)),
		"PI":            (_flt(pi_score),         _flt(config.pi_weightage)),
		"Extempore":     (_flt(extempore_score),  _flt(config.extempore_weightage)),
	}

	components, total_weighted, total_weightage = [], 0.0, 0.0
	for comp, (score, weightage) in component_map.items():
		weighted = _flt((score * weightage) / 100, 4) if weightage else 0
		components.append({"component": comp, "score": score, "weightage": weightage, "weighted_score": weighted})
		total_weighted += weighted
		total_weightage += weightage

	consolidated = _flt((total_weighted / total_weightage) * 100, 2) if total_weightage else 0

	return {
		"consolidated_score": consolidated,
		"best_external_exam_score": best_score,
		"best_external_exam_name": best_name,
		"external_exam_scores": external_exam_scores,
		"components": components,
		"weightage_config": config.name,
		"total_weightage": total_weightage,
	}


@frappe.whitelist()
def get_applicant_scores_list(program=None, academic_year=None):
	"""Return a ranked list of applicants with their consolidated scores."""
	filters = {"status": ("!=", "Draft")}
	if program:
		filters["program"] = program
	if academic_year:
		filters["academic_year"] = academic_year

	records = frappe.get_all(
		"Applicant Consolidated Score",
		filters=filters,
		fields=[
			"name", "student_applicant", "applicant_name", "program",
			"academic_year", "consolidated_score", "best_external_exam_name",
			"best_external_exam_score", "cet_score", "gd_score", "pi_score",
			"extempore_score", "status",
		],
		order_by="consolidated_score desc",
	)

	for idx, rec in enumerate(records, start=1):
		rec["rank"] = idx

	return records
