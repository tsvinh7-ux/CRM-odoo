from odoo import api, fields, models

PAID_STATES = ('paid', 'in_payment', 'reversed')


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    dmag_contract_ids = fields.One2many('dmag.contract', 'lead_id', string='Hợp đồng')
    dmag_invoice_ids = fields.Many2many('account.move', compute='_compute_dmag_hub', string='Hoá đơn')
    dmag_plan_ids = fields.Many2many('dmag.delivery.plan', compute='_compute_dmag_hub', string='Lộ trình triển khai')
    dmag_contract_count = fields.Integer(compute='_compute_dmag_hub')
    dmag_invoice_count = fields.Integer(compute='_compute_dmag_hub')
    dmag_plan_count = fields.Integer(compute='_compute_dmag_hub')
    dmag_project_count = fields.Integer(compute='_compute_dmag_hub')
    dmag_prescription_count = fields.Integer(compute='_compute_dmag_hub')
    dmag_commission_count = fields.Integer(compute='_compute_dmag_hub')
    dmag_currency_id = fields.Many2one('res.currency', compute='_compute_dmag_hub')
    dmag_amount_ordered = fields.Monetary('Giá trị đơn đã xác nhận', compute='_compute_dmag_hub', currency_field='dmag_currency_id')
    dmag_amount_invoiced = fields.Monetary('Đã xuất hoá đơn', compute='_compute_dmag_hub', currency_field='dmag_currency_id')
    dmag_amount_paid = fields.Monetary('Đã thu', compute='_compute_dmag_hub', currency_field='dmag_currency_id')
    dmag_amount_due = fields.Monetary('Còn phải thu', compute='_compute_dmag_hub', currency_field='dmag_currency_id')
    dmag_amount_overdue = fields.Monetary('Quá hạn', compute='_compute_dmag_hub', currency_field='dmag_currency_id')
    dmag_pulse = fields.Selection(related='partner_id.commercial_partner_id.dmag_pulse', string='Pulse triển khai')

    @api.depends('order_ids.state', 'order_ids.invoice_ids.amount_residual', 'dmag_contract_ids', 'dmag_prescription_ids')
    def _compute_dmag_hub(self):
        today = fields.Date.today()
        Plan = self.env['dmag.delivery.plan']
        CommissionLine = self.env['dmag.commission.line']
        for lead in self:
            orders = lead.order_ids.filtered(lambda o: o.state == 'sale')
            invoices = lead.order_ids.invoice_ids.filtered(lambda m: m.move_type in ('out_invoice', 'out_refund'))
            posted = invoices.filtered(lambda m: m.state == 'posted')
            plans = Plan.search([('sale_order_id', 'in', lead.order_ids.ids)]) if lead.order_ids else Plan
            sign = {'out_invoice': 1, 'out_refund': -1}
            lead.dmag_invoice_ids = invoices
            lead.dmag_plan_ids = plans
            lead.dmag_contract_count = len(lead.dmag_contract_ids)
            lead.dmag_invoice_count = len(invoices)
            lead.dmag_plan_count = len(plans)
            lead.dmag_project_count = len(plans.line_ids.project_id)
            lead.dmag_prescription_count = len(lead.dmag_prescription_ids)
            lead.dmag_commission_count = CommissionLine.search_count([('invoice_id', 'in', invoices.ids)]) if invoices else 0
            lead.dmag_currency_id = (orders[:1].currency_id or lead.company_currency or self.env.company.currency_id)
            lead.dmag_amount_ordered = sum(orders.mapped('amount_total'))
            lead.dmag_amount_invoiced = sum(sign[m.move_type] * m.amount_total for m in posted)
            lead.dmag_amount_paid = sum(sign[m.move_type] * (m.amount_total - m.amount_residual) for m in posted)
            lead.dmag_amount_due = max(0.0, lead.dmag_amount_ordered - lead.dmag_amount_paid)
            lead.dmag_amount_overdue = sum(m.amount_residual for m in posted
                                           if m.move_type == 'out_invoice' and m.invoice_date_due and m.invoice_date_due < today)

    def _dmag_action(self, xmlid, domain, context=None):
        action = self.env['ir.actions.act_window']._for_xml_id(xmlid)
        action['domain'] = domain
        action['context'] = dict(context or {}, create=False)
        return action

    def action_dmag_open_clinic(self):
        self.ensure_one()
        clinic = self.partner_id.commercial_partner_id
        return {'type': 'ir.actions.act_window', 'res_model': 'res.partner', 'res_id': clinic.id, 'view_mode': 'form'}

    def action_dmag_view_contracts(self):
        self.ensure_one()
        return self._dmag_action('dmag_contract.action_dmag_contract', [('lead_id', '=', self.id)],
                                 {'default_lead_id': self.id, 'default_partner_id': self.partner_id.commercial_partner_id.id})

    def action_dmag_view_invoices(self):
        self.ensure_one()
        return self._dmag_action('account.action_move_out_invoice_type', [('id', 'in', self.dmag_invoice_ids.ids)])

    def action_dmag_view_plans(self):
        self.ensure_one()
        return self._dmag_action('dmag_delivery.action_dmag_delivery_plan', [('id', 'in', self.dmag_plan_ids.ids)])

    def action_dmag_view_projects(self):
        self.ensure_one()
        return self._dmag_action('project.open_view_project_all', [('id', 'in', self.dmag_plan_ids.line_ids.project_id.ids)])

    def action_dmag_view_prescriptions(self):
        self.ensure_one()
        return self._dmag_action('dmag_dda.action_dmag_prescription', [('lead_id', '=', self.id)])

    def action_dmag_view_commissions(self):
        self.ensure_one()
        return self._dmag_action('dmag_commission.action_dmag_commission_line', [('invoice_id', 'in', self.dmag_invoice_ids.ids)])
