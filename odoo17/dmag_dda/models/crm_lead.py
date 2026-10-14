from odoo import _, api, fields, models
from odoo.exceptions import UserError

PAID_STATES = ('paid', 'in_payment')


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    dmag_audit_ids = fields.One2many('dmag.dda.audit', 'lead_id', string='Hồ sơ DDA')
    dmag_prescription_ids = fields.One2many('dmag.prescription', 'lead_id', string='Đơn kê')
    dmag_dda_paid_manual = fields.Boolean('Xác nhận cọc DDA thủ công', tracking=True)
    dmag_dda_paid = fields.Boolean('Đã cọc DDA', compute='_compute_dmag_dda_paid')
    dmag_radar_ready = fields.Boolean('Đã có Radar', compute='_compute_dmag_progress')
    dmag_prescription_ready = fields.Boolean('Đã có đơn kê duyệt', compute='_compute_dmag_progress')
    dmag_audit_count = fields.Integer(compute='_compute_dmag_progress')

    @api.depends('dmag_dda_paid_manual', 'order_ids.invoice_ids.payment_state', 'order_ids.order_line.product_id')
    def _compute_dmag_dda_paid(self):
        for lead in self:
            paid = lead.dmag_dda_paid_manual
            if not paid:
                for order in lead.order_ids:
                    has_deposit = any(order.order_line.mapped('product_id.product_tmpl_id.dmag_is_dda_deposit'))
                    if has_deposit and any(inv.payment_state in PAID_STATES for inv in order.invoice_ids):
                        paid = True
                        break
            lead.dmag_dda_paid = paid

    @api.depends('dmag_audit_ids.state', 'dmag_prescription_ids.state')
    def _compute_dmag_progress(self):
        for lead in self:
            lead.dmag_audit_count = len(lead.dmag_audit_ids)
            lead.dmag_radar_ready = any(audit.state == 'done' for audit in lead.dmag_audit_ids)
            lead.dmag_prescription_ready = any(
                p.state in ('confirmed', 'quoted') for p in lead.dmag_prescription_ids)

    def action_dmag_create_audit(self):
        self.ensure_one()
        clinic = self.partner_id.commercial_partner_id
        if not clinic:
            raise UserError(_('Cơ hội chưa gắn phòng khám.'))
        audit = self.env['dmag.dda.audit'].create({
            'partner_id': clinic.id,
            'lead_id': self.id,
            'state': 'deposit' if self.dmag_dda_paid else 'draft',
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'dmag.dda.audit',
            'res_id': audit.id,
            'view_mode': 'form',
        }

    def action_dmag_create_deposit_quotation(self):
        self.ensure_one()
        product = self.env['product.product'].search([('product_tmpl_id.dmag_is_dda_deposit', '=', True)], limit=1)
        if not product:
            raise UserError(_('Chưa cấu hình sản phẩm "Đặt cọc kiểm toán DDA".'))
        order = self.env['sale.order'].create({
            'partner_id': self.partner_id.commercial_partner_id.id or self.partner_id.id,
            'opportunity_id': self.id,
            'user_id': (self.user_id or self.env.user).id,
            'team_id': self.team_id.id,
            'order_line': [fields.Command.create({'product_id': product.id, 'product_uom_qty': 1})],
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'res_id': order.id,
            'view_mode': 'form',
        }

    def action_dmag_view_audits(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('dmag_dda.action_dmag_dda_audit')
        action['domain'] = [('lead_id', '=', self.id)]
        action['context'] = {'default_lead_id': self.id,
                             'default_partner_id': self.partner_id.commercial_partner_id.id}
        return action
