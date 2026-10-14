from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    dmag_audit_ids = fields.One2many('dmag.dda.audit', 'partner_id', string='Kiểm toán DDA')
    dmag_audit_count = fields.Integer(compute='_compute_dmag_audit_count')
    dmag_prescription_count = fields.Integer(compute='_compute_dmag_audit_count')

    def _compute_dmag_audit_count(self):
        Prescription = self.env['dmag.prescription']
        for partner in self:
            partner.dmag_audit_count = len(partner.dmag_audit_ids)
            partner.dmag_prescription_count = Prescription.search_count([('partner_id', '=', partner.id)])

    def action_dmag_view_audits(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('dmag_dda.action_dmag_dda_audit')
        action['domain'] = [('partner_id', '=', self.id)]
        action['context'] = {'default_partner_id': self.id}
        return action

    def action_dmag_view_prescriptions(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('dmag_dda.action_dmag_prescription')
        action['domain'] = [('partner_id', '=', self.id)]
        action['context'] = {'default_partner_id': self.id}
        return action
