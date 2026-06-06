// Copyright (c) 2024, Frappe Technologies and contributors
// For license information, please see license.txt

frappe.ui.form.on("Merit List Status", {
	refresh(frm) {
		frm.trigger("set_status_indicator");
		frm.trigger("add_action_buttons");
	},

	set_status_indicator(frm) {
		if (frm.doc.is_locked) {
			frm.set_intro(__("This Merit List is published and locked. No further changes are allowed."), "green");
		} else if (frm.doc.total_applicants_processed) {
			frm.set_intro(
				__("Draft — {0} applicants processed. Publish to lock.", [frm.doc.total_applicants_processed]),
				"blue"
			);
		}
	},

	add_action_buttons(frm) {
		if (frm.doc.__islocal) return;

		if (!frm.doc.is_locked) {
			frm.add_custom_button(__("Generate Merit List"), () => {
				frappe.confirm(
					__("This will assign merit statuses to all applicants for <b>{0}</b>. Continue?", [frm.doc.title]),
					() => {
						frappe.show_alert({ message: __("Generating merit list…"), indicator: "blue" });
						frappe.call({
							method: "education.education.doctype.merit_list_status.merit_list_status.generate_merit_list",
							args: { merit_list_name: frm.doc.name },
							callback(r) {
								if (r.message) {
									const { total, counts } = r.message;
									const summary = Object.entries(counts)
										.filter(([, c]) => c > 0)
										.map(([s, c]) => `${s}: ${c}`)
										.join(" | ");
									frappe.show_alert({
										message: __("Done — {0} applicants processed. {1}", [total, summary]),
										indicator: "green",
									});
									frm.reload_doc();
								}
							},
						});
					}
				);
			}, __("Actions"));

			frm.add_custom_button(__("Publish & Lock"), () => {
				frappe.confirm(
					__("Publishing will permanently lock this Merit List. This cannot be undone. Continue?"),
					() => {
						frappe.call({
							method: "education.education.doctype.merit_list_status.merit_list_status.publish_merit_list",
							args: { merit_list_name: frm.doc.name },
							callback(r) {
								if (r.message) {
									frappe.show_alert({ message: __("Merit List published and locked."), indicator: "green" });
									frm.reload_doc();
								}
							},
						});
					}
				);
			}, __("Actions"));
		}

		// Always show report button for saved docs
		frm.add_custom_button(__("View Merit Report"), () => {
			frappe.call({
				method: "education.education.doctype.merit_list_status.merit_list_status.get_merit_report",
				args: { merit_list_name: frm.doc.name },
				callback(r) {
					if (!r.message) return;
					const { applicants, total, title } = r.message;
					if (!total) {
						frappe.msgprint(__("No applicants found for this Merit List."));
						return;
					}
					const rows = applicants.map((a, i) =>
						`<tr>
							<td>${i + 1}</td>
							<td>${frappe.utils.escape_html(a.title || a.name)}</td>
							<td>${frappe.utils.escape_html(a.program || "")}</td>
							<td>${flt(a.consolidated_score, 2)}</td>
							<td><span class="indicator-pill ${_statusColor(a.merit_status)}">${a.merit_status}</span></td>
						</tr>`
					).join("");
					frappe.msgprint({
						title: __("Merit Report — {0}", [title]),
						message: `
							<p><b>${total}</b> applicants</p>
							<table class="table table-bordered table-condensed" style="font-size:0.85em">
								<thead><tr>
									<th>#</th><th>Applicant</th><th>Program</th>
									<th>Score</th><th>Merit Status</th>
								</tr></thead>
								<tbody>${rows}</tbody>
							</table>`,
						wide: true,
					});
				},
			});
		}, __("Actions"));
	},
});

function _statusColor(status) {
	return { Selected: "green", Waiting: "yellow", "In Progress": "blue", Rejected: "red" }[status] || "grey";
}
