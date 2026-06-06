// Copyright (c) 2016, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on('Student Applicant', {
  refresh: function (frm) {
    frm.set_query('academic_term', function (doc, cdt, cdn) {
      return {
        filters: {
          academic_year: frm.doc.academic_year,
        },
      }
    })

    frm.set_query('selection_criteria', function () {
      return { filters: { program: frm.doc.program, is_active: 1 } }
    })

    if (!frm.is_new() && frm.doc.application_status === 'Applied') {
      frm.add_custom_button(
        __('Approve'),
        function () {
          frm.set_value('application_status', 'Approved')
          frm.save_or_update()
        },
        'Actions'
      )

      frm.add_custom_button(
        __('Reject'),
        function () {
          frm.set_value('application_status', 'Rejected')
          frm.save_or_update()
        },
        'Actions'
      )
    }

    if (!frm.is_new() && frm.doc.application_status === 'Approved') {
      frm.add_custom_button(__('Enroll'), function () {
        frm.events.enroll(frm)
      })

      frm.add_custom_button(
        __('Reject'),
        function () {
          frm.set_value('application_status', 'Rejected')
          frm.save_or_update()
        },
        'Actions'
      )
    }

    if (!frm.is_new() && frm.doc.application_status === 'Rejected') {
      frm.add_custom_button(
        __('Approve'),
        function () {
          frm.set_value('application_status', 'Approved')
          frm.save_or_update()
        },
        'Actions'
      )
    }

    frappe.realtime.on('enroll_student_progress', function (data) {
      if (data.progress) {
        frappe.hide_msgprint(true)
        frappe.show_progress(
          __('Enrolling student'),
          data.progress[0],
          data.progress[1]
        )
      }
    })

    frappe.db.get_value(
      'Education Settings',
      { name: 'Education Settings' },
      'user_creation_skip',
      (r) => {
        if (cint(r.user_creation_skip) !== 1) {
          frm.set_df_property('student_email_id', 'reqd', 1)
        }
      }
    )
  },

  enroll: function (frm) {
    frappe.model.open_mapped_doc({
      method: 'education.education.api.enroll_student',
      frm: frm,
    })
  },

  // Auto-resolve Selection Criteria whenever scope fields change
  program: (frm) => frm.events._resolve_selection_criteria(frm),
  academic_year: (frm) => frm.events._resolve_selection_criteria(frm),
  student_admission: (frm) => frm.events._resolve_selection_criteria(frm),

  _resolve_selection_criteria: function (frm) {
    if (!frm.doc.program) return
    // Only auto-fill if not manually set
    if (frm.doc.selection_criteria) return
    frappe.db.get_list('Selection Criteria', {
      filters: {
        program: frm.doc.program,
        is_active: 1,
        ...(frm.doc.academic_year    && { academic_year:    frm.doc.academic_year }),
        ...(frm.doc.student_admission && { admission_round: frm.doc.student_admission }),
      },
      fields: ['name'],
      limit: 1,
    }).then(rows => {
      if (rows && rows.length) {
        frm.set_value('selection_criteria', rows[0].name)
      }
    })
  },
})
